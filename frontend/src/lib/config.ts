/**
 * Адрес API. Пусто - тот же домен: так работает вариант «один контейнер» и локальная разработка
 * (Vite проксирует /api на 8000). На Vercel переменная VITE_API_BASE указывает на сервис Render.
 */
const RAW = (import.meta.env.VITE_API_BASE ?? "").trim();
export const API_BASE = RAW.replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}
