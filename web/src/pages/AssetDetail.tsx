import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Chart, sampleRows } from "../components/Chart";
import { Card, ErrorState, Loading, PageHeader, Stat, Tag } from "../components/ui";
import { useJson } from "../lib/data";
import { num, pct } from "../lib/format";
import { ASSET_CLASS, GROUP, leverageTag } from "../lib/labels";
import type { Tokens } from "../lib/theme";
import type { Asset, Manifest } from "../lib/types";

function Picker({ m, current }: { m: Manifest; current?: string }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const list = m.assets.filter((a) => !q || a.ticker.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <Card title="選擇標的">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs text-ink-2">代號（已發布 {m.assets.length} 檔：今日 Top 50、今日掉出者與基準）</span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && list[0]) nav(`/asset/${list[0].ticker}`);
          }}
          className="w-48 rounded border border-line bg-surface px-2 py-1"
          placeholder="輸入代號"
        />
      </label>
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {list.map((a) => (
          <li key={a.ticker}>
            <Link
              to={`/asset/${a.ticker}`}
              aria-current={a.ticker === current ? "page" : undefined}
              className={`num inline-block rounded border border-line px-2 py-0.5 text-xs ${
                a.ticker === current ? "bg-surface-2 font-semibold text-ink" : "text-accent hover:bg-surface-2"
              }`}
            >
              {a.ticker}
              {!a.in_top && <span className="sr-only">（未在今日 Top 50）</span>}
              {!a.in_top && <span aria-hidden="true" className="text-ink-2">°</span>}
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-2">° 未在今日 Top 50（掉出者或基準）。</p>
    </Card>
  );
}

function PriceChart({ a }: { a: Asset }) {
  const build = useCallback(
    (t: Tokens) => ({
      color: t.series.slice(0, 3),
      grid: { left: 64, right: 24, top: 56, bottom: 64 },
      xAxis: { type: "category", data: a.price.dates, boundaryGap: false },
      yAxis: { type: "value", scale: true, name: "調整後價格", nameTextStyle: { color: t.muted } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, textStyle: { color: t.muted } }],
      series: [
        { name: "收盤（調整後）", type: "line", data: a.price.close, showSymbol: false, lineStyle: { width: 2 } },
        { name: "50 日均線", type: "line", data: a.price.ma50, showSymbol: false, lineStyle: { width: 1.5 } },
        { name: "200 日均線", type: "line", data: a.price.ma200, showSymbol: false, lineStyle: { width: 1.5, type: "dashed" } },
      ],
    }),
    [a],
  );
  const rows = sampleRows(a.price.dates.map((d, i) => [d, num(a.price.close[i]), num(a.price.ma50[i]), num(a.price.ma200[i])]));
  return (
    <Chart title={`${a.ticker} 價格與均線`} build={build} height={340} table={{ columns: ["日期", "收盤", "MA50", "MA200"], rows }} />
  );
}

function Radar({ a }: { a: Asset }) {
  const fs = useMemo(() => a.factors.filter((f) => f.percentile != null), [a]);
  const build = useCallback(
    (t: Tokens) => ({
      tooltip: { trigger: "item" },
      legend: { show: false },
      radar: {
        indicator: fs.map((f) => ({ name: f.label, max: 100 })),
        radius: "56%",
        center: ["50%", "52%"],
        axisName: { color: t.ink2, fontSize: 10 },
        splitLine: { lineStyle: { color: t.grid } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: t.axis } },
      },
      series: [
        {
          type: "radar",
          name: "因子分位",
          symbolSize: 8,
          lineStyle: { width: 2, color: t.series[0] },
          itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2 },
          areaStyle: { color: t.series[0], opacity: 0.15 },
          data: [{ name: `${a.ticker} 因子分位（0–100）`, value: fs.map((f) => Math.round((f.percentile ?? 0) * 100)) }],
        },
      ],
    }),
    [a, fs],
  );
  if (!fs.length) return <p className="text-sm text-ink-2">沒有可用的因子分位。</p>;
  return (
    <Chart
      title={`${a.ticker} 因子雷達圖（今日合格標的中的分位數）`}
      build={build}
      height={320}
      caption="分位數已依因子方向調整：越外圈越有利（例如低波動、回撤較淺）。"
      table={{
        columns: ["因子", "群組", "原始值", "z", "分位"],
        rows: a.factors.map((f) => [f.label, GROUP[f.group] ?? f.group, num(f.value, 3), num(f.z), pct(f.percentile, 0)]),
      }}
    />
  );
}

