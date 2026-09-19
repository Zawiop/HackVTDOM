# HackVTDOM

Built for **VTHacks 14**, targeting the **Procedura AI** sponsor track.

## What it does

Turn a real building into its "Scorched Nebraska" post-apocalyptic version, then place it back on a live map at its exact real-world location, correctly scaled and rotated to match its real footprint.

1. Enter a building's address and upload a photo of it
2. Describe the transformation (overgrown, collapsed, abandoned, etc.)
3. An AI model generates the redesigned building image
4. The image is converted into a 3D mesh
5. The mesh is geocoded, matched to the real building footprint, and placed on the map with correct position, scale, and rotation
6. Every generated building persists on a shared map, growing into a collective "Scorched Nebraska" of campus

## Tech stack

- **Language:** TypeScript end to end
- **Backend:** Node.js + Express
- **Frontend:** React + Vite
- **Map + 3D placement:** Mapbox GL JS + deck.gl (`ScenegraphLayer`)
- **Geocoding:** Mapbox Geocoding API
- **Building footprints:** OpenStreetMap Overpass API
- **AI image redesign:** Replicate
- **Image → 3D mesh:** Tripo3D (fallback: Meshy.ai)
- **Database:** Supabase (Postgres)

## Repo layout

```
apps/api/        # Express backend
apps/web/        # React frontend
packages/shared/ # Shared TypeScript types (the API contract everyone builds against)
docs/            # Per-module build specs
```

## Team

Built by our VTHacks 14 team. See `docs/` for the module breakdown and `docs/01-git-workflow.md` for our branching convention.
