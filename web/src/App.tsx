import { lazy, Suspense } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { Disclaimer, Loading } from "./components/ui";
import { useJson } from "./lib/data";
import { dateTime } from "./lib/format";
import { useTheme } from "./lib/theme";
import type { Manifest } from "./lib/types";

const Overview = lazy(() => import("./pages/Overview"));
const Rankings = lazy(() => import("./pages/Rankings"));
const AssetDetail = lazy(() => import("./pages/AssetDetail"));
const MacroRisk = lazy(() => import("./pages/MacroRisk"));
const BacktestPage = lazy(() => import("./pages/Backtest"));
const ChangesPage = lazy(() => import("./pages/Changes"));
const Methodology = lazy(() => import("./pages/Methodology"));

export const NAV = [
  { to: "/", label: "Overview", zh: "總覽", end: true },
  { to: "/rankings", label: "Rankings", zh: "排名" },
  { to: "/asset", label: "Asset Detail", zh: "標的詳情" },
  { to: "/macro", label: "Macro & Risk", zh: "總體與風險" },
  { to: "/backtest", label: "Backtest", zh: "回測" },
  { to: "/changes", label: "Changes", zh: "異動" },
  { to: "/methodology", label: "Methodology & Data", zh: "方法與資料" },
];

function DataStamp() {
  const m = useJson<Manifest>("manifest.json");
  if (m.status !== "ready") return null;
  return (
    <p className="text-xs text-ink-2">
      資料日 <span className="num text-ink">{m.data.asof}</span>
      <br />
      發布 <span className="num">{dateTime(m.data.generated_at)}</span>
    </p>
  );
}

function Shell() {
  const [theme, toggle] = useTheme();
  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-surface focus:p-2">
        跳到主要內容
      </a>
      <aside className="border-b border-line bg-surface md:fixed md:inset-y-0 md:left-0 md:w-56 md:border-b-0 md:border-r">
        <div className="flex h-full flex-col gap-4 p-4">
          <div>
            <p className="text-base font-semibold text-ink">quant-rank</p>
            <p className="text-xs text-ink-2">多資產每日 Top 50（研究用）</p>
          </div>
          <nav aria-label="主要導覽">
            <ul className="flex gap-1 overflow-x-auto md:flex-col">
              {NAV.map((n) => (
                <li key={n.to}>
                  <NavLink
                    to={n.to}
                    end={n.end}
                    className={({ isActive }) =>
                      `block whitespace-nowrap rounded px-3 py-2 text-sm ${
                        isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-2 hover:bg-surface-2"
                      }`
                    }
                  >
                    {n.label}
                    <span className="ml-1 text-xs text-ink-2 md:ml-0 md:block">{n.zh}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="mt-auto hidden space-y-3 md:block">
            <DataStamp />
            <button
              type="button"
              onClick={toggle}
              className="w-full rounded border border-line px-3 py-1.5 text-sm text-ink hover:bg-surface-2"
              aria-label={theme === "dark" ? "切換為淺色主題" : "切換為深色主題"}
            >
              {theme === "dark" ? "☀ 淺色" : "☾ 深色"}
            </button>
          </div>
          <button
            type="button"
            onClick={toggle}
            className="rounded border border-line px-3 py-1 text-sm text-ink md:hidden"
            aria-label={theme === "dark" ? "切換為淺色主題" : "切換為深色主題"}
          >
            {theme === "dark" ? "☀ 淺色" : "☾ 深色"}
          </button>
        </div>
      </aside>
      <div className="flex-1 md:ml-56">
        <main id="main" className="mx-auto max-w-7xl p-4 md:p-6">
          <Suspense fallback={<Loading what="頁面" />}>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/rankings" element={<Rankings />} />
              <Route path="/asset" element={<AssetDetail />} />
              <Route path="/asset/:ticker" element={<AssetDetail />} />
              <Route path="/macro" element={<MacroRisk />} />
              <Route path="/backtest" element={<BacktestPage />} />
              <Route path="/changes" element={<ChangesPage />} />
              <Route path="/methodology" element={<Methodology />} />
              <Route path="*" element={<p className="text-ink-2">找不到這個頁面。</p>} />
            </Routes>
          </Suspense>
        </main>
        <footer className="mx-auto max-w-7xl border-t border-line px-4 py-4 md:px-6">
          <Disclaimer text="For research and educational purposes only. Not investment advice." />
          <p className="mt-1 text-xs text-ink-2">
            Regime 與宏觀指標是國際局勢的代理變數；回測含存活者偏誤等限制，詳見「方法與資料」。
          </p>
        </footer>
      </div>
    </div>
  );
}

export function App() {
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  );
}
