import { describe, expect, it } from "vitest";
import { isCompatible } from "./bundle";

describe("isCompatible", () => {
  it("accepts any minor or patch of the supported major", () => {
    expect(isCompatible("0.1.0", "0.1.0")).toBe(true);
    expect(isCompatible("0.4.2", "0.1.0")).toBe(true);
  });

  it("rejects a different major", () => {
    expect(isCompatible("1.0.0", "0.1.0")).toBe(false);
  });
});
