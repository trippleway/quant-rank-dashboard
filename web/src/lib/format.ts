// Number formatting. Missing values render as an em dash, never as 0.

export const DASH = "—";

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

export function pct(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? `${(x * 100).toFixed(digits)}%` : DASH;
}

export function signedPct(x: number | null | undefined, digits = 1): string {
  if (!isNum(x)) return DASH;
  const s = (x * 100).toFixed(digits);
  return x > 0 ? `+${s}%` : `${s}%`;
}

export function num(x: number | null | undefined, digits = 2): string {
  return isNum(x) ? x.toFixed(digits) : DASH;
}

export function signed(x: number | null | undefined, digits = 2): string {
  if (!isNum(x)) return DASH;
  return x > 0 ? `+${x.toFixed(digits)}` : x.toFixed(digits);
}

export function usd(x: number | null | undefined): string {
  if (!isNum(x)) return DASH;
  const a = Math.abs(x);
  if (a >= 1e9) return `$${(x / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(x / 1e3).toFixed(0)}K`;
  return `$${x.toFixed(0)}`;
}

/** Direction marker so up/down never relies on color alone. */
export function arrow(x: number | null | undefined): "▲" | "▼" | "＝" | "" {
  if (!isNum(x)) return "";
  if (x > 0) return "▲";
  if (x < 0) return "▼";
  return "＝";
}

/** Rank change: positive = moved up (prev 10 → now 4 is +6). */
export function rankChange(rank: number, prev: number | null | undefined): number | null {
  return isNum(prev) ? prev - rank : null;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}
