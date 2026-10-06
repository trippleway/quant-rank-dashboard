import { useCallback } from "react";
import { num } from "../lib/format";
import type { Tokens } from "../lib/theme";
import { Chart, sampleRows } from "./Chart";

export interface Line {
  name: string;
  data: (number | null)[];
  dashed?: boolean;
  /** Fixed categorical slot (0-based) so an entity keeps its color across charts. */
  slot?: number;
}

interface Props {
  title: string;
  dates: string[];
  lines: Line[];
  yName?: string;
  height?: number;
  zeroLine?: boolean;
  caption?: string;
  digits?: number;
  zoom?: boolean;
  extra?: (t: Tokens) => Record<string, unknown>;
}

/** Multi-series daily line chart on one y-axis, with crosshair tooltip and table view. */
export function TimeLines({ title, dates, lines, yName, height = 280, zeroLine, caption, digits = 2, zoom = true, extra }: Props) {
  const build = useCallback(
    (t: Tokens) => ({
      legend: { type: "scroll", show: lines.length > 1, top: 0, textStyle: { color: t.ink2 }, pageTextStyle: { color: t.ink2 } },
      grid: { left: 56, right: 24, top: (lines.length > 1 ? 28 : 0) + (yName ? 28 : 16), bottom: zoom ? 60 : 32 },
      xAxis: { type: "category", data: dates, boundaryGap: false },
      yAxis: { type: "value", scale: true, name: yName, nameTextStyle: { color: t.muted } },
      ...(zoom ? { dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, textStyle: { color: t.muted } }] } : {}),
      series: lines.map((l, i) => ({
        name: l.name,
        type: "line",
        data: l.data,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2, type: l.dashed ? "dashed" : "solid", color: t.series[(l.slot ?? i) % 8] },
        itemStyle: { color: t.series[(l.slot ?? i) % 8] },
        ...(i === 0 && zeroLine
          ? { markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: t.axis, type: "solid" }, data: [{ yAxis: 0 }] } }
          : {}),
      })),
      ...(extra ? extra(t) : {}),
    }),
    [dates, lines, yName, zeroLine, zoom, extra],
  );
  const rows = sampleRows(dates.map((d, i) => [d, ...lines.map((l) => num(l.data[i], digits))]));
  return <Chart title={title} build={build} height={height} caption={caption} table={{ columns: ["日期", ...lines.map((l) => l.name)], rows }} />;
}
