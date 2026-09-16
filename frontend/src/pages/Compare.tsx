import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Footer, TopBar } from "../components/Chrome";
import { Icon } from "../components/Icon";
import { PhotoDialog } from "../components/PhotoDialog";
import { SearchBox } from "../components/SearchBox";
import { FactStamp } from "../components/Stamp";
import { distance, minutes, num, seconds, temp } from "../lib/format";
import type { FactView, PhotoView } from "../lib/types";
import { useProfileStream, type ProfileState } from "../lib/useProfileStream";

const CATS: { key: string; label: string }[] = [
  { key: "campus", label: "Кампус" },
  { key: "dormitory", label: "Общежития" },
  { key: "classroom", label: "Аудитории" },
  { key: "library", label: "Библиотеки" },
  { key: "lab", label: "Лаборатории" },
  { key: "sport", label: "Спорт" },
  { key: "canteen", label: "Столовые" },
  { key: "student_life", label: "Студенческая жизнь" },
  { key: "city", label: "Город" },
];

const FACT_ROWS: { id: string; label: string }[] = [
  { id: "dorm_beds", label: "Кроватей на фото комнаты" },
  { id: "dorm_bunk", label: "Двухъярусные кровати" },
  { id: "dorm_desks", label: "Столы в комнатах" },
  { id: "dorm_kitchen", label: "Фото кухни" },
  { id: "dorm_bathroom", label: "Фото душевой" },
  { id: "dorm_osm", label: "Общежития на карте" },
  { id: "sport_pool", label: "Бассейн" },
  { id: "sport_gym", label: "Тренажёрный зал" },
  { id: "sport_stadium", label: "Стадион или поле" },
  { id: "sport_court", label: "Спортзал с площадкой" },
];

type Cell = { text: string; key: string; fact?: FactView; photo?: PhotoView | null; muted?: boolean };
type Row = { label: string; cells: [Cell, Cell] };

function photosOf(s: ProfileState): PhotoView[] {
  return s.order.map((id) => s.photos[id]).filter((p): p is PhotoView => Boolean(p) && p.level !== "low");
}

function basics(s: ProfileState): Cell[] {
  const u = s.university;
  const ctx = s.context;
  const car = ctx?.routes.find((r) => r.key === "city_car");
  const walk = ctx?.routes.filter((r) => r.key.startsWith("dorm_")).sort((a, b) => a.duration_s - b.duration_s)[0];
  const t = (v: string | null | undefined, key = v ?? ""): Cell => (v ? { text: v, key } : { text: "нет данных", key: "—", muted: true });
  return [
    t([u?.city?.label, u?.country?.label].filter(Boolean).join(", ") || null),
    t(u?.inception ? `${u.inception}` : null),
    t(u?.students ? `${num(u.students)}` : null),
    t(car ? `${minutes(car.duration_s)}, ${distance(car.distance_m)}` : u?.city_distance_m != null ? `${distance(u.city_distance_m)} по прямой` : null),
    t(walk ? `${minutes(walk.duration_s)} пешком` : null),
    t(ctx?.climate ? temp(ctx.climate.coldest.t_mean) + ` (${ctx.climate.coldest.label})` : null),
    t(ctx?.climate ? temp(ctx.climate.warmest.t_mean) + ` (${ctx.climate.warmest.label})` : null),
    t(ctx?.amenities ? `${ctx.amenities.counts.transport}` : null),
  ];
}

const BASIC_LABELS = ["Город", "Основан", "Студентов (Wikidata)", "От центра города на машине", "От общежития до корпуса", "Самый холодный месяц", "Самый тёплый месяц", "Остановок в 900 м"];

