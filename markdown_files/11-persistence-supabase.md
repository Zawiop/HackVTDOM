# Function: saveGeneration / getHistoryForAddress

## Purpose
Persist every generation as its own row, and let a single address accumulate multiple rows over time (different World States applied at different points), queryable as a sequence. Directly matches Procedura's own line about keeping "history and generated state durable and replayable."

## Service
Supabase (hosted Postgres). Free tier.

## Cost / auth
Free tier: Postgres database, storage for photos/images/meshes, and auth if needed, all within free-tier limits at hackathon scale. No card required to start a free project.

## Schema (one row per generation, not per address)
```
id, address, lat, lng, source_photo (url), artifact (redesigned image url),
placement (json: rotation, scale, position, confidence, scoredRotationCandidates),
mesh_url, world_state, confidence_state ('auto-high' | 'auto-low' | 'manually-verified'),
created_at
```
Field names are intentionally styled after Procedura/Scorched Nebraska's own vocabulary (`artifact`, `placement`, `source_photo`) rather than generic app terms — this is a small, free, deliberate choice that makes the record read as pipeline-native output rather than a generic CRUD row, worth keeping exactly as named here.

## The one behavior change from a naive implementation
Do not treat "one row per address" as an assumption anywhere in the code — no upsert-by-address, no unique constraint on address. A single address accumulates multiple rows over time, each a different World State. When a user clicks a building on the map, query:
```sql
SELECT * FROM generations WHERE address = ? ORDER BY created_at ASC
```
and render the results as a sequence — "Reality → Flooded → Reclaimed" — rather than just the latest row. This is the only schema-level requirement; everything else about the data model already supports it if the "one row per generation" rule above is followed from the start.

## Failure handling
Writes here are the one place a silent failure is unacceptable — if a Supabase write fails, surface it to the user/dev console immediately rather than letting a generation appear to succeed in the UI but never get persisted (which would quietly break both the history feature and World Propagate, since both read from this table).
