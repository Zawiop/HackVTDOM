# Function: generateRedesignedImage — VERIFY BEFORE BUILDING

## Status
This file is a starting contract, not a verified one. Google's image-generation model naming and exact response shape have changed across releases (the model is marketed as "Nano Banana" and has shipped under names like `gemini-2.5-flash-image` and later generations). **Before Claude Code writes this function, someone on the team must make one real call by hand (curl, or the Python `google-genai` SDK in a REPL) and paste the actual request and actual response into this file below the line marked CAPTURED EXAMPLE.** That captured pair is what prevents the model from guessing a plausible-but-wrong field name.

## Purpose
Takes the source photo (step 03) and the World State description (step 04), sends both to an image-editing model, gets back a distinct redesigned image. This output is the literal fulfillment of "generate the redesigned building image" as its own deliverable — it also becomes the "after" side of the before/after UI panel.

## Service
Google Gemini API via Google AI Studio, image generation/editing model (currently marketed as "Nano Banana").

## Cost / auth
Confirmed free tier, no credit card required to start — Google's own billing docs state new accounts begin on the Free Tier with no billing account needed, and paid tier only activates once you explicitly link a card and prepay a minimum $5. Get a free API key at `aistudio.google.com` (Google account only, no payment info requested at that step).

## Rate limits — check this live, don't assume
Free tier limits are account- and model-specific, and Google's docs point to a live per-account dashboard rather than a fixed published number (`https://aistudio.google.com/rate-limit`). Check your team's actual quota there before build day, since image-generation-capable models are tracked separately (images-per-minute) from text models. Budget generation calls accordingly — if the quota looks tight, generate your final demo-quality images early and cache them rather than regenerating live during judging.

## Request contract (shape as of writing — confirm exact SDK call before use)
Using the `google-genai` Python SDK, conceptually:
```python
from google import genai
client = genai.Client(api_key="...")
response = client.models.generate_content(
    model="gemini-2.5-flash-image",  # confirm current model name in AI Studio at build time
    contents=[
        {"text": "<World State description from step 04>"},
        {"inline_data": {"mime_type": "image/jpeg", "data": "<base64 source photo>"}}
    ]
)
```
The exact parameter names (`inline_data` vs `inlineData`, `contents` structure) depend on the SDK version pinned at build time — verify against whatever `pip install google-genai` pulls in that day, not against this file alone.

## Response contract
The response contains one or more `candidates`, each with `content.parts`; the image comes back as inline base64 data in one of those parts (alongside or instead of text). Decode the base64, write it to storage, get a URL for downstream steps.

## CAPTURED EXAMPLE (fill this in before building)

Captured 2026-09-19 with `google-genai==2.24.0` (Python), using the team's `GEMINI_API_KEY`
from `backend/.env` and a real photo (`backend/tests/fixtures/burruss_hall.jpg`, Burruss Hall, 1280x830 JPEG).
Script: `backend/scripts/capture_gemini.py`.

**Result: the Gemini API has NO free-tier quota for any image-output model on this key.**
Every image-capable model returned `429 RESOURCE_EXHAUSTED` with `limit: 0` (not "used up" —
the free tier allocation is literally zero). Tried: `gemini-2.5-flash-image`, `gemini-3.1-flash-lite-image`,
`gemini-3.1-flash-image`, `gemini-3.1-flash-image-preview`, `gemini-3-pro-image-preview`,
`gemini-omni-flash-preview`, `gemini-omni-1.1-flash`. The key itself is valid: a text call to
`gemini-3.6-flash` succeeded (note `gemini-2.5-flash` text now 404s for new users). So the free,
no-card Gemini image path assumed in 00-overview does not exist today; the working free path is the
Hugging Face fallback captured further below. Gemini stays wired in as the first provider so it
starts working automatically if the key's project ever gets image quota.

### Gemini — Python SDK request (exactly what was sent)
```
REQUEST:
from google import genai
from google.genai import types
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[
        types.Part.from_text(text="Transform this building into a post-apocalyptic ruin: moss and ivy "
            "overgrowth, cracked concrete, broken windows, muted amber-green palette. Keep the same "
            "building shape, camera angle and framing."),
        types.Part.from_bytes(data=<burruss_hall.jpg bytes>, mime_type="image/jpeg"),
    ],
)

RESPONSE (SDK raises google.genai.errors.ClientError):
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded
your current quota ... Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests,
limit: 0, model: gemini-2.5-flash-preview-image ...', 'status': 'RESOURCE_EXHAUSTED', 'details': [...]}}
```

