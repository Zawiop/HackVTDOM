# Scorched Nebraska — Free-Stack Build Overview

Last verified: 2026-09-19. Every external dependency below was checked against its own current docs. Where a number could drift (rate limits, credit costs), that's flagged explicitly — re-check it yourself before building, don't trust this file's number blindly on hackathon day.

## What changed from the original plan

**Replicate (Flux Kontext) → Google Gemini API, image generation model.** Replicate has no standing free tier: after a small number of curated free runs it requires a linked card and charges per image ($0.01-0.08 depending on the Flux variant). The Gemini API's free tier needs no card at all — new accounts start on it automatically — and its image model (marketed as "Nano Banana," currently `gemini-2.5-flash-image` or a newer generation depending on what's live when you build) does image-to-image editing: send an input image plus a text instruction, get an edited image back. This is a direct swap for the "photo + description → redesigned image" step.

**Meshy REST API → self-hosted-via-Hugging-Face-Space TripoSR.** This is the important correction: Meshy's "100 credits/month, no card" plan is a **web-app-only** plan. Meshy's own API docs state plainly that the API is "pay-before-you-go" — you must purchase credits before any API call works, full stop, regardless of the web app's free tier. There is no way to hit Meshy's image-to-3D pipeline programmatically for free. It has to come out of the stack entirely if the constraint is zero payment.

The free replacement is `stabilityai/TripoSR`, an open-license (MIT-family) single-image-to-3D model that Stability AI publishes as a public Hugging Face Space. You call it the same way anyone using the public demo does — through Hugging Face's Gradio API client (`gradio_client` in Python, or a plain HTTP POST to the Space's API endpoint) — no key required for basic use, a free HF account token if you want less aggressive anonymous rate limiting. It costs nothing because it runs on Hugging Face's shared community compute.

The tradeoff, and it's real: you're now on a public, shared, best-effort queue with no SLA, instead of a paid dedicated endpoint. This is the single least predictable piece of the whole day. Treat it accordingly (see the mitigation in file 06).

**MapTiler → drop it, use free keyless OSM raster tiles only.** The original plan already listed this as an option; making it the only option removes any temptation to reach for a MapTiler key that has its own (small but real) free-tier ceiling.

## Confirmed fully free, no card, unchanged from the original plan
Nominatim (geocoding, 1 req/sec, needs a real `User-Agent`), Overpass API (building footprints, public server, no key), Mapillary (confirmed "100% free for any use case" in their own FAQ, token is just registration), Supabase free tier (Postgres + storage), MapLibre GL JS + deck.gl (open source libraries).

## Net result
Every external call in the pipeline is now free with no credit card anywhere. The cost you're paying instead is reliability risk on exactly one step (mesh generation), which the fallback plan below is built around.

## One-day build order
Build in this order, not step-number order. Front-load the least predictable dependency so you find out early if it's having a bad day, not at hour 10.

1. **Hour 0-1:** Manually test the TripoSR Space and the Gemini image API by hand (curl / a Python REPL / the Space's own web UI), before writing any app code. Capture one real request and one real response from each into files 05 and 06 below. This is the single highest-leverage hour of the day — it's what turns those two spec files from "probably right" into "verified correct," which is the whole point of writing them before Claude Code touches the function.
2. **Hour 1-3:** Steps 1-2 (geocode + footprint) and step 3 (photo upload + Mapillary fallback). These are the most standard REST calls in the stack; Claude Code should produce correct code fast here.
3. **Hour 3-5:** Step 4 (World State selector) and step 5 (Gemini image edit), using the verified contract from file 05.
4. **Hour 5-7:** Step 6 (TripoSR mesh generation) using the verified contract from file 06, and immediately pre-generate and cache the meshes for your 2-3 demo buildings. Do this well before you need it for anything else — if the public queue is slow or down, you want to know now, not at hour 11.
5. **Hour 7-9:** Steps 7-8 (normalization + placement transform). Pure math, no external calls, lowest risk, but the part that actually differentiates the submission — worth real time.
6. **Hour 9-11:** Step 12 (Supabase writes + MapLibre/deck.gl render) so you have something visibly on a map as early as possible.
7. **Remaining time, in priority order if it runs short:** step 9 (correction UI) first since it reuses data you already computed, then step 11 (history), then step 10 (propagate, pre-baked for the demo rather than live), then step 13 (UI skin), then step 14 (pitch rehearsal). Cut from the bottom of this list, not the top, if the day compresses.

## The hallucination-guard method, applied
Per-function markdown files work because an LLM coding agent doesn't hallucinate randomly — it hallucinates plausibly, filling gaps in a spec with the most statistically likely API shape, which is often wrong for a specific model version, a specific Space's function signature, or a specific SDK's current field names. The fix isn't "write more detailed prose," it's "paste in one real captured request/response pair before the function gets written." A markdown file with a verified example in it can't be second-guessed by the model; a markdown file with only a prose description of what the API "should" return still leaves room to guess. Files 05 and 06 in this set are marked `VERIFY BEFORE BUILDING` for exactly this reason — everything else here is standard, stable, well-documented API surface where a written contract alone is enough.
