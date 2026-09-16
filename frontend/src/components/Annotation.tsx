import type { DescriptionView } from "../lib/types";

export function Annotation({ description, building }: { description: DescriptionView | null; building: boolean }) {
  return (
    <section className="annotation" aria-labelledby="annotation-title">
      <h2 id="annotation-title" className="panel-title">Аннотация</h2>
      {!description ? (
        building ? (
          <div aria-hidden="true">
            <div className="skel skel--line" />
            <div className="skel skel--line" />
            <div className="skel skel--line skel--short" />
          </div>
        ) : (
          <p className="panel-note">Описание не собралось.</p>
        )
      ) : description.sentences.length === 0 ? (
        <p className="panel-note">{description.message ?? "Текстовых источников о кампусе не нашлось, поэтому описания нет."}</p>
      ) : (
        <>
          <p className="annotation__text">
            {description.sentences.map((s, i) => (
              <span key={i}>
                {s.text}
                {s.sources.map((id) => {
                  const n = description.sources.findIndex((x) => x.id === id) + 1;
                  return (
                    <sup key={id}>
                      <a href={`#src-${id}`} aria-label={`Источник ${n}`}>{n}</a>
                    </sup>
                  );
                })}{" "}
              </span>
            ))}
          </p>
          <ol className="annotation__sources">
            {description.sources.map((s) => (
              <li key={s.id} id={`src-${s.id}`}>
                <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
              </li>
            ))}
          </ol>
          <p className="panel-note">
            {description.mode === "gemini"
              ? `Составлено моделью ${description.model} только по этим источникам. Предложения без подтверждения в источниках удалены автоматически.`
              : "Выдержки из источников без генерации текста."}
          </p>
        </>
      )}
    </section>
  );
}
