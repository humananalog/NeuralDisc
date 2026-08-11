#!/usr/bin/env bash
# Create a tiny sample disc folder and ingest it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAMPLE="${1:-$ROOT/data/sample_disc}"

mkdir -p "$SAMPLE"
python3.12 - <<'PY' "$SAMPLE"
import sys
from pathlib import Path
from PIL import Image, ImageDraw
root = Path(sys.argv[1])
specs = [
    ((30, 90, 180), (0, 0, 400, 300), (255, 220, 80)),
    ((200, 40, 40), (100, 80, 700, 500), (255, 255, 255)),
    ((40, 160, 80), (50, 200, 750, 550), (20, 20, 20)),
    ((90, 40, 160), (200, 50, 600, 400), (0, 255, 180)),
]
for i, (bg, box, fg) in enumerate(specs, 1):
    im = Image.new("RGB", (800, 600), bg)
    d = ImageDraw.Draw(im)
    d.rectangle(box, fill=fg)
    d.text((20, 20), f"Sample {i}", fill=(255, 255, 255))
    im.save(root / f"IMG_{i:04d}.jpg", "JPEG", quality=90)
# exact duplicate of first
(root / "IMG_0001_copy.jpg").write_bytes((root / "IMG_0001.jpg").read_bytes())
print(f"Wrote sample media to {root}")
PY

source "$ROOT/backend/.venv/bin/activate"
export NEURALDISC_LIBRARY_ROOT="${NEURALDISC_LIBRARY_ROOT:-$HOME/NeuralDisc}"
neuraldisc init
neuraldisc ingest "$SAMPLE" --name SAMPLE_DISC
neuraldisc stats
