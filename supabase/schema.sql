-- Схема Supabase для Candid AI. Выполнить в SQL Editor проекта (Supabase -> SQL -> New query).
--
-- Хранилище нужно ради трёх вещей:
--   1) profile_cache - готовый профиль целиком, чтобы повтор открывался мгновенно даже после
--      перезапуска бесплатного инстанса Render;
--   2) kv_cache      - медленные внешние данные (границы кампусов Overpass, климат, маршруты);
--   3) feedback / queries - отметки пользователей для дообучения и журнал скорости.
--
-- Таблицы закрыты политиками RLS: сервис ходит сюда service_role-ключом с сервера,
-- в браузер ключ не попадает.

create table if not exists public.profile_cache (
  qid         text primary key,
  payload     jsonb       not null,
  built_ms    integer,
  model       text,
  updated_at  timestamptz not null default now()
);
create index if not exists profile_cache_updated_idx on public.profile_cache (updated_at desc);

create table if not exists public.kv_cache (
  ns          text        not null,
  key         text        not null,
  value       jsonb       not null,
  updated_at  timestamptz not null default now(),
  primary key (ns, key)
);

create table if not exists public.feedback (
  id          bigint generated always as identity primary key,
  ts          timestamptz not null default now(),
  qid         text        not null,
  photo_id    text        not null,
  kind        text        not null,
  category    text,
  features    jsonb,
  label       smallint
);
create index if not exists feedback_qid_idx on public.feedback (qid);

create table if not exists public.queries (
  id          bigint generated always as identity primary key,
  ts          timestamptz not null default now(),
  qid         text,
  ms          integer,
  ready_ms    integer,
  photos      integer,
  rejected    integer
);
create index if not exists queries_ts_idx on public.queries (ts desc);

alter table public.profile_cache enable row level security;
alter table public.kv_cache      enable row level security;
alter table public.feedback      enable row level security;
alter table public.queries       enable row level security;

-- Политик для anon и authenticated намеренно нет: с публичным ключом таблицы недоступны.
-- service_role обходит RLS, и только он используется на сервере.

-- Уборка: профили старше недели и журнал старше двух месяцев не нужны.
create or replace function public.candid_cleanup() returns void language sql as $$
  delete from public.profile_cache where updated_at < now() - interval '7 days';
  delete from public.kv_cache      where updated_at < now() - interval '30 days';
  delete from public.queries       where ts         < now() - interval '60 days';
$$;
