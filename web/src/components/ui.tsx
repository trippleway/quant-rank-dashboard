import type { ReactNode } from "react";
import { REGIME } from "../lib/labels";
import { arrow } from "../lib/format";

export function Card({
  title,
  children,
  className = "",
  actions,
  id,
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <section
      id={id}
      aria-label={typeof title === "string" ? title : undefined}
      className={`rounded-lg border border-line bg-surface p-4 shadow-sm ${className}`}
    >
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

export function Loading({ what = "資料" }: { what?: string }) {
  return (
    <div role="status" aria-live="polite" className="animate-pulse space-y-3 p-2">
      <span className="text-sm text-ink-2">載入{what}中…</span>
      <div className="h-24 rounded bg-surface-2" />
      <div className="h-48 rounded bg-surface-2" />
    </div>
  );
}

export function ErrorState({ error, hint }: { error: string; hint?: ReactNode }) {
  return (
    <div role="alert" className="rounded-lg border border-line bg-surface p-4">
      <p className="font-semibold text-ink">
        <span aria-hidden="true">⚠ </span>無法載入資料
      </p>
      <p className="mt-1 text-sm text-ink-2 break-all">{error}</p>
      <p className="mt-2 text-sm text-ink-2">
        {hint ?? (
          <>
            前端只讀 pipeline 產生的真實輸出，不以示範資料替代。請在 repo 根目錄執行{" "}
            <code className="num">make rank backtest publish</code> 後重新整理。
          </>
        )}
      </p>
    </div>
  );
}

export function RegimeBadge({ regime, size = "md" }: { regime: string; size?: "md" | "lg" }) {
  const r = REGIME[regime] ?? REGIME.unknown!;
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface-2 font-semibold text-ink ${
        size === "lg" ? "px-3 py-1 text-base" : "px-2 py-0.5 text-xs"
      }`}
    >
      <span aria-hidden="true" className="swatch" style={{ color: r.color }}>
        {r.icon}
      </span>
      {r.label}
    </span>
  );
}

export function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-xs font-semibold text-ink">
      <span aria-hidden="true" className="swatch" style={{ color: ok ? "var(--status-good)" : "var(--status-warning)" }}>
        {ok ? "✔" : "⚠"}
      </span>
      {label}
    </span>
  );
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" }) {
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[11px] leading-none ${
        tone === "warn" ? "border-[var(--status-serious)] text-ink" : "border-line text-ink-2"
      }`}
    >
      {tone === "warn" && <span aria-hidden="true">⚠ </span>}
      {children}
    </span>
  );
}

/** Signed value with arrow + color (never color alone). */
export function Delta({ value, text, neutral = false }: { value: number | null | undefined; text: string; neutral?: boolean }) {
  // neutral: direction only (e.g. a rising credit spread is not "good"), no up/down color.
  const cls = neutral || value == null || value === 0 ? "text-ink-2" : value > 0 ? "text-up" : "text-down";
  return (
    <span className={`num ${cls}`}>
      <span aria-hidden="true">{arrow(value)} </span>
      {text}
    </span>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink num">{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-2">{sub}</div>}
    </div>
  );
}

export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const v = values.filter((x): x is number => x != null);
  if (v.length < 2) return <span className="text-muted">—</span>;
  const w = 88;
  const h = 24;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const span = hi - lo || 1;
  const pts = v.map((x, i) => `${((i / (v.length - 1)) * w).toFixed(1)},${(h - 2 - ((x - lo) / span) * (h - 4)).toFixed(1)}`);
  const up = v[v.length - 1]! >= v[0]!;
  return (
    <svg width={w} height={h} role="img" aria-label={`${label}：近 3 個月${up ? "上漲" : "下跌"}`}>
      <polyline points={pts.join(" ")} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

export function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="text-xs text-ink-2">
      僅供研究與學習，不構成投資建議。{text && <span className="num">（{text}）</span>}
    </p>
  );
}
