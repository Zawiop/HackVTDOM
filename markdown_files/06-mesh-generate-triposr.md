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

Captured 2026-09-19 with `gradio_client==2.7.1` (Python), `HF_TOKEN` from `backend/.env` (free account).
Script: `backend/scripts/capture_hf.py`.

### stabilityai/TripoSR — DOWN (Space is in RUNTIME_ERROR, not just slow)
```
Space API signature:
>>> Client("stabilityai/TripoSR", token=HF_TOKEN).view_api()
ValueError: The current space is in the invalid state: RUNTIME_ERROR. Please contact the owner to fix this.

HF API GET /api/spaces/stabilityai/TripoSR -> runtime:
{'stage': 'RUNTIME_ERROR', 'hardware': {'current': None, 'requested': 'zero-a10g'},
 'errorMessage': '... scikit_build_core.errors.CMakeConfigError: scikit-build-core version 0.12.2 is too old.
   Minimum required version is 1.0. ... error: metadata-generation-failed ... from
   git+https://github.com/tatsy/torchmcubes.git ... File "/home/user/app/app.py", line 16 ...
   subprocess.CalledProcessError: Command ['pip', 'install', '--no-build-isolation',
   'git+https://github.com/tatsy/torchmcubes.git'] returned non-zero exit status 1.'}
lastModified 2026-05-24
```
The Space's own container can't build (its `torchmcubes` dependency no longer compiles), so no call can
succeed until Stability fixes it. No running public duplicate of TripoSR was found either. The backend still
lists TripoSR first but checks the Space's runtime stage before calling it, so it costs ~0.3s to skip.

### stabilityai/stable-fast-3d (SF3D) — WORKING replacement (live-captured)
Same org (Stability AI), direct successor to TripoSR, outputs a textured **.glb** directly (no .obj->.glb
conversion needed). ZeroGPU, runtime RUNNING, Gradio 4.41.0, license: Stability AI Community License.
```
Space API signature (from Client("stabilityai/stable-fast-3d").view_api()):
 - predict(fr, api_name="/update_foreground_ratio") -> preview_background_removal
 - predict(x, api_name="/lambda") -> 3d_model
 - predict(image, fr, api_name="/requires_bg_remove") -> (preview_background_removal, 3d_model)
     - [Image] image: filepath (required)
     - [Slider] fr: float (default 0.85, 0.5..1.0)
 - predict(input_image, foreground_ratio, remesh_option, vertex_count, texture_size, api_name="/run_button")
       -> (preview_background_removal, 3d_model)
     - [Image] input_image: filepath (required)
     - [Slider] foreground_ratio: float (default 0.85)
     - [Radio] remesh_option: Literal['None', 'Triangle', 'Quad'] (default 'None')
     - [Slider] vertex_count: float (default -1, -1..20000)
     - [Slider] texture_size: float (default 1024, 512..2048)
     Returns: [Image] preview_background_removal: filepath, [Litmodel3d] 3d_model: filepath
```
**GOTCHA — the documented `/run_button` signature above does not work as shown.** The real function
(`gradio_app.py`) is `run_button(run_btn, input_image, background_state, foreground_ratio, remesh_option,
vertex_count, texture_size)`. `view_api()` hides the `run_btn` Button and the `background_state` State, and
`gradio_client` only re-inserts placeholders for *State* inputs, so the 5-argument call arrives misaligned:
```
Example call (FAILS):
client.predict(input_image=handle_file(img), foreground_ratio=0.85, remesh_option="None",
               vertex_count=-1, texture_size=1024, api_name="/run_button")
Example response:
gradio_client.exceptions.AppError: The upstream Gradio app has raised an exception but has not enabled
verbose error reporting.
```
It is also stateful: `run_model` reads the cut-out image from the session State that `/requires_bg_remove`
fills — and that only happens when the input image already has transparency (alpha min == 0).
Working sequence (same `Client` instance = same session; `_skip_components=False` so every input is passed
explicitly):
```
Example call (WORKS):
client = Client("stabilityai/stable-fast-3d", token=HF_TOKEN, download_files="<dir>", _skip_components=False)
img = handle_file("rgba_cutout.png")                     # RGBA, background alpha = 0 (we cut it out locally)
a = client.predict(img, 0.85, api_name="/requires_bg_remove")
b = client.predict("Run", img, None, 0.85, "None", -1, 1024, api_name="/run_button")
#                   ^run_btn    ^background_state (server substitutes session value)

Example response:
a (0.7s) = ({'visible': True, 'value': 'Run', '__type__': 'update'}, None, None,
            {'visible': True, 'value': '<dir>/d1e78.../image.webp', '__type__': 'update'},
            {'visible': False, '__type__': 'update'}, {'visible': False, '__type__': 'update'})
b (3.4s) = ({'__type__': 'update'}, None, None, {'__type__': 'update'},
            {'visible': True, 'value': '<dir>/73effd85.../tmpg4dfka99.glb', '__type__': 'update'},
            {'visible': True, '__type__': 'update'})
# -> the mesh path is b[4]['value']. 1,004,836-byte .glb.
```
Captured mesh facts (trimesh): one node `geometry_0`, identity transform, 14,034 verts / 18,704 faces,
`TextureVisuals` + `PBRMaterial` (baseColor texture), bounds `[-0.448,-0.238,-0.269]..[0.486,0.179,0.254]`
— i.e. **unitless, ~1-unit box, pivot near the bounding-box center**, not meters, not base-centered.

