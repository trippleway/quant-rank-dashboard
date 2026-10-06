import { useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { Chart } from "../components/Chart";
import { Card, Delta, ErrorState, Loading, PageHeader, RegimeBadge, Sparkline, Stat, StatusBadge, Tag } from "../components/ui";
import { useJson } from "../lib/data";
import { dateTime, num, pct, rankChange, signed } from "../lib/format";
import { ASSET_CLASS, GROUP, MACRO, REGIME_COMPONENT } from "../lib/labels";
import { changeOver, lastValid, trailingPercentile } from "../lib/stats";
import type { Tokens } from "../lib/theme";
import type { Macro, Manifest, Rankings } from "../lib/types";

const GAUGES = ["vix", "hy_oas", "curve_10y2y", "ig_oas"] as const;

function RegimeCard({ r }: { r: Rankings }) {
  const entries = useMemo(() => Object.entries(r.regime.contributions).sort((a, b) => a[1] - b[1]), [r]);
  const build = useCallback(
    (t: Tokens) => ({
      legend: { show: false },
      grid: { left: 150, right: 40, top: 8, bottom: 24 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", name: "", axisLabel: { color: t.muted, fontFamily: t.mono } },
      yAxis: {
        type: "category",
        data: entries.map(([k]) => REGIME_COMPONENT[k] ?? k),
        axisLabel: { color: t.ink2 },
        splitLine: { show: false },
      },
      series: [
        {
          type: "bar",
          name: "壓力貢獻",
          barMaxWidth: 14,
          data: entries.map(([, v]) => ({
            value: v,
            itemStyle: { color: v > 0 ? t.divNeg : t.divPos, borderRadius: v > 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] },
          })),
        },
      ],
    }),
    [entries],
  );
  return (
    <Card title="今日市場 Regime">
      <div className="flex flex-wrap items-center gap-3">
        <RegimeBadge regime={r.regime.label} size="lg" />
        <span className="text-sm text-ink-2">
          壓力分數 <span className="num text-ink">{signed(r.regime.stress_score, 3)}</span>（{r.regime.n_components} 個成分）
        </span>
      </div>
      <p className="mt-2 text-xs text-ink-2">
        權重組：<span className="num">{r.regime.weights_regime}</span> ·{" "}
        {Object.entries(r.weights)
          .filter(([, w]) => w > 0)
          .map(([g, w]) => `${GROUP[g] ?? g} ${pct(w, 0)}`)
          .join(" · ")}
      </p>
      <Chart
        title="Regime 壓力分數各成分貢獻（正值＝偏 risk-off）"
        height={Math.max(160, entries.length * 26)}
        build={build}
        caption="正值（紅）推向 risk-off，負值（藍）推向 risk-on。成分都是代理指標。"
        table={{ columns: ["成分", "貢獻"], rows: entries.map(([k, v]) => [REGIME_COMPONENT[k] ?? k, v.toFixed(4)]) }}
      />
    </Card>
  );
}

function Gauges({ m }: { m: Macro }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {GAUGES.map((k) => {
        const xs = m.series[k] ?? [];
        const last = lastValid(xs);
        const p = trailingPercentile(xs);
        const d = changeOver(xs, 21);
        const src = m.sources[k];
        return (
          <Stat
            key={k}
            label={MACRO[k]?.label ?? k}
            value={last ? `${num(last.value)}${MACRO[k]?.unit === "%" || MACRO[k]?.unit === "pp" ? MACRO[k]!.unit : ""}` : "—"}
            sub={
              <>
                <span>
                  1 年分位 <span className="num">{p == null ? "—" : pct(p, 0)}</span>
                </span>
                {p != null && (
                  <span className="mt-1 block h-1.5 w-full rounded bg-surface-2" aria-hidden="true">
                    <span className="block h-1.5 rounded bg-accent" style={{ width: `${Math.round(p * 100)}%` }} />
                  </span>
                )}
                <span className="mt-1 block">
                  1 個月變化 <Delta value={d} text={signed(d)} neutral />
                </span>
                {src?.is_proxy && <Tag tone="warn">代理來源 {src.source}</Tag>}
                {!last && <Tag tone="warn">無資料</Tag>}
              </>
            }
          />
        );
      })}
    </div>
  );
}

