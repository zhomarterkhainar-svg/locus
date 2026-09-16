import type { ReactElement } from "react";

type Name = "search" | "external" | "close" | "prev" | "next" | "hole" | "walk" | "car" | "compare" | "flag" | "link";

const PATHS: Record<Name, ReactElement> = {
  search: (
    <>
      <circle cx="7" cy="7" r="4.75" />
      <path d="M10.5 10.5L14 14" />
    </>
  ),
  external: <path d="M6 3.5H3.5v9h9V10M9 3.5h3.5V7M12.5 3.5L7.5 8.5" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  prev: <path d="M10 3.5L5.5 8 10 12.5" />,
  next: <path d="M6 3.5L10.5 8 6 12.5" />,
  hole: <circle cx="8" cy="8" r="3" />,
  walk: (
    <>
      <circle cx="8.5" cy="2.75" r="1.25" />
      <path d="M7 14.5l1.5-5 2 2v3.5M8.5 9.5l.5-3.5-3 1.5v2.5M9 6l1.5 2H13" />
    </>
  ),
  car: (
    <>
      <path d="M2.5 11.5V8.5l1.5-4h8l1.5 4v3h-11zM2.5 8.5h11" />
      <path d="M4.5 11.5v2M11.5 11.5v2" />
    </>
  ),
  compare: <path d="M5.5 2.5v11M10.5 2.5v11M2.5 5.5h3M10.5 10.5h3" />,
  flag: <path d="M3.5 14.5v-12h8l-2 3 2 3h-8" />,
  link: <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 014.5 9l1-1" />,
};

export function Icon({ name, size = 16, title }: { name: Name; size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="square"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {PATHS[name]}
    </svg>
  );
}
