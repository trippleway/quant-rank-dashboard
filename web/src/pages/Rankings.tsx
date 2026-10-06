import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Delta, ErrorState, Loading, PageHeader, RegimeBadge, Sparkline, Tag } from "../components/ui";
import { useJson } from "../lib/data";
import { num, pct, rankChange, signed, signedPct } from "../lib/format";
import { ASSET_CLASS, GROUP, leverageTag } from "../lib/labels";
import { sortBy, type SortDir } from "../lib/stats";
import type { RankEntry, Rankings as RankingsT } from "../lib/types";

type Key = "rank" | "ticker" | "score" | "composite" | "risk_penalty" | "change" | "ret_1d" | "coverage";

const COLUMNS: { key: Key; label: string; numeric: boolean }[] = [
  { key: "rank", label: "#", numeric: true },
  { key: "ticker", label: "標的", numeric: false },
  { key: "score", label: "分數", numeric: true },
  { key: "composite", label: "因子合成", numeric: true },
  { key: "risk_penalty", label: "風險懲罰", numeric: true },
  { key: "change", label: "名次變化", numeric: true },
  { key: "ret_1d", label: "1 日報酬", numeric: true },
  { key: "coverage", label: "因子覆蓋", numeric: true },
];

const keyFn = (k: Key) => (e: RankEntry) => {
  if (k === "change") return rankChange(e.rank, e.prev_rank);
  return e[k] ?? null;
};

export function riskTags(e: RankEntry): { text: string; warn: boolean }[] {
  const tags: { text: string; warn: boolean }[] = [];
  const lev = leverageTag(e.leverage);
  if (lev) tags.push({ text: lev, warn: true });
  if (e.short_history) tags.push({ text: "歷史不足、信心低", warn: true });
  for (const r of e.risks) {
    if (r.code === "systematic" || r.code === "leveraged_inverse" || r.code === "short_history") continue;
    tags.push({ text: r.label, warn: r.code === "volatility_etp" });
  }
  return tags;
}

