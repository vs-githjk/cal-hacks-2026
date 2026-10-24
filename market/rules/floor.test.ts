import { describe, expect, it } from "vitest";
import { checkFloor } from "./floor";

const lines = [
  { sku_spec: "onion", unit_price: 20, quantity: 1 },
  { sku_spec: "romaine", unit_price: 40, quantity: 2 },
];

describe("floor", () => {
  it("passes when every line is at or above the floor", () => {
    expect(checkFloor({ lines }, { onion: 20, romaine: 35 })).toEqual({ ok: true });
  });

  it("rejects a line below the floor with a reason naming the line", () => {
    const r = checkFloor({ lines }, { onion: 25, romaine: 35 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain("onion");
  });

  it("lists every offending line", () => {
    const r = checkFloor({ lines }, { onion: 25, romaine: 45 });
    expect(r.ok === false && r.reasons.length).toBe(2);
  });

  it("rejects non-positive or non-finite prices even with no floor set", () => {
    expect(checkFloor({ lines: [{ sku_spec: "x", unit_price: 0, quantity: 1 }] }, {}).ok).toBe(false);
    expect(checkFloor({ lines: [{ sku_spec: "x", unit_price: NaN, quantity: 1 }] }, {}).ok).toBe(false);
  });
});
