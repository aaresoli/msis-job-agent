import { describe, expect, it } from "vitest";

import { matchBand } from "../../lib/match";

describe("matchBand", () => {
  it("labels strong and exploratory matches", () => {
    expect(matchBand(86)).toBe("Strong alignment");
    expect(matchBand(42)).toBe("Exploratory match");
  });

  it("makes local-AI degradation explicit", () => {
    expect(matchBand(91, true)).toBe("Awaiting AI refinement");
  });
});