function RankHistory({ a }: { a: Asset }) {
  const h = a.rank_history;
  const build = useCallback(
    (t: Tokens) => ({
      legend: { show: false },
      grid: { left: 48, right: 24, top: 28, bottom: 32 },
      xAxis: { type: "category", data: h.map((x) => x.date) },
      yAxis: { type: "value", inverse: true, min: 1, max: 50, name: "名次", nameLocation: "start", nameTextStyle: { color: t.muted } },
      series: [
        {
          name: "名次",
          type: "line",
          data: h.map((x) => x.rank),
          connectNulls: false,
          symbol: "circle",
          symbolSize: 8,
          lineStyle: { width: 2, color: t.series[0] },
          itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2 },
        },
      ],
    }),
    [h],
  );
  const inTop = h.filter((x) => x.rank != null).length;
  return (
    <>
      <p className="mb-2 text-sm text-ink-2">
        {h.length} 個觀察點中有 <span className="num">{inTop}</span> 次進入 Top 50（斷線處＝當期未進榜）。
      </p>
      <Chart
        title={`${a.ticker} 歷史排名`}
        build={build}
        height={220}
        caption={a.rank_history_note}
        table={{ columns: ["日期", "名次", "來源"], rows: h.map((x) => [x.date, x.rank ?? "未進榜", x.source === "daily" ? "每日榜" : "回測月度"]) }}
      />
    </>
  );
}

function SingleBacktest({ a }: { a: Asset }) {
  const b = a.backtest;
  const s = b.series;
  const build = useCallback(
    (t: Tokens) => ({
      color: t.series.slice(0, 2),
      grid: { left: 56, right: 24, top: 56, bottom: 32 },
      xAxis: { type: "category", data: s?.dates ?? [], boundaryGap: false },
      yAxis: { type: "value", scale: true, name: "淨值（起點 = 1）", nameTextStyle: { color: t.muted } },
      series: [
        { name: `${a.ticker} 買進持有`, type: "line", data: s?.equity ?? [], showSymbol: false, lineStyle: { width: 2 } },
        ...(s?.benchmark ? [{ name: "SPY 買進持有", type: "line", data: s.benchmark, showSymbol: false, lineStyle: { width: 2 } }] : []),
      ],
    }),
    [a, s],
  );
  if (!b.available || !s) return <p className="text-sm text-ink-2">無法回測：{b.reason}</p>;
  const m = b.metrics ?? {};
  const bm = b.benchmark_metrics;
  const rows: [string, string, string][] = [
    ["CAGR", pct(m.cagr), pct(bm?.cagr)],
    ["年化波動", pct(m.ann_vol), pct(bm?.ann_vol)],
    ["Sharpe", num(m.sharpe), num(bm?.sharpe)],
    ["Sortino", num(m.sortino), num(bm?.sortino)],
    ["最大回撤", pct(m.max_drawdown), pct(bm?.max_drawdown)],
    ["Calmar", num(m.calmar), num(bm?.calmar)],
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <Chart
          title={`${a.ticker} 單獨回測：買進持有 vs SPY`}
          build={build}
          height={280}
          table={{ columns: ["週", a.ticker, "SPY"], rows: sampleRows(s.dates.map((d, i) => [d, num(s.equity[i], 3), num(s.benchmark?.[i], 3)])) }}
        />
      </div>
      <div>
        <table className="w-full text-sm">
          <caption className="mb-1 text-left text-xs text-ink-2">
            <span className="num">{b.start}</span> ～ <span className="num">{b.end}</span>（{num(b.years, 1)} 年{b.shortened ? "，歷史不足 5 年已縮短" : ""}）
          </caption>
          <thead className="text-left text-xs text-ink-2">
            <tr>
              <th scope="col">指標</th>
              <th scope="col" className="text-right">{a.ticker}</th>
              <th scope="col" className="text-right">SPY</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, v, w]) => (
              <tr key={k} className="border-t border-line">
                <td className="py-1">{k}</td>
                <td className="num text-right">{v}</td>
                <td className="num text-right">{bm ? w : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-2">
          這是單一標的買進持有的歷史模擬，不是排名策略，也不代表未來報酬；含存活者偏誤與調整價限制。
        </p>
      </div>
    </div>
  );
}

