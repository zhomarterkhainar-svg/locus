import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { searchUniversities } from "../lib/api";
import type { Candidate, SearchResult } from "../lib/types";
import { Icon } from "./Icon";

/** Столько подсказок показываем: пять ближайших совпадений помещаются на экран целиком. */
const TOP = 5;
const RECENT_KEY = "candid:recent";
const RECENT_MAX = 5;

type Recent = { qid: string; label: string; meta: string };

function readRecent(): Recent[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.slice(0, RECENT_MAX) : [];
  } catch {
    // Приватное окно или запрет на хранение: подсказки просто не показываем.
    return [];
  }
}

export function rememberRecent(item: Recent) {
  try {
    const list = readRecent().filter((r) => r.qid !== item.qid);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify([item, ...list].slice(0, RECENT_MAX)));
  } catch {
    /* хранение недоступно - история просто не ведётся */
  }
}

/** Подсветка совпавшего куска названия: видно, почему подсказка попала в список. */
function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (q.length < 2) return <>{text}</>;
  const at = text.toLowerCase().indexOf(q.toLowerCase());
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark>{text.slice(at, at + q.length)}</mark>
      {text.slice(at + q.length)}
    </>
  );
}

type Props = {
  size?: "large" | "compact";
  initial?: string;
  autoFocus?: boolean;
  onResult?: (result: SearchResult | null, loading: boolean) => void;
  /** Если задано, выбор вуза не открывает профиль, а передаётся наружу (например, для сравнения). */
  onPick?: (c: Candidate) => void;
  placeholder?: string;
  submitLabel?: string;
};

export function SearchBox({ size = "large", initial = "", autoFocus = false, onResult, onPick, placeholder, submitLabel = "Найти" }: Props) {
  const [value, setValue] = useState(initial);
  const [items, setItems] = useState<Candidate[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pending, setPending] = useState(false);
  const [recent, setRecent] = useState<Recent[]>([]);
  // Бесплатный инстанс API засыпает после простоя: честно предупреждаем, а не молчим со спиннером.
  const [slow, setSlow] = useState(false);
  const navigate = useNavigate();
  const listId = useId();
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const skipNext = useRef(false);
  const submitted = useRef<string | null>(null);

  useEffect(() => {
    setRecent(readRecent());
  }, []);

  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
    const id = window.setTimeout(() => setSlow(true), 4500);
    return () => window.clearTimeout(id);
  }, [pending]);

  useEffect(() => {
    if (skipNext.current) {
      skipNext.current = false;
      return;
    }
    window.clearTimeout(timer.current);
    const q = value.trim();
    if (q.length < 2) {
      setItems([]);
      setOpen(false);
      return;
    }
    timer.current = window.setTimeout(async () => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      setPending(true);
      try {
        const res = await searchUniversities(q, ctrl.signal);
        if (submitted.current === q) return;
        setItems(res.candidates.slice(0, TOP));
        setOpen(res.candidates.length > 0);
        setActive(res.candidates.length ? 0 : -1);
      } catch {
        /* запрос отменён новым вводом */
      } finally {
        if (abort.current === ctrl) setPending(false);
      }
    }, 320);
    return () => window.clearTimeout(timer.current);
  }, [value]);

  const showRecent = open && !items.length && value.trim().length < 2 && recent.length > 0;

  function go(c: Candidate) {
    skipNext.current = true;
    setValue(c.label);
    setOpen(false);
    if (onPick) {
      onPick(c);
      return;
    }
    rememberRecent({ qid: c.qid, label: c.label, meta: [c.city, c.country].filter(Boolean).join(", ") });
    setRecent(readRecent());
    navigate(`/u/${c.qid}`);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (open && active >= 0 && items[active]) {
      go(items[active]);
      return;
    }
    const q = value.trim();
    if (q.length < 2) return;
    submitted.current = q;
    window.clearTimeout(timer.current);
    setOpen(false);
    setItems([]);
    setPending(true);
    abort.current?.abort();
    onResult?.(null, true);
    const res = await searchUniversities(q);
    setPending(false);
    if (onPick) {
      onResult?.(null, false);
      if (res.candidates.length) {
        setItems(res.candidates.slice(0, TOP));
        setOpen(true);
        setActive(0);
      } else {
        onResult?.(res, false);
      }
      return;
    }
    if (res.status === "ok" && res.candidates[0]) {
      onResult?.(null, false);
      go(res.candidates[0]);
      return;
    }
    if (onResult) onResult(res, false);
    else navigate(`/?q=${encodeURIComponent(q)}`);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" && !open && (items.length || recent.length)) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    const len = showRecent ? recent.length : items.length;
    if (!open || !len) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % len);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? len - 1 : a - 1));
    } else if (e.key === "Enter" && showRecent && active >= 0) {
      e.preventDefault();
      navigate(`/u/${recent[active].qid}`);
      setOpen(false);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <form className={`search search--${size}`} onSubmit={submit} role="search">
      <label className="visually-hidden" htmlFor={`${listId}-input`}>
        Название университета
      </label>
      <div className="search__field">
        <span className="search__icon">
          <Icon name="search" size={size === "large" ? 20 : 16} />
        </span>
        <input
          id={`${listId}-input`}
          type="text"
          value={value}
          onChange={(e) => {
            submitted.current = null;
            setValue(e.target.value);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onFocus={() => (items.length || recent.length) && setOpen(true)}
          placeholder={placeholder ?? (size === "large" ? "Например, ЕНУ, Nazarbayev University, КазНУ или адрес сайта" : "Другой вуз")}
          autoComplete="off"
          spellCheck={false}
          autoFocus={autoFocus}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          aria-autocomplete="list"
        />
        {pending ? <span className="search__pending" aria-hidden="true" /> : null}
        <button type="submit" className="btn btn--primary search__submit">
          {submitLabel}
        </button>
      </div>
      {slow ? (
        <p className="search__slow" role="status">
          Сервис просыпается после простоя, первый запрос может занять до минуты. Дальше поиск идёт за секунду.
        </p>
      ) : null}
      {open && (items.length || showRecent) ? (
        <ul className="search__list" id={listId} role="listbox">
          {showRecent ? <li className="search__group" role="presentation">Недавно смотрели</li> : null}
          {showRecent
            ? recent.map((r, i) => (
                <li
                  key={r.qid}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? "is-active" : undefined}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    navigate(`/u/${r.qid}`);
                    setOpen(false);
                  }}
                >
                  <span className="search__name">{r.label}</span>
                  <span className="search__meta">{r.meta}</span>
                </li>
              ))
            : items.map((c, i) => (
                <li
                  key={c.qid}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? "is-active" : undefined}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    go(c);
                  }}
                >
                  <span className="search__rank field" aria-hidden="true">{i + 1}</span>
                  <span className="search__name">
                    <Highlight text={c.label} query={value} />
                  </span>
                  <span className="search__meta">
                    {[c.city, c.country].filter(Boolean).join(", ") || c.description || "нет города в Wikidata"}
                  </span>
                  {c.score >= 95 ? <span className="search__badge field">точное</span> : null}
                </li>
              ))}
          {!showRecent ? (
            <li className="search__hint" role="presentation">
              ↑ ↓ — выбор, Enter — открыть профиль
            </li>
          ) : null}
        </ul>
      ) : null}
    </form>
  );
}
