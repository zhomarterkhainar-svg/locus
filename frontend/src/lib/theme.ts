import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "candid:theme";
const listeners = new Set<(t: Theme) => void>();

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    // Приватное окно: выбор просто не запоминается, тема берётся из системной настройки.
    return null;
  }
}

let current: Theme = "light";

/** Применяем тему до первой отрисовки, иначе страница мигает светлым. */
export function initTheme() {
  current = stored() ?? systemTheme();
  document.documentElement.dataset.theme = current;
}

export function setTheme(next: Theme) {
  current = next;
  document.documentElement.dataset.theme = next;
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    /* хранение недоступно - тема действует до перезагрузки */
  }
  listeners.forEach((fn) => fn(next));
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, set] = useState<Theme>(current);
  useEffect(() => {
    set(current);
    listeners.add(set);
    return () => {
      listeners.delete(set);
    };
  }, []);
  return [theme, setTheme];
}
