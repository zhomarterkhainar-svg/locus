import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { searchUniversities } from "../lib/api";
import type { Candidate, SearchResult } from "../lib/types";
import { Icon } from "./Icon";

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
  const navigate = useNavigate();
  const listId = useId();
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const skipNext = useRef(false);
  const submitted = useRef<string | null>(null);

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
        setItems(res.candidates.slice(0, 6));
        setOpen(res.candidates.length > 0);
        setActive(-1);
      } catch {
        /* запрос отменён новым вводом */
      } finally {
        if (abort.current === ctrl) setPending(false);
      }
    }, 320);
    return () => window.clearTimeout(timer.current);
  }, [value]);

  function go(c: Candidate) {
    skipNext.current = true;
    setValue(c.label);
    setOpen(false);
    if (onPick) onPick(c);
    else navigate(`/u/${c.qid}`);
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
    setPending(false);
    abort.current?.abort();
    onResult?.(null, true);
    const res = await searchUniversities(q);
    if (onPick) {
      onResult?.(null, false);
      if (res.candidates.length) {
        setItems(res.candidates.slice(0, 6));
        setOpen(true);
        setActive(0);
      } else {
        onResult?.(res, false);
      }
      return;
    }
    if (res.status === "ok" && res.candidates[0]) {
      onResult?.(null, false);
      navigate(`/u/${res.candidates[0].qid}`);
      return;
    }
    if (onResult) onResult(res, false);
    else navigate(`/?q=${encodeURIComponent(q)}`);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? items.length - 1 : a - 1));
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
          onFocus={() => items.length && setOpen(true)}
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
      {open ? (
        <ul className="search__list" id={listId} role="listbox">
          {items.map((c, i) => (
            <li
              key={c.qid}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "is-active" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                go(c);
              }}
            >
              <span className="search__name">{c.label}</span>
              <span className="search__meta">{[c.city, c.country].filter(Boolean).join(", ") || c.description}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}
