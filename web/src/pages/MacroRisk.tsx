import { useCallback, useMemo } from "react";
import { Chart } from "../components/Chart";
import { TimeLines } from "../components/TimeLines";
import { Card, ErrorState, Loading, PageHeader, RegimeBadge, Tag } from "../components/ui";
import { useJson } from "../lib/data";
import { num, pct } from "../lib/format";
import { MACRO, REGIME } from "../lib/labels";
import { rebase } from "../lib/stats";
import type { Tokens } from "../lib/theme";
import type { Macro } from "../lib/types";

function YieldCurve({ m }: { m: Macro }) {
  const tenors = useMemo(() => m.curves[0]?.points.map((p) => p.tenor) ?? [], [m]);
  const build = useCallback(
    (t: Tokens) => ({
      tooltip: { trigger: "axis" },
      grid: { left: 56, right: 24, top: 56, bottom: 32 },
      xAxis: { type: "category", data: tenors, boundaryGap: false },
      yAxis: { type: "value", scale: true, name: "殖利率 %", nameTextStyle: { color: t.muted } },
      series: m.curves.map((c, i) => ({
        name: `${c.label}（${c.date}）`,
        type: "line",
        data: c.points.map((p) => p.value),
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { width: 2, type: i === 0 ? "solid" : i === 1 ? "dashed" : "dotted", color: t.series[i] },
        itemStyle: { color: t.series[i], borderColor: t.surface, borderWidth: 2 },
      })),
    }),
    [m, tenors],
  );
  return (
    <Chart
      title="美國公債殖利率曲線"
      build={build}
      height={280}
      table={{ columns: ["期限", ...m.curves.map((c) => `${c.label} ${c.date}`)], rows: tenors.map((tn, j) => [tn, ...m.curves.map((c) => num(c.points[j]?.value))]) }}
    />
  );
}

