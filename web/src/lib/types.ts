// Types of the versioned JSON written by `qrd publish` (schema 1.x).

export interface Envelope {
  schema_version: string;
  kind: string;
  asof: string;
  generated_at: string;
  disclaimer: string;
}

export interface GroupBreakdown {
  score: number | null;
  weight: number | null;
  contribution: number;
}

export interface FactorEntry {
  factor: string;
  label: string;
  group: string;
  value: number | null;
  z: number | null;
  contribution: number;
}

export interface Reason {
  factor: string;
  label: string;
  group: string;
  z: number | null;
  contribution: number;
}

export interface Risk {
  code: string;
  label: string;
}

export interface RankEntry {
  rank: number;
  ticker: string;
  asset_class: string;
  category: string;
  leverage: number;
  score: number;
  composite: number;
  risk_penalty: number;
  concentration_penalty: number;
  penalties: Record<string, number>;
  coverage: number;
  short_history: boolean;
  groups: Record<string, GroupBreakdown>;
  factors: FactorEntry[];
  reasons: Reason[];
  risks: Risk[];
  prev_rank?: number | null;
  sparkline?: (number | null)[];
  ret_1d?: number | null;
}

export interface Regime {
  label: string;
  stress_score: number | null;
  n_components: number;
  contributions: Record<string, number>;
  weights_regime: string;
}

export interface Rankings extends Envelope {
  notes: string[];
  regime: Regime;
  weights: Record<string, number>;
  constraints: {
    top_n: number;
    asset_class_caps: Record<string, number>;
    category_cap: number;
    leveraged_cap: number;
    max_correlation: number;
    corr_window: number;
    concentration_penalty: number;
    min_coverage: number;
  };
  universe: { candidates: number; eligible: number; ineligible: number };
  counts: { asset_class: Record<string, number>; leveraged_or_inverse: number };
  top: RankEntry[];
  skipped: { ticker: string; score: number; reason: string }[];
  ineligible: { ticker: string; reason: string }[];
  group_labels: Record<string, string>;
  ranking_generated_at?: string;
}

export interface ChangeItem {
  ticker: string;
  asset_class: string;
  rank?: number;
  prev_rank?: number;
  change?: number;
  score_prev: number | null;
  score: number | null;
  reasons: string[];
}

export interface Changes extends Envelope {
  prev_asof: string | null;
  regime: { prev: string; cur: string } | null;
  regime_changed: boolean;
  threshold: number;
  entered: ChangeItem[];
  exited: ChangeItem[];
  movers: ChangeItem[];
  unchanged: number;
}

export interface MacroSource {
  description: string;
  source: string | null;
  is_proxy: boolean | null;
  last_obs: string | null;
  last_value: number | null;
  coverage: number | null;
}

export interface Macro extends Envelope {
  dates: string[];
  series: Record<string, (number | null)[]>;
  sources: Record<string, MacroSource>;
  curves: { label: string; date: string; points: { tenor: string; value: number | null }[] }[];
  regime: {
    dates: string[];
    label: string[];
    stress_score: (number | null)[];
    segments: { regime: string; start: string; end: string; days: number }[];
  };
}

export interface IngestRun {
  file: string;
  started_at: string | null;
  summary: Record<string, Record<string, number>>;
  problems_total: number;
  problems: { dataset: string; key: string; status: string; source?: string; message?: string }[];
}

export interface Health {
  status: "ok" | "degraded";
  status_rule: string;
  prices: { tickers: number; fresh: number; stale: { ticker: string; last_bar: string }[] };
  ingest_runs: IngestRun[];
  quality_reports: {
    file: string;
    issues: number;
    by_check: Record<string, number>;
    errors: { ticker: string; check: string; detail: string }[];
  }[];
}

export interface AssetIndexEntry {
  ticker: string;
  file: string;
  in_top: boolean;
  asset_class: string | null;
  category: string | null;
  leverage: number | null;
}

export interface Manifest extends Envelope {
  notes: string[];
  demo: boolean;
  files: string[];
  assets: AssetIndexEntry[];
  ranking_asof: string;
  backtest_asof: string | null;
  features_end: string;
  health: Health;
  warnings: string[];
}

export type Metrics = Record<string, number | null>;

export interface AssetBacktest {
  available: boolean;
  reason?: string;
  start?: string;
  end?: string;
  years?: number;
  shortened?: boolean;
  metrics?: Metrics;
  benchmark_metrics?: Metrics;
  series?: {
    dates: string[];
    equity: (number | null)[];
    drawdown: (number | null)[];
    benchmark?: (number | null)[];
  };
}

export interface Asset extends Envelope {
  ticker: string;
  asset_class: string | null;
  category: string | null;
  leverage: number | null;
  in_top: boolean;
  ranking: RankEntry | null;
  score: number | null;
  factors: {
    factor: string;
    label: string;
    group: string;
    value: number | null;
    z: number | null;
    percentile: number | null;
  }[];
  price: {
    dates: string[];
    close: (number | null)[];
    ma50: (number | null)[];
    ma200: (number | null)[];
  };
  rank_history: { date: string; rank: number | null; source: string }[];
  rank_history_note: string;
  backtest: AssetBacktest;
}

export interface FrequencyBlock {
  frequency: string;
  rebalances: number;
  first_trade: string;
  metrics: Record<string, Metrics>;
  split: { in_sample: Record<string, Metrics>; out_of_sample: Record<string, Metrics> };
  random: {
    n: number;
    seed: number;
    method: string;
    cagr: Record<string, number | null>;
    sharpe: Record<string, number | null>;
    max_drawdown: Record<string, number | null>;
    strategy_percentile: Record<string, number | null>;
  };
  ic: {
    periods: number;
    mean_ic: number | null;
    mean_rank_ic: number | null;
    rank_ic_std: number | null;
    rank_ic_t: number | null;
    rank_ic_ir_annual: number | null;
    rank_ic_hit_rate: number | null;
    deciles: {
      mean_period_return: Record<string, number | null>;
      ann_return: Record<string, number | null>;
      top_minus_bottom_mean_period: number | null;
      top_minus_bottom_t: number | null;
    };
    series: { signal: string; ic: number | null; rank_ic: number | null; n: number }[];
  };
  regimes: Record<string, { days: number } & Record<string, unknown>>;
  capacity: Record<string, number | null>;
  monthly_returns: Record<string, { year: number; month: number; ret: number | null }[]>;
  series: {
    dates: string[];
    equity: Record<string, (number | null)[]>;
    drawdown: Record<string, (number | null)[]>;
    rolling_sharpe: Record<string, (number | null)[]>;
    rolling_window: number;
  };
}

export interface Backtest extends Envelope {
  headline: string;
  period: {
    start: string;
    end: string;
    years: number;
    requested_start: string;
    shortened: boolean;
    in_sample_end: string;
  };
  assumptions: Record<string, unknown>;
  series_labels: Record<string, string>;
  frequencies: Record<string, FrequencyBlock>;
  robustness?: {
    frequency: string;
    variants: {
      name: string;
      kind: string;
      label: string;
      cagr: number | null;
      sharpe: number | null;
      max_drawdown: number | null;
      turnover_annual: number | null;
      sharpe_in_sample: number | null;
      sharpe_out_of_sample: number | null;
    }[];
    deflated_sharpe: Record<string, number | null>;
    note: string;
  };
  biases: string[];
}
