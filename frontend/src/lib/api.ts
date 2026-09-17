import { apiUrl } from "./config";
import type { FindResult, SearchResult } from "./types";

export async function searchUniversities(q: string, signal?: AbortSignal): Promise<SearchResult> {
  const r = await fetch(apiUrl(`/api/search?q=${encodeURIComponent(q)}`), { signal });
  if (!r.ok) {
    return { query: q, status: "error", candidates: [], suggestion: null, message: "Сервер поиска ответил ошибкой. Попробуйте ещё раз." };
  }
  return r.json();
}

export async function findInProfile(qid: string, q: string, signal?: AbortSignal): Promise<FindResult> {
  const r = await fetch(apiUrl(`/api/profile/${encodeURIComponent(qid)}/find?q=${encodeURIComponent(q)}`), { signal });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) return { query: q, english: null, results: [], error: body.error ?? "Поиск по фото сейчас недоступен." };
  return body as FindResult;
}

export type FeedbackKind = "wrong_university" | "wrong_category" | "correct";

export async function sendFeedback(qid: string, photoId: string, kind: FeedbackKind, category: string): Promise<{ ok: boolean; message: string }> {
  try {
    const r = await fetch(apiUrl("/api/feedback"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ qid, photo_id: photoId, kind, category }),
    });
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, message: body.message ?? body.error ?? (r.ok ? "Отметка сохранена." : "Не удалось отправить отметку.") };
  } catch {
    return { ok: false, message: "Нет связи с сервером, отметка не отправлена." };
  }
}
