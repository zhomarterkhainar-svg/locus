import { useState } from "react";
import { temp } from "../lib/format";
import type { ClimateMonth } from "../lib/types";

const W = 300;
const H = 150;
const L = 30;
const R = 6;
const T = 12;
const B = 20;

/** Средняя температура по месяцам: столбик от среднего минимума до среднего максимума, риска на среднем. */
export function ClimateChart({ months, title }: { months: ClimateMonth[]; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const lo = Math.min(...months.map((m) => m.t_min ?? m.t_mean));
  const hi = Math.max(...months.map((m) => m.t_max ?? m.t_mean));
  const step = 10;
  const yMin = Math.floor(Math.min(lo, 0) / step) * step;
  const yMax = Math.ceil(Math.max(hi, 0) / step) * step;
  const y = (t: number) => T + ((yMax - t) / (yMax - yMin || 1)) * (H - T - B);
  const band = (W - L - R) / 12;
  const bw = Math.min(14, band - 6);
  const ticks: number[] = [];
  for (let t = yMin; t <= yMax; t += step) ticks.push(t);
  const active = hover != null ? months.find((m) => m.month === hover) ?? null : null;

  return (
    <figure className="climate">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className={t === 0 ? "climate__zero" : "climate__grid"} />
            <text x={L - 5} y={y(t) + 3.5} textAnchor="end" className="climate__tick">{t > 0 ? `+${t}` : t < 0 ? `−${-t}` : "0"}</text>
          </g>
        ))}
        {months.map((m, i) => {
          const cx = L + band * i + band / 2;
          const top = y(m.t_max ?? m.t_mean);
          const bottom = y(m.t_min ?? m.t_mean);
          const cold = m.t_mean < 0;
          return (
            <g key={m.month} className={`climate__m${hover === m.month ? " is-hover" : ""}`} onMouseEnter={() => setHover(m.month)} onFocus={() => setHover(m.month)} tabIndex={0}>
              <rect x={L + band * i} y={T} width={band} height={H - T - B} className="climate__hit" />
              <rect x={cx - bw / 2} y={top} width={bw} height={Math.max(2, bottom - top)} rx="4" className={cold ? "climate__bar climate__bar--cold" : "climate__bar climate__bar--warm"} />
              <line x1={cx - bw / 2 - 2} x2={cx + bw / 2 + 2} y1={y(m.t_mean)} y2={y(m.t_mean)} className="climate__mean" />
              <text x={cx} y={H - 6} textAnchor="middle" className="climate__tick">{m.label[0].toUpperCase()}</text>
            </g>
          );
        })}
      </svg>
      <p className="climate__readout field" aria-live="polite">
        {active
          ? `${active.label}: в среднем ${temp(active.t_mean)}, от ${temp(active.t_min)} до ${temp(active.t_max)}${active.precip_mm != null ? `, осадки ${active.precip_mm} мм` : ""}${active.snow_days ? `, снег ${active.snow_days} дн.` : ""}`
          : "Наведите на месяц: столбик от средней ночной до средней дневной температуры, риска на среднем значении."}
      </p>
      <table className="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr><th>Месяц</th><th>Средняя</th><th>Минимум</th><th>Максимум</th><th>Осадки, мм</th></tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m.month}><td>{m.label}</td><td>{m.t_mean}</td><td>{m.t_min}</td><td>{m.t_max}</td><td>{m.precip_mm}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
