# Function: getSourcePhoto

## Purpose
Get a real photo of the building to feed into image generation (step 05). Two paths: manual upload (mandatory, per spec) and an auto-fetch convenience from Mapillary (optional layer on top).

## Path A — manual upload (the real, required path)
No external service, no cost. Implementation requirement: the file input must accept **multiple** files (`<input type="file" multiple>`), not one. The spec's own line is "one or more photographs" — a single-file input technically falls short of it even if nobody ever uploads more than one.

## Path B — Mapillary auto-fetch (convenience layer, not the fallback of last resort — manual upload is)

### Service
Mapillary (Meta). Confirmed by Mapillary's own FAQ: "100% free to use — for any use case," for any developer, hobbyist, or company. There is no paid tier gating the imagery API itself.

### Cost / auth
Free. Requires a registered client access token (free signup at mapillary.com — this is registration, not billing) attached to every call as a query param or bearer header.

### Request contract
```
GET https://graph.mapillary.com/images
  ?access_token=<YOUR_CLIENT_TOKEN>
  &fields=id,thumb_2048_url,geometry,captured_at
  &bbox=<minLng>,<minLat>,<maxLng>,<maxLat>
```
Build the bbox as a small box (~30-50m) around the target lat/lng. `VERIFY BEFORE BUILDING`: confirm current field names against `https://www.mapillary.com/developer/api-documentation` at build time — Mapillary has changed field names across API versions before, and this is exactly the kind of detail worth pasting a real captured response into this file once you've made one live test call.

### Response contract (example shape, verify before relying on it)
```json
{
  "data": [
    { "id": "123", "thumb_2048_url": "https://...", "geometry": {"type":"Point","coordinates":[-80.41,37.23]}, "captured_at": 1690000000000 }
  ]
}
```
Empty `data` array = no imagery within that bbox. This is expected and common — coverage near VT/Blacksburg specifically is untested as of writing.

### Failure handling
Do not build any downstream logic that assumes Mapillary will return something. If `data` is empty, silently fall through to requiring manual upload — no error state needed, this is the normal case for most addresses.

## What NOT to build
No fallback-of-last-resort logic that tries to synthesize or stock-photo a building image. If neither path produces a photo, the user must upload one. That's the spec's actual requirement; Mapillary is a nice-to-have on top of it.

---

## VERIFIED CAPTURE — 2026-09-19 (live call, `graph.mapillary.com`)

Field names in the request contract above are **confirmed correct** as written.
`thumb_1024_url` also exists and is a useful fallback when `thumb_2048_url` is absent.
Token was sent as an `Authorization: OAuth <token>` header rather than a query param
(both work; the header keeps the token out of proxy and access logs).

### Request
```
GET https://graph.mapillary.com/images
  ?fields=id,thumb_2048_url,geometry,captured_at
  &bbox=-80.4238507,37.2280396,-80.4229493,37.2287604
  &limit=2
Authorization: OAuth <token>
```
(bbox = ~40m box around Burruss Hall, 37.2284 / -80.4234)

### Response — HTTP 200
```json
{
  "data": [
    {
      "id": "1137417950117930",
      "thumb_2048_url": "https://scontent-iad6-1.xx.fbcdn.net/m1/v/t6/An-tFiYAw9w8Rjqw...?<signed params, ~600 chars, expiring>",
      "geometry": { "type": "Point", "coordinates": [-80.423436899972, 37.2280748] },
      "captured_at": 1631875240000
    }
  ]
}
```

Notes confirmed against this capture:
- `geometry.coordinates` is GeoJSON order — **[lng, lat]**, not [lat, lng]. Easy to get backwards.
- `captured_at` is **epoch milliseconds** (1631875240000 → 2021-09-17), not seconds.
- `thumb_*_url` is a signed, expiring Facebook CDN URL. Do not persist it as a long-lived
  reference — download the bytes if the photo is going into a Supabase row (step 11).

## VERIFIED BEHAVIOUR — the index is non-deterministic (important)

Five consecutive **byte-identical** requests to a known-dense area (Times Square, r=40m)
returned **0, 2, 5, 6, 5** images. A `limit` sweep on the same bbox returned
0 / 1 / 1 / 4 / 0 results for limit = 1 / 2 / 5 / 10 / 50.

So `"data": []` on a single request is frequently a **false negative**, not evidence that
there is no coverage. The "empty = fall through to manual upload" rule in this file is still
the correct behaviour, but it should only be concluded after a retry.

Implemented policy (`backend/src/services/mapillary.ts`): try the spec'd ~40m radius, retry
it once, then make one wider ~100m pass; stop at the first non-empty result; de-duplicate by
id and rank by true haversine distance from the target so the nearest capture wins. Widening
is last and modest on purpose — imagery 100m away may be of a *different* building, and this
photo feeds image generation, so relevance beats hit rate.

## VERIFIED COVERAGE — Blacksburg / VT (this file previously said "untested")

Coverage exists and is usable:

| Location | Photos | Nearest | Captured |
|---|---|---|---|
| Burruss Hall (37.2284, -80.4234) | 7 | 23.1 m | 2024-10-11 |
| Squires Student Center (37.2293, -80.4180) | 1 | 37.4 m | 2018-08-07 |
| Torgersen Hall (37.2295, -80.4189) | 2 | 122.6 m (needed the wide pass) | 2021-09-17 |

Control: mid-Lake-Superior (47.7, -87.5) returns 0 after all three passes — genuine absence
reads differently from the flaky-index false negative.
