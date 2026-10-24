import { schema, table, t } from 'spacetimedb/server';
import { checkFloor } from '../../rules/floor';

const hello = table({ name: 'hello', public: true }, { id: t.u64().primaryKey().autoInc(), text: t.string(), floorOk: t.bool() });

const spacetimedb = schema({ hello });
export default spacetimedb;

export const sayHello = spacetimedb.reducer({ text: t.string(), price: t.f64() }, (ctx, { text, price }) => {
  const r = checkFloor({ lines: [{ sku_spec: 'x', unit_price: price, quantity: 1 }] }, { x: 10 });
  ctx.db.hello.insert({ id: 0n, text, floorOk: r.ok });
});
