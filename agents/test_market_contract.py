"""#447: every reducer call and SQL read in agents/market_bridge.py must match the market module in this tree
(market/spacetimedb/src/index.ts and schema.ts), the module that is published to Maincloud. The bridge was written
against #165's module (review_candidates, line_meta_json, binding_hash, review_deadline, set_bid_line_meta), which is
not live, so every call on the buyer's market path failed on the real server while mocked tests passed."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "market" / "spacetimedb" / "src"
BRIDGE = ROOT / "agents" / "market_bridge.py"

# Lane A follow-ups: used only by the chat (ASI:One) purchase path, which needs a buyer-role status view and a settle
# reducer that main's module does not have. Kept explicit so they are never silently forgotten; the web path avoids them.
CHAT_ONLY = {"reducer:settle_goal", "table:my_purchase_status"}


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _object_fields(body: str) -> set[str]:
    return set(re.findall(r"(\w+)\s*:\s*t\.", body))


def _balanced(text: str, start: int) -> str:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced braces")


def module_reducers() -> dict[str, set[str]]:
    src = (SRC / "index.ts").read_text()
    out = {}
    for m in re.finditer(r"export const (\w+) = spacetimedb\.reducer\(\s*", src):
        rest = src[m.end():]
        out[m.group(1)] = {_snake(f) for f in _object_fields(_balanced(rest, 0))} if rest.startswith("{") else set()
    return out


def module_columns() -> dict[str, set[str]]:
    """Columns of every table (schema.ts) and every view (index.ts), snake_case as SQL sees them."""
    schema = (SRC / "schema.ts").read_text()
    tables, by_const = {}, {}
    for m in re.finditer(r"export const (\w+) = table\(\s*\{\s*name: '(\w+)'[^}]*\},\s*", schema):
        cols = {_snake(f) for f in _object_fields(_balanced(schema, m.end()))}
        tables[m.group(2)] = by_const[m.group(1)] = cols
    objects = {m.group(1): {_snake(f) for f in _object_fields(_balanced(schema, m.end()))}
               for m in re.finditer(r"export const (\w+) = t\.object\(\s*'\w+',\s*", schema)}
    index = (SRC / "index.ts").read_text()
    for m in re.finditer(r"spacetimedb\.view\(\s*\{\s*name: '(\w+)'[^}]*\},\s*t\.array\((\w+)(?:\.rowType)?\)", index):
        tables[m.group(1)] = by_const.get(m.group(2)) or objects.get(m.group(2), set())
    return tables


def _consts(tree: ast.Module) -> dict[str, object]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _local_values(func: ast.AST) -> dict[str, ast.AST]:
    out = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
    return out


def _text(node, consts, local) -> str:
    """The SQL text an expression builds, with any value it cannot know replaced by '?'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left, consts, local) + _text(node.right, consts, local)
    if isinstance(node, ast.Name):
        if isinstance(consts.get(node.id), str):
            return consts[node.id]
        if node.id in local:
            return _text(local[node.id], consts, local)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant) and len(node.args) == 1):
        arg = node.args[0]
        names = None
        if isinstance(arg, ast.Name):
            names = consts.get(arg.id)
            if names is None and isinstance(local.get(arg.id), ast.Name):
                names = consts.get(local[arg.id].id)
            if names is None and arg.id in local:
                try:
                    names = ast.literal_eval(local[arg.id])
                except ValueError:
                    names = None
        elif isinstance(arg, (ast.Tuple, ast.List)):
            names = ast.literal_eval(arg)
        if isinstance(names, (tuple, list)):
            return node.func.value.value.join(names)
    return "?"


def bridge_usage():
    tree = ast.parse(BRIDGE.read_text())
    consts = _consts(tree)
    calls, queries = [], []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        local = _local_values(func)
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr in ("_call", "call") and node.args and isinstance(node.args[0], ast.Constant):
                names = {k.arg for k in node.keywords if k.arg}
                for k in node.keywords:
                    if k.arg is None and isinstance(k.value, ast.Name) and isinstance(local.get(k.value.id), ast.Dict):
                        names |= {ast.literal_eval(key) for key in local[k.value.id].keys}
                calls.append((func.name, node.args[0].value, names))
            elif node.func.attr == "_sql" and node.args:
                sql = _text(node.args[0], consts, local)
                if not sql.startswith("SELECT ? FROM ?"):   # a shared helper; its callers are read below
                    queries.append((func.name, sql))
            elif node.func.attr == "_agent_row" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                cols = _text(ast.Call(func=ast.Attribute(value=ast.Constant(", "), attr="join"), args=[node.args[1]],
                                      keywords=[]), consts, local)
                queries.append((func.name, f"SELECT {cols} FROM {node.args[0].value}"))
    return calls, queries


def contract_problems() -> list[str]:
    reducers, columns = module_reducers(), module_columns()
    calls, queries = bridge_usage()
    problems = []
    for func, name, args in calls:
        if name not in reducers:
            if f"reducer:{name}" not in CHAT_ONLY:
                problems.append(f"{func}: reducer {name} does not exist")
        elif args != reducers[name]:
            problems.append(f"{func}: {name} sends {sorted(args)}, the module takes {sorted(reducers[name])}")
    for func, sql in queries:
        m = re.search(r"SELECT (.+?) FROM (\w+)", sql, re.S)
        assert m, f"{func}: unreadable SQL {sql!r}"
        cols, table = [c.strip() for c in m.group(1).split(",")], m.group(2)
        if table not in columns:
            if f"table:{table}" not in CHAT_ONLY:
                problems.append(f"{func}: table or view {table} does not exist")
            continue
        problems += [f"{func}: {table}.{c} does not exist" for c in cols if c not in columns[table]]
    return problems


def test_the_parser_reads_the_module():
    reducers, columns = module_reducers(), module_columns()
    assert reducers["create_mandate"] >= {"deal_id", "payee", "amount"} and "review_candidates" not in columns
    assert {"bid_id", "rank", "landed", "lines"} <= columns["round_result"] and "my_bids" in columns


def test_every_bridge_call_and_query_matches_the_market_module():
    assert contract_problems() == []


def test_chat_only_gaps_are_still_real_and_listed():
    reducers, columns = module_reducers(), module_columns()
    assert "settle_goal" not in reducers and "my_purchase_status" not in columns
