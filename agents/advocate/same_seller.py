"""Pure same-seller exclusion over already-ranked candidates."""
from collections import defaultdict
from collections.abc import Mapping
from urllib.parse import urlsplit

TRUSTED_PROVENANCE = {"registry", "mirror", "bound_state"}
MARKETPLACE_DOMAINS = {
    "amazon.com", "ebay.com", "bestbuy.com", "newegg.com", "microcenter.com", "bhphotovideo.com",
}
IGNORED_DOMAINS = {"example.com", "github.com", "cpsc.gov"}
URL_FIELDS = ("listing_url", "evidence_url", "source_url")
REASON = {
    "rule_id": "advocate.same_seller",
    "summary": "This seller shares trusted identity evidence with a higher-ranked seller",
    "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/same_seller.py",
}


def _stable_value(value):
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _merchant_host(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if host.endswith("."):
            host = host[:-1]
        if host.endswith("."):
            return None
    except ValueError:
        return None
    if not host or host == "test" or host.endswith(".test"):
        return None
    if any(host == domain or host.endswith(f".{domain}")
           for domain in MARKETPLACE_DOMAINS | IGNORED_DOMAINS):
        return None
    return host


def _evidence_hosts(candidate):
    sources = [candidate]
    lines = candidate.get("lines", [])
    if isinstance(lines, list):
        sources.extend(line for line in lines if isinstance(line, Mapping))
    return {
        host
        for source in sources
        for field in URL_FIELDS
        if (host := _merchant_host(source.get(field)))
    }


def exclude_same_seller(candidates, trusted_identity_by_seller):
    """Keep the first ranked seller in each trusted shared-identity component."""
    candidates = list(candidates)
    seller_ids = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate must be a mapping")
        seller_id = candidate.get("supplier_id")
        if not isinstance(seller_id, str) or not seller_id.strip():
            raise ValueError("candidate supplier_id must be a nonempty string")
        if seller_id not in seller_ids:
            seller_ids.append(seller_id)

    parent = {seller_id: seller_id for seller_id in seller_ids}

    def find(seller_id):
        while parent[seller_id] != seller_id:
            parent[seller_id] = parent[parent[seller_id]]
            seller_id = parent[seller_id]
        return seller_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_identity = defaultdict(list)
    for seller_id in seller_ids:
        identity = trusted_identity_by_seller.get(seller_id, {}) if isinstance(trusted_identity_by_seller, Mapping) else {}
        if not isinstance(identity, Mapping) or identity.get("provenance") not in TRUSTED_PROVENANCE:
            continue
        for field in ("payee", "owner"):
            value = _stable_value(identity.get(field))
            if value:
                by_identity[(field, value)].append(seller_id)
    for candidate in candidates:
        for host in _evidence_hosts(candidate):
            by_identity[("host", host)].append(candidate["supplier_id"])
    for matching_sellers in by_identity.values():
        for seller_id in matching_sellers[1:]:
            union(matching_sellers[0], seller_id)

    components = defaultdict(list)
    for seller_id in seller_ids:
        components[find(seller_id)].append(seller_id)
    excluded = {}
    for component in components.values():
        if len(component) < 2:
            continue
        winner = next(c["supplier_id"] for c in candidates if c["supplier_id"] in component)
        for seller_id in component:
            if seller_id != winner:
                excluded[seller_id] = winner

    kept = [c for c in candidates if c["supplier_id"] not in excluded]
    exclusions = []
    for seller_id in seller_ids:
        if seller_id in excluded:
            exclusions.append({
                "kept_seller_id": excluded[seller_id],
                "excluded_seller_id": seller_id,
                "reason": dict(REASON),
            })
    return kept, exclusions
