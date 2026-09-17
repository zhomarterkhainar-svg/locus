import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../lib/theme";
import type { CampusView, OsmObjectView, PhotoView, RouteView } from "../lib/types";
import { Icon } from "./Icon";

const KIND_MARK: Record<string, string> = { dormitory: "О", academic: "К", library: "Б", sport: "С", canteen: "П" };
const W = 340;
const H = 250;
const PAD = 22;
const TILE = 256;
const MIN_Z = 11;
const MAX_Z = 19;

// Web Mercator в пикселях мира на уровне z
function wx(lon: number, z: number) {
  return ((lon + 180) / 360) * TILE * 2 ** z;
}
function wy(lat: number, z: number) {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * TILE * 2 ** z;
}
// Обратное преобразование: нужно при перетаскивании, чтобы сдвиг в пикселях стал новым центром.
function lonAt(x: number, z: number) {
  return (x / (TILE * 2 ** z)) * 360 - 180;
}
function latAt(y: number, z: number) {
  const n = Math.PI - (2 * Math.PI * y) / (TILE * 2 ** z);
  return (180 / Math.PI) * Math.atan(Math.sinh(n));
}

type Selected =
  | { kind: "object"; title: string; note: string; url: string; lat: number; lon: number }
  | { kind: "photo"; id: string; title: string; note: string; lat: number; lon: number };

type Layers = { objects: boolean; photos: boolean; routes: boolean; stops: boolean };

type Props = {
  campus: CampusView | null;
  photos: PhotoView[];
  highlight?: Set<string>;
  routes?: RouteView[];
  onOpen?: (id: string) => void;
};

