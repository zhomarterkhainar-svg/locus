import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Annotation } from "../components/Annotation";
import { CampusPlan } from "../components/CampusPlan";
import { CatalogCard, SkeletonCard } from "../components/CatalogCard";
import { Footer, TopBar } from "../components/Chrome";
import { Facts } from "../components/Facts";
import { Icon } from "../components/Icon";
import { PhotoDialog } from "../components/PhotoDialog";
import { Progress } from "../components/Progress";
import { RejectedList } from "../components/Rejected";
import { distance, num } from "../lib/format";
import type { Box, FactView, PhotoView } from "../lib/types";
import { useProfileStream } from "../lib/useProfileStream";

const DRAWERS: { key: string; label: string }[] = [
  { key: "all", label: "Все" },
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

const EMPTY_HINT: Record<string, string> = {
  dormitory: "Фото общежитий редко публикуют с понятным происхождением. Это не значит, что общежитий нет.",
  lab: "Лаборатории снимают реже остальных помещений. Это не значит, что их нет.",
  sport: "Подтверждённых фото спортобъектов не нашлось. Проверьте карту OpenStreetMap в фактах.",
};

export function Profile() {
  const { qid = "" } = useParams();
  const [nonce, setNonce] = useState(0);
  const [fresh, setFresh] = useState(false);
  const state = useProfileStream(qid, nonce, fresh);
  const [drawer, setDrawer] = useState("all");
  const [sort, setSort] = useState<"confidence" | "date">("confidence");
  const [openId, setOpenId] = useState<string | null>(null);
  const [hoverFact, setHoverFact] = useState<FactView | null>(null);

  const building = state.phase === "connecting" || state.phase === "building";
  const uni = state.university;

  useEffect(() => {
    document.title = uni ? `${uni.label} · Candid AI` : "Сборка профиля · Candid AI";
  }, [uni]);

  const all = useMemo(() => state.order.map((id) => state.photos[id]).filter(Boolean) as PhotoView[], [state.order, state.photos]);
  const confirmed = useMemo(() => all.filter((p) => p.level !== "low"), [all]);
  const unconfirmed = useMemo(() => all.filter((p) => p.level === "low"), [all]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: confirmed.length };
    for (const p of confirmed) c[p.category] = (c[p.category] ?? 0) + 1;
    return c;
  }, [confirmed]);

  const visible = useMemo(() => {
    const list = drawer === "all" ? confirmed : confirmed.filter((p) => p.category === drawer);
    const sorted = [...list];
    if (sort === "confidence") sorted.sort((a, b) => b.confidence - a.confidence);
    else sorted.sort((a, b) => (b.taken || b.published || "").localeCompare(a.taken || a.published || ""));
    return sorted;
  }, [confirmed, drawer, sort]);

  const evidence = useMemo(() => {
    const m = new Map<string, Box[]>();
    hoverFact?.evidence.forEach((e) => m.set(e.photo_id, e.boxes));
    return m;
  }, [hoverFact]);

  const navList = useMemo(() => [...visible, ...unconfirmed], [visible, unconfirmed]);
  const openPhoto = openId ? state.photos[openId] ?? null : null;
  const openIndex = openPhoto ? navList.findIndex((p) => p.id === openPhoto.id) : -1;
  const step = useCallback(
    (dir: -1 | 1) => {
      if (openIndex < 0 || !navList.length) return;
      setOpenId(navList[(openIndex + dir + navList.length) % navList.length].id);
    },
    [openIndex, navList],
  );

  function rebuild() {
    setFresh(true);
    setNonce((n) => n + 1);
  }

  if (state.fatal && !uni) {
    return (
      <>
        <TopBar withSearch />
        <main className="page page--narrow">
          <div className="notice notice--error" role="alert">
            <h1>Профиль не собрался</h1>
            <p>{state.error}</p>
            <p>
              <button type="button" className="btn btn--primary" onClick={() => setNonce((n) => n + 1)}>Попробовать снова</button>{" "}
              <Link to="/">Вернуться к поиску</Link>
            </p>
          </div>
        </main>
        <Footer />
      </>
    );
  }

  const facts = state.facts;
  const drawerCount = (key: string) => counts[key] ?? 0;

  return (
    <>
      <TopBar withSearch />
      <main className="profile">
        <header className="label-block">
          <div className="label-block__text">
            {uni ? (
              <>
                <h1>{uni.label}</h1>
                <p className="label-block__meta">
                  {[uni.city?.label, uni.country?.label].filter(Boolean).join(", ")}
                  {uni.inception ? ` · основан в ${uni.inception}` : ""}
                  {uni.students ? ` · ${num(uni.students)} студентов по Wikidata` : ""}
                </p>
                <p className="label-block__links">
                  {uni.website ? (
                    <a href={uni.website} target="_blank" rel="noreferrer">
                      {uni.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} <Icon name="external" size={12} />
                    </a>
                  ) : null}
                  <a href={uni.wikidata_url} target="_blank" rel="noreferrer" className="field">
                    Wikidata {uni.qid} <Icon name="external" size={12} />
                  </a>
                  {uni.city_distance_m != null && uni.city ? (
                    <span>до центра города {uni.city.label}: {distance(uni.city_distance_m)} по прямой</span>
                  ) : null}
                </p>
              </>
            ) : (
              <div aria-hidden="true">
                <div className="skel skel--title" />
                <div className="skel skel--line skel--short" />
              </div>
            )}
            {state.error && !state.fatal ? <p className="notice notice--warn" role="status">{state.error}</p> : null}
            {state.notices.map((n) => (
              <p key={n} className="notice notice--warn" role="status">{n}</p>
            ))}
            <Progress state={state} onRebuild={rebuild} />
          </div>
          <CampusPlan campus={state.campus} photos={confirmed} highlight={new Set(evidence.keys())} />
        </header>

        <div className="profile__body">
          <aside className="profile__side">
            <Facts facts={facts} building={building} photos={state.photos} onHover={setHoverFact} onOpen={setOpenId} activeFact={hoverFact?.id ?? null} />
            <Annotation description={state.description} building={building} />
          </aside>

          <section className="profile__fonds" aria-labelledby="fonds-title">
            <div className="fonds__head">
              <h2 id="fonds-title" className="panel-title">Фонд фотографий</h2>
              <label className="sort">
                <span>Порядок</span>
                <select value={sort} onChange={(e) => setSort(e.target.value as "confidence" | "date")}>
                  <option value="confidence">по достоверности</option>
                  <option value="date">сначала новые</option>
                </select>
              </label>
            </div>

            <div className="guides" role="tablist" aria-label="Разделы фонда">
              {DRAWERS.map((d, i) => {
                const n = drawerCount(d.key);
                const low = d.key !== "all" && !building && n > 0 && n < 3;
                return (
                  <button
                    key={d.key}
                    type="button"
                    role="tab"
                    aria-selected={drawer === d.key}
                    className={`guide guide--cut${i % 3}${drawer === d.key ? " is-active" : ""}${n === 0 && d.key !== "all" ? " is-empty" : ""}`}
                    onClick={() => setDrawer(d.key)}
                  >
                    <span className="guide__label">{d.label}</span>
                    <span className="guide__count num">{n}</span>
                    {low ? <span className="guide__low">мало</span> : null}
                  </button>
                );
              })}
            </div>

            <div className="fonds__panel" role="tabpanel">
              {visible.length ? (
                <div className="grid">
                  {visible.map((p) => (
                    <CatalogCard key={p.id} photo={p} onOpen={setOpenId} highlightBoxes={evidence.has(p.id) ? evidence.get(p.id)! : null} />
                  ))}
                  {building ? [0, 1, 2].map((i) => <SkeletonCard key={`s${i}`} />) : null}
                </div>
              ) : building ? (
                <div className="grid">
                  {Array.from({ length: 8 }, (_, i) => <SkeletonCard key={i} />)}
                </div>
              ) : (
                <div className="empty">
                  <p className="empty__title">
                    {drawer === "all" ? "Подтверждённых фото не нашлось" : `В разделе «${DRAWERS.find((d) => d.key === drawer)?.label}» нет подтверждённых фото`}
                  </p>
                  <p>
                    {EMPTY_HINT[drawer] ??
                      "Открытых снимков с понятным происхождением не нашлось. Мы не подставляем похожие фото из других мест, поэтому раздел пуст."}
                  </p>
                  {unconfirmed.length ? <p>Ниже есть неподтверждённые кандидаты: их можно проверить вручную по источнику.</p> : null}
                </div>
              )}
            </div>

            {unconfirmed.length ? (
              <details className="drawer">
                <summary>
                  <span className="drawer__title">Не подтверждено</span>
                  <span className="drawer__count num">{unconfirmed.length}</span>
                  <span className="drawer__hint">снимки, принадлежность которых сервис не смог надёжно подтвердить</span>
                </summary>
                <div className="grid grid--low">
                  {unconfirmed.map((p) => (
                    <CatalogCard key={p.id} photo={p} onOpen={setOpenId} />
                  ))}
                </div>
              </details>
            ) : null}
            {state.rejected.length ? <RejectedList items={state.rejected} /> : null}
          </section>
        </div>
      </main>
      <Footer />
      <PhotoDialog
        photo={openPhoto}
        onClose={() => setOpenId(null)}
        onStep={step}
        position={openIndex >= 0 ? `${openIndex + 1} из ${navList.length}` : ""}
        calibratorTrained={state.calibrator ? state.calibrator.trained : null}
      />
    </>
  );
}
