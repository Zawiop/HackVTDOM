"""Metric polygon frames, observable facade selection, and hard-edged extrusion."""
from dataclasses import dataclass
import math
import re

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, MultiPolygon, shape, LineString
from shapely.geometry.polygon import orient
from shapely.ops import transform
import trimesh


@dataclass
class Footprint:
    polygon: Polygon | MultiPolygon
    target: np.ndarray
    bearing: float
    center_en: np.ndarray
    to_wgs84: object
    warnings: list

    def position(self, offset_xz):
        b = math.radians(self.bearing)
        x, z = offset_xz
        en = self.center_en + [x * math.sin(b) + z * math.cos(b),
                               x * math.cos(b) - z * math.sin(b)]
        return list(self.to_wgs84(*en)) if self.to_wgs84 else None


def parts(poly):
    return list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]


def prepare_footprint(coordinates, crs="EPSG:4326", bearing=None, dimensions=None):
    """Coordinates are ALWAYS x,y (longitude,latitude for geographic CRS).

    Accept a ring, GeoJSON Polygon/MultiPolygon/Feature, or Shapely geometry.
    Dimensions are X,Z extents in the supplied bearing frame, not world AABB.
    """
    if isinstance(coordinates, dict):
        poly = shape(coordinates.get("geometry", coordinates))
    elif isinstance(coordinates, (Polygon, MultiPolygon)):
        poly = coordinates
    else:
        poly = Polygon(coordinates)
    if not isinstance(poly, (Polygon, MultiPolygon)) or poly.is_empty:
        raise ValueError("Expected a nonempty Polygon or MultiPolygon")
    if not poly.is_valid or not np.isfinite(poly.bounds).all():
        raise ValueError("Invalid/self-intersecting footprint; repair OSM rings explicitly")
    warnings = []
    if crs in ("meters", "local"):
        inverse = None
    else:
        source = CRS.from_user_input("EPSG:4326" if crs == "latlon" else crs)
        to_geo = Transformer.from_crs(source, 4326, always_xy=True).transform
        geo = transform(to_geo, poly)
        lon, lat = geo.centroid.coords[0]
        if not (-180 <= lon <= 180 and -89 < lat < 89) or geo.bounds[2]-geo.bounds[0] > 1:
            raise ValueError("Coordinates must describe one local building, in x,y order")
        local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
        poly = transform(Transformer.from_crs(source, local, always_xy=True).transform, poly)
        inverse = Transformer.from_crs(local, 4326, always_xy=True).transform
    if poly.area < 0.1 or max(np.subtract(poly.bounds[2:], poly.bounds[:2])) > 2000:
        raise ValueError("Footprint area/extent outside building-scale limits")
    if bearing is None:
        edges = []
        for part in parts(poly):
            edges.extend(np.diff(np.asarray(part.exterior.coords), axis=0))
        edge = max(edges, key=lambda e: np.linalg.norm(e))
        bearing = math.degrees(math.atan2(edge[0], edge[1])) % 180
    if not np.isfinite(bearing):
        raise ValueError("Bearing must be finite")
    b = math.radians(bearing)
    center = np.asarray(poly.centroid.coords[0])

    def to_frame(e, n, z=None):
        e, n = np.asarray(e)-center[0], np.asarray(n)-center[1]
        return e*math.sin(b)+n*math.cos(b), e*math.cos(b)-n*math.sin(b)

    poly = transform(to_frame, poly)
    lo, hi = np.asarray(poly.bounds).reshape(2, 2)
    shift = (lo+hi)/2
    center += [shift[0]*math.sin(b)+shift[1]*math.cos(b),
               shift[0]*math.cos(b)-shift[1]*math.sin(b)]
    poly = transform(lambda x, z: (np.asarray(x)-shift[0], np.asarray(z)-shift[1]), poly)
    target = hi-lo
    if dimensions is not None:
        dimensions = np.asarray(dimensions, float)
        if dimensions.shape != (2,) or not np.isfinite(dimensions).all() or (dimensions <= 0).any():
            raise ValueError("dimensions must be positive (width, depth) meters")
        scale = dimensions/target
        if max(abs(scale-1)) > .02:
            warnings.append(f"Known dimensions override polygon extents; X/Z scale {scale.tolist()}")
        poly = transform(lambda x, z: (np.asarray(x)*scale[0], np.asarray(z)*scale[1]), poly)
        target = dimensions
    # Normalize winding, preserve all courtyards and disconnected parts.
    normalized = [orient(p, sign=1) for p in parts(poly)]
    poly = normalized[0] if len(normalized) == 1 else MultiPolygon(normalized)
    return Footprint(poly, target, bearing % 360, center, inverse, warnings)


