import type { ReactElement } from "react";

type Name = "search" | "external" | "close" | "prev" | "next" | "hole";

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
