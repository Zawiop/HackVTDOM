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
