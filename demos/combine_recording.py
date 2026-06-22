#!/usr/bin/env python3
"""Combine CLI demo frames + web UI screenshots into one full demo video."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REC = ROOT / "recording"
WEB_SRC = Path("/var/folders/vp/q4bkk5w92dq_sps5m24dyq_h0000gn/T/cursor/screenshots/demos/recording")
CLI_MP4 = REC / "hydrabrain-demo.mp4"
FULL_MP4 = REC / "hydrabrain-full-demo.mp4"
WEB_DIR = REC / "web_frames"


def copy_web_shots() -> list[Path]:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []
    if WEB_SRC.exists():
        for src in sorted(WEB_SRC.glob("*.png")):
            dst = WEB_DIR / src.name
            shutil.copy2(src, dst)
            shots.append(dst)
    # Also use CLI frames as fallback section markers
    return shots


def make_web_segment(shots: list[Path], out: Path, sec: float = 6.0) -> None:
    if not shots:
        return
    lst = REC / "web_frames.txt"
    with lst.open("w") as f:
        for s in shots:
            f.write(f"file '{s}'\n")
            f.write(f"duration {sec}\n")
        f.write(f"file '{shots[-1]}'\n")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0f",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(out),
        ],
        check=True,
        capture_output=True,
    )


def concat_videos(parts: list[Path], out: Path) -> None:
    lst = REC / "concat.txt"
    with lst.open("w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
        check=True,
        capture_output=True,
    )


def main() -> None:
    shots = copy_web_shots()
    web_mp4 = REC / "web-segment.mp4"
    if shots:
        make_web_segment(shots, web_mp4, sec=8.0)
        concat_videos([CLI_MP4, web_mp4], FULL_MP4)
    else:
        shutil.copy2(CLI_MP4, FULL_MP4)
    print(FULL_MP4)


if __name__ == "__main__":
    main()
