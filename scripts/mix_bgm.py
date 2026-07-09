"""Mix background music into an existing narrated video."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from video_slicer.pipeline import load_dotenv
from video_slicer.rendering import add_background_music


def main() -> None:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Mix BGM into an existing final_with_voiceover.mp4.")
    parser.add_argument("--input", default="outputs/final_with_voiceover.mp4", help="Narrated video input path.")
    parser.add_argument("--output", default="outputs/final_with_bgm.mp4", help="Mixed video output path.")
    parser.add_argument("--bgm-audio", default=os.environ.get("BGM_AUDIO", ""), help="Background music audio path.")
    parser.add_argument("--bgm-volume", type=float, default=float(os.environ.get("BGM_VOLUME", "0.16")))
    parser.add_argument("--voiceover-volume", type=float, default=float(os.environ.get("VOICEOVER_VOLUME", "1.0")))
    parser.add_argument("--bgm-start", type=float, default=float(os.environ.get("BGM_START", "0")))
    parser.add_argument("--bgm-fade-in", type=float, default=float(os.environ.get("BGM_FADE_IN", "0.8")))
    parser.add_argument("--bgm-fade-out", type=float, default=float(os.environ.get("BGM_FADE_OUT", "2.5")))
    args = parser.parse_args()

    if not args.bgm_audio:
        raise SystemExit("BGM audio is required. Set BGM_AUDIO in .env or pass --bgm-audio.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    add_background_music(
        video_path=Path(args.input),
        bgm_audio=Path(args.bgm_audio),
        output_path=output_path,
        bgm_volume=args.bgm_volume,
        voiceover_volume=args.voiceover_volume,
        bgm_start=args.bgm_start,
        bgm_fade_in=args.bgm_fade_in,
        bgm_fade_out=args.bgm_fade_out,
    )
    print(f"Wrote BGM mix: {output_path}")


if __name__ == "__main__":
    main()
