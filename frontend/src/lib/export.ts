import type { PhotoView } from "./types";

const COLUMNS: { key: string; label: string; get: (p: PhotoView) => string | number | null }[] = [
  { key: "shelfmark", label: "шифр", get: (p) => p.shelfmark },
  { key: "category", label: "раздел", get: (p) => p.category_label },
  { key: "title", label: "название", get: (p) => p.title },
  { key: "confidence", label: "достоверность", get: (p) => p.confidence },
  { key: "level", label: "уровень", get: (p) => p.level },
  { key: "source", label: "источник", get: (p) => p.source },
  { key: "host", label: "домен", get: (p) => p.host },
  { key: "page_url", label: "страница источника", get: (p) => p.page_url },
  { key: "image_url", label: "файл", get: (p) => p.image_url },
  { key: "author", label: "автор", get: (p) => p.author },
  { key: "license", label: "лицензия", get: (p) => p.license },
  { key: "taken", label: "снято", get: (p) => p.taken },
  { key: "published", label: "опубликовано", get: (p) => p.published },
  { key: "lat", label: "широта", get: (p) => p.lat },
  { key: "lon", label: "долгота", get: (p) => p.lon },
  { key: "distance_m", label: "до кампуса, м", get: (p) => p.distance_m },
];

function cell(value: string | number | null): string {
  if (value == null) return "";
  const text = String(value);
  return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Выгрузка фонда таблицей. Разделитель - точка с запятой: Excel с русской локалью открывает
 * такой файл сразу, без мастера импорта. BOM в начале - чтобы кириллица не превратилась в кракозябры.
 */
export function photosToCsv(photos: PhotoView[]): string {
  const head = COLUMNS.map((c) => c.label).join(";");
  const rows = photos.map((p) => COLUMNS.map((c) => cell(c.get(p))).join(";"));
  return `﻿${[head, ...rows].join("\r\n")}`;
}

export function download(name: string, content: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Ссылку освобождаем не сразу: Safari успевает начать скачивание только после тика.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