function Breakdown({ e, labels }: { e: RankEntry; labels: Record<string, string> }) {
  const groups = Object.entries(e.groups).filter(([, g]) => (g.weight ?? 0) > 0);
  const maxAbs = Math.max(0.01, ...groups.map(([, g]) => Math.abs(g.contribution)));
  return (
    <div className="grid gap-4 p-3 lg:grid-cols-2">
      <div>
        <h3 className="mb-2 text-xs font-semibold text-ink">分數分解（因子群組貢獻）</h3>
        <table className="w-full text-xs">
          <thead className="text-left text-ink-2">
            <tr>
              <th scope="col">群組</th>
              <th scope="col" className="text-right">群組分數</th>
              <th scope="col" className="text-right">權重</th>
              <th scope="col" className="text-right">貢獻</th>
              <th scope="col" className="w-1/3"><span className="sr-only">貢獻長條</span></th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([g, v]) => (
              <tr key={g} className="border-t border-line">
                <td className="py-1">{labels[g] ?? GROUP[g] ?? g}</td>
                <td className="num text-right">{num(v.score)}</td>
                <td className="num text-right">{pct(v.weight, 0)}</td>
                <td className="num text-right">{signed(v.contribution, 3)}</td>
                <td className="pl-2" aria-hidden="true">
                  <div className="relative h-2 rounded bg-surface-2">
                    <div
                      className="absolute top-0 h-2 rounded"
                      style={{
                        left: v.contribution >= 0 ? "50%" : `${50 - (Math.abs(v.contribution) / maxAbs) * 50}%`,
                        width: `${(Math.abs(v.contribution) / maxAbs) * 50}%`,
                        background: v.contribution >= 0 ? "var(--div-pos)" : "var(--div-neg)",
                      }}
                    />
                  </div>
                </td>
              </tr>
            ))}
            <tr className="border-t border-line font-semibold">
              <td className="py-1">因子合成</td>
              <td colSpan={2} />
              <td className="num text-right">{num(e.composite, 3)}</td>
              <td />
            </tr>
            <tr>
              <td className="py-1">− 風險懲罰</td>
              <td colSpan={2} className="text-ink-2">
                {Object.entries(e.penalties).map(([k, v]) => `${k} ${v}`).join("、") || "無"}
              </td>
              <td className="num text-right">{num(-e.risk_penalty, 3)}</td>
              <td />
            </tr>
            <tr>
              <td className="py-1">− 集中度懲罰</td>
              <td colSpan={2} />
              <td className="num text-right">{num(-e.concentration_penalty, 3)}</td>
              <td />
            </tr>
            <tr className="border-t border-line font-semibold">
              <td className="py-1">最終分數</td>
              <td colSpan={2} />
              <td className="num text-right">{num(e.score, 3)}</td>
              <td />
            </tr>
          </tbody>
        </table>
        <h3 className="mb-1 mt-3 text-xs font-semibold text-ink">入選理由（前三大正貢獻）</h3>
        <ul className="list-disc pl-5 text-xs text-ink-2">
          {e.reasons.map((r) => (
            <li key={r.factor}>
              {r.label}：z <span className="num">{num(r.z)}</span>，貢獻 <span className="num">{signed(r.contribution, 3)}</span>
            </li>
          ))}
        </ul>
        <h3 className="mb-1 mt-3 text-xs font-semibold text-ink">主要風險</h3>
        <ul className="list-disc pl-5 text-xs text-ink-2">
          {e.risks.map((r) => (
            <li key={r.code}>{r.label}</li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="mb-2 text-xs font-semibold text-ink">各因子（原始值、橫斷面 z、貢獻）</h3>
        <table className="w-full text-xs">
          <thead className="text-left text-ink-2">
            <tr>
              <th scope="col">因子</th>
              <th scope="col">群組</th>
              <th scope="col" className="text-right">原始值</th>
              <th scope="col" className="text-right">z</th>
              <th scope="col" className="text-right">貢獻</th>
            </tr>
          </thead>
          <tbody>
            {e.factors.map((f) => (
              <tr key={f.factor} className="border-t border-line">
                <td className="py-0.5">{f.label}</td>
                <td className="text-ink-2">{labels[f.group] ?? f.group}</td>
                <td className="num text-right">{num(f.value, 3)}</td>
                <td className="num text-right">{num(f.z)}</td>
                <td className="num text-right">{f.z == null ? "缺值（降權）" : signed(f.contribution, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-2">
          因子覆蓋 <span className="num">{pct(e.coverage, 0)}</span>：缺少的因子以降權處理，不當作 0。
        </p>
        <Link to={`/asset/${e.ticker}`} className="mt-2 inline-block text-xs text-accent underline">
          {e.ticker} 詳情（價格、雷達圖、歷史排名、單獨回測）→
        </Link>
      </div>
    </div>
  );
}

export default function Rankings() {
  const s = useJson<RankingsT>("rankings.json");
  const [cls, setCls] = useState("all");
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: Key; dir: SortDir }>({ key: "rank", dir: "asc" });
  const [open, setOpen] = useState<Set<string>>(new Set());

  const rows = useMemo(() => {
    if (s.status !== "ready") return [];
    const f = s.data.top.filter(
      (e) =>
        (cls === "all" || e.asset_class === cls) &&
        (cat === "all" || e.category === cat) &&
        (!q || e.ticker.toLowerCase().includes(q.trim().toLowerCase())),
    );
    return sortBy(f, keyFn(sort.key), sort.dir);
  }, [s, cls, cat, q, sort]);

  if (s.status === "error") return <ErrorState error={s.error} />;
  if (s.status === "loading") return <Loading what="排名" />;
  const r = s.data;
  const classes = [...new Set(r.top.map((e) => e.asset_class))];
  const cats = [...new Set(r.top.filter((e) => cls === "all" || e.asset_class === cls).map((e) => e.category))].sort();
  const toggle = (t: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });
  const setSortKey = (key: Key) =>
    setSort((cur) => ({ key, dir: cur.key === key ? (cur.dir === "asc" ? "desc" : "asc") : key === "rank" || key === "ticker" ? "asc" : "desc" }));

  return (
    <>
      <PageHeader
        title="Rankings 排名"
        subtitle={
          <>
            <span className="num">{r.asof}</span> 的 Top {r.constraints.top_n}。Regime <RegimeBadge regime={r.regime.label} />{" "}
            · 名次變化對照前一交易日。點選列可展開分數分解。
          </>
        }
      />
      <Card>
        <div className="mb-3 flex flex-wrap items-end gap-3 text-sm" role="search">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-2">資產類別</span>
            <select value={cls} onChange={(e) => { setCls(e.target.value); setCat("all"); }} className="rounded border border-line bg-surface px-2 py-1">
              <option value="all">全部（{r.top.length}）</option>
              {classes.map((c) => (
                <option key={c} value={c}>
                  {ASSET_CLASS[c] ?? c}（{r.counts.asset_class[c] ?? 0}）
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-2">產業／子類別</span>
            <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded border border-line bg-surface px-2 py-1">
              <option value="all">全部</option>
              {cats.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-2">代號搜尋</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="例如 SPY" className="w-32 rounded border border-line bg-surface px-2 py-1" />
          </label>
          <span className="text-xs text-ink-2" aria-live="polite">顯示 {rows.length} 檔</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Top 50 排名表，可排序</caption>
            <thead className="text-left text-xs text-ink-2">
              <tr>
                <th scope="col"><span className="sr-only">展開</span></th>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={`py-1 pr-2 ${c.numeric ? "text-right" : ""}`}
                    aria-sort={sort.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                  >
                    <button type="button" onClick={() => setSortKey(c.key)} className="hover:text-ink">
                      {c.label}
                      <span aria-hidden="true">{sort.key === c.key ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}</span>
                    </button>
                  </th>
                ))}
                <th scope="col" className="pr-2">類別 / 產業</th>
                <th scope="col" className="pr-2">近 3 月</th>
                <th scope="col">風險標籤</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const ch = rankChange(e.rank, e.prev_rank);
                const isOpen = open.has(e.ticker);
                return (
                  <Fragment key={e.ticker}>
                    <tr className="border-t border-line hover:bg-surface-2">
                      <td className="pr-1">
                        <button
                          type="button"
                          onClick={() => toggle(e.ticker)}
                          aria-expanded={isOpen}
                          aria-label={`${isOpen ? "收合" : "展開"} ${e.ticker} 分數分解`}
                          className="h-6 w-6 rounded text-ink-2 hover:bg-surface-2"
                        >
                          {isOpen ? "▾" : "▸"}
                        </button>
                      </td>
                      <td className="num py-1.5 pr-2 text-right">{e.rank}</td>
                      <td className="pr-2 font-semibold">
                        <Link className="text-accent underline" to={`/asset/${e.ticker}`}>{e.ticker}</Link>
                      </td>
                      <td className="num pr-2 text-right">{num(e.score, 3)}</td>
                      <td className="num pr-2 text-right">{num(e.composite, 3)}</td>
                      <td className="num pr-2 text-right">{e.risk_penalty ? num(-e.risk_penalty, 3) : "0"}</td>
                      <td className="pr-2 text-right">
                        {e.prev_rank == null ? <Tag>新進</Tag> : <Delta value={ch} text={ch === 0 ? "0" : signed(ch, 0)} />}
                      </td>
                      <td className="pr-2 text-right"><Delta value={e.ret_1d} text={signedPct(e.ret_1d, 2)} /></td>
                      <td className="num pr-2 text-right">{pct(e.coverage, 0)}</td>
                      <td className="pr-2 text-xs text-ink-2">
                        {ASSET_CLASS[e.asset_class] ?? e.asset_class}
                        <br />
                        {e.category}
                      </td>
                      <td className="pr-2"><Sparkline values={e.sparkline ?? []} label={e.ticker} /></td>
                      <td className="space-x-1 space-y-1">
                        {riskTags(e).map((t) => (
                          <Tag key={t.text} tone={t.warn ? "warn" : "neutral"}>{t.text}</Tag>
                        ))}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-surface-2/50">
                        <td colSpan={COLUMNS.length + 4}>
                          <Breakdown e={e} labels={r.group_labels} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="選取約束">
          <ul className="space-y-1 text-sm text-ink-2">
            <li>
              資產類別上限：
              <span className="num">
                {Object.entries(r.constraints.asset_class_caps).map(([k, v]) => `${ASSET_CLASS[k] ?? k} ${v}`).join("、")}
              </span>
            </li>
            <li>單一產業／子類別上限 <span className="num">{r.constraints.category_cap}</span>；槓桿／反向上限 <span className="num">{r.constraints.leveraged_cap}</span>（今日入選 <span className="num">{r.counts.leveraged_or_inverse}</span>）</li>
            <li>相關性去重：<span className="num">{r.constraints.corr_window}</span> 日報酬相關 &gt; <span className="num">{r.constraints.max_correlation}</span> 只留分數高者</li>
            <li>集中度懲罰 <span className="num">{r.constraints.concentration_penalty}</span>；因子覆蓋下限 <span className="num">{pct(r.constraints.min_coverage, 0)}</span></li>
          </ul>
        </Card>
        <Card title="未入選說明">
          <details>
            <summary className="cursor-pointer text-sm text-ink-2">因約束被略過（{r.skipped.length}）</summary>
            <ul className="mt-2 space-y-0.5 text-xs text-ink-2">
              {r.skipped.map((x) => (
                <li key={x.ticker}><span className="num font-semibold text-ink">{x.ticker}</span>（分數 <span className="num">{num(x.score, 3)}</span>）：{x.reason}</li>
              ))}
            </ul>
          </details>
          <details className="mt-2">
            <summary className="cursor-pointer text-sm text-ink-2">不合格（{r.ineligible.length}）</summary>
            <ul className="mt-2 space-y-0.5 text-xs text-ink-2">
              {r.ineligible.map((x) => (
                <li key={x.ticker}><span className="num font-semibold text-ink">{x.ticker}</span>：{x.reason}</li>
              ))}
            </ul>
          </details>
        </Card>
      </div>
    </>
  );
}
