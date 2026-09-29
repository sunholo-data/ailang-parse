"""Write one parse result as a committed golden (used by generate_golden.sh).

    python3 benchmarks/metrics/write_golden.py OUTPUT.json GOLDEN.json

- Extracted-image temp paths are replaced by normalize.LOCAL_IMAGE_SRC and
  their dataLength (the path's length) is dropped, so no golden holds a
  /tmp path from the machine that generated it.
- document.filename is kept from the existing golden when there is one. The
  suite ignores it; keeping it means a regeneration diff shows only what the
  parser changed.
- Serialised exactly as the parser writes JSON (compact, UTF-8), so an
  unchanged document regenerates byte-for-byte.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from normalize import canonicalize_images_in_place  # noqa: E402


def main() -> None:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    doc = json.loads(src.read_text(encoding="utf-8"))
    canonicalize_images_in_place(doc)
    if dest.exists():
        old = json.loads(dest.read_text(encoding="utf-8")).get("document", {})
        if "filename" in old and "filename" in doc.get("document", {}):
            doc["document"]["filename"] = old["filename"]
    dest.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
