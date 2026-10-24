import { describe, expect, it } from "vitest";
import { sellerFee } from "./fees";
import { SELLER_FEE } from "../config";

describe("flat seller fee", () => {
  it("is 3 percent of the sale", () => {
    expect(sellerFee(400, SELLER_FEE).value).toBe(12);
  });
  it("is at least the minimum", () => {
    expect(sellerFee(10, SELLER_FEE).value).toBe(1);
  });
  it("is capped per item", () => {
    expect(sellerFee(2000, SELLER_FEE).value).toBe(25);
  });
  it("is labelled PROPOSED and says when it is due", () => {
    const f = sellerFee(400, SELLER_FEE);
    expect(f.how_computed).toContain("PROPOSED");
    expect(f.how_computed).toContain("receiving check");
  });
  it("is the same function for every seller: it takes no seller input", () => {
    expect(sellerFee.length).toBe(2);
  });
});
