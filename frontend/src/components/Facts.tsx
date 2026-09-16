import type { FactView, PhotoView } from "../lib/types";
import { FactStamp } from "./Stamp";

const GROUPS: { key: FactView["group"]; label: string }[] = [
  { key: "dormitory", label: "Общежитие" },
  { key: "sport", label: "Спорт" },
];

type Props = {
  facts: FactView[] | null;
  building: boolean;
  photos: Record<string, PhotoView>;
  onHover: (fact: FactView | null) => void;
  onOpen: (photoId: string) => void;
  activeFact: string | null;
};

export function Facts({ facts, building, photos, onHover, onOpen, activeFact }: Props) {
  return (
    <section className="facts" aria-labelledby="facts-title">
      <h2 id="facts-title" className="panel-title">Что видно на фото</h2>
      <p className="panel-note">Факты считаются только по подтверждённым фото. Наведите на факт, чтобы увидеть доказательства на снимках.</p>
      {!facts ? (
        <div className="facts__skeleton" aria-hidden={!building}>
          {building ? [0, 1, 2, 3].map((i) => <div key={i} className="skel skel--row" />) : <p className="panel-note">Факты не собрались.</p>}
        </div>
      ) : (
        GROUPS.map((g) => {
          const items = facts.filter((f) => f.group === g.key);
          if (!items.length) return null;
          return (
            <div key={g.key} className="facts__group">
              <h3>{g.label}</h3>
              <ul>
                {items.map((f) => (
                  <li
                    key={f.id}
                    className={`fact fact--${f.status}${activeFact === f.id ? " is-active" : ""}`}
                    onMouseEnter={() => onHover(f)}
                    onMouseLeave={() => onHover(null)}
                    onFocus={() => onHover(f)}
                    onBlur={() => onHover(null)}
                    tabIndex={f.evidence.length ? 0 : -1}
                  >
                    <div className="fact__head">
                      <span className="fact__label">{f.label}</span>
                      <FactStamp status={f.status} />
                    </div>
                    <p className="fact__value">{f.value}</p>
                    {f.evidence.length ? (
                      <p className="fact__evidence">
                        <span>Доказательства:</span>
                        {f.evidence.map((e) =>
                          photos[e.photo_id] ? (
                            <button key={e.photo_id} type="button" className="shelf-link field" onClick={() => onOpen(e.photo_id)}>
                              {e.shelfmark}
                            </button>
                          ) : null,
                        )}
                      </p>
                    ) : null}
                    {f.osm.length ? (
                      <p className="fact__evidence">
                        <span>На карте:</span>
                        {f.osm.slice(0, 3).map((o) => (
                          <a key={o.osm} href={o.url} target="_blank" rel="noreferrer">{o.name || o.kind_label}</a>
                        ))}
                      </p>
                    ) : null}
                    {f.note ? <p className="fact__note">{f.note}</p> : null}
                  </li>
                ))}
              </ul>
            </div>
          );
        })
      )}
    </section>
  );
}
