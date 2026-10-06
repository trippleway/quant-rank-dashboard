import { describe, expect, it, vi } from "vitest";
import { checkSchema, fetchJson } from "./data";
import { arrow, num, pct, rankChange, signed, signedPct, usd } from "./format";
import { changeOver, rebase, sortBy, trailingPercentile } from "./stats";

describe("format", () => {
  it("renders missing values as a dash, never 0", () => {
    expect(pct(null)).toBe("—");
    expect(num(Number.NaN)).toBe("—");
    expect(signed(undefined)).toBe("—");
    expect(usd(null)).toBe("—");
  });
  it("formats signs and units", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(signedPct(0.05)).toBe("+5.0%");
    expect(signedPct(-0.05)).toBe("-5.0%");
    expect(signed(0)).toBe("0.00");
    expect(usd(25_400_000)).toBe("$25.4M");
  });
  it("marks direction with a symbol, not only color", () => {
    expect(arrow(1)).toBe("▲");
    expect(arrow(-1)).toBe("▼");
    expect(arrow(0)).toBe("＝");
    expect(arrow(null)).toBe("");
  });
  it("rank change is positive when moving up", () => {
    expect(rankChange(4, 10)).toBe(6);
    expect(rankChange(10, 4)).toBe(-6);
    expect(rankChange(3, null)).toBeNull();
  });
});

describe("stats", () => {
  it("trailing percentile uses only the latest window and ignores nulls", () => {
    const xs = [...Array.from({ length: 99 }, (_, i) => i), null, 1000];
    expect(trailingPercentile(xs, 252)).toBeCloseTo(0.995, 3);
    expect(trailingPercentile([1, 2, 3])).toBeNull(); // too short
  });
  it("change over a lag skips trailing nulls", () => {
    expect(changeOver([1, 2, 3, 5, null], 2)).toBe(3);
    expect(changeOver([1], 5)).toBeNull();
  });
  it("rebases to 100 at the first valid value", () => {
    expect(rebase([null, 50, 100])).toEqual([null, 100, 200]);
  });
  it("sorts stably with nulls last in both directions", () => {
    const rows = [{ k: 2 }, { k: null }, { k: 1 }, { k: 2 }];
    expect(sortBy(rows, (r) => r.k, "asc").map((r) => r.k)).toEqual([1, 2, 2, null]);
    expect(sortBy(rows, (r) => r.k, "desc").map((r) => r.k)).toEqual([2, 2, 1, null]);
  });
});

describe("data loading", () => {
  it("rejects unknown schema majors and missing versions", () => {
    expect(() => checkSchema("x.json", { schema_version: "2.0" })).toThrow(/不支援/);
    expect(() => checkSchema("x.json", {})).toThrow(/schema_version/);
    expect(() => checkSchema("x.json", { schema_version: "1.3" })).not.toThrow();
  });
  it("turns HTTP and network failures into readable errors (no fallback data)", async () => {
    const notFound = vi.fn().mockResolvedValue(new Response("nope", { status: 404 }));
    await expect(fetchJson("rankings.json", notFound)).rejects.toThrow("rankings.json: HTTP 404");
    const offline = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchJson("macro.json", offline)).rejects.toThrow(/無法連線取得 macro.json/);
    const bad = vi.fn().mockResolvedValue(new Response("{oops", { status: 200 }));
    await expect(fetchJson("x.json", bad)).rejects.toThrow(/不是有效的 JSON/);
  });
});