def select_facade(fp, edge_index=None, camera_bearing=None):
    """Stable indices refer to normalized exterior rings, flattened by polygon.

    camera_bearing is building-to-camera compass bearing, NOT camera heading.
    No metadata: choose longest exterior edge and flag the ambiguity.
    """
    edges = []
    for p in parts(fp.polygon):
        ring = np.asarray(p.exterior.coords)
        edges.extend((a, b) for a, b in zip(ring[:-1], ring[1:]))
    if edge_index is not None:
        if not isinstance(edge_index, int) or not 0 <= edge_index < len(edges):
            raise ValueError("facade_edge_index outside normalized exterior edge list")
        selected, source = edge_index, "explicit edge"
    elif camera_bearing is not None:
        if not np.isfinite(camera_bearing):
            raise ValueError("camera_bearing must be finite")
        angle = math.radians(camera_bearing-fp.bearing)
        toward_camera = np.array([math.cos(angle), math.sin(angle)])
        # EN to footprint frame: X=cos(delta), Z=sin(delta).
        scores = []
        for a, b in edges:
            d = b-a
            normal = np.array([d[1], -d[0]])/np.linalg.norm(d)
            facing = max(0., float(normal @ toward_camera))
            mid = (a+b)/2
            ray = LineString([mid+normal*.002, mid+toward_camera*5000])
            visible = not fp.polygon.intersects(ray)
            scores.append(np.linalg.norm(d)*facing**2 if visible else 0.)
        if max(scores) <= 0:
            raise ValueError("No visible exterior edge for camera bearing")
        selected, source = int(np.argmax(scores)), "camera bearing and visibility"
    else:
        selected = int(np.argmax([np.linalg.norm(b-a) for a, b in edges]))
        source = "longest edge heuristic"
        fp.warnings.append("Photo-to-edge association is ambiguous; longest edge selected. Supply camera_bearing or facade_edge_index.")
    a, b = edges[selected]
    d = b-a
    normal = np.array([d[1], -d[0]])/np.linalg.norm(d)
    angle = math.atan2(normal[0], normal[1])
    return selected, edges, angle, source


def estimate_height(tags=None, height_m=None, default_levels=3, level_height=3.2):
    """Explicit meters > OSM height (m/ft) > OSM levels > 3-level fallback.

    Trusted heights accepted up to 500m; malformed tags fall through with warning.
    No image aspect-ratio estimate: perspective and towers make it unreliable.
    """
    tags, warnings = tags or {}, []
    if not np.isfinite([default_levels, level_height]).all() or default_levels <= 0 or level_height <= 0:
        raise ValueError("Level count and storey height must be finite and positive")
    if height_m is not None:
        h = float(height_m)
        if not math.isfinite(h) or not .5 <= h <= 500:
            raise ValueError("Explicit height must be 0.5–500 meters")
        return h, "explicit height_m", warnings
    raw = str(tags.get("height", "")).strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|meters|metres|ft|feet|')?", raw)
    if match:
        h = float(match[1]) * (.3048 if match[2] in ("ft", "feet", "'") else 1)
        if .5 <= h <= 500:
            return h, "OSM height", warnings
    if raw:
        warnings.append(f"Unusable OSM height {raw!r}; using levels/fallback")
    try:
        levels = float(tags.get("building:levels", default_levels))
        if not math.isfinite(levels) or not 1 <= levels <= 100:
            raise ValueError()
        source = "OSM building:levels" if "building:levels" in tags else "default levels (uncertain)"
    except (ValueError, TypeError):
        levels, source = default_levels, "default levels (invalid OSM levels)"
        warnings.append("Unusable building:levels")
    h = float(np.clip(levels*level_height, 3.2, 120))
    if "default" in source:
        warnings.append("Height is an estimate, not a measurement")
    return h, source, warnings


