// Hello milestone: call a reducer over SpacetimeDB's HTTP API and read the row back with SQL.
const HOST = process.env.SPACETIMEDB_URI ?? 'http://127.0.0.1:3000';
const DB = process.env.SPACETIMEDB_DB ?? 'bidding-royale';

const { token } = await (await fetch(`${HOST}/v1/identity`, { method: 'POST' })).json();
const auth = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

const call = await fetch(`${HOST}/v1/database/${DB}/call/say_hello`, {
  method: 'POST', headers: auth, body: JSON.stringify({ text: 'hello from node', price: 12.5 }),
});
console.log('call status', call.status, await call.text());

const sql = await fetch(`${HOST}/v1/database/${DB}/sql`, { method: 'POST', headers: auth, body: 'SELECT * FROM hello' });
console.log('sql status', sql.status, JSON.stringify(await sql.json()).slice(0, 400));
