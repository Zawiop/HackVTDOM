# Function: geocodeAddress

## Purpose
Turn a user-typed address into a normalized address string plus lat/lng. Entry point for the whole pipeline. Skipped entirely when the user clicks the map directly (that path hands lat/lng straight to step 02).

## Service
Nominatim public API (OpenStreetMap Foundation). Free, no signup, no key.

## Cost / auth
Free. No credit card, no API key. Auth is just a required header (see below) — this is not optional, requests without it get silently dropped or blocked.

## Request contract
```
GET https://nominatim.openstreetmap.org/search
  ?q=<url-encoded address>
  &format=json
  &limit=1
  &addressdetails=1
```
Required header on every request:
```
User-Agent: ScorchedNebraskaVTHacks/1.0 (team@email.com)
```
Do not use a bare HTTP-library default user agent (e.g. `python-requests/2.x`, `axios/1.x`) — Nominatim's usage policy explicitly rejects generic library agents.

## Response contract (example shape)
```json
[
  {
    "place_id": 123456,
    "lat": "37.2296",
    "lon": "-80.4139",
    "display_name": "Virginia Tech, Blacksburg, Montgomery County, Virginia, USA",
    "address": { "road": "...", "city": "Blacksburg", "state": "Virginia", "postcode": "24061" },
    "boundingbox": ["37.22", "37.24", "-80.42", "-80.40"]
  }
]
```
`lat`/`lon` are strings — cast to float. Empty array `[]` means no match found; handle that as a user-facing "address not found" state, not a crash.

## Rate limit
Hard cap: 1 request/second for interactive use (4 requests/minute if you're doing anything that looks like batch geocoding). At hackathon scale — one user typing into one form — this is a non-issue. Don't fire a request on every keystroke; debounce.

## Fallback / degraded mode
If Nominatim returns empty or errors, let the user click directly on the MapLibre map instead — that path never touches this function.

## Attribution requirement
OSM's license (ODbL) requires attribution somewhere in the UI ("© OpenStreetMap contributors"). Cheap to add, easy to forget, worth doing before demo day.
