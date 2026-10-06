import { useCallback, useMemo, useState } from "react";
import { Chart } from "../components/Chart";
import { RichText } from "../components/RichText";
import { TimeLines, type Line } from "../components/TimeLines";
import { Card, ErrorState, Loading, PageHeader, RegimeBadge, Stat } from "../components/ui";
import { useJson } from "../lib/data";
import { num, pct, usd } from "../lib/format";
import type { Tokens } from "../lib/theme";
import type { Backtest as BacktestT, FrequencyBlock, Metrics } from "../lib/types";

// Fixed slot per entity so colors never change between charts or frequencies.
const SLOT: Record<string, number> = { strategy: 0, spy: 1, sixty_forty: 2, equal_weight: 6 };
const SERIES = ["strategy", "spy", "sixty_forty", "equal_weight"] as const;
const METRIC_COLS: { key: string; label: string; fmt: (x: number | null | undefined) => string }[] = [
  { key: "cagr", label: "CAGR", fmt: (x) => pct(x) },
  { key: "ann_vol", label: "年化波動", fmt: (x) => pct(x) },
  { key: "sharpe", label: "Sharpe", fmt: (x) => num(x) },
  { key: "sortino", label: "Sortino", fmt: (x) => num(x) },
  { key: "max_drawdown", label: "最大回撤", fmt: (x) => pct(x) },
  { key: "calmar", label: "Calmar", fmt: (x) => num(x) },
  { key: "turnover_annual", label: "年換手", fmt: (x) => (x == null ? "—" : `${num(x, 1)}×`) },
  { key: "cost_drag_annual", label: "成本拖累/年", fmt: (x) => pct(x, 2) },
  { key: "win_rate_periods", label: "每期勝率", fmt: (x) => pct(x, 0) },
];
const MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