export function Compare() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const valid = /^Q\d+$/.test(a) && /^Q\d+$/.test(b) && a !== b;
  const sa = useProfileStream(valid ? a : "", 0, false);
  const sb = useProfileStream(valid ? b : "", 0, false);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [open, setOpen] = useState<{ side: 0 | 1; id: string } | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    document.title = sa.university && sb.university ? `${sa.university.label} и ${sb.university.label} · Candid AI` : "Сравнение вузов · Candid AI";
  }, [sa.university, sb.university]);

  const sides = [sa, sb] as const;
  const sections = useMemo(() => {
    const pa = photosOf(sa);
    const pb = photosOf(sb);
    const ba = basics(sa);
    const bb = basics(sb);
    const general: Row[] = BASIC_LABELS.map((label, i) => ({ label, cells: [ba[i], bb[i]] }));
    const fonds: Row[] = [
      { label: "Подтверждённых фото", cells: [{ text: `${pa.length}`, key: `${pa.length}` }, { text: `${pb.length}`, key: `${pb.length}` }] },
      ...CATS.map((c) => {
        const cell = (ps: PhotoView[]): Cell => {
          const list = ps.filter((p) => p.category === c.key).sort((x, y) => y.confidence - x.confidence);
          return { text: list.length ? `${list.length}` : "0", key: `${Math.min(list.length, 3)}`, photo: list[0] ?? null, muted: !list.length };
        };
        return { label: c.label, cells: [cell(pa), cell(pb)] as [Cell, Cell] };
      }),
    ];
    const facts: Row[] = FACT_ROWS.map((r) => {
      const cell = (s: ProfileState): Cell => {
        const f = s.facts?.find((x) => x.id === r.id);
        if (!f) return { text: s.facts ? "нет данных" : "…", key: "—", muted: true };
        const ev = f.evidence[0] ? s.photos[f.evidence[0].photo_id] ?? null : null;
        return { text: f.value, key: `${f.status}:${f.value}`, fact: f, photo: ev };
      };
      return { label: r.label, cells: [cell(sa), cell(sb)] as [Cell, Cell] };
    });
    return [
      { title: "Общее", rows: general },
      { title: "Фонд фотографий", rows: fonds },
      { title: "Что видно на фото", rows: facts },
    ];
  }, [sa, sb]);

  if (!valid) {
    return (
      <>
        <TopBar withSearch />
        <main className="page page--narrow">
          <h1>Сравнение вузов</h1>
          <p>Выберите два разных вуза. Первый можно открыть из поиска, второй выбрать кнопкой «Сравнить с другим вузом» в профиле.</p>
          <p><Link to="/">На главную</Link></p>
        </main>
        <Footer />
      </>
    );
  }

  const openPhoto = open ? sides[open.side].photos[open.id] ?? null : null;
  const building = [sa, sb].some((s) => s.phase === "connecting" || s.phase === "building");

  return (
    <>
      <TopBar withSearch />
      <main className="compare">
        <header className="compare__head">
          <h1>Сравнение вузов</h1>
          <div className="compare__actions">
            <label className="chip">
              <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> только различия
            </label>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(window.location.href);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                } catch {
                  setCopied(false);
                }
              }}
            >
              <Icon name="link" size={14} /> {copied ? "Ссылка скопирована" : "Скопировать ссылку"}
            </button>
          </div>
        </header>

        <div className="ctable" role="table" aria-label="Сравнение двух вузов">
          <div className="ctable__row ctable__row--head" role="row">
            <span className="ctable__label" role="columnheader">
              {building ? "Профили собираются…" : "Оба профиля собраны"}
            </span>
            {sides.map((s, i) => (
              <div key={i} className="ctable__uni" role="columnheader">
                {s.university ? (
                  <Link to={`/u/${s.university.qid}`} className="ctable__name">{s.university.label}</Link>
                ) : s.fatal ? (
                  <span className="ctable__name">Вуз не загрузился</span>
                ) : (
                  <span className="skel skel--line" aria-hidden="true" />
                )}
                <span className="field ctable__time">
                  {s.phase === "done" ? `собран за ${seconds(s.totalMs ?? 0)}${s.replay ? ", из кэша" : ""}` : s.phase === "failed" ? s.error ?? "ошибка" : `сборка · ${s.counters.in_profile} фото`}
                </span>
                <div className="ctable__swap">
                  <SearchBox
                    size="compact"
                    placeholder="Заменить вуз"
                    submitLabel="Заменить"
                    onPick={(c) => navigate(i === 0 ? `/compare?a=${c.qid}&b=${b}` : `/compare?a=${a}&b=${c.qid}`)}
                  />
                </div>
              </div>
            ))}
          </div>
          {sections.map((sec) => {
            const rows = onlyDiff ? sec.rows.filter((r) => r.cells[0].key !== r.cells[1].key) : sec.rows;
            if (!rows.length) return null;
            return (
              <div key={sec.title} role="rowgroup" className="ctable__group">
                <div className="ctable__section" role="row">
                  <span role="cell">{sec.title}</span>
                </div>
                {rows.map((r) => {
                  const diff = r.cells[0].key !== r.cells[1].key && !r.cells.some((c) => c.key === "—");
                  return (
                    <div key={r.label} className={`ctable__row${diff ? " is-diff" : ""}`} role="row">
                      <span className="ctable__label" role="rowheader">
                        {r.label}
                        {diff ? <span className="ctable__diff">различается</span> : null}
                      </span>
                      {r.cells.map((c, i) => (
                        <div key={i} className={`ctable__cell${c.muted ? " is-muted" : ""}`} role="cell">
                          <span className="ctable__value">{c.text}</span>
                          {c.fact ? <FactStamp status={c.fact.status} /> : null}
                          {c.photo ? (
                            <button type="button" className="ctable__ev" onClick={() => setOpen({ side: i as 0 | 1, id: c.photo!.id })} aria-label={`Фото-доказательство ${c.photo.shelfmark}`}>
                              <img src={c.photo.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
                              <span className="field">{c.photo.shelfmark}</span>
                            </button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
        <p className="panel-note compare__note">
          Значения собраны теми же проверками, что и в профиле: факты только по подтверждённым фото, маршруты и климат из OpenStreetMap и Open-Meteo.
          «Нет данных» и «не найдено» не значат, что этого нет в вузе.
        </p>
      </main>
      <Footer />
      <PhotoDialog
        photo={openPhoto}
        onClose={() => setOpen(null)}
        onStep={() => undefined}
        position={open ? (sides[open.side].university?.label ?? "") : ""}
        calibratorTrained={sides[open?.side ?? 0].calibrator?.trained ?? null}
        qid={open ? (open.side === 0 ? a : b) : undefined}
      />
    </>
  );
}
