import { useState } from "react";
import { isOld, shortDate } from "../lib/format";

const SHORT_SOURCE: Record<string, string> = { commons: "Commons", official: "Сайт вуза", flickr: "Flickr", wikipedia: "Википедия" };
import type { Box, PhotoView } from "../lib/types";
import { Stamp } from "./Stamp";

export function Boxes({ boxes }: { boxes: Box[] }) {
  if (!boxes.length) return null;
  return (
    <svg className="boxes" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {boxes.map((b, i) => (
        <g key={i}>
          <rect x={b.x * 100} y={b.y * 100} width={b.w * 100} height={b.h * 100} className="boxes__outline" vectorEffect="non-scaling-stroke" />
          <rect
            x={b.x * 100}
            y={b.y * 100}
            width={b.w * 100}
            height={b.h * 100}
            className={`boxes__rect${(b.bunk ?? 0) >= 0.6 ? " boxes__rect--bunk" : ""}`}
            vectorEffect="non-scaling-stroke"
          />
        </g>
      ))}
    </svg>
  );
}

type Props = {
  photo: PhotoView;
  onOpen: (id: string) => void;
  highlightBoxes?: Box[] | null;
};

export function CatalogCard({ photo, onOpen, highlightBoxes }: Props) {
  const [failed, setFailed] = useState(false);
  const year = photo.taken || photo.published;
  const hl = highlightBoxes != null;
  return (
    <article className={`ccard ccard--${photo.level}${hl ? " is-evidence" : ""}`}>
      <button type="button" className="ccard__open" onClick={() => onOpen(photo.id)} aria-label={`Открыть карточку ${photo.shelfmark}: ${photo.title}`}>
        <div className="ccard__photo">
          {failed ? (
            <div className="ccard__broken">
              <span>Источник не отдал превью</span>
            </div>
          ) : (
            <img src={photo.image_url} alt={photo.title} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
          )}
          {hl ? <Boxes boxes={highlightBoxes!} /> : null}
        </div>
        <div className="ccard__body">
          <div className="ccard__row">
            <span className="ccard__shelf field">{photo.shelfmark}</span>
            <Stamp confidence={photo.confidence} level={photo.level} compact />
          </div>
          <p className="ccard__title">{photo.title || "Без названия"}</p>
          <p className="ccard__meta field">
            {SHORT_SOURCE[photo.source] ?? photo.source}
            {year ? ` · ${shortDate(year)}` : ""}
            {isOld(photo.taken, photo.published) ? <span className="ccard__old"> · старше 5 лет</span> : null}
          </p>
          {photo.duplicates.length ? <p className="ccard__dups field">+{photo.duplicates.length} копии склеены</p> : null}
        </div>
        <span className="hole" aria-hidden="true" />
      </button>
    </article>
  );
}

export function SkeletonCard() {
  return (
    <div className="ccard ccard--skeleton" aria-hidden="true">
      <div className="ccard__photo skel" />
      <div className="ccard__body">
        <div className="skel skel--line skel--short" />
        <div className="skel skel--line" />
        <div className="skel skel--line skel--short" />
      </div>
      <span className="hole" />
    </div>
  );
}
