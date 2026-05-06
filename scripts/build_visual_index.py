from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from customer_context_assistant.visual_index import build_visual_entries, save_visual_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local visual index from door/window knowledge images.")
    parser.add_argument("--sample-library", type=Path, default=ROOT / "data" / "knowledge" / "visual_sample_library.md")
    parser.add_argument("--image-root", type=Path, default=Path("/Users/cc/Desktop/门窗知识库"))
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "visual_index.json")
    parser.add_argument("--sample-only", action="store_true", help="Only index curated visual_sample_library images.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    entries = build_visual_entries(args.sample_library, args.image_root, include_all_images=not args.sample_only)
    save_visual_index(entries, args.output)
    print(f"visual_entries={len(entries)} output={args.output}")


if __name__ == "__main__":
    main()
