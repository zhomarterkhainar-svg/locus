import type { SearchResult } from "./types";

export async function searchUniversities(q: string, signal?: AbortSignal): Promise<SearchResult> {
  const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal });
  if (!r.ok) {
    return { query: q, status: "error", candidates: [], suggestion: null, message: "Сервер поиска ответил ошибкой. Попробуйте ещё раз." };
  }
  return r.json();
}