Axis convention (read from SF3D's source, confirmed by rendering): SF3D's conditioning camera sits on +X of a
Z-up internal frame; export applies `Rx(-90°)` then `Ry(+90°)`. So the exported GLB is **+Y up** and the
**photographed facade faces −Z** (image-left → +X). glTF's convention is front = +Z, so step 07 applies a
180° yaw.

Input quality note: SF3D is an object model. A street photo must be cut out first. Tested local cutouts on
the Kontext output: `rembg` `isnet-general-use` kept 0.3% of pixels (grabbed the flag), `u2net` 18% (lost a
wing), `birefnet-general` 43% (whole building + tree; ~5-8s warm on CPU). The backend uses `birefnet-general`.

## Expected shape (subject to the captured example above overriding this)
Input: a single image (the redesigned building image from step 05, as a local file path or PIL image, not a URL — Gradio clients typically want a local file, so download step 05's output first).
Output: a mesh file, likely `.obj` rather than `.glb` — if so, add one Blender/trimesh export line to convert to `.glb` before step 07, matching the same conversion note the original plan already had for the Procedura/SpatiaOS experimental path.

## Failure handling
Wrap the call in a hard timeout (60-90s is reasonable for a shared queue) and a retry-once policy. On failure or timeout, fall through to the placeholder `.glb`, flag `confidence: "low"`, and let step 09's correction flow surface it — don't let a stuck mesh job block the rest of the pipeline for that building.

## What stays the same from the original plan
Everything about step 07 (normalization) and beyond is unaffected — they only care that this function returns a mesh file, not which service produced it. Tripo3D remains a paid fallback if the team decides late in the day that a card-based option is acceptable after all; it is not part of the free-only path.

### TripoSR run locally — WORKING (added 2026-09-19 after the HF token hit its ZeroGPU runs limit on Kontext)
Same model, no Space: `backend/app/generation/triposr_local.py` loads `stabilityai/TripoSR`
(`model.ckpt` + `config.yaml`, ~1.7 GB, into `backend/.cache/hf`) from the MIT-licensed
`VAST-AI-Research/TripoSR` repo, with a PyMCubes shim standing in for `torchmcubes`.
```
Example call:
from app.generation import triposr_local
glb = triposr_local.generate_glb(rgba_cutout)      # PIL RGBA, transparent background

Example response (Burruss cutout, Apple M5 Pro, MPS):
model load 4.7 s; inference 4.9 s cold / 3.2 s warm (marching cubes at 256^3)
raw mesh: 52,703 verts / 105,320 faces, ColorVisuals (vertex colors), no material,
bounds [-0.378,-0.556,-0.338]..[0.329,0.514,0.269] -> unitless, lying on its side in glTF terms
```
Axis convention: TripoSR's code says "right hand coordinate system, x back, y right, z up" with the
input-view camera at azimuth 0 = +X (`tsr/utils.py` `get_spherical_cameras`), and the repo exports
unrotated. So the raw mesh is **+Z up, facade toward +X** (image-right = +Y), confirmed by render.
Needs `transformers<5`: 5.x renamed the ViT weight keys and the checkpoint fails to load.
