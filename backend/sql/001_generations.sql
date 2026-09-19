-- Scorched Nebraska — step 11 persistence schema (Supabase / Postgres)
--
-- Run this once in the Supabase SQL editor (DDL cannot be issued over PostgREST).
--
-- DESIGN RULE (from markdown_files/11-persistence-supabase.md):
--   One row per GENERATION, never one row per address. A single address
--   accumulates many rows over time, one per World State applied to it.
--   There is deliberately NO unique constraint on `address` and no upsert path.

create extension if not exists "pgcrypto";

create table if not exists public.generations (
  id               uuid primary key default gen_random_uuid(),
  address          text not null,
  lat              double precision not null,
  lng              double precision not null,
  source_photo     text,
  artifact         text,
  placement        jsonb not null default '{}'::jsonb,
  mesh_url         text,
  world_state      text,
  confidence_state text not null default 'auto-low'
    check (confidence_state in ('auto-high', 'auto-low', 'manually-verified')),
  propagated_from  uuid references public.generations(id) on delete set null,
  created_at       timestamptz not null default now()
);

-- History query is `where address = ? order by created_at asc` (step 11).
-- NOT unique: the whole point is that one address holds a sequence.
create index if not exists generations_address_created_idx
  on public.generations (address, created_at asc);

-- Propagate (step 10) filters neighbours by coordinate.
create index if not exists generations_lat_lng_idx
  on public.generations (lat, lng);

-- Step 12 renders low-confidence rows with a warning ring; it queries by state.
create index if not exists generations_confidence_idx
  on public.generations (confidence_state);

alter table public.generations enable row level security;

-- The map frontend reads with the publishable (anon) key.
drop policy if exists generations_public_read on public.generations;
create policy generations_public_read
  on public.generations for select
  to anon, authenticated
  using (true);

-- Writes go through the backend, which uses the secret key and bypasses RLS.
-- No anon insert/update policy is created on purpose.
