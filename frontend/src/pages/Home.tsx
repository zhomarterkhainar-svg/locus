import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Footer, TopBar } from "../components/Chrome";
import { SearchBox } from "../components/SearchBox";
import { searchUniversities } from "../lib/api";
import type { SearchResult } from "../lib/types";

const EXAMPLES = [
  "Евразийский национальный университет",
  "Nazarbayev University",
  "КазНУ имени аль-Фараби",
  "Satbayev University",
  "Astana IT University",
];

export function Home() {
  const [params] = useSearchParams();
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    document.title = "Candid AI · университет на реальных фото";
    const q = params.get("q");
    if (q) void run(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(q: string) {
    setLoading(true);
    setResult(null);
    const res = await searchUniversities(q);
    setLoading(false);
    if (res.status === "ok" && res.candidates[0]) {
      navigate(`/u/${res.candidates[0].qid}`);
      return;
    }
    setResult(res);
  }

  return (
    <>
      <TopBar />
      <main className="home">
        <section className="home__entry" aria-labelledby="home-title">
          <div className="home__search">
            <h1 id="home-title" className="home__title">Как на самом деле выглядит университет</h1>
            <p className="home__lead">
              Введите название вуза. За полминуты Candid AI соберёт фото кампуса, общежитий, аудиторий, библиотек и города из открытых
              источников, проверит, что они относятся к этому вузу, и покажет, откуда взято каждое.
            </p>
            <SearchBox autoFocus onResult={(r, l) => { setResult(r); setLoading(l); }} />
            <div className="home__examples">
              <span>Попробуйте:</span>
              <ul>
                {EXAMPLES.map((e) => (
                  <li key={e}>
                    <button type="button" className="linkish" onClick={() => run(e)}>
                      {e}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <SearchOutcome result={result} loading={loading} onSuggestion={run} />
            <p className="home__compare">
              Выбираете из двух?{" "}
              <Link to="/compare?a=Q127745&b=Q2783344">Сравните вузы по фактам с фото-доказательствами</Link>
            </p>
          </div>
          <CardAnatomy />
        </section>

        <section className="method-strip" aria-labelledby="method-title">
          <h2 id="method-title">Как собирается фонд вуза</h2>
          <ol className="method-strip__steps">
            <li>
              <b>Находим вуз</b>
              <span>в Wikidata: координаты, город, сайт, названия на трёх языках и сокращения вроде ЕНУ.</span>
            </li>
            <li>
              <b>Собираем кандидатов</b>
              <span>из Wikimedia Commons, с официального сайта, из Flickr и с карты OpenStreetMap, параллельно.</span>
            </li>
            <li>
              <b>Проверяем принадлежность</b>
              <span>по геометке относительно границы кампуса, по названию в подписи, по типу источника.</span>
            </li>
            <li>
              <b>Убираем лишнее</b>
              <span>дубликаты, фотобанки, логотипы, афиши, марки и снимки далеко от кампуса. Причина видна.</span>
            </li>
            <li>
              <b>Читаем фото</b>
              <span>детектор считает кровати и отличает двухъярусные, фото спортобъектов сверяются с картой, рядом климат и путь до корпуса.</span>
            </li>
          </ol>
          <p className="method-strip__more">
            <Link to="/method">Подробно о методе, моделях и ограничениях</Link>
          </p>
        </section>
      </main>
      <Footer />
    </>
  );
}

function SearchOutcome({ result, loading, onSuggestion }: { result: SearchResult | null; loading: boolean; onSuggestion: (q: string) => void }) {
  if (loading) {
    return (
      <div className="outcome" aria-live="polite">
        <p className="outcome__status">Ищем в Wikidata…</p>
        <div className="outcome__list">
          {[0, 1, 2].map((i) => (
            <div key={i} className="cand cand--skeleton" aria-hidden="true">
              <div className="skel skel--thumb" />
              <div className="cand__body">
                <div className="skel skel--line" />
                <div className="skel skel--line skel--short" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (!result) return null;
  if (result.status === "error") {
    return (
      <div className="outcome outcome--error" role="alert">
        <p>{result.message ?? "Поиск не ответил."}</p>
      </div>
    );
  }
  if (result.status === "not_found" || result.status === "too_short") {
    return (
      <div className="outcome" role="status">
        <p className="outcome__status">
          {result.status === "too_short" ? "Введите хотя бы два символа." : `По запросу «${result.query}» вуз в Wikidata не нашёлся.`}
        </p>
        {result.suggestion ? (
          <p>
            Возможно, вы имели в виду{" "}
            <button type="button" className="linkish" onClick={() => onSuggestion(result.suggestion!)}>
              {result.suggestion}
            </button>
            .
          </p>
        ) : null}
        <p className="outcome__hint">Проверьте написание, попробуйте полное официальное название или название на английском.</p>
      </div>
    );
  }
  return (
    <div className="outcome" aria-live="polite">
      <p className="outcome__status">Под запрос «{result.query}» подходит несколько вузов. Уточните, какой нужен:</p>
      <ul className="outcome__list">
        {result.candidates.map((c) => (
          <li key={c.qid}>
            <Link to={`/u/${c.qid}`} className="cand">
              <CandThumb src={c.image} />
              <span className="cand__body">
                <span className="cand__name">{c.label}</span>
                <span className="cand__meta">{[c.city, c.country].filter(Boolean).join(", ")}</span>
                {c.description && /[а-яёәғқңөұүһі]/i.test(c.description) ? <span className="cand__desc">{c.description}</span> : null}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CandThumb({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className="cand__thumb cand__thumb--empty" aria-hidden="true" />;
  return <img className="cand__thumb" src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

function CardAnatomy() {
  return (
    <figure className="anatomy" aria-labelledby="anatomy-caption">
      <div className="anatomy__card">
        <div className="anatomy__photo">
          <span>фото по ссылке источника</span>
        </div>
        <dl className="anatomy__fields">
          <div>
            <dt>Шифр</dt>
            <dd className="field">ОБЩ-004</dd>
          </div>
          <div>
            <dt>Раздел</dt>
            <dd>Общежития</dd>
          </div>
          <div>
            <dt>Источник</dt>
            <dd>страница файла, кликабельно</dd>
          </div>
          <div>
            <dt>Автор, лицензия</dt>
            <dd>как указаны у источника</dd>
          </div>
          <div>
            <dt>Даты</dt>
            <dd>съёмки, публикации, получения</dd>
          </div>
          <div>
            <dt>Достоверность</dt>
            <dd>
              <span className="stamp stamp--high">
                <span className="num">0–100</span>
                <span className="stamp__word">с разбором</span>
              </span>
            </dd>
          </div>
        </dl>
        <span className="hole" aria-hidden="true" />
      </div>
      <figcaption id="anatomy-caption">
        Каждое фото хранится в фонде как каталожная карточка. Шифр показывает раздел, штамп показывает, насколько сервис уверен, что снимок относится к вузу.
      </figcaption>
    </figure>
  );
}
