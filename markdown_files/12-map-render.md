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

## Low-confidence visual treatment
Rows with `confidence_state` of `auto-low` get a visible colored ring/outline (not hidden) — clicking one opens the correction controls from step 09 directly, not just a flag with no action.

## Click panel
Opens: the original photo next to the redesigned image (step 03 vs step 05 outputs), a Mapillary street-view/satellite toggle anchored to that coordinate (reuse step 03's Mapillary integration), and the history timeline from step 11 if more than one row exists for that address.
