import { distance, minutes, temp } from "../lib/format";
import type { ContextView, University } from "../lib/types";
import { ClimateChart } from "./ClimateChart";
import { Icon } from "./Icon";

export function CityPanel({ context, university, building }: { context: ContextView | null; university: University | null; building: boolean }) {
  const city = university?.city?.label;
  return (
    <section className="city" aria-labelledby="city-title">
      <h2 id="city-title" className="panel-title">Город и дорога</h2>
      {!context ? (
        building ? (
          <div aria-hidden="true">
            <div className="skel skel--row" />
            <div className="skel skel--row" />
          </div>
        ) : (
          <p className="panel-note">Климат и маршруты не собрались.</p>
        )
      ) : (
        <>
          {context.error ? <p className="panel-note">{context.error}</p> : null}
          {context.routes.length ? (
            <ul className="routes">
              {context.routes.map((r) => (
                <li key={r.key} className="route">
                  <Icon name={r.mode === "foot" ? "walk" : "car"} />
                  <span className="route__label">
                    {r.label}
                    {r.from.osm_url ? (
                      <>
                        {" "}
                        <a href={r.from.osm_url} target="_blank" rel="noreferrer" aria-label="Общежитие на карте OSM">
                          <Icon name="external" size={12} />
                        </a>
                      </>
                    ) : null}
                  </span>
                  <span className="route__value num">
                    <a href={r.source_url} target="_blank" rel="noreferrer">
                      {r.mode === "foot" ? "пешком " : "на машине "}
                      {minutes(r.duration_s)}
                    </a>
                    <span className="route__dist">{distance(r.distance_m)}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="panel-note">
              Маршрутов нет: в OpenStreetMap не отмечены общежития рядом{city ? ` или центр города ${city} совпадает с кампусом` : ""}.
            </p>
          )}
          {context.winter_walk ? (
            <p className="city__winter">
              Дорога от общежития занимает {context.winter_walk.minutes} мин, а средняя температура в самый холодный месяц ({context.winter_walk.month}){" "}
              {temp(context.winter_walk.t_mean)}.
            </p>
          ) : null}
          {context.amenities ? (
            <dl className="city__near">
              <div><dt>остановок</dt><dd className="num">{context.amenities.counts.transport}</dd></div>
              <div><dt>магазинов</dt><dd className="num">{context.amenities.counts.shop}</dd></div>
              <div><dt>аптек</dt><dd className="num">{context.amenities.counts.pharmacy}</dd></div>
              <p className="panel-note">В радиусе {distance(context.amenities.radius_m)} от главного корпуса по OpenStreetMap.{context.amenities.note ? ` ${context.amenities.note}` : ""}</p>
            </dl>
          ) : null}
          {context.climate ? (
            <>
              <h3 className="city__sub">Климат{city ? `: ${city}` : ""}</h3>
              <ClimateChart months={context.climate.months} title={`Температура по месяцам, средние за ${context.climate.years}`} />
              <p className="panel-note">
                Средние за {context.climate.years}, <a href={context.climate.url} target="_blank" rel="noreferrer">{context.climate.source}</a>
                {context.climate.from_cache ? ", из кэша" : ""}. Самый холодный месяц: {context.climate.coldest.label}, {temp(context.climate.coldest.t_mean)}; самый тёплый: {context.climate.warmest.label}, {temp(context.climate.warmest.t_mean)}.
              </p>
            </>
          ) : (
            <p className="panel-note">Климат не загрузился{context.climate_error ? `: ${context.climate_error}` : ""}.</p>
          )}
          {context.cost ? <p className="panel-note">Стоимость жизни: {context.cost.note}</p> : null}
        </>
      )}
    </section>
  );
}
