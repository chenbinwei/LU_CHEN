"""Print the frontend-editable context packet schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from video_slicer.context_packet import frontend_context_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the context packet schema used by future frontend forms.")
    parser.add_argument("--output", default=None, help="Optional JSON output path. Prints to stdout when omitted.")
    args = parser.parse_args()

    text = json.dumps(frontend_context_schema(), ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Wrote context schema: {path}")
    else:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
