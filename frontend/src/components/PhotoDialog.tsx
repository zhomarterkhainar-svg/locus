import { useEffect, useRef, useState } from "react";
import { sendFeedback, type FeedbackKind } from "../lib/api";
import { date, distance, isOld, largeThumb, LEVEL_WORD, percent, SOURCE_NAMES } from "../lib/format";
import type { PhotoView } from "../lib/types";
import { Boxes } from "./CatalogCard";
import { Icon } from "./Icon";
import { Stamp } from "./Stamp";

const CATEGORY_RU: Record<string, string> = {
  campus: "Кампус и корпуса", dormitory: "Общежития", classroom: "Аудитории", library: "Библиотеки", lab: "Лаборатории",
  sport: "Спорт", canteen: "Столовые и кафе", student_life: "Студенческая жизнь", city: "Город",
};

type Props = {
  photo: PhotoView | null;
  onClose: () => void;
  onStep: (dir: -1 | 1) => void;
  position: string;
  calibratorTrained: boolean | null;
  qid?: string;
};

export function PhotoDialog({ photo, onClose, onStep, position, calibratorTrained, qid }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [sent, setSent] = useState<Record<string, string>>({});
  const [imgSrc, setImgSrc] = useState<string>("");

  useEffect(() => {
    if (photo) setImgSrc(largeThumb(photo.image_url));
  }, [photo]);

  async function mark(kind: FeedbackKind) {
    if (!photo || !qid) return;
    setSent((s) => ({ ...s, [photo.id]: "отправляем…" }));
    const res = await sendFeedback(qid, photo.id, kind, photo.category);
    setSent((s) => ({ ...s, [photo.id]: res.message }));
  }

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (photo && !d.open) d.showModal();
    if (!photo && d.open) d.close();
  }, [photo]);

  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (!photo) return;
      if (e.key === "ArrowLeft") onStep(-1);
      if (e.key === "ArrowRight") onStep(1);
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [photo, onStep]);

  return (
    <dialog ref={ref} className="record" onClose={onClose} onCancel={onClose} aria-labelledby="record-title">
      {photo ? (
        <div className="record__inner">
          <div className="record__bar">
            <span className="field">{photo.shelfmark} · {position}</span>
            <div className="record__nav">
              <button type="button" className="btn btn--ghost btn--icon" onClick={() => onStep(-1)} aria-label="Предыдущая карточка"><Icon name="prev" /></button>
              <button type="button" className="btn btn--ghost btn--icon" onClick={() => onStep(1)} aria-label="Следующая карточка"><Icon name="next" /></button>
              <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label="Закрыть"><Icon name="close" /></button>
            </div>
          </div>
          <div className="record__grid">
            <div className="record__media">
              <div className="record__photo">
                <img
                  src={imgSrc || photo.image_url}
                  alt={photo.title}
                  referrerPolicy="no-referrer"
                  onError={() => imgSrc !== photo.image_url && setImgSrc(photo.image_url)}
                />
                {showBoxes ? <Boxes boxes={photo.boxes} /> : null}
              </div>
              {photo.boxes.length ? (
                <label className="record__toggle">
                  <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
                  Рамки детектора ({photo.boxes.map((b) => ((b.bunk ?? 0) >= 0.6 ? "двухъярусная кровать" : b.label)).filter((v, i, a) => a.indexOf(v) === i).join(", ")})
                </label>
              ) : null}
            </div>
            <div className="record__card">
              <h2 id="record-title">{photo.title || "Без названия"}</h2>
              {photo.description && photo.description !== photo.title ? <p className="record__desc">{photo.description}</p> : null}
              <dl className="record__fields">
                <div><dt>Раздел</dt><dd>{photo.category_label}</dd></div>
                <div>
                  <dt>Источник</dt>
                  <dd>
                    <a href={photo.page_url} target="_blank" rel="noreferrer">
                      {SOURCE_NAMES[photo.source] ?? photo.source}: {photo.host} <Icon name="external" size={12} />
                    </a>
                  </dd>
                </div>
                <div>
                  <dt>Автор</dt>
                  <dd>{photo.author ? (photo.author_url ? <a href={photo.author_url} target="_blank" rel="noreferrer">{photo.author}</a> : photo.author) : "не указан"}</dd>
                </div>
                <div>
                  <dt>Лицензия</dt>
                  <dd>{photo.license ? (photo.license_url ? <a href={photo.license_url} target="_blank" rel="noreferrer">{photo.license}</a> : photo.license) : "не указана"}</dd>
                </div>
                <div>
                  <dt>Снято</dt>
                  <dd>
                    {date(photo.taken) || "дата неизвестна"}
                    {isOld(photo.taken, photo.published) ? <span className="record__old">, фото старше 5 лет: кампус мог измениться</span> : null}
                  </dd>
                </div>
                <div><dt>Опубликовано</dt><dd>{date(photo.published) || "дата неизвестна"}</dd></div>
                <div><dt>Получено</dt><dd>{date(photo.retrieved.slice(0, 10))}</dd></div>
                <div>
                  <dt>Место</dt>
                  <dd>
                    {photo.lat != null
                      ? `${photo.lat.toFixed(5)}, ${photo.lon!.toFixed(5)}${photo.distance_m != null ? (photo.distance_m === 0 ? ", внутри кампуса" : `, ${distance(photo.distance_m)} от кампуса`) : ""}`
                      : "без геометки"}
                    {photo.nearest ? (
                      <>
                        <br />
                        рядом: <a href={photo.nearest.url} target="_blank" rel="noreferrer">{photo.nearest.name}</a> ({photo.nearest.kind_label.toLowerCase()}, {distance(photo.nearest.distance_m)})
                      </>
                    ) : null}
                  </dd>
                </div>
              </dl>

              <section className="record__verdict">
                <div className="record__verdict-head">
                  <h3>Достоверность</h3>
                  <Stamp confidence={photo.confidence} level={photo.level} />
                </div>
                <table className="signals">
                  <caption className="visually-hidden">Вклад сигналов в достоверность</caption>
                  <thead>
                    <tr><th scope="col">Сигнал</th><th scope="col">Что найдено</th><th scope="col" className="num">Вклад</th></tr>
                  </thead>
                  <tbody>
                    {photo.signals.map((s) => (
                      <tr key={s.key} className={s.contribution < -0.05 ? "is-neg" : s.contribution > 0.05 ? "is-pos" : ""}>
                        <th scope="row">{s.label}</th>
                        <td>{s.detail}</td>
                        <td className="num">{s.contribution > 0 ? "+" : ""}{s.contribution.toFixed(2).replace(".", ",")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="panel-note">
                  Итог {percent(photo.confidence)} ({LEVEL_WORD[photo.level]}): логистическая модель складывает вклады сигналов.
                  {calibratorTrained === false
                    ? " Веса пока заданы вручную и будут заменены обученными на размеченных фото."
                    : calibratorTrained
                      ? " Веса обучены на открытых размеченных данных, метрики на странице «Как это работает»."
                      : ""}
                </p>
                <p className="panel-note">
                  Раздел: {photo.category_scores.map((c) => `${CATEGORY_RU[c.key] ?? c.key} ${percent(c.p)}`).join(", ")}
                </p>
              </section>

              {qid ? (
                <section className="record__feedback" aria-label="Отметить ошибку">
                  <h3>Что-то не так?</h3>
                  <div className="record__feedback-row">
                    <button type="button" className="btn btn--ghost btn--small" onClick={() => mark("wrong_university")} disabled={Boolean(sent[photo.id])}>
                      <Icon name="flag" size={14} /> Это не тот вуз
                    </button>
                    <button type="button" className="btn btn--ghost btn--small" onClick={() => mark("wrong_category")} disabled={Boolean(sent[photo.id])}>
                      Не тот раздел
                    </button>
                    <button type="button" className="btn btn--ghost btn--small" onClick={() => mark("correct")} disabled={Boolean(sent[photo.id])}>
                      Всё верно
                    </button>
                  </div>
                  <p className="panel-note" role="status">{sent[photo.id] ?? "Отметки копятся и используются при дообучении модели достоверности."}</p>
                </section>
              ) : null}

              {photo.duplicates.length ? (
                <section className="record__dups">
                  <h3>Копии, склеенные с этой карточкой</h3>
                  <ul>
                    {photo.duplicates.map((d) => (
                      <li key={d.id}>
                        <a href={d.page_url} target="_blank" rel="noreferrer">{d.host}</a> <span className="panel-note">{d.detail}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
