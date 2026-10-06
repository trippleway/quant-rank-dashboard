import { useEffect, useState } from "react";

// Loads the static JSON written by `qrd publish` (web/public/data/). There is no
// fallback to sample data: a missing file is shown as an error state.

export const SUPPORTED_MAJOR = "1";

export type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; data: T };

const cache = new Map<string, Promise<unknown>>();

export function dataUrl(name: string): string {
  return `${import.meta.env.BASE_URL}data/${name}`;
}

export function checkSchema(name: string, payload: unknown): void {
  const v = (payload as { schema_version?: unknown } | null)?.schema_version;
  if (typeof v !== "string") throw new Error(`${name}: 缺少 schema_version`);
  if (v.split(".")[0] !== SUPPORTED_MAJOR)
    throw new Error(`${name}: 不支援的 schema 版本 ${v}（前端支援 ${SUPPORTED_MAJOR}.x）`);
}

export async function fetchJson<T>(name: string, fetcher: typeof fetch = fetch): Promise<T> {
  let res: Response;
  try {
    res = await fetcher(dataUrl(name), { cache: "no-cache" });
  } catch (e) {
    throw new Error(`無法連線取得 ${name}：${(e as Error).message}`, { cause: e });
  }
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    throw new Error(`${name}: 不是有效的 JSON`);
  }
  checkSchema(name, payload);
  return payload as T;
}

export function loadJson<T>(name: string): Promise<T> {
  let p = cache.get(name);
  if (!p) {
    p = fetchJson<T>(name);
    cache.set(name, p);
    p.catch(() => cache.delete(name)); // allow retry after a failure
  }
  return p as Promise<T>;
}

export function useJson<T>(name: string | null): LoadState<T> {
  const [state, setState] = useState<{ name: string | null; s: LoadState<T> }>({
    name,
    s: { status: "loading" },
  });
  useEffect(() => {
    if (!name) return;
    let alive = true;
    loadJson<T>(name).then(
      (data) => alive && setState({ name, s: { status: "ready", data } }),
      (e: Error) => alive && setState({ name, s: { status: "error", error: e.message } }),
    );
    return () => {
      alive = false;
    };
  }, [name]);
  if (!name) return { status: "error", error: "未指定資料檔" };
  return state.name === name ? state.s : { status: "loading" };
}

/** Test hook: forget loaded files. */
export function clearDataCache(): void {
  cache.clear();
}
