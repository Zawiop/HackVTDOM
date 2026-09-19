"""Live contract check for steps 01 and 02 against the real Nominatim/Overpass APIs.

Asserts the response *shape* the spec files promise, not just HTTP 200.

    cd backend && .venv/bin/python tests/verify_live.py

Needs the API running (uvicorn app.main:app). Overpass is a shared public
instance, so a FAIL here may be their load rather than our bug — the failure
line says which endpoint answered.
"""

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ADDRESS = "Torgersen Hall, Blacksburg, VA"
OPEN_FIELD = (37.2278, -80.4225)  # middle of the Drillfield — no building

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return bool(condition)


def main():
    client = httpx.Client(base_url=BASE, timeout=180.0)

    # --- health ---
    r = client.get("/api/health")
    check("health returns 200", r.status_code == 200, f"HTTP {r.status_code}")
    check("health reports ok", r.json().get("status") == "ok")

    # --- 01 geocode: real address ---
    r = client.get("/api/geocode", params={"q": ADDRESS})
    check("geocode returns 200", r.status_code == 200, f"HTTP {r.status_code}")
    geo = r.json()
    check("geocode found the address", geo.get("found") is True)
    check("lat is a float, not a string", isinstance(geo.get("lat"), float), repr(geo.get("lat")))
    check("lng is a float, not a string", isinstance(geo.get("lng"), float), repr(geo.get("lng")))
    check(
        "coordinates land in Blacksburg",
        37.1 < (geo.get("lat") or 0) < 37.3 and -80.6 < (geo.get("lng") or 0) < -80.3,
        f"{geo.get('lat')}, {geo.get('lng')}",
    )
    check("display_name came back", isinstance(geo.get("address"), str) and geo["address"])
    check("addressDetails present (addressdetails=1)", isinstance(geo.get("addressDetails"), dict))
    check(
        "boundingBox is 4 floats",
        isinstance(geo.get("boundingBox"), list)
        and len(geo["boundingBox"]) == 4
        and all(isinstance(v, float) for v in geo["boundingBox"]),
    )
    check("OSM attribution present (ODbL)", "OpenStreetMap" in geo.get("attribution", ""))

    # --- 01 geocode: no match is a state, not a crash ---
    r = client.get("/api/geocode", params={"q": "zzzqqq not a real place 99999"})
    check("unmatched address still returns 200", r.status_code == 200, f"HTTP {r.status_code}")
    check("unmatched address reports found=false", r.json().get("found") is False)

    # --- 02 footprint: the geocoded building ---
    r = client.post("/api/footprint", json={"lat": geo["lat"], "lng": geo["lng"]})
    if not check("footprint returns 200", r.status_code == 200, r.text[:160]):
        return summarize()
    fp = r.json()

    check("confidence is a known state", fp["confidence"] in ("auto-high", "auto-low"), fp["confidence"])
    check("reason explains the decision", isinstance(fp.get("reason"), str) and fp["reason"])
    check("neighbors returned for steps 08/10", len(fp["neighbors"]) > 0, f"{len(fp['neighbors'])} neighbors")
    check("query point echoed as [lng, lat]", fp["queryPoint"] == [geo["lng"], geo["lat"]])
    check("source names the endpoint used", fp["source"].startswith("http"), fp["source"])

    selected = fp.get("selected")
    if check("a footprint was selected", selected is not None, fp["reason"]):
        check(
            "selected building is the one we asked for",
            "Torgersen" in (selected["tags"].get("name") or ""),
            selected["tags"].get("name"),
        )
        check("query point is inside it", selected["distanceMeters"] == 0.0, f"{selected['distanceMeters']}m")
        check(
            "width/depth are plausible metres",
            5.0 < selected["footprintWidthMeters"] < 400.0
            and 5.0 < selected["footprintDepthMeters"] < 400.0,
            f"{selected['footprintWidthMeters']} x {selected['footprintDepthMeters']} m",
        )
        check(
            "rotation is a 0-180 bearing",
            0.0 <= selected["rotationDegrees"] < 180.0,
            f"{selected['rotationDegrees']} deg",
        )
        check(
            "geometry is a closed-able ring of [lng, lat] pairs",
            len(selected["geometry"]) >= 3
            and all(len(p) == 2 for p in selected["geometry"])
            and all(-180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in selected["geometry"]),
            f"{len(selected['geometry'])} points",
        )
        check(
            "centroid falls inside the polygon's bounds",
            selected["boundingBox"]["minLng"] <= selected["centroid"][0] <= selected["boundingBox"]["maxLng"]
            and selected["boundingBox"]["minLat"] <= selected["centroid"][1] <= selected["boundingBox"]["maxLat"],
        )

    # --- 02 footprint: caching ---
    r = client.post("/api/footprint", json={"lat": geo["lat"], "lng": geo["lng"]})
    check("repeat call is served from cache", r.json().get("cached") is True)

    # --- 02 footprint: nothing there ---
    r = client.post("/api/footprint", json={"lat": OPEN_FIELD[0], "lng": OPEN_FIELD[1]})
    if check("open-field lookup returns 200", r.status_code == 200, r.text[:160]):
        empty = r.json()
        check("no building is auto-low, not an error", empty["confidence"] == "auto-low")
        check("nothing auto-picked when nothing matched", empty["selected"] is None)
        check("neighbors still returned for propagate", len(empty["neighbors"]) > 0)

    # --- 02 footprint: input validation ---
    r = client.post("/api/footprint", json={"lat": 999, "lng": 0})
    check("out-of-range latitude is rejected", r.status_code == 422, f"HTTP {r.status_code}")

    return summarize()


def summarize():
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