export function CampusMap({ campus, photos, highlight, routes = [], onOpen }: Props) {
  const [tilesFailed, setTilesFailed] = useState(false);
  const [zoomDelta, setZoomDelta] = useState(0);
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [layers, setLayers] = useState<Layers>({ objects: true, photos: true, routes: true, stops: true });
  const [theme] = useTheme();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ x: number; y: number; center: [number, number]; moved: boolean } | null>(null);

  const own = useMemo(() => (campus?.objects ?? []).filter((o) => o.kind !== "other_university"), [campus]);
  const stops = useMemo(() => (campus?.amenities ?? []).filter((o) => o.kind === "transport"), [campus]);
  const pins = useMemo(
    () => photos.filter((p) => p.lat != null && p.lon != null && p.scope === "campus" && (p.distance_m ?? 0) < 900),
    [photos],
  );
  const walks = useMemo(() => routes.filter((r) => r.key.startsWith("dorm_") && r.line.length > 1), [routes]);

  // Автоподбор охвата по данным: он же используется как «исходный вид» для кнопки сброса.
  const fit = useMemo(() => {
    if (!campus || (!campus.center && !campus.rings.length)) return null;
    const pts: [number, number][] = [];
    campus.rings.forEach((r) => pts.push(...r));
    own.forEach((o) => pts.push([o.lat, o.lon]));
    pins.forEach((p) => pts.push([p.lat!, p.lon!]));
    walks.forEach((r) => pts.push(r.line[0]));
    if (campus.center) pts.push(campus.center);
    if (!pts.length) return null;
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    const [s, n, w, e] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
    let z = 18;
    while (z > MIN_Z && (wx(e, z) - wx(w, z) > W - 2 * PAD || wy(s, z) - wy(n, z) > H - 2 * PAD)) z -= 1;
    return { z, center: [(s + n) / 2, (w + e) / 2] as [number, number] };
  }, [campus, own, pins, walks]);

  const z = fit ? Math.min(MAX_Z, Math.max(MIN_Z, fit.z + zoomDelta)) : 16;
  const view = useMemo(() => {
    if (!fit) return null;
    const c = center ?? fit.center;
    return { z, x0: wx(c[1], z) - W / 2, y0: wy(c[0], z) - H / 2, lat0: c[0] };
  }, [fit, center, z]);

  const reset = useCallback(() => {
    setZoomDelta(0);
    setCenter(null);
    setSelected(null);
  }, []);

  // Колесо мыши: слушатель вешаем сами, потому что React отдаёт wheel пассивным
  // и preventDefault в нём не работает — страница уезжала бы вместе с зумом карты.
  useEffect(() => {
    const el = svgRef.current;
    if (!el || !view) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const box = el.getBoundingClientRect();
      const sx = ((e.clientX - box.left) / box.width) * W;
      const sy = ((e.clientY - box.top) / box.height) * H;
      const dir = e.deltaY > 0 ? -1 : 1;
      const next = Math.min(MAX_Z, Math.max(MIN_Z, view.z + dir));
      if (next === view.z) return;
      // Держим точку под курсором на месте: так зум ощущается как в настоящей карте.
      const lat = latAt(view.y0 + sy, view.z);
      const lon = lonAt(view.x0 + sx, view.z);
      const nx = wx(lon, next) - sx + W / 2;
      const ny = wy(lat, next) - sy + H / 2;
      setZoomDelta(next - (fit?.z ?? next));
      setCenter([latAt(ny, next), lonAt(nx, next)]);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [view, fit]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  if (!campus || !view) {
    return (
      <div className="plan plan--empty">
        <p>{campus ? "Для этого вуза нет координат на карте." : "Загружаем карту кампуса…"}</p>
      </div>
    );
  }

  const { x0, y0, lat0 } = view;
  const proj = (lat: number, lon: number): [number, number] => [wx(lon, z) - x0, wy(lat, z) - y0];
  const tiles: { x: number; y: number }[] = [];
  const n = 2 ** z;
  for (let tx = Math.floor(x0 / TILE); tx <= Math.floor((x0 + W) / TILE); tx++) {
    for (let ty = Math.floor(y0 / TILE); ty <= Math.floor((y0 + H) / TILE); ty++) {
      if (ty >= 0 && ty < n) tiles.push({ x: tx, y: ty });
    }
  }
  const mPerPx = (156543.03392 * Math.cos((lat0 * Math.PI) / 180)) / n;
  const barMeters = niceBar(W * 0.28 * mPerPx);
  const barPx = barMeters / mPerPx;
  const mapCenter = campus.center ?? [lat0, 0];
  const osmLink = `https://www.openstreetmap.org/#map=${Math.min(z, 18)}/${mapCenter[0].toFixed(5)}/${mapCenter[1].toFixed(5)}`;
  const moved = zoomDelta !== 0 || center !== null;

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest("[data-hit]")) return;
    (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, center: center ?? (fit as { center: [number, number] }).center, moved: false };
    setDragging(true);
  };

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d) return;
    const box = e.currentTarget.getBoundingClientRect();
    const dx = ((e.clientX - d.x) / box.width) * W;
    const dy = ((e.clientY - d.y) / box.height) * H;
    if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
    const cx = wx(d.center[1], z) - dx;
    const cy = wy(d.center[0], z) - dy;
    setCenter([latAt(cy, z), lonAt(cx, z)]);
  };

  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };

  const zoomBy = (dir: 1 | -1) => {
    const next = Math.min(MAX_Z, Math.max(MIN_Z, z + dir));
    if (next === z) return;
    setCenter(center ?? (fit as { center: [number, number] }).center);
    setZoomDelta(next - (fit?.z ?? next));
  };

  const toggle = (key: keyof Layers) => setLayers((l) => ({ ...l, [key]: !l[key] }));
  const selXY = selected ? proj(selected.lat, selected.lon) : null;

  return (
    <figure className={`plan${expanded ? " plan--expanded" : ""}${dragging ? " is-dragging" : ""}`}>
      <div className="plan__stage">
        <svg
          ref={svgRef}
          className="plan__svg"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Карта кампуса по данным OpenStreetMap: перетаскивайте мышью, колесо меняет масштаб"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <defs>
            <clipPath id="plan-clip">
              <rect x="0" y="0" width={W} height={H} />
            </clipPath>
          </defs>
          <g clipPath="url(#plan-clip)">
            <rect x="0" y="0" width={W} height={H} className="plan__bg" />
            {!tilesFailed
              ? tiles.map((t) => (
                  <image
                    key={`${z}-${t.x}-${t.y}`}
                    className={`plan__tile${theme === "dark" ? " plan__tile--dark" : ""}`}
                    href={`https://tile.openstreetmap.org/${z}/${((t.x % n) + n) % n}/${t.y}.png`}
                    x={t.x * TILE - x0}
                    y={t.y * TILE - y0}
                    width={TILE}
                    height={TILE}
                    onError={() => setTilesFailed(true)}
                  />
                ))
              : null}
            {campus.rings.map((ring, i) => (
              <polygon key={i} className="plan__campus" points={ring.map(([a, b]) => proj(a, b).join(",")).join(" ")} />
            ))}
            {!campus.rings.length && campus.center ? (
              <circle
                className="plan__campus plan__campus--approx"
                cx={proj(...campus.center)[0]}
                cy={proj(...campus.center)[1]}
                r={Math.max(14, (campus.radius_m * 0.5) / mPerPx)}
              />
            ) : null}
            {layers.routes
              ? walks.map((r) => (
                  <polyline key={r.key} className="plan__route" points={r.line.map(([a, b]) => proj(a, b).join(",")).join(" ")}>
                    <title>{r.label}</title>
                  </polyline>
                ))
              : null}
            {layers.stops
              ? stops.map((o) => {
                  const [x, y] = proj(o.lat, o.lon);
                  return (
                    <circle key={o.osm} className="plan__stop" cx={x} cy={y} r="2.5">
                      <title>{`Остановка${o.name ? `: ${o.name}` : ""}`}</title>
                    </circle>
                  );
                })
              : null}
            {layers.objects
              ? own.map((o) => (
                  <ObjMark
                    key={o.osm}
                    o={o}
                    xy={proj(o.lat, o.lon)}
                    active={selected?.kind === "object" && selected.title === (o.name || o.kind_label)}
                    onPick={() =>
                      setSelected({
                        kind: "object",
                        title: o.name || o.kind_label,
                        note: o.name ? o.kind_label : "Объект на карте OpenStreetMap",
                        url: o.url,
                        lat: o.lat,
                        lon: o.lon,
                      })
                    }
                  />
                ))
              : null}
            {layers.photos
              ? pins.map((p) => {
                  const [x, y] = proj(p.lat!, p.lon!);
                  const hl = highlight?.has(p.id) || (selected?.kind === "photo" && selected.id === p.id);
                  return (
                    <circle
                      key={p.id}
                      data-hit="1"
                      className={`plan__pin${hl ? " is-hl" : ""} is-clickable`}
                      cx={x}
                      cy={y}
                      r={hl ? 5.5 : 4}
                      onClick={() =>
                        setSelected({ kind: "photo", id: p.id, title: p.shelfmark, note: p.title || p.category_label, lat: p.lat!, lon: p.lon! })
                      }
                    >
                      <title>{`${p.shelfmark}: ${p.title}`}</title>
                    </circle>
                  );
                })
              : null}
          </g>
          <g className="plan__scale" transform={`translate(${PAD}, ${H - 12})`}>
            <rect x="-6" y="-9" width={barPx + 58} height="16" className="plan__scale-bg" />
            <line x1="0" y1="0" x2={barPx} y2="0" />
            <text x={barPx + 6} y="3.5">{barMeters >= 1000 ? `${barMeters / 1000} км` : `${barMeters} м`}</text>
          </g>
        </svg>

        <div className="plan__zoom">
          <button type="button" onClick={() => zoomBy(1)} aria-label="Приблизить" disabled={z >= MAX_Z}>+</button>
          <button type="button" onClick={() => zoomBy(-1)} aria-label="Отдалить" disabled={z <= MIN_Z}>−</button>
          <button type="button" onClick={reset} aria-label="Вернуть исходный вид" disabled={!moved} title="Исходный вид">
            <Icon name="target" size={13} />
          </button>
          <button type="button" onClick={() => setExpanded((v) => !v)} aria-label={expanded ? "Свернуть карту" : "Развернуть карту"} title={expanded ? "Свернуть" : "Развернуть"}>
            <Icon name={expanded ? "shrink" : "expand"} size={13} />
          </button>
        </div>

        {selected && selXY ? (
          <div
            className="plan__popup"
            style={{ left: `${(selXY[0] / W) * 100}%`, top: `${(selXY[1] / H) * 100}%` }}
            role="dialog"
            aria-label={selected.title}
          >
            <button type="button" className="plan__popup-close" onClick={() => setSelected(null)} aria-label="Закрыть">
              ×
            </button>
            <p className="plan__popup-title">{selected.title}</p>
            {selected.note ? <p className="plan__popup-note">{selected.note}</p> : null}
            {selected.kind === "photo" && onOpen ? (
              <button type="button" className="btn btn--ghost btn--small" onClick={() => onOpen(selected.id)}>
                Открыть фото
              </button>
            ) : null}
            {selected.kind === "object" ? (
              <a href={selected.url} target="_blank" rel="noreferrer">
                Открыть в OpenStreetMap <Icon name="external" size={11} />
              </a>
            ) : null}
          </div>
        ) : null}

        {expanded ? (
          <button type="button" className="plan__backdrop" aria-label="Закрыть карту" onClick={() => setExpanded(false)} />
        ) : null}
      </div>

      <figcaption className="plan__legend">
        <span><i className="lg lg--campus" /> {campus.rings.length ? "граница кампуса" : "примерное место, границы нет в OSM"}</span>
        <LayerToggle on={layers.objects} onClick={() => toggle("objects")} mark="obj" count={own.length}>
          О общежитие, К корпус, Б библиотека, С спорт
        </LayerToggle>
        <LayerToggle on={layers.photos} onClick={() => toggle("photos")} mark="pin" count={pins.length}>
          фото с геометкой
        </LayerToggle>
        {walks.length ? (
          <LayerToggle on={layers.routes} onClick={() => toggle("routes")} mark="route" count={walks.length}>
            пешком от общежития
          </LayerToggle>
        ) : null}
        {stops.length ? (
          <LayerToggle on={layers.stops} onClick={() => toggle("stops")} mark="stop" count={stops.length}>
            остановка
          </LayerToggle>
        ) : null}
        <span className="plan__credit">
          <a href={osmLink} target="_blank" rel="noreferrer">© OpenStreetMap</a>
          {campus.from_cache ? " · карта из кэша" : ""}
        </span>
      </figcaption>
    </figure>
  );
}

