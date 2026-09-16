import { useMemo, useState } from "react";
import type { CampusView, OsmObjectView, PhotoView, RouteView } from "../lib/types";

const KIND_MARK: Record<string, string> = { dormitory: "О", academic: "К", library: "Б", sport: "С", canteen: "П" };
const W = 340;
const H = 250;
const PAD = 22;
const TILE = 256;

// Web Mercator в пикселях мира на уровне z
function wx(lon: number, z: number) {
  return ((lon + 180) / 360) * TILE * 2 ** z;
}
function wy(lat: number, z: number) {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * TILE * 2 ** z;
}

type Props = {
  campus: CampusView | null;
  photos: PhotoView[];
  highlight?: Set<string>;
  routes?: RouteView[];
  onOpen?: (id: string) => void;
};

export function CampusMap({ campus, photos, highlight, routes = [], onOpen }: Props) {
  const [tilesFailed, setTilesFailed] = useState(false);
  const own = useMemo(() => (campus?.objects ?? []).filter((o) => o.kind !== "other_university"), [campus]);
  const stops = useMemo(() => (campus?.amenities ?? []).filter((o) => o.kind === "transport"), [campus]);
  const pins = useMemo(
    () => photos.filter((p) => p.lat != null && p.lon != null && p.scope === "campus" && (p.distance_m ?? 0) < 900),
    [photos],
  );
  const walks = routes.filter((r) => r.key.startsWith("dorm_") && r.line.length > 1);

  const view = useMemo(() => {
    if (!campus || (!campus.center && !campus.rings.length)) return null;
    const pts: [number, number][] = [];
    campus.rings.forEach((r) => pts.push(...r));
    own.forEach((o) => pts.push([o.lat, o.lon]));
    pins.forEach((p) => pts.push([p.lat!, p.lon!]));
    walks.forEach((r) => pts.push(r.line[0]));
    if (campus.center) pts.push(campus.center);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    const [s, n, w, e] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
    let z = 18;
    while (z > 11 && (wx(e, z) - wx(w, z) > W - 2 * PAD || wy(s, z) - wy(n, z) > H - 2 * PAD)) z -= 1;
    const cx = (wx(w, z) + wx(e, z)) / 2;
    const cy = (wy(s, z) + wy(n, z)) / 2;
    return { z, x0: cx - W / 2, y0: cy - H / 2, lat0: (s + n) / 2 };
  }, [campus, own, pins, walks]);

  if (!campus || !view) {
    return (
      <div className="plan plan--empty">
        <p>{campus ? "Для этого вуза нет координат на карте." : "Загружаем карту кампуса…"}</p>
      </div>
    );
  }
  const { z, x0, y0, lat0 } = view;
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
  const center = campus.center ?? [lat0, 0];
  const osmLink = `https://www.openstreetmap.org/#map=${Math.min(z, 18)}/${center[0].toFixed(5)}/${center[1].toFixed(5)}`;

  return (
    <figure className="plan">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Карта кампуса по данным OpenStreetMap">
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
                  key={`${t.x}-${t.y}`}
                  className="plan__tile"
                  href={`https://${"abcd"[(t.x + t.y) % 4]}.basemaps.cartocdn.com/light_all/${z}/${((t.x % n) + n) % n}/${t.y}@2x.png`}
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
          {walks.map((r) => (
            <polyline key={r.key} className="plan__route" points={r.line.map(([a, b]) => proj(a, b).join(",")).join(" ")}>
              <title>{r.label}</title>
            </polyline>
          ))}
          {stops.map((o) => {
            const [x, y] = proj(o.lat, o.lon);
            return (
              <circle key={o.osm} className="plan__stop" cx={x} cy={y} r="2.5">
                <title>{`Остановка${o.name ? `: ${o.name}` : ""}`}</title>
              </circle>
            );
          })}
          {own.map((o) => (
            <ObjMark key={o.osm} o={o} xy={proj(o.lat, o.lon)} />
          ))}
          {pins.map((p) => {
            const [x, y] = proj(p.lat!, p.lon!);
            const hl = highlight?.has(p.id);
            return (
              <circle
                key={p.id}
                className={`plan__pin${hl ? " is-hl" : ""}${onOpen ? " is-clickable" : ""}`}
                cx={x}
                cy={y}
                r={hl ? 5.5 : 4}
                onClick={onOpen ? () => onOpen(p.id) : undefined}
              >
                <title>{`${p.shelfmark}: ${p.title}`}</title>
              </circle>
            );
          })}
        </g>
        <g className="plan__scale" transform={`translate(${PAD}, ${H - 12})`}>
          <rect x="-6" y="-9" width={barPx + 58} height="16" className="plan__scale-bg" />
          <line x1="0" y1="0" x2={barPx} y2="0" />
          <text x={barPx + 6} y="3.5">{barMeters >= 1000 ? `${barMeters / 1000} км` : `${barMeters} м`}</text>
        </g>
      </svg>
      <figcaption className="plan__legend">
        <span><i className="lg lg--campus" /> {campus.rings.length ? "граница кампуса" : "примерное место, границы нет в OSM"}</span>
        <span><i className="lg lg--obj" /> О общежитие, К корпус, Б библиотека, С спорт</span>
        <span><i className="lg lg--pin" /> фото с геометкой</span>
        {walks.length ? <span><i className="lg lg--route" /> пешком от общежития</span> : null}
        {stops.length ? <span><i className="lg lg--stop" /> остановка</span> : null}
        <span className="plan__credit">
          <a href={osmLink} target="_blank" rel="noreferrer">© OpenStreetMap</a>
          {!tilesFailed ? ", © CARTO" : ""}
          {campus.from_cache ? " · карта из кэша" : ""}
        </span>
      </figcaption>
    </figure>
  );
}

function ObjMark({ o, xy: [x, y] }: { o: OsmObjectView; xy: [number, number] }) {
  return (
    <g className={`plan__obj plan__obj--${o.kind}`}>
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
