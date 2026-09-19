"""One-off: make real calls to the HF Spaces used for image edit / mesh generation.

Used to fill the CAPTURED EXAMPLE blocks in markdown_files/05 and 06.
Usage:
  .venv/bin/python scripts/capture_hf.py kontext [image_path]
  .venv/bin/python scripts/capture_hf.py sf3d [image_path]
"""
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from gradio_client import Client, handle_file

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
OUT = ROOT / "tests/output"
OUT.mkdir(parents=True, exist_ok=True)

which = sys.argv[1]
image = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "tests/fixtures/burruss_hall.jpg"
token = os.environ.get("HF_TOKEN")

if which == "kontext":
    client = Client("black-forest-labs/FLUX.1-Kontext-Dev", token=token, verbose=False)
    t0 = time.time()
    result = client.predict(
        input_image=handle_file(str(image)),
        prompt=(
            "Transform this building into a post-apocalyptic ruin: moss and ivy overgrowth, "
            "cracked stone, broken windows, muted amber-green palette. Keep the same building "
            "shape, camera angle and framing."
        ),
        seed=0,
        randomize_seed=True,
        guidance_scale=2.5,
        steps=28,
        api_name="/infer",
    )
    print(f"elapsed={time.time() - t0:.1f}s")
    print("RAW RESULT:", repr(result))
    src = result[0]["path"] if isinstance(result[0], dict) else result[0]
    dst = OUT / ("capture_kontext" + Path(src).suffix)
    shutil.copy(src, dst)
    print("copied to", dst)
elif which == "sf3d":
    client = Client("stabilityai/stable-fast-3d", token=token, verbose=False)
    t0 = time.time()
    result = client.predict(
        input_image=handle_file(str(image)),
        foreground_ratio=0.85,
        remesh_option="None",
        vertex_count=-1,
        texture_size=1024,
        api_name="/run_button",
    )
    print(f"elapsed={time.time() - t0:.1f}s")
    print("RAW RESULT:", repr(result))
    for i, src in enumerate(result):
        dst = OUT / (f"capture_sf3d_{i}" + Path(src).suffix)
        shutil.copy(src, dst)
        print("copied to", dst, dst.stat().st_size, "bytes")
