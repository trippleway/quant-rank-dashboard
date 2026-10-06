import { Link } from "react-router-dom";
import { Card, Delta, ErrorState, Loading, PageHeader, RegimeBadge, Stat } from "../components/ui";
import { useJson } from "../lib/data";
import { num, signed } from "../lib/format";
import { ASSET_CLASS } from "../lib/labels";
import type { ChangeItem, Changes as ChangesT } from "../lib/types";

function ChangeTable({ items, kind }: { items: ChangeItem[]; kind: "entered" | "exited" | "movers" }) {
  if (!items.length) return <p className="text-sm text-ink-2">無。</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-ink-2">
          <tr>
            <th scope="col" className="py-1 pr-2">標的</th>
            <th scope="col" className="pr-2">類別</th>
            {kind !== "exited" && <th scope="col" className="pr-2 text-right">今日名次</th>}
            {kind !== "entered" && <th scope="col" className="pr-2 text-right">昨日名次</th>}
            {kind === "movers" && <th scope="col" className="pr-2 text-right">變化</th>}
            <th scope="col" className="pr-2 text-right">分數（昨 → 今）</th>
            <th scope="col">原因</th>
          </tr>
        </thead>
        <tbody>
          {items.map((x) => (
            <tr key={x.ticker} className="border-t border-line align-top">
              <td className="py-1.5 pr-2 font-semibold">
                <Link className="text-accent underline" to={`/asset/${x.ticker}`}>{x.ticker}</Link>
              </td>
              <td className="pr-2 text-ink-2">{ASSET_CLASS[x.asset_class] ?? x.asset_class}</td>
              {kind !== "exited" && <td className="num pr-2 text-right">{x.rank}</td>}
              {kind !== "entered" && <td className="num pr-2 text-right">{x.prev_rank}</td>}
              {kind === "movers" && (
                <td className="pr-2 text-right">
                  <Delta value={x.change} text={signed(x.change, 0)} />
                </td>
              )}
              <td className="num pr-2 text-right whitespace-nowrap">
                {num(x.score_prev, 3)} → {num(x.score, 3)}
              </td>
              <td className="text-ink-2">
                <ul className="space-y-0.5">
                  {x.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Changes() {
  const s = useJson<ChangesT>("changes.json");
  if (s.status === "error") return <ErrorState error={s.error} />;
  if (s.status === "loading") return <Loading what="異動" />;
  const c = s.data;
  if (!c.prev_asof)
    return (
      <>
        <PageHeader title="Changes 異動" />
        <p role="status" className="text-sm text-ink-2">沒有前一交易日的特徵資料，無法比較。</p>
      </>
    );
  const up = c.movers.filter((m) => (m.change ?? 0) > 0);
  const down = c.movers.filter((m) => (m.change ?? 0) < 0);
  return (
    <>
      <PageHeader
        title="Changes 異動"
        subtitle={
          <>
            <span className="num">{c.asof}</span> vs 前一交易日 <span className="num">{c.prev_asof}</span>。兩天的排名都只用各自當日以前的資料計算。
            「大幅升降」門檻：名次變動 ≥ {c.threshold}。
          </>
        }
      />
      {c.regime && (
        <p className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-2">
          Regime：<RegimeBadge regime={c.regime.prev} /> → <RegimeBadge regime={c.regime.cur} />
          {c.regime_changed ? <strong className="text-ink">（權重組改變，排名可能大幅變動）</strong> : "（未改變）"}
        </p>
      )}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="新進" value={c.entered.length} />
        <Stat label="掉出" value={c.exited.length} />
        <Stat label="大幅上升" value={up.length} />
        <Stat label="大幅下降" value={down.length} />
        <Stat label="名次不變" value={c.unchanged} />
      </div>
      <div className="grid gap-4">
        <Card title={`新進 Top 50（${c.entered.length}）`}>
          <ChangeTable items={c.entered} kind="entered" />
        </Card>
        <Card title={`掉出 Top 50（${c.exited.length}）`}>
          <ChangeTable items={c.exited} kind="exited" />
        </Card>
        <Card title={`大幅升降（${c.movers.length}）`}>
          <ChangeTable items={c.movers} kind="movers" />
        </Card>
      </div>
      <p className="mt-4 text-xs text-ink-2">
        原因欄說明：「貢獻 ±x」是該因子群組對因子合成分數的貢獻變化；「受約束排除」代表分數仍高但被資產類別／產業／相關性等上限擋下；
        名次變化也可能只是其他標的分數改變造成的相對排序。
      </p>
    </>
  );
}
