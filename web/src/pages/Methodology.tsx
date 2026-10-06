import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { RichText } from "../components/RichText";
import { Card, ErrorState, Loading, PageHeader, StatusBadge, Tag } from "../components/ui";
import { useJson } from "../lib/data";
import { dateTime, pct } from "../lib/format";
import { ASSET_CLASS, GROUP, MACRO } from "../lib/labels";
import type { Backtest, Macro, Manifest, Rankings } from "../lib/types";

function Health({ m }: { m: Manifest }) {
  const h = m.health;
  return (
    <Card title="資料健康：抓取紀錄與品質報告" id="health">
      <div className="mb-2 flex items-center gap-2">
        <StatusBadge ok={h.status === "ok"} label={h.status === "ok" ? "正常" : "部分降級"} />
        <span className="text-xs text-ink-2">{h.status_rule}</span>
      </div>
      <h3 className="mt-3 text-xs font-semibold text-ink">最近 {h.ingest_runs.length} 次 ingest</h3>
      <div className="overflow-x-auto">
        <table className="mt-1 w-full text-xs">
          <thead className="text-left text-ink-2">
            <tr>
              <th scope="col" className="py-1">開始時間</th>
              <th scope="col">資料集：ok / 備援 / 降級 / 失敗</th>
              <th scope="col" className="text-right">問題數</th>
            </tr>
          </thead>
          <tbody>
            {h.ingest_runs.map((r) => (
              <tr key={r.file} className="border-t border-line align-top">
                <td className="num py-1">{dateTime(r.started_at)}</td>
                <td className="num">
                  {Object.entries(r.summary).map(([k, v]) => (
                    <div key={k}>
                      {k}: {v.ok ?? 0} / {v.fallback ?? 0} / {v.degraded ?? 0} / {v.failed ?? 0}
                    </div>
                  ))}
                  {r.problems.length > 0 && (
                    <details>
                      <summary className="cursor-pointer text-ink-2">問題明細</summary>
                      <ul>
                        {r.problems.map((p, i) => (
                          <li key={i}>
                            {p.dataset}/{p.key}：{p.status} {p.source ? `（${p.source}）` : ""} {p.message}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
                <td className="num text-right">{r.problems_total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="mt-4 text-xs font-semibold text-ink">資料品質報告（缺值、異常跳動、過期）</h3>
      <ul className="mt-1 space-y-1 text-xs text-ink-2">
        {h.quality_reports.map((q) => (
          <li key={q.file}>
            <span className="num">{q.file}</span>：{q.issues} 項{" "}
            {Object.entries(q.by_check)
              .map(([k, v]) => `${k} ×${v}`)
              .join("、")}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-2">
        價格最新 <span className="num">{h.prices.fresh}</span> / {h.prices.tickers} 檔；過期：
        <span className="num">{h.prices.stale.map((s) => `${s.ticker}（${s.last_bar}）`).join("、") || "無"}</span>
      </p>
    </Card>
  );
}

export default function Methodology() {
  const man = useJson<Manifest>("manifest.json");
  const rk = useJson<Rankings>("rankings.json");
  const bt = useJson<Backtest>("backtest.json");
  const mac = useJson<Macro>("macro.json");
  const loc = useLocation();
  const ready = man.status === "ready";
  useEffect(() => {
    if (ready && loc.hash === "#health") document.getElementById("health")?.scrollIntoView();
  }, [ready, loc.hash]);
  if (man.status === "error") return <ErrorState error={man.error} />;
  if (man.status === "loading") return <Loading what="方法與資料" />;
  const m = man.data;
  return (
    <>
      <PageHeader title="Methodology & Data 方法與資料" subtitle="排名與回測怎麼做、資料從哪裡來、有哪些已知限制。完整文件在 repo 的 docs/。" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="排名方法（摘要）">
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-ink-2">
            <li><strong className="text-ink">Universe 過濾：</strong>60 日平均成交額、最低價格、最少上市天數；資料過期或缺漏嚴重者剔除。</li>
            <li>
              <strong className="text-ink">因子：</strong>
              {Object.values(GROUP).join("、")}。財報型品質／價值因子未納入（免費來源沒有 point-in-time 財報），缺值降權不當作 0。
            </li>
            <li><strong className="text-ink">Regime：</strong>VIX、信用利差、殖利率曲線、SPY 趨勢、美元／油價／黃金動能、GDELT 語調合成壓力分數，分成 risk-on / neutral / risk-off；只用當日以前資料。</li>
            <li><strong className="text-ink">合成分數：</strong>winsorize + z-score（依資產類別分組），按 regime 權重加總，再扣風險懲罰（槓桿、反向、波動率 ETP、高波動、歷史不足）與集中度懲罰。</li>
            <li><strong className="text-ink">Top 50 與約束：</strong>資產類別、單一產業、槓桿／反向上限，高相關去重；每檔附前三大貢獻因子與主要風險。</li>
          </ol>
          {rk.status === "ready" && (
            <p className="mt-2 text-xs text-ink-2">
              今日權重（{rk.data.regime.weights_regime}）：
              {Object.entries(rk.data.weights).map(([g, w]) => `${GROUP[g] ?? g} ${pct(w, 0)}`).join("、")}；類別上限：
              {Object.entries(rk.data.constraints.asset_class_caps).map(([k, v]) => `${ASSET_CLASS[k] ?? k} ${v}`).join("、")}。
            </p>
          )}
          <p className="mt-2 text-xs text-ink-2">
            詳見 <code className="num">docs/methodology.md</code>、<code className="num">docs/adr/0003</code>、<code className="num">docs/adr/0004</code>。
          </p>
        </Card>
        <Card title="回測方法（摘要）">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
            <li>Walk-forward：每週／每月第一個交易日收盤後，用當日以前資料呼叫同一個每日排名；t+1 收盤成交。</li>
            <li>成本：依流動性分級單邊 5–10 bps，槓桿／反向／波動率產品加倍，計入換手。</li>
            <li>基準：SPY、60/40（SPY+AGG）、等權重 universe、隨機選股 1000 次。</li>
            <li>穩健性：樣本內 3 年／樣本外、參數敏感度、因子 ablation、Deflated Sharpe。</li>
            <li>每月為事前選定的主要頻率；參數未依回測結果調整。</li>
          </ul>
          <p className="mt-2 text-xs text-ink-2">
            詳見 <code className="num">docs/backtest.md</code>、<code className="num">docs/adr/0005</code>、自動報告 <code className="num">docs/backtest-report.md</code>。
          </p>
        </Card>
        <Card title="資料來源" className="lg:col-span-2">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
            <li>價格：yfinance（主要）→ Yahoo chart API（備援）→ 本地快取；調整後價格。</li>
            <li>宏觀：FRED API（有 key 時）→ FRED CSV → yfinance 代理（例如 ^TNX、DX-Y.NYB、CL=F）。代理來源會在 UI 標示。</li>
            <li>新聞語調：GDELT DOC API；失敗或限流時降級，regime 以其餘成分計算。</li>
          </ul>
          {mac.status === "ready" && (
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(mac.data.sources).map(([k, s]) => (
                <Tag key={k} tone={s.source == null || s.is_proxy ? "warn" : "neutral"}>
                  {MACRO[k]?.label ?? k}：{s.source ?? "無資料"}
                  {s.is_proxy ? "（代理）" : ""}
                </Tag>
              ))}
            </div>
          )}
        </Card>
        <Card title="已知限制與偏誤" className="lg:col-span-2">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
            {rk.status === "ready" && rk.data.notes.map((n) => <li key={n}>{n}</li>)}
            {m.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            {bt.status === "ready" && bt.data.biases.map((b) => <li key={b}><RichText text={b} /></li>)}
          </ul>
          {bt.status === "error" && <p className="mt-2 text-xs text-ink-2">回測偏誤清單無法載入：{bt.error}</p>}
        </Card>
        <div className="lg:col-span-2">
          <Health m={m} />
        </div>
        <Card title="免責聲明" className="lg:col-span-2">
          <p className="text-sm text-ink">
            本網站所有內容僅供研究與學習，不構成投資建議。排名與回測皆為模型輸出與歷史模擬，不代表未來報酬；使用者應自行判斷並承擔風險。
          </p>
          <p className="mt-1 text-xs text-ink-2 num">{m.disclaimer}</p>
          <p className="mt-2 text-xs text-ink-2">
            資料版本：schema <span className="num">{m.schema_version}</span>；排名 <span className="num">{m.ranking_asof}</span>；回測{" "}
            <span className="num">{m.backtest_asof ?? "—"}</span>；特徵至 <span className="num">{m.features_end}</span>；發布{" "}
            <span className="num">{dateTime(m.generated_at)}</span>。{m.demo ? "（DEMO 資料）" : "（真實 pipeline 輸出，非示範資料）"}
          </p>
        </Card>
      </div>
    </>
  );
}
