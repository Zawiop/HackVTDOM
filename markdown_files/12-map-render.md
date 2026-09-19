# Function: renderScene (MapLibre + deck.gl)

## Purpose
Render every saved generation (step 11) as a real 3D model at its real coordinate on a real map, plus the panel that opens on click.

## Services
MapLibre GL JS (base map) + deck.gl (`ScenegraphLayer`, 3D model rendering). Both open source libraries — no API cost.

## Base map tiles
Use free keyless OSM raster tiles only. Do not reach for a MapTiler API key — it has its own free-tier ceiling that adds a dependency and a possible future cost for no real benefit over the free OSM option at hackathon scale.

## deck.gl ScenegraphLayer contract
```js
new ScenegraphLayer({
  data: generations, // rows from step 11
  getPosition: d => [d.lng, d.lat, 0],
  getOrientation: d => [0, d.placement.rotationDegrees, 90], // [pitch, yaw, roll] in degrees
  getScale: d => [d.placement.scale, d.placement.scale, d.placement.scale],
  scenegraph: d => d.mesh_url, // deck.gl's built-in glTF loader handles the fetch
})
```
`VERIFY BEFORE BUILDING`: the `[pitch, yaw, roll]` axis order and the `90` roll constant are dependent on the up-axis convention your normalized meshes ended up in after step 07 — if step 06's TripoSR output needed axis correction, this constant may need to change. Confirm by rendering one known mesh and checking it stands upright and facing a sensible direction before wiring up the full data-driven layer.

## VERIFIED 2026-09-19 (deck.gl 9.4.0, maplibre-gl 5.24.0) — two corrections

**1. `roll: 90` is correct, and it is load-bearing.** Confirmed visually against a
purpose-built asymmetric mesh (`frontend/public/placeholder.glb`: 10m x 6m
footprint, pitched roof, a marker block on its front face, base-centred pivot,
Y-up). At `roll: 90` buildings stand upright; at `roll: 0` they lie flat on the
ground. Step 07 must keep emitting Y-up glTF for this constant to hold — the
axis-check slider in the app's left panel flips it live if that ever changes.

**2. `scenegraph: d => d.mesh_url` does NOT work.** In deck.gl 9 the `scenegraph`
prop is typed `any` (a URL / parsed glTF / Promise) — it is *not* an
`Accessor<DataT, ...>` the way `getOrientation`, `getScale` and `getTranslation`
are. Passing a function makes the layer attempt to load the function itself as a
model. Since every building has its own mesh, rows must be **grouped by
`mesh_url`, one ScenegraphLayer per distinct mesh**. See
`frontend/src/map/layers.js` (`groupByMesh`, `buildScenegraphLayers`).

Also worth knowing: a glTF without a `NORMAL` attribute makes luma.gl warn and
fall back to geometric normals, which flattens the shading so the roof pitch is
invisible. Whatever step 07 exports should carry normals.

## Low-confidence visual treatment
Rows with `confidence_state` of `auto-low` get a visible colored ring/outline (not hidden) — clicking one opens the correction controls from step 09 directly, not just a flag with no action.

## Click panel
Opens: the original photo next to the redesigned image (step 03 vs step 05 outputs), a Mapillary street-view/satellite toggle anchored to that coordinate (reuse step 03's Mapillary integration), and the history timeline from step 11 if more than one row exists for that address.
