# Function: propagateWorldState

## Purpose
Extend one building's World State to nearby buildings without generating each one from scratch — turns "we redesigned one building" into "we redesigned a neighborhood." Directly implements Procedura's own description of Scorched Nebraska as a "persistent geospatial game world."

## Cost / auth
No new external calls for footprint data (reuses step 02/08 results already on hand). Generating each additional building's image and mesh still costs a call to steps 05 and 06 respectively — same free services, same rate-limit budget, just more of it.

## Contract
User picks a radius (50m / 100m / 250m). Filter the neighboring footprints already fetched in step 02 down to ones inside that radius. For each, apply the same World State description (step 04's output) already chosen for the source building, running that neighbor through steps 05-08 the same way the original building went through them.

## Demo-day handling — do not generate live during judging
Pre-run 2-3 neighboring buildings ahead of time and have them fully processed and cached in Supabase before judging starts. Clicking "Propagate" during the pitch should be an instant reveal of already-computed results, not a live wait on two async generation calls per neighbor (which, on the free TripoSR Space especially, is not something you want riding on a shared public queue in front of judges).

## Output
One additional row per propagated neighbor, same schema as the source building's row (see step 11), each flagged with whatever confidence state its own step 08 run produced.
