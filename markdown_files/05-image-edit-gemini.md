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
```
REQUEST:
<paste your actual curl/SDK call here>

RESPONSE:
<paste the actual JSON response here, at least the shape of one candidate/part>
```

## Failure handling
Wrap in a timeout (this is a synchronous call, not async-poll like Replicate/Meshy were, so a hang here blocks the request — set a hard client-side timeout, 30-60s, and fail loud with a retry option rather than freezing the UI).

## What this replaces
The original plan targeted Replicate + a Flux Kontext model (paid, ~$0.01-0.08/image, requires a linked card). This is the free, no-card substitute for that exact step. Everything downstream (steps 06-12) is unaffected — they only care that this function returns a URL to a distinct redesigned image, not how it was generated.