function LayerToggle({
  on,
  onClick,
  mark,
  count,
  children,
}: {
  on: boolean;
  onClick: () => void;
  mark: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <button type="button" className={`lg-toggle${on ? " is-on" : ""}`} onClick={onClick} aria-pressed={on} title={on ? "Скрыть слой" : "Показать слой"}>
      <i className={`lg lg--${mark}`} /> {children} <span className="lg-toggle__count num">{count}</span>
    </button>
  );
}

function ObjMark({ o, xy: [x, y], active, onPick }: { o: OsmObjectView; xy: [number, number]; active: boolean; onPick: () => void }) {
  return (
    <g className={`plan__obj plan__obj--${o.kind}${active ? " is-active" : ""}`} data-hit="1" onClick={onPick} role="button" tabIndex={-1}>
      <rect x={x - 7} y={y - 7} width="14" height="14" />
      <text x={x} y={y + 3.5} textAnchor="middle">{KIND_MARK[o.kind] ?? "·"}</text>
      <title>{`${o.kind_label}${o.name ? `: ${o.name}` : ""}`}</title>
    </g>
  );
}

function niceBar(m: number): number {
  const steps = [20, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000];
  return steps.reduce((best, s) => (Math.abs(s - m) < Math.abs(best - m) ? s : best), steps[0]);
}
