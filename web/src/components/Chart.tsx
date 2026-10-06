import { BarChart, HeatmapChart, LineChart, RadarChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { readTokens, useThemeVersion, type Tokens } from "../lib/theme";

echarts.use([
  LineChart,
  BarChart,
  HeatmapChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  DataZoomComponent,
  VisualMapComponent,
  RadarComponent,
  CanvasRenderer,
]);

export type Option = echarts.EChartsCoreOption;

/** Shared chrome: recessive axes/grid, themed text, crosshair tooltips. */
export function baseOption(t: Tokens): Option {
  const axis = {
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid, width: 1 } },
  };
  return {
    animation: false,
    textStyle: { color: t.ink2, fontFamily: "system-ui, sans-serif" },
    grid: { left: 56, right: 24, top: 40, bottom: 36, containLabel: false },
    legend: { type: "scroll", top: 0, textStyle: { color: t.ink2 }, icon: "roundRect", itemWidth: 14, pageTextStyle: { color: t.ink2 } },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: t.axis } },
      backgroundColor: t.surface,
      borderColor: t.axis,
      textStyle: { color: t.ink1, fontSize: 12 },
      confine: true,
    },
    xAxis: { ...axis, splitLine: { show: false } },
    yAxis: { ...axis },
  };
}

export interface TableView {
  columns: string[];
  rows: (string | number)[][];
}

interface Props {
  title: string;
  build: (t: Tokens) => Option;
  height?: number;
  table?: TableView;
  caption?: ReactNode;
}

/** ECharts wrapper: rebuilt on theme change, resized with its container, disposed on unmount. */
export function Chart({ title, build, height = 300, table, caption }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useThemeVersion();
  const option = useMemo(() => {
    void theme; // tokens are read from CSS variables of the current theme
    const t = readTokens();
    return { ...baseOption(t), ...build(t) };
  }, [build, theme]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    chart.setOption(option, true);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [option]);

  return (
    <figure className="m-0">
      <div ref={ref} role="img" aria-label={title} style={{ height, width: "100%" }} />
      {caption && <figcaption className="mt-1 text-xs text-muted">{caption}</figcaption>}
      {table && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-ink-2">資料表檢視：{title}</summary>
          <div className="mt-2 max-h-64 overflow-auto">
            <table className="w-full text-left">
              <thead>
                <tr>
                  {table.columns.map((c) => (
                    <th key={c} scope="col" className="sticky top-0 bg-surface px-2 py-1 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    {r.map((v, j) => (
                      <td key={j} className="num px-2 py-0.5">
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </figure>
  );
}

/** Thin out a long daily series for the table view (every n-th row + last). */
export function sampleRows<T>(rows: T[], max = 120): T[] {
  if (rows.length <= max) return rows;
  const step = Math.ceil(rows.length / max);
  const out = rows.filter((_, i) => i % step === 0);
  if (out[out.length - 1] !== rows[rows.length - 1]) out.push(rows[rows.length - 1] as T);
  return out;
}
