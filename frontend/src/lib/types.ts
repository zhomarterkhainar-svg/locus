export type Candidate = {
  qid: string;
  label: string;
  description: string;
  country: string | null;
  city: string | null;
  image: string | null;
  website: string | null;
  lat: number | null;
  lon: number | null;
  score: number;
};

export type SearchResult = {
  query: string;
  status: "ok" | "ambiguous" | "not_found" | "too_short" | "error";
  candidates: Candidate[];
  suggestion: string | null;
  message?: string;
};

export type Place = { qid: string; label: string; lat: number | null; lon: number | null };

export type University = {
  qid: string;
  label: string;
  labels: Record<string, string>;
  description: string;
  country: Place | null;
  city: Place | null;
  lat: number | null;
  lon: number | null;
  website: string | null;
  inception: number | null;
  students: number | null;
  wikidata_url: string;
  city_distance_m?: number;
};

export type SignalView = {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  detail: string;
};

export type Box = { label: string; conf: number; x: number; y: number; w: number; h: number; bunk?: number };

export type PhotoView = {
  id: string;
  shelfmark: string;
  source: string;
  origin: string;
  host: string;
  page_url: string;
  image_url: string;
  title: string;
  description: string;
  author: string;
  author_url: string;
  license: string;
  license_url: string;
  published: string | null;
  taken: string | null;
  retrieved: string;
  lat: number | null;
  lon: number | null;
  width: number;
  height: number;
  scope: string;
  category: string;
  category_label: string;
  category_scores: { key: string; p: number }[];
  confidence: number;
  level: "high" | "medium" | "low";
  signals: SignalView[];
  cluster: string;
  nearest: { name: string; kind: string; kind_label: string; distance_m: number; url: string } | null;
  distance_m: number | null;
  duplicates: { id: string; source: string; host: string; page_url: string; detail: string }[];
  boxes: Box[];
};

export type RejectedView = {
  id: string;
  source: string;
  host: string;
  page_url: string;
  image_url: string;
  title: string;
  reason: string;
  detail: string;
  duplicate_of: string | null;
};

export type OsmObjectView = {
  osm: string;
  kind: string;
  kind_label: string;
  sport: string | null;
  name: string;
  lat: number;
  lon: number;
  url: string;
};

export type CampusView = {
  rings: [number, number][][];
  center: [number, number] | null;
  radius_m: number;
  matched_by: string;
  from_cache?: boolean;
  late?: boolean;
  objects: OsmObjectView[];
  amenities?: OsmObjectView[];
  university: { lat: number | null; lon: number | null } | null;
  city: Place | null;
};

export type SourceStatus = {
  key: string;
  label: string;
  status: "running" | "ok" | "empty" | "error" | "skipped";
  count?: number;
  ms?: number;
  message?: string;
};

export type FactView = {
  id: string;
  group: "dormitory" | "sport";
  label: string;
  value: string;
  status: "confirmed" | "weak" | "insufficient" | "not_found";
  note: string;
  evidence: { photo_id: string; shelfmark: string; boxes: Box[] }[];
  osm: OsmObjectView[];
};

export type DescriptionView = {
  mode: "gemini" | "extractive" | "none";
  model?: string;
  sentences: { text: string; sources: string[] }[];
  sources: { id: string; title: string; url: string; kind: string }[];
  message?: string;
};

export type Counters = {
  found: number;
  downloaded: number;
  analyzed: number;
  in_profile: number;
  unconfirmed: number;
  rejected: number;
  duplicates: number;
};

export type StageKey = "resolve" | "sources" | "analyze" | "facts" | "describe";
export type StageStatus = "idle" | "running" | "done" | "error";

export type ClimateMonth = {
  month: number;
  label: string;
  t_mean: number;
  t_min: number | null;
  t_max: number | null;
  precip_mm: number | null;
  snow_days: number | null;
};

export type RouteView = {
  key: string;
  mode: "foot" | "car";
  label: string;
  from: { name: string; lat: number; lon: number; osm_url?: string };
  to: { name: string; lat: number; lon: number };
  distance_m: number;
  duration_s: number;
  straight_m: number;
  line: [number, number][];
  source_url: string;
};

export type ContextView = {
  climate: {
    months: ClimateMonth[];
    years: string;
    coldest: ClimateMonth;
    warmest: ClimateMonth;
    source: string;
    url: string;
    from_cache: boolean;
  } | null;
  climate_error?: string;
  routes: RouteView[];
  amenities: { radius_m: number; counts: Record<"transport" | "shop" | "pharmacy", number>; nearest_m: Record<string, number>; note?: string } | null;
  winter_walk?: { minutes: number; month: string; t_mean: number };
  cost?: { status: string; note: string };
  main_point?: { lat: number; lon: number };
  error?: string;
};

export type FindResult = {
  query: string;
  english: string | null;
  via?: string;
  results: { id: string; score: number }[];
  message?: string;
  error?: string;
};
