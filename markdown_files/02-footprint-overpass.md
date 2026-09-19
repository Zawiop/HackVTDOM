# Function: getBuildingFootprint

## Purpose
Given a coordinate, find the real building polygon at that location, compute its bounding box (width/depth in meters) and longest-edge bearing (initial rotation guess). Also returns neighboring footprints, reused later for collision detection (step 08) and World Propagate (step 10) — do not re-fetch for those, cache the result here.

## Service
Overpass API (OpenStreetMap). Free, public server, no key.

## Cost / auth
Free. No card, no key. The public instance is shared community infrastructure, not built for high-frequency interactive traffic — see caching note below.

## Request contract
POST to `https://overpass-api.de/api/interpreter` with body:
```
data=[out:json];way["building"](around:50,<lat>,<lng>);out geom;
```
Content-Type: `application/x-www-form-urlencoded`. `around:50` = 50 meter search radius from the point; widen if a demo address returns nothing.

## Response contract (example shape)
```json
{
  "elements": [
    {
      "type": "way",
      "id": 123,
      "geometry": [
        { "lat": 37.2296, "lon": -80.4139 },
        { "lat": 37.2297, "lon": -80.4138 }
      ],
      "tags": { "building": "yes" }
    }
  ]
}
```
Zero elements = no building found at that point. More than one element = ambiguous match.

## Derived values to compute
- Bounding box → `footprintWidthMeters`, `footprintDepthMeters` (convert lat/lng degree deltas to meters at that latitude — don't assume 1 degree = fixed meters, it varies with latitude).
- Longest edge → compass bearing → initial `rotationDegrees` guess (refined later in step 08's IoU search).
- Full polygon geometry, kept as-is, for the IoU calculation in step 08.

## Ambiguity handling (do not skip)
Zero candidates or multiple equally-close candidates → do **not** silently pick the nearest centroid. Set `confidence: "low"`, return every candidate polygon, and let step 09's correction UI show them as clickable outlines. Auto-picking wrong here is invisible until a judge is looking at a building growing out of the wrong footprint.

## Rate limit / reliability
The public Overpass instance rate-limits and occasionally 429s/406s under load, with no published hard number — treat it as "be polite, cache aggressively." Policy: back off 30 seconds on 429/406 before retrying. Keep a second mirror URL (e.g. `https://overpass.kumi.systems/api/interpreter`) ready to swap to if the primary is down.

## Caching (do this before demo day, not during)
Cache every successful response keyed by rounded lat/lng (a Supabase table or even an in-memory map is fine). Pre-run this step for your 2-3 demo buildings the night before judging so the live demo never depends on Overpass responding in real time.

## Note for the pitch
OSM/Overpass is community-sourced, not an official cadastral/GIS dataset — it is not literally "authoritative" in the strict sense. It's the correct practical choice for a hackathon timeline and budget; say so in one sentence in the pitch rather than letting a judge catch the gap unaddressed.