### Gemini — same call as raw REST (wire-level field names, camelCase)
```
REQUEST:
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent
x-goog-api-key: <GEMINI_API_KEY>
Content-Type: application/json
{
  "contents": [{
    "role": "user",
    "parts": [
      {"text": "Transform this building into a post-apocalyptic ruin: ..."},
      {"inlineData": {"mimeType": "image/jpeg", "data": "<526728 chars base64>"}}
    ]
  }],
  "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
}

RESPONSE: HTTP 429
{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. ... \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, limit: 0, model: gemini-2.5-flash-preview-image\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.5-flash-preview-image\n* ...\nPlease retry in 23.307829851s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {"@type": "type.googleapis.com/google.rpc.Help", "links": [{"description": "Learn more about Gemini API quotas", "url": "https://ai.google.dev/gemini-api/docs/rate-limits"}]},
      {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count", "quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier", "quotaDimensions": {"location": "global", "model": "gemini-2.5-flash-preview-image"}},
        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests", "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaDimensions": {"model": "gemini-2.5-flash-preview-image", "location": "global"}},
        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests", "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaDimensions": {"location": "global", "model": "gemini-2.5-flash-preview-image"}}
      ]},
      {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}
    ]
  }
}
```
Success-path parsing (NOT live-captured — no quota to capture it with; taken from the pinned SDK's own
typed model, `google.genai.types.GenerateContentResponse`): image bytes are at
`response.candidates[0].content.parts[i].inline_data.data` (already-decoded `bytes` in Python) with
`.inline_data.mime_type`; text parts have `.text` instead. The backend treats "no part with inline_data"
as a failure and falls through to the next provider rather than trusting this shape blindly.

### Working free provider — FLUX.1 Kontext [dev] Hugging Face Space (live-captured)
Space `black-forest-labs/FLUX.1-Kontext-Dev` (ZeroGPU, runtime RUNNING), `gradio_client==2.7.1`, `HF_TOKEN` from `.env`.
Script: `backend/scripts/capture_hf.py kontext`.
```
Space API signature (from Client(...).view_api()):
 - predict(input_image, prompt, seed, randomize_seed, guidance_scale, steps, api_name="/infer") -> (result, seed)
    Parameters:
     - [Image] input_image: dict(path | url | ...) (required)
     - [Textbox] prompt: str (required)
     - [Slider] seed: float (default 0)
     - [Checkbox] randomize_seed: bool (default True)
     - [Slider] guidance_scale: float (default 2.5)
     - [Slider] steps: float (default 28)
    Returns:
     - [Image] result: filepath dict (client downloads it; returned as a local path)
     - [Slider] seed: float

REQUEST:
from gradio_client import Client, handle_file
client = Client("black-forest-labs/FLUX.1-Kontext-Dev", token=HF_TOKEN)
result = client.predict(
    input_image=handle_file("tests/fixtures/burruss_hall.jpg"),
    prompt="Transform this building into a post-apocalyptic ruin: moss and ivy overgrowth, cracked stone, "
           "broken windows, muted amber-green palette. Keep the same building shape, camera angle and framing.",
    seed=0, randomize_seed=True, guidance_scale=2.5, steps=28,
    api_name="/infer",
)

RESPONSE (elapsed 32.9s):
('/private/var/folders/.../gradio/89a2a9d87fd6.../image.webp', 1093773858)
# -> tuple(local_path_to_webp, seed_used). Output was a 1264x816 RGB WebP, 178 KB.
```
Note the input is resized by the Space (1280x830 in -> 1264x816 out, multiples of 16) and the output
is **WebP**, not PNG/JPEG. The backend re-encodes to PNG before storing so every consumer gets one format.

## Failure handling
Wrap in a timeout (this is a synchronous call, not async-poll like Replicate/Meshy were, so a hang here blocks the request — set a hard client-side timeout, 30-60s, and fail loud with a retry option rather than freezing the UI).

## What this replaces
The original plan targeted Replicate + a Flux Kontext model (paid, ~$0.01-0.08/image, requires a linked card). This is the free, no-card substitute for that exact step. Everything downstream (steps 06-12) is unaffected — they only care that this function returns a URL to a distinct redesigned image, not how it was generated.
