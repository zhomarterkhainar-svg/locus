import { REJECT_WORD } from "../lib/format";
import type { RejectedView } from "../lib/types";

export function RejectedList({ items }: { items: RejectedView[] }) {
  const shown = items.filter((i) => i.reason !== "download");
  const failed = items.length - shown.length;
  const counts = shown.reduce<Record<string, number>>((acc, i) => ({ ...acc, [i.reason]: (acc[i.reason] ?? 0) + 1 }), {});
  return (
    <details className="drawer">
      <summary>
        <span className="drawer__title">Изъято из фонда</span>
        <span className="drawer__count num">{shown.length}</span>
        <span className="drawer__hint">
          {Object.entries(counts).map(([k, v]) => `${REJECT_WORD[k] ?? k} ${v}`).join(" · ")}
          {failed ? ` · не скачалось ${failed}` : ""}
        </span>
      </summary>
      <table className="rejects">
        <thead>
          <tr><th scope="col">Причина</th><th scope="col">Подробно</th><th scope="col">Источник</th></tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id + r.reason}>
              <td><span className="reject-tag">{REJECT_WORD[r.reason] ?? r.reason}</span></td>
              <td>{r.title ? <span className="rejects__title">{r.title}</span> : null}{r.detail}</td>
              <td><a href={r.page_url} target="_blank" rel="noreferrer">{r.host}</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