function AssetView({ m, ticker }: { m: Manifest; ticker: string }) {
  const entry = useMemo(() => m.assets.find((x) => x.ticker.toUpperCase() === ticker.toUpperCase()), [m, ticker]);
  const s = useJson<Asset>(entry ? entry.file : null);
  if (!entry)
    return (
      <>
        <PageHeader title={`Asset Detail：${ticker}`} />
        <p role="alert" className="mb-4 text-sm text-ink">
          <span aria-hidden="true">⚠ </span>
          {ticker} 沒有發布詳情頁（只發布今日 Top 50、今日掉出者與基準）。
        </p>
        <Picker m={m} />
      </>
    );
  if (s.status === "error") return <ErrorState error={s.error} />;
  if (s.status === "loading") return <Loading what={`${ticker} 詳情`} />;
  const a = s.data;
  const lev = leverageTag(a.leverage);
  return (
    <>
      <PageHeader
        title={`${a.ticker}`}
        subtitle={
          <>
            {ASSET_CLASS[a.asset_class ?? ""] ?? a.asset_class} · {a.category} · 資料日 <span className="num">{a.asof}</span>
          </>
        }
      >
        <div className="flex flex-wrap gap-1">
          {lev && <Tag tone="warn">{lev}</Tag>}
          {a.ranking?.short_history && <Tag tone="warn">歷史不足、信心低</Tag>}
        </div>
      </PageHeader>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="今日名次" value={a.ranking ? `#${a.ranking.rank}` : "未進榜"} />
        <Stat label="分數" value={num(a.ranking?.score ?? a.score, 3)} sub={a.ranking ? undefined : "合格池中的原始分數"} />
        <Stat label="5 年 CAGR（買進持有）" value={pct(a.backtest.metrics?.cagr)} />
        <Stat label="5 年最大回撤" value={pct(a.backtest.metrics?.max_drawdown)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="價格與均線" className="lg:col-span-2">
          <PriceChart a={a} />
        </Card>
        <Card title="因子雷達圖">
          <Radar a={a} />
        </Card>
        <Card title="歷史排名變化" className="lg:col-span-2">
          <RankHistory a={a} />
        </Card>
        <Card title="主要風險">
          {a.ranking ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
              {a.ranking.risks.map((r) => (
                <li key={r.code}>{r.label}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-2">未在今日 Top 50，未產生風險標籤；請參考因子雷達圖的低風險群組。</p>
          )}
          {a.ranking && (
            <>
              <h3 className="mb-1 mt-3 text-xs font-semibold text-ink">入選理由</h3>
              <ul className="list-disc pl-5 text-sm text-ink-2">
                {a.ranking.reasons.map((r) => (
                  <li key={r.factor}>{r.label}</li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title="單獨回測" className="lg:col-span-3">
          <SingleBacktest a={a} />
        </Card>
      </div>
      <div className="mt-4">
        <Picker m={m} current={a.ticker} />
      </div>
    </>
  );
}

export default function AssetDetail() {
  const { ticker } = useParams();
  const man = useJson<Manifest>("manifest.json");
  if (man.status === "error") return <ErrorState error={man.error} />;
  if (man.status === "loading") return <Loading what="標的清單" />;
  if (!ticker)
    return (
      <>
        <PageHeader title="Asset Detail 標的詳情" subtitle="價格與均線、因子雷達圖、歷史排名、單獨回測與主要風險。" />
        <Picker m={man.data} />
      </>
    );
  return <AssetView key={ticker} m={man.data} ticker={ticker} />;
}