function Top10({ r }: { r: Rankings }) {
  return (
    <Card title="Top 10 快照" actions={<Link className="text-sm text-accent underline" to="/rankings">完整 Top 50 →</Link>}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">今日排名前 10 名</caption>
          <thead className="text-left text-xs text-ink-2">
            <tr>
              <th scope="col" className="py-1 pr-2">#</th>
              <th scope="col" className="pr-2">標的</th>
              <th scope="col" className="pr-2">類別</th>
              <th scope="col" className="pr-2 text-right">分數</th>
              <th scope="col" className="pr-2 text-right">名次變化</th>
              <th scope="col" className="pr-2">近 3 月</th>
              <th scope="col">主要入選因子</th>
            </tr>
          </thead>
          <tbody>
            {r.top.slice(0, 10).map((e) => {
              const ch = rankChange(e.rank, e.prev_rank);
              return (
                <tr key={e.ticker} className="border-t border-line">
                  <td className="num py-1.5 pr-2">{e.rank}</td>
                  <td className="pr-2 font-semibold">
                    <Link className="text-accent underline" to={`/asset/${e.ticker}`}>{e.ticker}</Link>
                  </td>
                  <td className="pr-2 text-ink-2">{ASSET_CLASS[e.asset_class] ?? e.asset_class}</td>
                  <td className="num pr-2 text-right">{num(e.score, 3)}</td>
                  <td className="pr-2 text-right">
                    {e.prev_rank == null ? <Tag>新進</Tag> : <Delta value={ch} text={ch === 0 ? "0" : signed(ch, 0)} />}
                  </td>
                  <td className="pr-2"><Sparkline values={e.sparkline ?? []} label={e.ticker} /></td>
                  <td className="text-ink-2">{e.reasons.map((x) => x.label).join("、")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function HealthCard({ m }: { m: Manifest }) {
  const h = m.health;
  const latestRun = h.ingest_runs[0];
  return (
    <Card title="資料更新與健康狀態">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge ok={h.status === "ok"} label={h.status === "ok" ? "正常" : "部分降級"} />
        {m.demo && <Tag tone="warn">DEMO 資料</Tag>}
      </div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-2">排名資料日</dt>
        <dd className="num">{m.ranking_asof}</dd>
        <dt className="text-ink-2">回測資料日</dt>
        <dd className="num">{m.backtest_asof ?? "—"}</dd>
        <dt className="text-ink-2">發布時間</dt>
        <dd className="num">{dateTime(m.generated_at)}</dd>
        <dt className="text-ink-2">價格最新</dt>
        <dd className="num">
          {h.prices.fresh} / {h.prices.tickers} 檔
        </dd>
        <dt className="text-ink-2">最近一次抓取</dt>
        <dd className="num">
          {latestRun ? `${dateTime(latestRun.started_at)}（問題 ${latestRun.problems_total}）` : "—"}
        </dd>
      </dl>
      {h.prices.stale.length > 0 && (
        <p className="mt-2 text-xs text-ink-2">
          資料過期（不進入今日排名）：
          <span className="num">{h.prices.stale.map((s) => `${s.ticker}（${s.last_bar}）`).join("、")}</span>
        </p>
      )}
      {m.warnings.map((w) => (
        <p key={w} role="alert" className="mt-2 text-xs text-ink">
          <span aria-hidden="true">⚠ </span>
          {w}
        </p>
      ))}
      <p className="mt-2 text-xs text-muted">{h.status_rule}</p>
      <Link to="/methodology#health" className="mt-1 inline-block text-xs text-accent underline">
        抓取紀錄與資料品質明細 →
      </Link>
    </Card>
  );
}

export default function Overview() {
  const man = useJson<Manifest>("manifest.json");
  const rk = useJson<Rankings>("rankings.json");
  const mac = useJson<Macro>("macro.json");
  if (man.status === "error") return <ErrorState error={man.error} />;
  if (rk.status === "error") return <ErrorState error={rk.error} />;
  if (man.status === "loading" || rk.status === "loading") return <Loading what="總覽" />;
  const r = rk.data;
  return (
    <>
      <PageHeader
        title="Overview 總覽"
        subtitle={
          <>
            資料日 <span className="num">{r.asof}</span> 收盤後計算，供下一個交易日參考。合格標的{" "}
            <span className="num">{r.universe.eligible}</span> / {r.universe.candidates}。
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <RegimeCard r={r} />
        <HealthCard m={man.data} />
      </div>
      <h2 className="mb-2 mt-6 text-sm font-semibold text-ink">風險儀表</h2>
      {mac.status === "ready" ? <Gauges m={mac.data} /> : mac.status === "error" ? <ErrorState error={mac.error} /> : <Loading what="宏觀資料" />}
      <div className="mt-6">
        <Top10 r={r} />
      </div>
    </>
  );
}
