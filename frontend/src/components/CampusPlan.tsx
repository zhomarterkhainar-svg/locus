import type { CampusView, PhotoView } from "../lib/types";

const KIND_MARK: Record<string, string> = { dormitory: "О", academic: "К", library: "Б", sport: "С", canteen: "П" };

export function CampusPlan({ campus, photos, highlight }: { campus: CampusView | null; photos: PhotoView[]; highlight?: Set<string> }) {
  if (!campus || (!campus.center && !campus.rings.length)) {
    return (
      <div className="plan plan--empty">
        <p>{campus ? "Для этого вуза нет координат на карте." : "Загружаем план кампуса…"}</p>
      </div>
    );
  }
  const pts: [number, number][] = [];
  campus.rings.forEach((r) => pts.push(...r));
  const own = campus.objects.filter((o) => o.kind !== "other_university");
  own.forEach((o) => pts.push([o.lat, o.lon]));
  const pins = photos.filter((p) => p.lat != null && p.lon != null && p.scope === "campus" && (p.distance_m ?? 0) < 900);
  pins.forEach((p) => pts.push([p.lat!, p.lon!]));
  if (campus.center) pts.push(campus.center);
  const lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p[1] * k);
  const ys = pts.map((p) => -p[0]);
  let minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const minSpan = 0.004;
  if (maxX - minX < minSpan) { const c = (minX + maxX) / 2; minX = c - minSpan / 2; maxX = c + minSpan / 2; }
  if (maxY - minY < minSpan) { const c = (minY + maxY) / 2; minY = c - minSpan / 2; maxY = c + minSpan / 2; }
  const W = 320, H = 220, pad = 18;
  const scale = Math.min((W - 2 * pad) / (maxX - minX), (H - 2 * pad) / (maxY - minY));
  const ox = (W - (maxX - minX) * scale) / 2, oy = (H - (maxY - minY) * scale) / 2;
  const proj = (lat: number, lon: number): [number, number] => [ox + (lon * k - minX) * scale, oy + (-lat - minY) * scale];
  const metersPerUnit = 111_320;
  const barMeters = niceBar(((W - 2 * pad) / scale) * metersPerUnit * 0.3);
  const barPx = (barMeters / metersPerUnit) * scale;

  return (
    <figure className="plan">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Схема кампуса по данным OpenStreetMap">
        <rect x="0" y="0" width={W} height={H} className="plan__bg" />
        {campus.rings.map((ring, i) => (
          <polygon key={i} className="plan__campus" points={ring.map(([a, b]) => proj(a, b).join(",")).join(" ")} />
        ))}
        {!campus.rings.length && campus.center ? (
          <circle className="plan__campus" cx={proj(...campus.center)[0]} cy={proj(...campus.center)[1]} r={Math.max(12, (campus.radius_m / metersPerUnit) * scale * 0.5)} />
        ) : null}
        {own.map((o) => {
          const [x, y] = proj(o.lat, o.lon);
          return (
            <g key={o.osm} className={`plan__obj plan__obj--${o.kind}`}>
              <rect x={x - 6} y={y - 6} width="12" height="12" />
              <text x={x} y={y + 3.5} textAnchor="middle">{KIND_MARK[o.kind] ?? "·"}</text>
              <title>{`${o.kind_label}${o.name ? `: ${o.name}` : ""}`}</title>
            </g>
          );
        })}
        {pins.map((p) => {
          const [x, y] = proj(p.lat!, p.lon!);
          return (
            <circle key={p.id} className={`plan__pin${highlight?.has(p.id) ? " is-hl" : ""}`} cx={x} cy={y} r={highlight?.has(p.id) ? 4.5 : 3}>
              <title>{`${p.shelfmark}: ${p.title}`}</title>
            </circle>
          );
        })}
        <g className="plan__scale" transform={`translate(${pad}, ${H - 10})`}>
          <line x1="0" y1="0" x2={barPx} y2="0" />
          <text x={barPx + 5} y="3.5">{barMeters >= 1000 ? `${barMeters / 1000} км` : `${barMeters} м`}</text>
        </g>
      </svg>
      <figcaption className="plan__legend">
        <span><i className="lg lg--campus" /> граница кампуса</span>
        <span><i className="lg lg--obj" /> О общежитие, К корпус, Б библиотека, С спорт</span>
        <span><i className="lg lg--pin" /> фото с геометкой</span>
      </figcaption>
    </figure>
  );
}

function niceBar(m: number): number {
  const steps = [50, 100, 200, 250, 500, 1000, 2000, 5000];
  return steps.reduce((best, s) => (Math.abs(s - m) < Math.abs(best - m) ? s : best), steps[0]);
}
