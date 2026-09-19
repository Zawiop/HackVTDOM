"""One-off: make a real Gemini image-edit call and dump the request/response shape.

Used to fill the CAPTURED EXAMPLE block in markdown_files/05-image-edit-gemini.md.
Usage: .venv/bin/python scripts/capture_gemini.py [model]
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash-image"
PHOTO = ROOT / "tests/fixtures/burruss_hall.jpg"
PROMPT = (
    "Transform this building into a post-apocalyptic ruin: moss and ivy overgrowth, "
    "cracked concrete, broken windows, muted amber-green palette. Keep the same "
    "building shape, camera angle and framing."
)


def truncate(obj):
    """Replace long base64 strings with a length marker so the shape is readable."""
    if isinstance(obj, dict):
        return {k: truncate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [truncate(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 200:
        return f"<{len(obj)} chars: {obj[:40]}...>"
    return obj


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
t0 = time.time()
response = client.models.generate_content(
    model=MODEL,
    contents=[
        types.Part.from_text(text=PROMPT),
        types.Part.from_bytes(data=PHOTO.read_bytes(), mime_type="image/jpeg"),
    ],
)
elapsed = time.time() - t0

dump = response.model_dump(mode="json", exclude_none=True)
print(f"model={MODEL} elapsed={elapsed:.1f}s")
print(json.dumps(truncate(dump), indent=2))

out_dir = ROOT / "tests/output"
out_dir.mkdir(parents=True, exist_ok=True)
for i, part in enumerate(response.candidates[0].content.parts):
    if part.inline_data is not None:
        ext = part.inline_data.mime_type.split("/")[-1]
        path = out_dir / f"capture_gemini_{i}.{ext}"
        path.write_bytes(part.inline_data.data)
        print("wrote", path, len(part.inline_data.data), "bytes", part.inline_data.mime_type)
    elif part.text:
        print("text part:", part.text[:300])
