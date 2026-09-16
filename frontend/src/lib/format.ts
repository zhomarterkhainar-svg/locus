const nf = new Intl.NumberFormat("ru-RU");

export function num(n: number | null | undefined): string {
  return n == null ? "" : nf.format(n);
}

export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1).replace(".", ",")} с`;
}

export function distance(m: number | null | undefined): string {
  if (m == null) return "";
  if (m < 1000) return `${Math.round(m)} м`;
  return `${(m / 1000).toFixed(1).replace(".", ",")} км`;
}

export function percent(p: number): string {
  return `${Math.round(p * 100)}%`;
}

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

export function date(value: string | null | undefined): string {
  if (!value) return "";
  const m = value.match(/^(\d{4})(?:-(\d{2})-(\d{2}))?/);
  if (!m) return value;
  if (!m[2]) return `${m[1]} г.`;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return one;
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return few;
  return many;
}

export const SOURCE_NAMES: Record<string, string> = {
  commons: "Wikimedia Commons",
  official: "Сайт вуза",
  flickr: "Flickr",
  wikipedia: "Википедия",
};

export const LEVEL_WORD: Record<string, string> = {
  high: "подтверждено",
  medium: "вероятно",
  low: "не подтверждено",
};

export const REJECT_WORD: Record<string, string> = {
  duplicate: "Дубликат",
  trash: "Не фото кампуса",
  stock: "Фотобанк",
  small: "Слишком маленькое",
  far: "Далеко от кампуса",
  download: "Не скачалось",
  off_topic_city: "Не вид города",
};

export function shortDate(value: string | null | undefined): string {
  if (!value) return "";
  const m = value.match(/^(\d{4})(?:-(\d{2})-(\d{2}))?/);
  if (!m) return value;
  return m[2] ? `${m[3]}.${m[2]}.${m[1]}` : m[1];
}
