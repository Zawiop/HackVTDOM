# Function: generateMesh — VERIFY BEFORE BUILDING — HIGHEST RISK STEP IN THE WHOLE PIPELINE

## Why this file exists / why this step changed
The original plan used Meshy's REST API on the assumption that its "100 credits/month, no card" free plan applied to API access. It doesn't. Meshy's own API docs state the API is "pay-before-you-go" — you must purchase credits before any programmatic call works, full stop, independent of the web app's free plan. There is no way to call Meshy's image-to-3D pipeline for free. It's removed from this stack entirely.

## Replacement service
`stabilityai/TripoSR`, an open-license single-image-to-3D model, published as a public Hugging Face Space (`huggingface.co/spaces/stabilityai/TripoSR`). Callable the same way the public demo works, via Hugging Face's Gradio API (the `gradio_client` Python package, or a raw HTTP POST to the Space's queue endpoint).

## Cost / auth
Free. No credit card. A free Hugging Face account + token is recommended (avoids the more aggressive anonymous-user rate limit) but not strictly required for light use.

## The real tradeoff — read this before committing to it
This is a public, shared, best-effort community Space, not a dedicated paid endpoint. There is no SLA. During a busy hackathon weekend, expect queueing, occasional slowness, and the possibility it's briefly unavailable if the Space owner restarts it or hits its own resource limits. This is the single least predictable dependency in the entire day. Mitigate it exactly like the original plan already mitigates Overpass and Replicate-equivalent flakiness: generate and cache your 2-3 demo-building meshes early (ideally in the first half of the day, not the last hour), and keep the static placeholder `.glb` — checked directly into the repo — as the hard fallback if generation is unavailable at all near judging.

## VERIFY BEFORE BUILDING
Gradio Space APIs are per-Space and can change with the app's own code updates — they are not a stable, versioned public API the way a vendor REST API is. Before Claude Code writes this function: open `https://huggingface.co/spaces/stabilityai/TripoSR`, use its "Use via API" panel (Gradio auto-generates one per Space) or `gradio_client.Client(space_id).view_api()`, and paste the actual current function signature and one real captured response below.

## CAPTURED EXAMPLE (fill this in before building)
```
Space API signature (from view_api() or the Space's own "Use via API" panel):
<paste here>

Example call:
<paste here — likely something like client.predict(input_image_path, api_name="/generate")>

Example response:
<paste here — expect a path/URL to a generated .glb or .obj file>
```

## Expected shape (subject to the captured example above overriding this)
Input: a single image (the redesigned building image from step 05, as a local file path or PIL image, not a URL — Gradio clients typically want a local file, so download step 05's output first).
Output: a mesh file, likely `.obj` rather than `.glb` — if so, add one Blender/trimesh export line to convert to `.glb` before step 07, matching the same conversion note the original plan already had for the Procedura/SpatiaOS experimental path.

## Failure handling
Wrap the call in a hard timeout (60-90s is reasonable for a shared queue) and a retry-once policy. On failure or timeout, fall through to the placeholder `.glb`, flag `confidence: "low"`, and let step 09's correction flow surface it — don't let a stuck mesh job block the rest of the pipeline for that building.

## What stays the same from the original plan
Everything about step 07 (normalization) and beyond is unaffected — they only care that this function returns a mesh file, not which service produced it. Tripo3D remains a paid fallback if the team decides late in the day that a card-based option is acceptable after all; it is not part of the free-only path.
