import type { ReactElement } from "react";

type Name =
  | "search" | "external" | "close" | "prev" | "next" | "hole" | "walk" | "car" | "compare" | "flag" | "link"
  | "target" | "expand" | "shrink" | "layers" | "zoomIn" | "zoomOut" | "spark" | "grid" | "check"
  | "sun" | "moon" | "share" | "download";

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
  target: (
    <>
      <circle cx="8" cy="8" r="4.5" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2" />
    </>
  ),
  expand: <path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" />,
  shrink: <path d="M6 2.5V6H2.5M13.5 6H10V2.5M10 13.5V10h3.5M2.5 10H6v3.5" />,
  layers: <path d="M8 2l5.5 3L8 8 2.5 5 8 2zM2.5 8.5L8 11.5l5.5-3M2.5 11.5L8 14.5l5.5-3" />,
  zoomIn: (
    <>
      <circle cx="7" cy="7" r="4.75" />
      <path d="M10.5 10.5L14 14M5 7h4M7 5v4" />
    </>
  ),
  zoomOut: (
    <>
      <circle cx="7" cy="7" r="4.75" />
      <path d="M10.5 10.5L14 14M5 7h4" />
    </>
  ),
  spark: <path d="M8 1.5l1.7 4.8 4.8 1.7-4.8 1.7L8 14.5l-1.7-4.8L1.5 8l4.8-1.7L8 1.5z" />,
  grid: <path d="M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z" />,
  check: <path d="M3 8.5l3.5 3.5L13 5" />,
  sun: (
    <>
      <circle cx="8" cy="8" r="3.25" />
      <path d="M8 1v1.75M8 13.25V15M1 8h1.75M13.25 8H15M3.05 3.05l1.24 1.24M11.71 11.71l1.24 1.24M12.95 3.05l-1.24 1.24M4.29 11.71l-1.24 1.24" />
    </>
  ),
  moon: <path d="M13 9.6A5.6 5.6 0 016.4 3a5.6 5.6 0 106.6 6.6z" />,
  share: (
    <>
      <circle cx="12" cy="4" r="2" />
      <circle cx="4" cy="8" r="2" />
      <circle cx="12" cy="12" r="2" />
      <path d="M5.8 7L10.2 5M5.8 9l4.4 2" />
    </>
  ),
  download: <path d="M8 2v8M4.5 7L8 10.5 11.5 7M3 13.5h10" />,
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
