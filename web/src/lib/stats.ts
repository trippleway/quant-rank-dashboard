// Small pure helpers shared by pages (unit-tested in stats.test.ts).

export function lastValid(xs: (number | null)[]): { value: number; index: number } | null {
  for (let i = xs.length - 1; i >= 0; i--) {
    const v = xs[i];
    if (v != null && Number.isFinite(v)) return { value: v, index: i };
  }
  return null;
}

/** Percentile (0–1) of the latest valid value within the trailing ``window`` valid values. */
export function trailingPercentile(xs: (number | null)[], window = 252): number | null {
  const last = lastValid(xs);
  if (!last) return null;
  const hist = xs
    .slice(Math.max(0, last.index - window + 1), last.index + 1)
    .filter((v): v is number => v != null && Number.isFinite(v));
  if (hist.length < 20) return null;
  const below = hist.filter((v) => v < last.value).length;
  const equal = hist.filter((v) => v === last.value).length;
  return (below + 0.5 * equal) / hist.length;
}

/** Change of the latest valid value vs the valid value ``lag`` observations earlier. */
export function changeOver(xs: (number | null)[], lag: number): number | null {
  const last = lastValid(xs);
  if (!last || last.index - lag < 0) return null;
  const prev = lastValid(xs.slice(0, last.index - lag + 1));
  return prev ? last.value - prev.value : null;
}

/** Rebase a price series to 100 at its first valid value (common base, one axis). */
export function rebase(xs: (number | null)[]): (number | null)[] {
  const first = xs.find((v): v is number => v != null && Number.isFinite(v) && v !== 0);
  if (first == null) return xs.map(() => null);
  return xs.map((v) => (v == null ? null : (v / first) * 100));
}

export type SortDir = "asc" | "desc";

/** Stable sort; nulls always last regardless of direction. */
export function sortBy<T>(rows: T[], key: (r: T) => number | string | null | undefined, dir: SortDir): T[] {
  return rows
    .map((r, i) => ({ r, i, k: key(r) }))
    .sort((a, b) => {
      const an = a.k == null;
      const bn = b.k == null;
      if (an || bn) return an === bn ? a.i - b.i : an ? 1 : -1;
      const c = a.k! < b.k! ? -1 : a.k! > b.k! ? 1 : 0;
      return (dir === "asc" ? c : -c) || a.i - b.i;
    })
    .map((x) => x.r);
}
