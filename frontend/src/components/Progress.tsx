import { useEffect, useState } from "react";
import { seconds } from "../lib/format";
import type { ProfileState } from "../lib/useProfileStream";
import type { StageKey } from "../lib/types";

const STAGES: { key: StageKey; label: string }[] = [
  { key: "resolve", label: "Вуз" },
  { key: "sources", label: "Источники" },
  { key: "analyze", label: "Проверка фото" },
  { key: "facts", label: "Факты" },
  { key: "describe", label: "Описание" },
];

const SOURCE_STATUS: Record<string, string> = {
  running: "запрос",
  ok: "ответил",
  empty: "пусто",
  error: "ошибка",
  skipped: "выключен",
};

export function Progress({ state, onRebuild }: { state: ProfileState; onRebuild: () => void }) {
  const [started] = useState(() => performance.now());
  const [now, setNow] = useState(() => performance.now());
  const building = state.phase === "connecting" || state.phase === "building";

  useEffect(() => {
    if (!building || state.replay) return;
    const id = window.setInterval(() => setNow(performance.now()), 100);
    return () => window.clearInterval(id);
  }, [building, state.replay]);

  const elapsed = state.totalMs ?? (state.replay ? state.lastT : Math.max(state.lastT, now - started));
  const c = state.counters;
  const sources = Object.values(state.sources);

  return (
    <section className={`progress${building ? " is-building" : ""}`} aria-label="Ход сборки профиля">
      <div className="progress__clock">
        <span className="progress__time num" aria-live="off">{seconds(elapsed)}</span>
        <span className="progress__caption">
          {state.replay && state.cachedAt
            ? `собрано ${new Date(state.cachedAt * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}, показано из кэша`
            : building
              ? "идёт сборка"
              : "время сборки"}
        </span>
        {!building ? (
          <button type="button" className="btn btn--ghost btn--small" onClick={onRebuild}>
            Пересобрать без кэша
          </button>
        ) : null}
      </div>
      <ol className="progress__stages">
        {STAGES.map((s) => (
          <li key={s.key} className={`stage stage--${state.stages[s.key]}`}>
            <i aria-hidden="true" />
            {s.label}
            <span className="visually-hidden">: {state.stages[s.key]}</span>
          </li>
        ))}
      </ol>
      <dl className="progress__counters" aria-live="polite">
        <div><dt>найдено</dt><dd className="num">{c.found}</dd></div>
        <div><dt>проверено</dt><dd className="num">{c.analyzed}</dd></div>
        <div><dt>в фонде</dt><dd className="num">{c.in_profile}</dd></div>
        <div><dt>не подтверждено</dt><dd className="num">{c.unconfirmed}</dd></div>
        <div><dt>изъято</dt><dd className="num">{c.rejected}</dd></div>
      </dl>
      {sources.length ? (
        <details className="progress__details" open={building || undefined}>
          <summary>
            Источники: {sources.filter((x) => x.status === "ok").length} ответили
            {sources.some((x) => x.status === "error") ? `, ${sources.filter((x) => x.status === "error").length} с ошибкой` : ""}
            {sources.some((x) => x.status === "empty") ? `, ${sources.filter((x) => x.status === "empty").length} без результатов` : ""}
            {sources.some((x) => x.status === "skipped") ? `, ${sources.filter((x) => x.status === "skipped").length} выключен` : ""}
          </summary>
        <ul className="progress__sources">
          {sources.map((s) => (
            <li key={s.key} className={`src src--${s.status}`}>
              <span className="src__name">{s.label}</span>
              <span className="src__status">{SOURCE_STATUS[s.status] ?? s.status}</span>
              <span className="src__nums num">
                {s.count != null ? s.count : ""}
                {s.ms != null ? ` · ${seconds(s.ms)}` : ""}
              </span>
              {s.message ? <span className="src__msg">{s.message}</span> : null}
            </li>
          ))}
        </ul>
        </details>
      ) : null}
    </section>
  );
}
