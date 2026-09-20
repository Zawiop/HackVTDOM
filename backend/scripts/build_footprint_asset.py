"""Bridge the existing /footprint response to the deterministic asset builder.

Run from backend: python scripts/build_footprint_asset.py --help
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.generation.footprint_asset import build_asset, restyle_existing_asset


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-mesh", help="Restyle existing geometry; footprint fitting preserves facade height/width")
    p.add_argument("--image")
    p.add_argument("--footprint", help="Existing footprint response JSON (selected) or selected object")
    p.add_argument("--output", required=True)
    p.add_argument("--state", default="scorched", choices=["reclaimed", "flooded", "scorched", "buried", "petrified"])
    p.add_argument("--camera-bearing", type=float, help="Building-to-camera compass bearing")
    p.add_argument("--corners", help='EXIF-oriented pixel coordinates: [[TLx,TLy],[TRx,TRy],[BRx,BRy],[BLx,BLy]]')
    p.add_argument("--edge", type=int, help="Normalized exterior edge index; see report")
    p.add_argument("--height", type=float, help="Explicit total height in meters; omitted in source mode to preserve facade proportions")
    p.add_argument("--allow-height-distortion", action="store_true",
                   help="Allow an explicit --height to change facade proportions by more than 20%%")
    p.add_argument("--texture-size", type=int, default=2048, choices=[512, 1024, 2048])
    a = p.parse_args()
    if a.source_mesh:
        if a.state != "scorched":
            p.error("Source-preserving surface weathering currently supports scorched")
        dimensions, metadata_height = None, None
        if a.footprint:
            from app.generation.footprint_asset.geometry import estimate_height
            data = json.loads(Path(a.footprint).read_text())
            f = data.get("selected", data)
            if not f:
                p.error("Footprint response has no selected building")
            dimensions = [f["footprintWidthMeters"], f["footprintDepthMeters"]]
            tags = f.get("tags") or {}
            # These tags do not establish a trustworthy height for every part
            # of a reconstructed tower/wing mesh. Keep the conflict visible.
            if "height" in tags or "building:levels" in tags:
                estimated, source, _ = estimate_height(tags)
                if source.startswith("OSM"):
                    metadata_height = estimated
        restyle_existing_asset(a.source_mesh, a.output, dimensions_m=dimensions, height_m=a.height,
                               metadata_height_m=metadata_height,
                               allow_height_distortion=a.allow_height_distortion)
        return
    if not a.image or not a.footprint:
        p.error("Supply --source-mesh, or both --image and --footprint for approximate massing")
    data = json.loads(Path(a.footprint).read_text())
    f = data.get("selected", data)
    if not f:
        p.error("Footprint response has no selected building")
    dimensions = None
    if f.get("footprintWidthMeters") and f.get("footprintDepthMeters"):
        dimensions = [f["footprintWidthMeters"], f["footprintDepthMeters"]]
    build_asset(a.image, f["geometry"], "EPSG:4326", f.get("rotationDegrees"), a.output,
                footprint_dimensions=dimensions, osm_tags=f.get("tags"), height_m=a.height,
                world_state=a.state, camera_bearing=a.camera_bearing,
                facade_edge_index=a.edge, facade_corners=json.loads(a.corners) if a.corners else None,
                texture_size=a.texture_size)


if __name__ == "__main__":
    main()
