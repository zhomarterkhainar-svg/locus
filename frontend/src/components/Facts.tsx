import { useEffect, useState } from "react";
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

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 1100px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1100px)");
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

const RANK: Record<string, number> = { confirmed: 0, weak: 1, insufficient: 2, not_found: 3 };

export function Facts({ facts, building, photos, onHover, onOpen, activeFact }: Props) {
  const narrow = useNarrow();
  const [showAll, setShowAll] = useState(false);
  const collapsed = narrow && !showAll;
  const shownIds = new Set(
    (facts ?? [])
      .slice()
      .sort((a, b) => RANK[a.status] - RANK[b.status])
      .slice(0, collapsed ? 3 : undefined)
      .map((f) => f.id),
  );
  return (
    <section className="facts" aria-labelledby="facts-title">
      <h2 id="facts-title" className="panel-title">Что видно на фото</h2>
      <p className="panel-note">Факты считаются только по подтверждённым фото. Наведите на факт, чтобы увидеть доказательства на снимках, или нажмите, чтобы открыть первое фото.</p>
      {!facts ? (
        <div className="facts__skeleton" aria-hidden={!building}>
          {building ? [0, 1, 2, 3].map((i) => <div key={i} className="skel skel--row" />) : <p className="panel-note">Факты не собрались.</p>}
        </div>
      ) : (
        GROUPS.map((g) => {
          const items = facts.filter((f) => f.group === g.key && shownIds.has(f.id));
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
                    data-clickable={f.evidence.length > 0}
                    onClick={(e) => {
                      if ((e.target as HTMLElement).closest("a, button")) return;
                      if (f.evidence[0] && photos[f.evidence[0].photo_id]) onOpen(f.evidence[0].photo_id);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && f.evidence[0] && photos[f.evidence[0].photo_id]) onOpen(f.evidence[0].photo_id);
                    }}
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
      {facts && narrow && facts.length > 3 ? (
        <button type="button" className="btn btn--ghost btn--small facts__more" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Свернуть факты" : `Все факты (${facts.length})`}
        </button>
      ) : null}
    </section>
  );
}