function MetricsTable({ metrics, labels }: { metrics: Record<string, Metrics>; labels: Record<string, string> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">績效指標比較</caption>
        <thead className="text-left text-xs text-ink-2">
          <tr>
            <th scope="col" className="py-1">組合</th>
            {METRIC_COLS.map((c) => (
              <th key={c.key} scope="col" className="px-2 text-right">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(metrics).map(([k, m]) => (
            <tr key={k} className={`border-t border-line ${k === "strategy" ? "font-semibold" : ""}`}>
              <th scope="row" className="py-1.5 text-left font-normal">
                {k === "strategy" ? <strong>{labels[k] ?? k}</strong> : (labels[k] ?? k)}
              </th>
              {METRIC_COLS.map((c) => (
                <td key={c.key} className="num px-2 text-right">{c.fmt(m[c.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquityChart({ f, labels }: { f: FrequencyBlock; labels: Record<string, string> }) {
  const e = f.series.equity;
  const band = useMemo(() => {
    const lo = e.random_p05 ?? [];
    const hi = e.random_p95 ?? [];
    return { lo, width: hi.map((h, i) => (h == null || lo[i] == null ? null : h - lo[i]!)) };
  }, [e]);
  const lines: Line[] = useMemo(
    () => SERIES.filter((k) => e[k]).map((k) => ({ name: labels[k] ?? k, data: e[k]!, slot: SLOT[k] })),
    [e, labels],
  );
  const extra = useCallback(
    (t: Tokens) => ({
      series: [
        ...lines.map((l) => ({
          name: l.name,
          type: "line",
          data: l.data,
          showSymbol: false,
          lineStyle: { width: l.slot === 0 ? 2.5 : 1.5, color: t.series[l.slot ?? 0] },
          itemStyle: { color: t.series[l.slot ?? 0] },
        })),
        { name: "隨機 p05", type: "line", data: band.lo, stack: "band", showSymbol: false, lineStyle: { opacity: 0 }, itemStyle: { color: t.muted }, tooltip: { show: true } },
        {
          name: "隨機 p05–p95 區間",
          type: "line",
          data: band.width,
          stack: "band",
          showSymbol: false,
          lineStyle: { opacity: 0 },
          areaStyle: { color: t.muted, opacity: 0.18 },
          itemStyle: { color: t.muted },
        },
        { name: "隨機中位數", type: "line", data: e.random_p50 ?? [], showSymbol: false, lineStyle: { width: 1.5, type: "dashed", color: t.muted }, itemStyle: { color: t.muted } },
      ],
      legend: { type: "scroll", top: 0, textStyle: { color: t.ink2 }, pageTextStyle: { color: t.ink2 }, data: [...lines.map((l) => l.name), "隨機中位數", "隨機 p05–p95 區間"] },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.surface,
        borderColor: t.axis,
        textStyle: { color: t.ink1, fontSize: 12 },
        valueFormatter: (v: unknown) => (typeof v === "number" ? v.toFixed(3) : "—"),
      },
    }),
    [lines, band, e],
  );
  return (
    <TimeLines
      title="權益曲線 vs 基準（起點 = 1）"
      dates={f.series.dates}
      lines={[...lines, { name: "隨機 p05", data: e.random_p05 ?? [] }, { name: "隨機中位數", data: e.random_p50 ?? [] }, { name: "隨機 p95", data: e.random_p95 ?? [] }]}
      yName="淨值"
      height={340}
      digits={3}
      extra={extra}
      caption="灰色區間為 1000 次隨機選股組合的 5%–95% 分位（每日分位，非單一路徑）；tooltip 中「p05–p95 區間」數值為區間寬度。"
    />
  );
}

function Heatmap({ f, labels }: { f: FrequencyBlock; labels: Record<string, string> }) {
  const [who, setWho] = useState("strategy");
  const { rows, years, maxAbs } = useMemo(() => {
    const rows = f.monthly_returns[who] ?? [];
    return {
      rows,
      years: [...new Set(rows.map((r) => r.year))].sort(),
      maxAbs: Math.max(0.01, ...rows.map((r) => Math.abs(r.ret ?? 0))),
    };
  }, [f, who]);
  const build = useCallback(
    (t: Tokens) => ({
      legend: { show: false },
      tooltip: {
        trigger: "item",
        backgroundColor: t.surface,
        borderColor: t.axis,
        textStyle: { color: t.ink1 },
        formatter: (p: { value: [number, number, number | null] }) =>
          `${years[p.value[1]]} ${MONTHS[p.value[0]]}：${pct(p.value[2])}`,
      },
      grid: { left: 56, right: 24, top: 8, bottom: 64 },
      xAxis: { type: "category", data: MONTHS, splitArea: { show: false } },
      yAxis: { type: "category", data: years.map(String), inverse: true },
      visualMap: {
        min: -maxAbs,
        max: maxAbs,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemHeight: 160,
        text: [`+${(maxAbs * 100).toFixed(0)}%`, `−${(maxAbs * 100).toFixed(0)}%`],
        textStyle: { color: t.ink2 },
        inRange: { color: [t.divNeg, t.divMid, t.divPos] },
      },
      series: [
        {
          type: "heatmap",
          data: rows.map((r) => [r.month - 1, years.indexOf(r.year), r.ret]),
          label: { show: true, color: t.ink1, fontSize: 10, fontFamily: t.mono, formatter: (p: { value: [number, number, number | null] }) => (p.value[2] == null ? "" : (p.value[2] * 100).toFixed(1)) },
          itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 2 },
        },
      ],
    }),
    [rows, years, maxAbs],
  );
  return (
    <>
      <div className="mb-2 flex gap-1" role="group" aria-label="選擇月報酬序列">
        {Object.keys(f.monthly_returns).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={who === k}
            onClick={() => setWho(k)}
            className={`rounded border border-line px-2 py-0.5 text-xs ${who === k ? "bg-surface-2 font-semibold text-ink" : "text-ink-2"}`}
          >
            {labels[k] ?? k}
          </button>
        ))}
      </div>
      <Chart
        title={`月報酬熱力圖：${labels[who] ?? who}（%）`}
        build={build}
        height={Math.max(200, years.length * 34 + 80)}
        caption="藍＝正報酬、紅＝負報酬，格內數字為月報酬 %（顏色之外另有數字）。"
        table={{
          columns: ["年", ...MONTHS],
          rows: years.map((y) => [y, ...MONTHS.map((_, m) => pct(rows.find((r) => r.year === y && r.month === m + 1)?.ret))]),
        }}
      />
    </>
  );
}

function IcBlock({ f }: { f: FrequencyBlock }) {
  const ic = f.ic;
  const build = useCallback(
    (t: Tokens) => ({
      legend: { show: false },
      grid: { left: 56, right: 24, top: 16, bottom: 32 },
      xAxis: { type: "category", data: ic.series.map((s) => s.signal) },
      yAxis: { type: "value", name: "Rank IC", nameTextStyle: { color: t.muted } },
      series: [
        {
          name: "Rank IC",
          type: "bar",
          barMaxWidth: 8,
          data: ic.series.map((s) => ({ value: s.rank_ic, itemStyle: { color: (s.rank_ic ?? 0) >= 0 ? t.divPos : t.divNeg } })),
        },
      ],
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, textStyle: { color: t.ink1 } },
    }),
    [ic],
  );
  const dec = Object.entries(ic.deciles.ann_return);
  const buildDec = useCallback(
    (t: Tokens) => ({
      legend: { show: false },
      grid: { left: 56, right: 24, top: 16, bottom: 40 },
      xAxis: { type: "category", data: dec.map(([k]) => k), name: "十分位（10 = 分數最高）", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.muted } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%`, color: t.muted } },
      series: [
        {
          name: "年化報酬",
          type: "bar",
          barMaxWidth: 28,
          data: dec.map(([, v]) => ({ value: v, itemStyle: { color: t.series[0], borderRadius: [4, 4, 0, 0] } })),
        },
      ],
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => pct(v as number), backgroundColor: t.surface, textStyle: { color: t.ink1 } },
    }),
    [dec],
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <div className="mb-2 grid grid-cols-3 gap-2">
          <Stat label="平均 Rank IC" value={num(ic.mean_rank_ic, 3)} sub={<>t = <span className="num">{num(ic.rank_ic_t)}</span></>} />
          <Stat label="IC 命中率" value={pct(ic.rank_ic_hit_rate, 0)} sub={`${ic.periods} 期`} />
          <Stat label="年化 IR" value={num(ic.rank_ic_ir_annual)} />
        </div>
        <Chart title="每期 Rank IC（訊號日分數 vs 下期報酬）" build={build} height={220} table={{ columns: ["訊號日", "IC", "Rank IC", "N"], rows: ic.series.map((s) => [s.signal, num(s.ic, 3), num(s.rank_ic, 3), s.n]) }} />
      </div>
      <div>
        <p className="mb-2 text-sm text-ink-2">
          十分位多空價差（每期）<span className="num text-ink">{pct(ic.deciles.top_minus_bottom_mean_period, 2)}</span>，t ={" "}
          <span className="num text-ink">{num(ic.deciles.top_minus_bottom_t)}</span>。|t| &lt; 2 代表沒有統計上顯著的區分能力。
        </p>
        <Chart title="十分位組合年化報酬" build={buildDec} height={260} table={{ columns: ["十分位", "年化報酬"], rows: dec.map(([k, v]) => [k, pct(v)]) }} />
      </div>
    </div>
  );
}

function SplitTable({ f, labels, cut }: { f: FrequencyBlock; labels: Record<string, string>; cut: string }) {
  const keys = Object.keys(f.split.in_sample);
  return (
    <table className="w-full text-sm">
      <caption className="mb-1 text-left text-xs text-ink-2">
        樣本內：起點 ～ <span className="num">{cut}</span>；樣本外：之後。參數沒有在樣本內調整（事前設定）。
      </caption>
      <thead className="text-left text-xs text-ink-2">
        <tr>
          <th scope="col">組合</th>
          <th scope="col" className="text-right">CAGR 內</th>
          <th scope="col" className="text-right">CAGR 外</th>
          <th scope="col" className="text-right">Sharpe 內</th>
          <th scope="col" className="text-right">Sharpe 外</th>
          <th scope="col" className="text-right">MDD 外</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((k) => {
          const a = f.split.in_sample[k] ?? {};
          const b = f.split.out_of_sample[k] ?? {};
          return (
            <tr key={k} className="border-t border-line">
              <th scope="row" className="py-1 text-left font-normal">{labels[k] ?? k}</th>
              <td className="num text-right">{pct(a.cagr)}</td>
              <td className="num text-right">{pct(b.cagr)}</td>
              <td className="num text-right">{num(a.sharpe)}</td>
              <td className="num text-right">{num(b.sharpe)}</td>
              <td className="num text-right">{pct(b.max_drawdown)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RegimeTable({ f, labels }: { f: FrequencyBlock; labels: Record<string, string> }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-ink-2">
        <tr>
          <th scope="col">Regime</th>
          <th scope="col" className="text-right">天數</th>
          {SERIES.map((k) => (
            <th key={k} scope="col" className="text-right">{labels[k] ?? k} 年化</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Object.entries(f.regimes).map(([r, v]) => (
          <tr key={r} className="border-t border-line">
            <th scope="row" className="py-1 text-left font-normal"><RegimeBadge regime={r} /></th>
            <td className="num text-right">{v.days}</td>
            {SERIES.map((k) => (
              <td key={k} className="num text-right">{pct((v[k] as Metrics | undefined)?.ann_return)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Assumptions({ b }: { b: BacktestT }) {
  const a = b.assumptions;
  const costs = a.costs as { tiers_bps: { min_adv_usd: number; bps: number }[]; complex_multiplier: number; multiplier: number } | undefined;
  const items = Object.entries(a).filter(([k]) => k !== "costs");
  return (
    <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-2 num">{k}</dt>
          <dd className="text-ink">{typeof v === "boolean" ? (v ? "是" : "否") : String(v)}</dd>
        </div>
      ))}
      {costs && (
        <>
          <dt className="text-ink-2 num">costs</dt>
          <dd>
            單邊成本依 60 日平均成交額分級：
            {costs.tiers_bps.map((t) => `≥ ${usd(t.min_adv_usd)}：${t.bps} bps`).join("；")}；槓桿／反向／波動率產品 ×{costs.complex_multiplier}；全域倍數 ×{costs.multiplier}
          </dd>
        </>
      )}
    </dl>
  );
}

function Robustness({ b }: { b: BacktestT }) {
  const r = b.robustness;
  if (!r) return <p className="text-sm text-ink-2">這次回測沒有執行穩健性檢查（--no-robustness）。</p>;
  const d = r.deflated_sharpe;
  return (
    <>
      <p className="mb-2 text-sm text-ink-2">{r.note}</p>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="PSR（Sharpe > 0）" value={pct(d.psr_vs_zero, 0)} />
        <Stat label="Deflated Sharpe" value={pct(d.deflated_sharpe, 0)} sub={`試驗數 ${num(d.n_trials, 0)}`} />
        <Stat label="偏態" value={num(d.skew)} />
        <Stat label="峰態" value={num(d.kurtosis)} />
      </div>
      <p className="mb-2 text-xs text-ink-2">
        Deflated Sharpe 校正了多重檢定：低於 95% 代表無法排除「試了很多變體而碰巧找到好結果」。
      </p>
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">敏感度與 ablation 變體</caption>
          <thead className="sticky top-0 bg-surface text-left text-xs text-ink-2">
            <tr>
              <th scope="col">變體</th>
              <th scope="col">類型</th>
              <th scope="col" className="text-right">CAGR</th>
              <th scope="col" className="text-right">Sharpe</th>
              <th scope="col" className="text-right">MDD</th>
              <th scope="col" className="text-right">年換手</th>
              <th scope="col" className="text-right">Sharpe 內</th>
              <th scope="col" className="text-right">Sharpe 外</th>
            </tr>
          </thead>
          <tbody>
            {r.variants.map((v) => (
              <tr key={v.name} className={`border-t border-line ${v.kind === "base" ? "font-semibold" : ""}`}>
                <th scope="row" className="py-1 text-left font-normal">{v.label}</th>
                <td className="text-ink-2">{v.kind === "base" ? "基準" : v.kind === "sensitivity" ? "敏感度" : "ablation"}</td>
                <td className="num text-right">{pct(v.cagr)}</td>
                <td className="num text-right">{num(v.sharpe)}</td>
                <td className="num text-right">{pct(v.max_drawdown)}</td>
                <td className="num text-right">{num(v.turnover_annual, 1)}×</td>
                <td className="num text-right">{num(v.sharpe_in_sample)}</td>
                <td className="num text-right">{num(v.sharpe_out_of_sample)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function Backtest() {
  const s = useJson<BacktestT>("backtest.json");
  const [freq, setFreq] = useState<string | null>(null);
  if (s.status === "error") return <ErrorState error={s.error} hint={<>請執行 <code className="num">make backtest publish</code>。</>} />;
  if (s.status === "loading") return <Loading what="回測" />;
  const b = s.data;
  const primary = String(b.assumptions.primary_frequency ?? "monthly");
  const fk = freq ?? primary;
  const f = b.frequencies[fk];
  if (!f) return <ErrorState error={`回測輸出缺少 ${fk} 頻率`} />;
  const labels = b.series_labels;
  const dd: Line[] = SERIES.filter((k) => f.series.drawdown[k]).map((k) => ({ name: labels[k] ?? k, data: f.series.drawdown[k]!, slot: SLOT[k] }));
  const rs: Line[] = SERIES.filter((k) => f.series.rolling_sharpe[k]).map((k) => ({ name: labels[k] ?? k, data: f.series.rolling_sharpe[k]!, slot: SLOT[k] }));
  const rp = f.random.strategy_percentile;
  return (
    <>
      <PageHeader
        title="Backtest 回測"
        subtitle={
          <>
            <span className="num">{b.period.start}</span> ～ <span className="num">{b.period.end}</span>（{num(b.period.years, 1)} 年
            {b.period.shortened ? `，歷史不足已從 ${b.period.requested_start} 縮短` : ""}）· 資料日 <span className="num">{b.asof}</span>
          </>
        }
      >
        <div role="group" aria-label="再平衡頻率" className="flex gap-1">
          {Object.keys(b.frequencies).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={fk === k}
              onClick={() => setFreq(k)}
              className={`rounded border border-line px-3 py-1 text-sm ${fk === k ? "bg-surface-2 font-semibold text-ink" : "text-ink-2"}`}
            >
              {k === "monthly" ? "每月" : k === "weekly" ? "每週" : k}
              {k === primary ? "（主要）" : ""}
            </button>
          ))}
        </div>
      </PageHeader>
      <div role="note" className="mb-4 rounded-lg border border-[var(--status-serious)] bg-surface p-3 text-sm text-ink">
        <span aria-hidden="true">⚠ </span>
        {b.headline}
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="策略 CAGR" value={pct(f.metrics.strategy?.cagr)} sub={<>SPY <span className="num">{pct(f.metrics.spy?.cagr)}</span> · 等權 <span className="num">{pct(f.metrics.equal_weight?.cagr)}</span></>} />
        <Stat label="策略 Sharpe" value={num(f.metrics.strategy?.sharpe)} sub={<>SPY <span className="num">{num(f.metrics.spy?.sharpe)}</span></>} />
        <Stat label="策略最大回撤" value={pct(f.metrics.strategy?.max_drawdown)} sub={<>SPY <span className="num">{pct(f.metrics.spy?.max_drawdown)}</span></>} />
        <Stat
          label="在隨機基準中的分位"
          value={pct(rp.cagr, 0)}
          sub={<>CAGR 分位（Sharpe <span className="num">{pct(rp.sharpe, 0)}</span>）；50% ＝ 與隨機選股相當</>}
        />
      </div>
      <div className="grid gap-4">
        <Card title="權益曲線 vs 基準">
          <EquityChart f={f} labels={labels} />
        </Card>
        <Card title="指標比較表">
          <MetricsTable metrics={f.metrics} labels={labels} />
          <p className="mt-2 text-xs text-ink-2">
            {f.rebalances} 次再平衡，首次成交 <span className="num">{f.first_trade}</span>。隨機基準：{f.random.method}（n = {f.random.n}，seed {f.random.seed}）。
          </p>
        </Card>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="回撤">
            <TimeLines title="回撤" dates={f.series.dates} lines={dd} yName="回撤" digits={3} />
          </Card>
          <Card title={`滾動 Sharpe（${f.series.rolling_window} 日）`}>
            <TimeLines title="滾動 Sharpe" dates={f.series.dates} lines={rs} zeroLine />
          </Card>
        </div>
        <Card title="月報酬熱力圖">
          <Heatmap f={f} labels={labels} />
        </Card>
        <Card title="選股能力：IC 與十分位">
          <IcBlock f={f} />
        </Card>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="樣本內 / 樣本外">
            <SplitTable f={f} labels={labels} cut={b.period.in_sample_end} />
          </Card>
          <Card title="各 regime 下的表現">
            <RegimeTable f={f} labels={labels} />
            <p className="mt-2 text-xs text-ink-2">
              容量（成交不超過持股 ADV 的 {pct(f.capacity.participation, 0)}）：中位數約 <span className="num">{usd(f.capacity.median_aum_usd)}</span>，最低{" "}
              <span className="num">{usd(f.capacity.min_aum_usd)}</span>。
            </p>
          </Card>
        </div>
        <Card title="穩健性：敏感度、Ablation、Deflated Sharpe">
          <Robustness b={b} />
        </Card>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="參數與假設">
            <Assumptions b={b} />
          </Card>
          <Card title="偏誤與限制（必讀）">
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
              {b.biases.map((x) => (
                <li key={x}><RichText text={x} /></li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
