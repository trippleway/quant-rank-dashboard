// Smoke-check the built site with headless Chrome: every page renders its heading,
// shows no load-error state, and logs no console errors / page errors / failed requests.
// Usage: npm run build && node scripts/check-site.mjs [--screens DIR]
// Needs Chrome/Chromium (CHROME_PATH or the default macOS / Linux locations).
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = fileURLToPath(new URL("../dist/", import.meta.url));
const args = process.argv.slice(2);
const screens = args.includes("--screens") ? args[args.indexOf("--screens") + 1] : null;

const CHROME = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].find((p) => p && existsSync(p));
if (!CHROME) {
  console.error("Chrome not found; set CHROME_PATH");
  process.exit(2);
}
if (!existsSync(join(root, "index.html"))) {
  console.error("dist/ missing; run `npm run build` first");
  process.exit(2);
}
if (!existsSync(join(root, "data", "manifest.json"))) {
  console.error("dist/data/manifest.json missing; run `make publish` then build");
  process.exit(2);
}

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const server = createServer((req, res) => {
  const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
  const path = normalize(join(root, url === "/" ? "index.html" : url));
  if (!path.startsWith(root) || !existsSync(path) || statSync(path).isDirectory()) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": TYPES[extname(path)] ?? "application/octet-stream" });
  res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

const manifest = JSON.parse(readFileSync(join(root, "data", "manifest.json"), "utf8"));
const firstTop = manifest.assets.find((a) => a.in_top)?.ticker ?? "SPY";
const PAGES = [
  ["overview", "#/", "Overview 總覽"],
  ["rankings", "#/rankings", "Rankings 排名"],
  ["asset-index", "#/asset", "Asset Detail 標的詳情"],
  ["asset", `#/asset/${firstTop}`, firstTop],
  ["macro", "#/macro", "Macro & Risk 總體與風險"],
  ["backtest", "#/backtest", "Backtest 回測"],
  ["changes", "#/changes", "Changes 異動"],
  ["methodology", "#/methodology", "Methodology & Data 方法與資料"],
];

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
const problems = [];
if (screens) mkdirSync(screens, { recursive: true });
for (const theme of ["light", "dark"]) {
  for (const [name, hash, heading] of PAGES) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 1000 });
    await page.evaluateOnNewDocument((t) => localStorage.setItem("qrd-theme", t), theme);
    const where = `${theme}/${name}`;
    page.on("console", (m) => {
      if (m.type() === "error" || m.type() === "warn") problems.push(`${where} console.${m.type()}: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`${where} pageerror: ${e.message}`));
    page.on("requestfailed", (r) => problems.push(`${where} requestfailed: ${r.url()}`));
    page.on("response", (r) => {
      if (r.status() >= 400) problems.push(`${where} HTTP ${r.status()}: ${r.url()}`);
    });
    await page.goto(base + hash, { waitUntil: "networkidle0" });
    await page.waitForFunction((h) => document.querySelector("h1")?.textContent?.includes(h), { timeout: 15000 }, heading).catch(() => {
      problems.push(`${where}: heading "${heading}" not rendered`);
    });
    await new Promise((r) => setTimeout(r, 300));
    const state = await page.evaluate(() => ({
      alerts: [...document.querySelectorAll('[role="alert"]')].map((e) => e.textContent),
      loading: document.querySelectorAll('[role="status"].animate-pulse').length,
      charts: document.querySelectorAll('figure [role="img"] canvas').length,
      demo: document.body.innerText.includes("DEMO"),
      theme: document.documentElement.dataset.theme,
    }));
    if (state.alerts.some((a) => a.includes("無法載入資料"))) problems.push(`${where}: load error ${state.alerts.join(" | ")}`);
    if (state.loading) problems.push(`${where}: still loading`);
    if (state.theme !== theme) problems.push(`${where}: theme ${state.theme}`);
    if (!manifest.demo && state.demo && name !== "methodology") problems.push(`${where}: shows DEMO with real data`);
    console.warn(`${where}: ok (${state.charts} charts)`);
    if (screens) await page.screenshot({ path: join(screens, `${theme}-${name}.png`), fullPage: true });
    await page.close();
  }
}
await browser.close();
server.close();
if (problems.length) {
  console.error(`\n${problems.length} problem(s):\n` + problems.join("\n"));
  process.exit(1);
}
console.warn("\nall pages rendered without console errors");
