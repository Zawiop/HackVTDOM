"""Render placed mesh outlines over their real OSM footprints, one SVG each.

A numeric IoU can be right while something is visibly wrong, so this is the
eyeball check -- and it doubles as the debug view step 09 wants.

Outlines are re-derived from the *returned transform record*, not from the
placement module's internal working, so if the record is wrong the picture is
wrong. That is the point.

    .venv/bin/python scripts/placement_preview.py [out.html]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services import placement_geom as g  # noqa: E402
from app.services.geo_math import meters_per_degree, polygon_centroid  # noqa: E402
from app.services.placement import compute_placement_transform, _resolve_mesh  # noqa: E402

sys.path.insert(0, str(BACKEND / "tests"))
from tests.helpers import all_buildings, centred_ring, extrude_to_glb, neighbors_of  # noqa: E402

PRE_ROTATIONS = (0, 37, 145, 213)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND / "placement-preview.html"
TMP = BACKEND / "outputs" / "_preview"


def svg_path(ring):
    return " ".join(f"{x:.2f},{-y:.2f}" for x, y in ring)


def card(building, pre_rotate: int) -> str:
    TMP.mkdir(parents=True, exist_ok=True)
    mesh_path = extrude_to_glb(
        centred_ring(building), TMP / "m.glb", height_meters=20, pre_rotate_degrees=pre_rotate
    )
    neighbours = neighbors_of(building)

    t = compute_placement_transform(
        {"polygon": building, "neighbors": neighbours},
        {"path": mesh_path, "upAxis": "y"},
    )

    pts = [(p[0], p[1]) for p in building["geometry"]]
    alng, alat = polygon_centroid(pts)
    per_lng, per_lat = meters_per_degree(alat)
    to_local = lambda ll: [((p[0] - alng) * per_lng, (p[1] - alat) * per_lat) for p in ll]

    footprint = g.open_ring(to_local(pts))
    outline = _resolve_mesh({"path": mesh_path, "upAxis": "y"})["outline"]

    # Rebuild the placement from the record alone: scale in model space, rotate,
    # then translate the origin to the returned lat/lng.
    sx, _, sz = t["scaleXYZ"]
    origin = ((t["position"][1] - alng) * per_lng, (t["position"][0] - alat) * per_lat)
    placed = g.translate_ring(
        g.rotate_ring(g.scale_ring(outline, (sx, sz)), t["diagnostics"]["headingDegrees"]),
        origin,
    )

    nbr_rings = [g.open_ring(to_local([(p[0], p[1]) for p in n["geometry"]])) for n in neighbours]

    box = g.bounds(list(footprint) + list(placed))
    pad = max(box["width"], box["depth"]) * 0.25
    view = (
        f'{box["minX"] - pad:.1f} {-box["maxY"] - pad:.1f} '
        f'{box["width"] + 2 * pad:.1f} {box["depth"] + 2 * pad:.1f}'
    )

    d = t["diagnostics"]
    flags = "".join(
        f'<li class="{f["severity"]}">{f["subStep"]}: {f["code"]}</li>' for f in t["flags"]
    )
    rows = [
        ("mesh pre-rotated", f"{pre_rotate}&deg;"),
        ("recovered yaw", f'{t["rotationDegrees"]:.1f}&deg;'),
        ("scale", f'{t["scale"]:.3f} ({t["scaleMode"]})'),
        ("ground z", f'{t["position"][2]:.3f} m'),
        ("IoU / ceiling", f'{d["iou"]:.3f} / {d["maxAchievableIou"]:.3f}'),
        ("fit quality", f'{d["fitQuality"] * 100:.1f}%'),
        (
            "neighbours",
            f'{t["collision"]["neighborsChecked"]} checked, '
            f'worst {t["collision"]["worstOverlapRatio"] * 100:.1f}%',
        ),
    ]

    return f"""
  <figure>
    <svg viewBox="{view}" preserveAspectRatio="xMidYMid meet">
      {''.join(f'<polygon class="nbr" points="{svg_path(n)}"/>' for n in nbr_rings if len(n) >= 3)}
      <polygon class="fp" points="{svg_path(footprint)}"/>
      <polygon class="mesh" points="{svg_path(placed)}"/>
      <circle class="org" cx="{origin[0]:.2f}" cy="{-origin[1]:.2f}" r="1.2"/>
    </svg>
    <figcaption>
      <strong>{building['tags'].get('name', building['osmId'])}</strong>
      <span class="{'ok' if t['confidence'] == 'auto-high' else 'warn'}">{t['confidence']}</span>
      <dl>{''.join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in rows)}</dl>
      {f'<ul class="flags">{flags}</ul>' if flags else ''}
    </figcaption>
  </figure>"""


def main() -> None:
    cards = [
        card(b, PRE_ROTATIONS[i % len(PRE_ROTATIONS)])
        for i, b in enumerate(all_buildings()[:12])
    ]

    OUT.write_text(f"""<!doctype html><meta charset="utf-8"><title>Placement preview</title>
<style>
:root{{color-scheme:dark;--bg:#0f1210;--panel:#171c19;--ink:#dfe6e0;--dim:#93a096;
--accent:#6ee7a0;--warn:#e6a028;--line:#2b332d}}
body{{margin:0;padding:20px;background:var(--bg);color:var(--ink);
font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}
h1{{font-size:15px;margin:0 0 4px;letter-spacing:.04em}}
p.lede{{color:var(--dim);margin:0 0 14px;max-width:70ch;font-size:11px}}
.key{{color:var(--dim);font-size:11px;margin-bottom:16px}}
.key .m{{color:var(--warn)}}.key .f{{color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:12px}}
figure{{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px}}
svg{{width:100%;height:13rem;background:#0c0f0d;border-radius:4px}}
.nbr{{fill:#1d241f;stroke:#2b332d;stroke-width:.4}}
.fp{{fill:rgba(110,231,160,.18);stroke:var(--accent);stroke-width:.7}}
.mesh{{fill:rgba(230,160,40,.16);stroke:var(--warn);stroke-width:.7;stroke-dasharray:2 1.5}}
.org{{fill:var(--warn)}}
figcaption strong{{display:inline-block;margin:8px 8px 0 0;font-size:12px}}
.ok{{color:var(--accent);font-size:10px}}.warn{{color:var(--warn);font-size:10px}}
dl{{margin:6px 0 0;font-size:10px;color:var(--dim)}}
dl div{{display:flex;justify-content:space-between;gap:10px;
border-bottom:1px dotted var(--line);padding:1px 0}}
dt,dd{{margin:0}}dd{{color:var(--ink)}}
.flags{{margin:6px 0 0;padding-left:14px;font-size:10px}}
.flags .low{{color:var(--warn)}}.flags .info{{color:var(--dim)}}
</style>
<h1>Placement preview &mdash; real OSM footprints, meshes pre-rotated by a known angle</h1>
<p class="lede">Each mesh was extruded from its building's own footprint and then turned by the
angle shown, so a correct placement puts the dashed outline back exactly on the solid one.
Outlines are re-derived from the returned transform record, not from the internal working.</p>
<p class="key"><b class="f">&#9646; solid green</b> = real OSM footprint &nbsp;
<b class="m">&#9647; dashed amber</b> = placed mesh base outline &nbsp;
<b>&#9679;</b> = model origin (the returned lat/lng) &nbsp; grey = neighbouring buildings</p>
<div class="grid">{''.join(cards)}</div>""")

    print(f"wrote {OUT} ({len(cards)} buildings)")


if __name__ == "__main__":
    main()