def extrude(fp, height, facade_index, angle, regions, floor=False):
    """Hard split vertices at walls/roof. No smoothing, apron or internal floors."""
    vertices, faces, uv = [], [], []

    def add(points, triangles, coords, region):
        offset = len(vertices)
        vertices.extend(np.asarray(points).copy().tolist())
        faces.extend(np.asarray(triangles)+offset)
        u0, v0, u1, v1 = regions[region]
        uv.extend([[u0+u*(u1-u0), v0+v*(v1-v0)] for u, v in coords])

    exterior_id = 0
    facade_length = None
    for p in parts(fp.polygon):
        for ring_index, ring in enumerate([p.exterior, *p.interiors]):
            points = np.asarray(ring.coords)
            for a, b in zip(points[:-1], points[1:]):
                length = np.linalg.norm(b-a)
                is_front = ring_index == 0 and exterior_id == facade_index
                if ring_index == 0:
                    exterior_id += 1
                if is_front:
                    facade_length = float(length)
                # Side tiles represent ~8 meters; subdivide UV islands to avoid
                # stretch/repeat across atlas regions. Front has only one quad.
                nx = 1 if is_front else max(1, math.ceil(length/8))
                ny = 1 if is_front else max(1, math.ceil(height/8))
                if len(faces)+2*nx*ny > 29500:
                    raise ValueError("Footprint exceeds triangle budget; split into separate assets")
                for i in range(nx):
                    for j in range(ny):
                        c, d = a+(b-a)*i/nx, a+(b-a)*(i+1)/nx
                        y0, y1 = height*j/ny, height*(j+1)/ny
                        add([[c[0], y0, c[1]], [c[0], y1, c[1]],
                             [d[0], y1, d[1]], [d[0], y0, d[1]]],
                            [[0, 1, 2], [0, 2, 3]],
                            # ring direction is right-to-left when viewed outside
                            [[1, 0], [1, 1], [0, 1], [0, 0]],
                            "facade" if is_front else "wall")
        xy, tri = trimesh.creation.triangulate_polygon(p, engine="earcut")
        triangle_area = sum(Polygon(xy[t]).area for t in tri)
        if not math.isclose(triangle_area, p.area, rel_tol=1e-7):
            raise ValueError("Roof triangulation does not cover the footprint")
        low, high = np.asarray(fp.polygon.bounds).reshape(2, 2)
        coords = (xy-low)/(high-low)
        roof = np.column_stack([xy[:, 0], np.full(len(xy), height), xy[:, 1]])
        # Earcut winding is verified explicitly in 3D (roof +Y).
        tri = np.asarray(tri).copy()
        normals = np.cross(roof[tri[:, 1]]-roof[tri[:, 0]], roof[tri[:, 2]]-roof[tri[:, 0]])
        flip = normals[:, 1] < 0
        tri[flip] = tri[flip][:, ::-1]
        add(roof, tri, coords, "roof")
        if floor:
            roof[:, 1] = 0
            add(roof, tri[:, ::-1], coords, "roof")
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv))
    mesh.remove_unreferenced_vertices()
    mesh = conform_edges(mesh)
    rotation = trimesh.transformations.rotation_matrix(-angle, [0, 1, 0])
    mesh.apply_transform(rotation)
    center = mesh.bounds.mean(axis=0)*[1, 0, 1]
    mesh.apply_translation(-center)
    # The returned map anchor accounts for re-centering after facade rotation.
    center_original = (np.linalg.inv(rotation) @ np.r_[center, 1])[[0, 2]]
    return mesh, rotation, center, center_original, facade_length


def conform_edges(mesh):
    """Split T junctions without moving the surface or blending architectural normals.

    UV tiles and roof triangulation have different edge subdivisions. Insert the
    missing edge points with interpolated UVs; fan only affected triangles to an
    interior centroid. This makes the capped solid topologically closed as well
    as visually covered. Seams stay split in the render mesh.
    """
    from scipy.spatial import cKDTree
    unique = np.unique(np.asarray(mesh.vertices), axis=0)
    tree = cKDTree(unique)
    vertices, faces, coords = [], [], []
    for face in mesh.faces:
        points = np.asarray(mesh.vertices)[face]
        uvs = np.asarray(mesh.visual.uv)[face]
        boundary, boundary_uv = [], []
        for i in range(3):
            a, b = points[i], points[(i+1) % 3]
            delta = b-a
            length = np.linalg.norm(delta)
            candidates = unique[tree.query_ball_point((a+b)/2, length/2+1e-7)]
            t = (candidates-a) @ delta/(length*length)
            distance = np.linalg.norm(candidates-(a+t[:, None]*delta), axis=1)
            keep = (t > 1e-7) & (t < 1-1e-7) & (distance < 1e-7)
            steps = np.r_[0., np.sort(t[keep])]
            for step in steps:
                boundary.append(a+step*delta)
                boundary_uv.append(uvs[i]+step*(uvs[(i+1) % 3]-uvs[i]))
        offset = len(vertices)
        vertices.extend(boundary)
        coords.extend(boundary_uv)
        if len(boundary) == 3:
            faces.append([offset, offset+1, offset+2])
        else:
            middle = len(vertices)
            vertices.append(points.mean(axis=0))
            coords.append(uvs.mean(axis=0))
            faces.extend([middle, offset+i, offset+(i+1) % len(boundary)] for i in range(len(boundary)))
        if len(faces) > 30000:
            raise ValueError("Closing UV/roof seams exceeds 30000 triangles")
    result = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    result.visual = trimesh.visual.TextureVisuals(uv=np.asarray(coords), material=mesh.visual.material)
    return result
