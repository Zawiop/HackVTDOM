# Function/Spec: World State Visual Skin (step 13)

## Purpose
Files 00-12 specify correct behavior but not appearance. Left unspecified, Claude Code will pick a reasonable-looking default — probably a generic light-mode dashboard — that won't read as "Scorched Nebraska" to a judge glancing at your screen for the first time. This file exists so the visual identity is a decision made once, not an improvisation made differently each time a component gets built, and it costs near-zero build time: no new dependency, no new external service, no new failure mode.

## Cost / auth
None. Pure CSS/config, no external call.

## Palette
Reuse the exact tone already locked into file 04's World State prompt strings — don't invent a second palette. Suggested tokens:
```
--bg: #14120f
--panel: #1f1c17
--text: #e8e2d4
--accent-amber: #c98a3c
--accent-moss: #5c7a4f
--confidence-low: #d9603b       /* auto-low ring, file 12 */
--confidence-verified: #5c7a4f  /* manually-verified badge, file 09 */
```

## Map tone, without a new dependency
File 12 already committed to free keyless OSM raster tiles and explicitly ruled out a MapTiler key. Don't reopen that decision to chase a moodier basemap. Instead apply a CSS filter to the MapLibre canvas element itself:
```css
.maplibregl-canvas { filter: sepia(0.35) saturate(0.7) contrast(1.05) brightness(0.9); }
```
This gets an amber, desaturated, post-apocalyptic tone for free — zero new API surface, zero new rate-limit risk, which matters more than it sounds like on a day where TripoSR and Overpass are already your reliability risk budget.

## Typography
One distressed/industrial display font for headings only (page title, World State picker labels) — pick a single free Google Font and load it once. Everything else — forms, buttons, the correction UI's sliders and buttons, the history timeline — stays a plain, highly legible system sans-serif. The 3D scene and the before/after imagery are the visual centerpiece; UI chrome should stay out of their way, not compete with them.

## Confidence-state visual language (ties directly to files 08/09/12)
- `auto-high`: no visual flag, mesh renders normally.
- `auto-low`: colored ring/outline around the mesh footprint on the map (file 12 already specifies this exists — this section just assigns it `--confidence-low` above) plus a small "Needs review" badge in the click panel.
- `manually-verified`: a small check-mark badge, `--confidence-verified` colored, visually distinct from `auto-high` so a judge can see the human-in-the-loop story on screen, not just read it in the database. This is the strongest technical-depth beat in file 09 and file 14 — it needs to be visible, or it isn't demonstrable.

## What NOT to build
No loading-screen animation, no splash/intro sequence, no custom map marker icon set beyond what deck.gl's `ScenegraphLayer` already renders. Every hour spent here is an hour not spent finishing files 09-12 correctly — this file exists to prevent inconsistent styling, not to invite scope growth.
