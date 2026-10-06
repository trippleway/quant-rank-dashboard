// FIXTURE data for unit tests only — never shipped or shown as real output.
import type { Changes, RankEntry, Rankings } from "../lib/types";

const env = {
  schema_version: "1.0",
  asof: "2026-01-05",
  generated_at: "2026-01-05T22:00:00+00:00",
  disclaimer: "FIXTURE",
};

export function entry(rank: number, ticker: string, extra: Partial<RankEntry> = {}): RankEntry {
  return {
    rank,
    ticker,
    asset_class: "equity",
    category: "energy",
    leverage: 1,
    score: 1 - rank / 10,
    composite: 1 - rank / 10,
    risk_penalty: 0,
    concentration_penalty: 0,
    penalties: {},
    coverage: 1,
    short_history: false,
    groups: { momentum: { score: 1, weight: 0.5, contribution: 0.5 }, low_risk: { score: -0.2, weight: 0.5, contribution: -0.1 } },
    factors: [{ factor: "mom_12_1", label: "12-1 月動能", group: "momentum", value: 0.3, z: 1.2, contribution: 0.5 }],
    reasons: [{ factor: "mom_12_1", label: "12-1 月動能", group: "momentum", z: 1.2, contribution: 0.5 }],
    risks: [{ code: "systematic", label: "市場風險" }],
    prev_rank: rank,
    sparkline: [1, 2, 3],
    ret_1d: 0.01,
    ...extra,
  };
}

export const rankingsFixture: Rankings = {
  ...env,
  kind: "top50",
  notes: [],
  regime: { label: "neutral", stress_score: 0, n_components: 8, contributions: {}, weights_regime: "neutral" },
  weights: { momentum: 0.5, low_risk: 0.5 },
  constraints: {
    top_n: 3,
    asset_class_caps: { equity: 2, bond_etf: 2 },
    category_cap: 8,
    leveraged_cap: 5,
    max_correlation: 0.95,
    corr_window: 126,
    concentration_penalty: 0.04,
    min_coverage: 0.6,
  },
  universe: { candidates: 5, eligible: 4, ineligible: 1 },
  counts: { asset_class: { equity: 2, bond_etf: 1 }, leveraged_or_inverse: 1 },
  top: [
    entry(1, "AAA", { prev_rank: 3 }),
    entry(2, "BBB", { prev_rank: null }),
    entry(3, "TLTX", { asset_class: "bond_etf", category: "treasury_long", leverage: 3, short_history: true }),
  ],
  skipped: [{ ticker: "CCC", score: 0.5, reason: "category cap energy (8)" }],
  ineligible: [{ ticker: "DDD", reason: "no bar on asof (stale data)" }],
  group_labels: { momentum: "動能", low_risk: "低風險" },
};

export const changesFixture: Changes = {
  ...env,
  kind: "changes",
  prev_asof: "2026-01-02",
  regime: { prev: "neutral", cur: "risk_off" },
  regime_changed: true,
  threshold: 5,
  entered: [{ ticker: "BBB", asset_class: "equity", rank: 2, score_prev: null, score: 0.8, reasons: ["前一交易日不在合格名單（流動性／資料）"] }],
  exited: [{ ticker: "CCC", asset_class: "equity", prev_rank: 2, score_prev: 0.9, score: 0.5, reasons: ["受約束排除：category cap energy (8)"] }],
  movers: [{ ticker: "AAA", asset_class: "equity", rank: 1, prev_rank: 9, change: 8, score_prev: 0.5, score: 0.9, reasons: ["動能貢獻 +0.400"] }],
  unchanged: 0,
};
