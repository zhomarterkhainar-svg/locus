import { LEVEL_WORD } from "../lib/format";

export function Stamp({ confidence, level, compact = false }: { confidence: number; level: "high" | "medium" | "low"; compact?: boolean }) {
  const pct = Math.round(confidence * 100);
  return (
    <span className={`stamp stamp--${level}${compact ? " stamp--compact" : ""}`} title={`Достоверность ${pct}%: ${LEVEL_WORD[level]}`}>
      <span className="num">{pct}</span>
      {compact ? null : <span className="stamp__word">{LEVEL_WORD[level]}</span>}
    </span>
  );
}

const STATUS_WORD: Record<string, string> = {
  confirmed: "подтверждено",
  weak: "есть основания",
  insufficient: "мало данных",
  not_found: "не найдено",
};

export function FactStamp({ status }: { status: string }) {
  return <span className={`fact-stamp fact-stamp--${status}`}>{STATUS_WORD[status] ?? status}</span>;
}
