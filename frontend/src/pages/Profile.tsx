import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Annotation } from "../components/Annotation";
import { CampusMap } from "../components/CampusMap";
import { CityPanel } from "../components/CityPanel";
import { CatalogCard, SkeletonCard } from "../components/CatalogCard";
import { Footer, TopBar } from "../components/Chrome";
import { Facts } from "../components/Facts";
import { Icon } from "../components/Icon";
import { PhotoDialog } from "../components/PhotoDialog";
import { Progress } from "../components/Progress";
import { RejectedList } from "../components/Rejected";
import { SearchBox } from "../components/SearchBox";
import { findInProfile } from "../lib/api";
import { download, photosToCsv } from "../lib/export";
import { distance, isOld, num } from "../lib/format";
import type { Box, FactView, FindResult, PhotoView } from "../lib/types";
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
  const [dense, setDense] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [hoverFact, setHoverFact] = useState<FactView | null>(null);
  const [onlyGeo, setOnlyGeo] = useState(false);
  const [onlyIndependent, setOnlyIndependent] = useState(false);
  const [onlyFresh, setOnlyFresh] = useState(false);
  const [find, setFind] = useState<{ q: string; loading: boolean; result: FindResult | null }>({ q: "", loading: false, result: null });
  const [comparing, setComparing] = useState(false);
  const [toast, setToast] = useState("");
  const findAbort = useRef<AbortController | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setFind({ q: "", loading: false, result: null });
    setComparing(false);
  }, [qid]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(id);
  }, [toast]);

  async function share() {
    const url = window.location.href;
    try {
      // На телефоне это системное меню «Поделиться», на десктопе - копирование ссылки.
      if (navigator.share) await navigator.share({ title: document.title, url });
      else {
        await navigator.clipboard.writeText(url);
        setToast("Ссылка скопирована");
      }
    } catch {
      setToast("Не удалось поделиться, скопируйте адрес из строки браузера");
    }
  }

  async function runFind(e: React.FormEvent) {
    e.preventDefault();
    const q = find.q.trim();
    if (q.length < 2) return;
    findAbort.current?.abort();
    const ctrl = new AbortController();
    findAbort.current = ctrl;
    setFind((f) => ({ ...f, loading: true }));
    try {
      const result = await findInProfile(qid, q, ctrl.signal);
      setFind((f) => ({ ...f, loading: false, result }));
    } catch {
      /* новый запрос отменил старый */
    }
  }

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

  const found = useMemo(() => {
    if (!find.result || find.result.error) return null;
    return new Map(find.result.results.map((r, i) => [r.id, i]));
  }, [find.result]);

  const visible = useMemo(() => {
    let list = drawer === "all" ? confirmed : confirmed.filter((p) => p.category === drawer);
    if (onlyGeo) list = list.filter((p) => p.lat != null);
    if (onlyIndependent) list = list.filter((p) => p.source !== "official");
    if (onlyFresh) list = list.filter((p) => !isOld(p.taken, p.published) && Boolean(p.taken || p.published));
    if (found) list = list.filter((p) => found.has(p.id));
    const sorted = [...list];
    if (found) sorted.sort((a, b) => found.get(a.id)! - found.get(b.id)!);
    else if (sort === "confidence") sorted.sort((a, b) => b.confidence - a.confidence);
    else sorted.sort((a, b) => (b.taken || b.published || "").localeCompare(a.taken || a.published || ""));
    return sorted;
  }, [confirmed, drawer, sort, onlyGeo, onlyIndependent, onlyFresh, found]);
  const filtered = onlyGeo || onlyIndependent || onlyFresh || Boolean(found);

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

  function retry() {
    setFresh(false);
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
              <button type="button" className="btn btn--primary" onClick={retry}>Попробовать снова</button>{" "}
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
                {uni.coords_source && uni.coords_source !== "Wikidata" ? (
                  <p className="label-block__meta panel-note">Координаты: {uni.coords_source}.</p>
                ) : null}
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
                  <button type="button" className="linkish label-block__compare" onClick={() => setComparing((v) => !v)} aria-expanded={comparing}>
                    <Icon name="compare" size={14} /> Сравнить с другим вузом
                  </button>
                  <button type="button" className="linkish" onClick={share}>
                    <Icon name="share" size={13} /> Поделиться
                  </button>
                  <button
                    type="button"
                    className="linkish"
                    onClick={() => download(`${uni.qid}-фонд.csv`, photosToCsv([...confirmed, ...unconfirmed]))}
                    disabled={!confirmed.length && !unconfirmed.length}
                    title="Таблица со ссылками на источники, авторами и лицензиями"
                  >
                    <Icon name="download" size={13} /> Выгрузить CSV
                  </button>
                </p>
                {comparing ? (
                  <div className="compare-pick">
                    <SearchBox
                      size="compact"
                      autoFocus
                      placeholder="С каким вузом сравнить"
                      submitLabel="Сравнить"
                      onPick={(c) => navigate(`/compare?a=${qid}&b=${c.qid}`)}
                    />
                  </div>
                ) : null}
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
            <Annotation description={state.description} building={building} />
            <Progress key={nonce} state={state} onRebuild={rebuild} />
            <div className="mobile-search">
              <SearchBox size="compact" />
            </div>
          </div>
          <CampusMap campus={state.campus} photos={confirmed} highlight={new Set(evidence.keys())} routes={state.context?.routes} onOpen={setOpenId} />
        </header>

        <div className="profile__body">
          <aside className="profile__side">
            <Facts facts={facts} building={building} photos={state.photos} onHover={setHoverFact} onOpen={setOpenId} activeFact={hoverFact?.id ?? null} />
            <CityPanel context={state.context} university={uni} building={building} />
          </aside>

          <section className="profile__fonds" aria-labelledby="fonds-title">
            <div className="fonds__head">
              <h2 id="fonds-title" className="panel-title">Фонд фотографий</h2>
              <button
                type="button"
                className="btn btn--ghost btn--small"
                onClick={() => setDense((v) => !v)}
                aria-pressed={dense}
                title={dense ? "Крупные карточки" : "Больше карточек на экране"}
              >
                <Icon name="grid" size={13} /> {dense ? "Крупнее" : "Плотнее"}
              </button>
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
                    <span className={`guide__count num${low ? " is-low" : ""}`} title={low ? "мало подтверждённых фото" : undefined}>
                      {n}
                    </span>
                    {low ? <span className="visually-hidden">, мало</span> : null}
                  </button>
                );
              })}
            </div>

            <div className="fonds__tools">
              <form className="find" onSubmit={runFind} role="search">
                <label className="visually-hidden" htmlFor="find-input">Найти на фото профиля</label>
                <input
                  id="find-input"
                  type="search"
                  value={find.q}
                  onChange={(e) => {
                    const q = e.target.value;
                    setFind((f) => ({ ...f, q, result: q ? f.result : null }));
                  }}
                  placeholder="Найти на фото: бассейн, двухъярусные кровати, зимой"
                  disabled={building && !all.length}
                />
                <button type="submit" className="btn btn--ghost btn--small" disabled={find.loading || find.q.trim().length < 2}>
                  {find.loading ? "Ищем…" : "Найти"}
                </button>
              </form>
              <fieldset className="filters">
                <legend className="visually-hidden">Фильтры фонда</legend>
                <label className="chip">
                  <input type="checkbox" checked={onlyGeo} onChange={(e) => setOnlyGeo(e.target.checked)} /> с геометкой
                </label>
                <label className="chip">
                  <input type="checkbox" checked={onlyIndependent} onChange={(e) => setOnlyIndependent(e.target.checked)} /> без сайта вуза
                </label>
                <label className="chip">
                  <input type="checkbox" checked={onlyFresh} onChange={(e) => setOnlyFresh(e.target.checked)} /> за последние 5 лет
                </label>
              </fieldset>
              {find.result ? (
                <p className="find__status" role="status">
                  {find.result.error
                    ? find.result.error
                    : find.result.english
                      ? `По запросу «${find.result.query}» (${find.result.english}) похожих фото: ${find.result.results.length}. Поиск идёт по содержанию кадра моделью CLIP.`
                      : find.result.message}{" "}
                  <button type="button" className="linkish" onClick={() => setFind({ q: "", loading: false, result: null })}>
                    Сбросить
                  </button>
                </p>
              ) : null}
            </div>

            <div className="fonds__panel" role="tabpanel">
              {visible.length ? (
                <div className={`grid${dense ? " grid--dense" : ""}`}>
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
                    {filtered
                      ? "Под выбранные фильтры фото не подошли"
                      : drawer === "all"
                        ? "Подтверждённых фото не нашлось"
                        : `В разделе «${DRAWERS.find((d) => d.key === drawer)?.label}» нет подтверждённых фото`}
                  </p>
                  {filtered ? <p>Снимите фильтры или сбросьте поиск по фото, чтобы увидеть весь фонд.</p> : null}
                  <p>
                    {EMPTY_HINT[drawer] ??
                      "Открытых снимков с понятным происхождением не нашлось. Мы не подставляем похожие фото из других мест, поэтому раздел пуст."}
                  </p>
                  {unconfirmed.length ? <p>Ниже есть неподтверждённые кандидаты: их можно проверить вручную по источнику.</p> : null}
                  {!filtered && !all.length ? (
                    <p className="empty__actions">
                      <button type="button" className="btn btn--primary btn--small" onClick={rebuild}>
                        Собрать заново без кэша
                      </button>{" "}
                      <Link to="/">Выбрать другой вуз</Link>
                    </p>
                  ) : null}
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
      {toast ? (
        <p className="toast" role="status">
          {toast}
        </p>
      ) : null}
      <Footer />
      <PhotoDialog
        photo={openPhoto}
        onClose={() => setOpenId(null)}
        onStep={step}
        position={openIndex >= 0 ? `${openIndex + 1} из ${navList.length}` : ""}
        calibratorTrained={state.calibrator ? state.calibrator.trained : null}
        qid={qid}
      />
    </>
  );
}
