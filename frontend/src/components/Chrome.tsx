import { useEffect } from "react";
import { Link, NavLink } from "react-router-dom";
import { useTheme } from "../lib/theme";
import { Icon } from "./Icon";
import { SearchBox } from "./SearchBox";

/** Светлая тема - бумага, тёмная - тот же архив при настольной лампе. Выбор запоминается. */
export function ThemeToggle() {
  const [theme, set] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => set(next)}
      aria-label={next === "dark" ? "Включить тёмную тему" : "Включить светлую тему"}
      title={next === "dark" ? "Тёмная тема" : "Светлая тема"}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} size={15} />
    </button>
  );
}

export function TopBar({ withSearch = false }: { withSearch?: boolean }) {
  // Клавиша «/» ставит курсор в поиск, если пользователь не печатает в другом поле.
  useEffect(() => {
    if (!withSearch) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = document.activeElement;
      const tag = el?.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || (el as HTMLElement)?.isContentEditable) return;
      const input = document.querySelector<HTMLInputElement>(".topbar__search input");
      if (!input) return;
      e.preventDefault();
      input.focus();
      input.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [withSearch]);

  return (
    <header className="topbar">
      <div className="topbar__inner">
        <Link to="/" className="wordmark" aria-label="Candid AI, на главную">
          <span className="wordmark__mark" aria-hidden="true" />
          Candid AI
        </Link>
        {withSearch ? (
          <div className="topbar__search">
            <SearchBox size="compact" />
          </div>
        ) : null}
        <nav className="topbar__nav" aria-label="Разделы">
          <NavLink to="/method">Как это работает</NavLink>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <p className="footer__lead">
          Candid AI собирает фото из открытых источников и показывает, откуда каждое. Фото принадлежат своим авторам.
        </p>
        <nav className="footer__nav" aria-label="Документы">
          <Link to="/method">Метод и ограничения</Link>
          <Link to="/terms">Условия использования</Link>
          <Link to="/privacy">Политика конфиденциальности</Link>
        </nav>
        <p className="footer__note">Прототип для LOCUS Startup Hackathon 2026, кейс 1. Данные: Wikidata, Wikimedia Commons, OpenStreetMap, сайты вузов, Flickr.</p>
      </div>
    </footer>
  );
}
