import { useEffect, useReducer, useRef } from "react";
import type {
  Box, CampusView, Counters, DescriptionView, FactView, PhotoView, RejectedView, SourceStatus, StageKey, StageStatus, University,
} from "./types";

export type ProfileState = {
  phase: "connecting" | "building" | "done" | "failed";
  replay: boolean;
  cachedAt: number | null;
  university: University | null;
  campus: CampusView | null;
  stages: Record<StageKey, StageStatus>;
  sources: Record<string, SourceStatus>;
  photos: Record<string, PhotoView>;
  order: string[];
  rejected: RejectedView[];
  counters: Counters;
  facts: FactView[] | null;
  description: DescriptionView | null;
  notices: string[];
  error: string | null;
  fatal: boolean;
  totalMs: number | null;
  lastT: number;
  calibrator: { trained: boolean; note: string } | null;
  model: string;
};

const initial: ProfileState = {
  phase: "connecting",
  replay: false,
  cachedAt: null,
  university: null,
  campus: null,
  stages: { resolve: "idle", sources: "idle", analyze: "idle", facts: "idle", describe: "idle" },
  sources: {},
  photos: {},
  order: [],
  rejected: [],
  counters: { found: 0, downloaded: 0, analyzed: 0, in_profile: 0, unconfirmed: 0, rejected: 0, duplicates: 0 },
  facts: null,
  description: null,
  notices: [],
  error: null,
  fatal: false,
  totalMs: null,
  lastT: 0,
  calibrator: null,
  model: "",
};

type Action =
  | { type: "reset" }
  | { type: "event"; name: string; data: any }
  | { type: "connection_lost" };

function reducer(state: ProfileState, action: Action): ProfileState {
  if (action.type === "reset") return initial;
  if (action.type === "connection_lost") {
    if (state.phase === "done") return state;
    return { ...state, phase: "failed", error: "Соединение с сервером прервалось. Профиль мог собраться не полностью.", fatal: false };
  }
  const { name, data } = action;
  const t = typeof data.t === "number" ? data.t : state.lastT;
  const s = { ...state, lastT: t, phase: state.phase === "connecting" ? "building" : state.phase } as ProfileState;
  switch (name) {
    case "meta":
      return { ...s, replay: data.replay, cachedAt: data.cached_at };
    case "stage":
      return { ...s, stages: { ...s.stages, [data.key]: data.status } };
    case "university":
      return { ...s, university: data };
    case "campus":
      return { ...s, campus: data };
    case "source":
      return { ...s, sources: { ...s.sources, [data.key]: data } };
    case "photos": {
      const photos = { ...s.photos };
      const order = [...s.order];
      for (const p of data.photos as PhotoView[]) {
        if (!photos[p.id]) order.push(p.id);
        photos[p.id] = p;
      }
      return { ...s, photos, order };
    }
    case "photo_update": {
      const photos = { ...s.photos };
      const p = data.photo as PhotoView;
      const replaces = data.replaces as string;
      let order = s.order;
      if (replaces !== p.id) {
        delete photos[replaces];
        order = s.order.map((id) => (id === replaces ? p.id : id));
      }
      photos[p.id] = { ...p, boxes: p.boxes.length ? p.boxes : s.photos[replaces]?.boxes ?? [] };
      return { ...s, photos, order };
    }
    case "boxes": {
      const photos = { ...s.photos };
      for (const item of data.items as { id: string; boxes: Box[] }[]) {
        if (photos[item.id]) photos[item.id] = { ...photos[item.id], boxes: item.boxes };
      }
      return { ...s, photos };
    }
    case "rejected":
      return { ...s, rejected: [...s.rejected, ...data.items] };
    case "progress":
      return { ...s, counters: data };
    case "facts":
      return { ...s, facts: data.facts };
    case "description":
      return { ...s, description: data };
    case "notice":
      return { ...s, notices: [...s.notices, data.message] };
    case "error":
      return { ...s, error: data.message, fatal: Boolean(data.fatal) };
    case "done":
      return { ...s, phase: s.fatal ? "failed" : "done", totalMs: data.total_ms, calibrator: data.calibrator ?? null, model: data.model ?? "" };
    default:
      return s;
  }
}

const EVENTS = ["meta", "stage", "university", "campus", "source", "photos", "photo_update", "boxes", "rejected", "progress", "facts", "description", "notice", "error", "done"];

export function useProfileStream(qid: string, nonce: number, fresh: boolean) {
  const [state, dispatch] = useReducer(reducer, initial);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    dispatch({ type: "reset" });
    const url = `/api/profile/${encodeURIComponent(qid)}/stream${fresh ? "?fresh=1" : ""}`;
    const es = new EventSource(url);
    esRef.current = es;
    let finished = false;
    for (const name of EVENTS) {
      es.addEventListener(name, (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        dispatch({ type: "event", name, data });
        if (name === "done") {
          finished = true;
          es.close();
        }
      });
    }
    es.onerror = () => {
      if (finished) return;
      es.close();
      dispatch({ type: "connection_lost" });
    };
    return () => {
      finished = true;
      es.close();
    };
  }, [qid, nonce, fresh]);

  return state;
}
