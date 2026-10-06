import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearDataCache } from "../lib/data";
import { changesFixture, rankingsFixture } from "../test/fixtures";
import Changes from "./Changes";
import Rankings, { riskTags } from "./Rankings";

function serve(files: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const name = String(url).split("/data/")[1] ?? "";
      return name in files ? new Response(JSON.stringify(files[name]), { status: 200 }) : new Response("", { status: 404 });
    }),
  );
}

beforeEach(() => clearDataCache());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Rankings page (FIXTURE)", () => {
  it("shows an error state instead of fake data when the JSON is missing", async () => {
    serve({});
    render(<MemoryRouter><Rankings /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("無法載入資料");
    expect(screen.queryByText("AAA")).toBeNull();
  });

  it("renders rows, filters by asset class and expands the score breakdown", async () => {
    serve({ "rankings.json": rankingsFixture });
    render(<MemoryRouter><Rankings /></MemoryRouter>);
    const table = await screen.findByRole("table", { name: /Top 50 排名表/ });
    expect(within(table).getAllByRole("link").map((a) => a.textContent)).toEqual(["AAA", "BBB", "TLTX"]);
    expect(within(table).getByText("新進")).toBeTruthy(); // BBB had no previous rank
    expect(within(table).getByText("+2")).toBeTruthy(); // AAA 3 → 1

    fireEvent.change(screen.getByLabelText("資產類別"), { target: { value: "bond_etf" } });
    expect(within(table).getAllByRole("link").map((a) => a.textContent)).toEqual(["TLTX"]);

    fireEvent.click(screen.getByRole("button", { name: "展開 TLTX 分數分解" }));
    expect(screen.getByText("分數分解（因子群組貢獻）")).toBeTruthy();
    expect(screen.getByRole("button", { name: "收合 TLTX 分數分解" })).toHaveAttribute("aria-expanded", "true");
  });

  it("sorts by a column and marks aria-sort", async () => {
    serve({ "rankings.json": { ...rankingsFixture, top: [...rankingsFixture.top].reverse() } });
    render(<MemoryRouter><Rankings /></MemoryRouter>);
    const table = await screen.findByRole("table", { name: /Top 50 排名表/ });
    expect(within(table).getAllByRole("link")[0]).toHaveTextContent("AAA"); // default: rank asc
    fireEvent.click(screen.getByRole("button", { name: /^#/ }));
    expect(within(table).getAllByRole("link")[0]).toHaveTextContent("TLTX");
    expect(screen.getByRole("columnheader", { name: /#/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("labels leverage and short history as risk tags", () => {
    const tags = riskTags(rankingsFixture.top[2]!).map((t) => t.text);
    expect(tags).toEqual(["槓桿 3x", "歷史不足、信心低"]);
  });
});

describe("Changes page (FIXTURE)", () => {
  it("lists entries, exits and movers with reasons and the regime switch", async () => {
    serve({ "changes.json": changesFixture });
    render(<MemoryRouter><Changes /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/權重組改變/)).toBeTruthy());
    expect(screen.getByText("受約束排除：category cap energy (8)")).toBeTruthy();
    expect(screen.getByText("動能貢獻 +0.400")).toBeTruthy();
    expect(screen.getByText("+8")).toBeTruthy();
  });
});