function RegimeTimeline({ m }: { m: Macro }) {
  const r = m.regime;
  const extra = useCallback(
    (t: Tokens) => {
      const color: Record<string, string> = { risk_on: t.good, risk_off: t.critical };
      return {
        series: [
          {
            name: "壓力分數",
            type: "line",
            data: r.stress_score,
            showSymbol: false,
            lineStyle: { width: 2, color: t.ink2 },
            itemStyle: { color: t.ink2 },
            markArea: {
              silent: true,
              data: r.segments
                .filter((s) => s.regime in color)
                .map((s) => [
                  { xAxis: s.start, itemStyle: { color: color[s.regime], opacity: 0.14 } },
                  { xAxis: s.end },
                ]),
            },
          },
        ],
      };
    },
    [r],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const l of r.label) c[l] = (c[l] ?? 0) + 1;
    return c;
  }, [r]);
  return (
    <>
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-ink-2">
        {Object.entries(counts).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1">
            <RegimeBadge regime={k} /> <span className="num">{v}</span> 天（{pct(v / r.label.length, 0)}）
          </span>
        ))}
      </div>
      <TimeLines
        title="Regime 歷史時間軸（壓力分數；綠底 risk-on、紅底 risk-off）"
        dates={r.dates}
        lines={[{ name: "壓力分數", data: r.stress_score }]}
        zeroLine
        extra={extra}
        caption="壓力分數 > 0 偏 risk-off；底色為當日 regime 標籤（只用當日以前資料判定）。"
      />
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-ink-2">最近 15 段 regime</summary>
        <table className="mt-2 w-full text-left">
          <thead className="text-ink-2">
            <tr>
              <th scope="col">Regime</th>
              <th scope="col">開始</th>
              <th scope="col">結束</th>
              <th scope="col" className="text-right">交易日</th>
            </tr>
          </thead>
          <tbody>
            {r.segments.slice(-15).reverse().map((s) => (
              <tr key={s.start} className="border-t border-line">
                <td className="py-0.5">{REGIME[s.regime]?.label ?? s.regime}</td>
                <td className="num">{s.start}</td>
                <td className="num">{s.end}</td>
                <td className="num text-right">{s.days}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function Sources({ m }: { m: Macro }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">宏觀資料來源</caption>
        <thead className="text-left text-ink-2">
          <tr>
            <th scope="col" className="py-1">序列</th>
            <th scope="col">說明</th>
            <th scope="col">來源</th>
            <th scope="col" className="text-right">最後觀測</th>
            <th scope="col" className="text-right">最新值</th>
            <th scope="col" className="text-right">5 年覆蓋</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(m.sources).map(([k, s]) => (
            <tr key={k} className="border-t border-line">
              <td className="py-1">{MACRO[k]?.label ?? k}</td>
              <td className="text-ink-2">{s.description}</td>
              <td>
                {s.source ?? <Tag tone="warn">無資料</Tag>} {s.is_proxy && <Tag tone="warn">代理</Tag>}
              </td>
              <td className="num text-right">{s.last_obs ?? "—"}</td>
              <td className="num text-right">{num(s.last_value)}</td>
              <td className="num text-right">{pct(s.coverage, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MacroRisk() {
  const s = useJson<Macro>("macro.json");
  const derived = useMemo(() => {
    if (s.status !== "ready") return null;
    const x = s.data.series;
    const get = (k: string) => x[k] ?? s.data.dates.map(() => null);
    return {
      get,
      fx: [
        { name: "美元指數", data: rebase(get("usd_broad")), slot: 0 },
        { name: "WTI 原油", data: rebase(get("wti")), slot: 1 },
        { name: "黃金", data: rebase(get("gold")), slot: 3 },
      ],
      hasGdelt: [...get("gdelt_tone_economy"), ...get("gdelt_tone_geopolitics")].some((v) => v != null),
    };
  }, [s]);
  if (s.status === "error") return <ErrorState error={s.error} />;
  if (s.status === "loading" || !derived) return <Loading what="宏觀資料" />;
  const m = s.data;
  const { get } = derived;
  return (
    <>
      <PageHeader
        title="Macro & Risk 總體與風險"
        subtitle={
          <>
            最近 5 年，資料日 <span className="num">{m.asof}</span>。每個值都以「發布可得日」對齊（不使用當日尚未公布的數據）。這些序列是國際局勢的
            <strong>代理指標</strong>，不是局勢本身的量測。
          </>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="殖利率曲線">
          <YieldCurve m={m} />
        </Card>
        <Card title="曲線斜率 10Y−2Y">
          <TimeLines title="10Y−2Y 利差（百分點）" dates={m.dates} lines={[{ name: "10Y−2Y", data: get("curve_10y2y") }]} yName="pp" zeroLine />
        </Card>
        <Card title="公債殖利率">
          <TimeLines
            title="3 個月、2 年、10 年、30 年殖利率"
            dates={m.dates}
            yName="%"
            lines={[
              { name: "3M", data: get("ust_3m") },
              { name: "2Y", data: get("ust_2y") },
              { name: "10Y", data: get("ust_10y") },
              { name: "30Y", data: get("ust_30y") },
            ]}
          />
        </Card>
        <Card title="信用利差">
          <TimeLines
            title="高收益與投資級債 OAS"
            dates={m.dates}
            yName="%"
            lines={[
              { name: "HY OAS", data: get("hy_oas") },
              { name: "IG OAS", data: get("ig_oas") },
            ]}
            caption={`HY/IG OAS 來自 FRED（ICE BofA），免費來源只提供約 3 年歷史：5 年覆蓋 ${pct(m.sources.hy_oas?.coverage, 0)}；缺值期間 regime 改用 HYG/IEF 信用代理。`}
          />
        </Card>
        <Card title="VIX">
          <TimeLines title="VIX 收盤" dates={m.dates} lines={[{ name: "VIX", data: get("vix") }]} />
        </Card>
        <Card title="美元、油價、黃金">
          <TimeLines
            title="美元、WTI、黃金（起點 = 100）"
            dates={m.dates}
            yName="指數化"
            lines={derived.fx}
            digits={1}
            caption="三者單位不同，統一以期初 = 100 指數化後放在同一軸比較。"
          />
        </Card>
        <Card title="GDELT 全球新聞語調" className="lg:col-span-2">
          {derived.hasGdelt ? (
            <TimeLines
              title="GDELT 經濟與地緣政治新聞語調"
              dates={m.dates}
              lines={[
                { name: "經濟", data: get("gdelt_tone_economy") },
                { name: "地緣政治", data: get("gdelt_tone_geopolitics") },
              ]}
              zeroLine
            />
          ) : (
            <p role="status" className="text-sm text-ink-2">
              <span aria-hidden="true">⚠ </span>
              目前沒有 GDELT 語調資料（來源抓取失敗或被限流，pipeline 已降級：regime 以其餘成分計算）。不以假資料補上。
            </p>
          )}
        </Card>
        <Card title="Regime 歷史" className="lg:col-span-2">
          <RegimeTimeline m={m} />
        </Card>
        <Card title="資料來源與覆蓋" className="lg:col-span-2">
          <Sources m={m} />
        </Card>
      </div>
    </>
  );
}
