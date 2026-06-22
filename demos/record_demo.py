#!/usr/bin/env python3
"""Run HydraBrain demos and produce an MP4 screen-recording-style video."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "recording"
FRAMES = OUT_DIR / "frames"
DEMO_NOTES = Path(__file__).resolve().parent / "sample-notes"

# Terminal aesthetic
BG = (10, 10, 15)
FG = (232, 232, 240)
ACCENT = (124, 58, 237)
MUTED = (154, 154, 176)
GREEN = (22, 163, 74)
RED = (239, 68, 68)
FONT_SIZE = 18
LINE_H = 26
PAD = 40
W, H = 1280, 720


def run(cmd: list[str], *, cwd: Path = ROOT, timeout: int = 120) -> tuple[int, str]:
    env = {**dict(__import__("os").environ)}
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def render_frame(title: str, subtitle: str, body: str, badge: str = "CLI") -> Path:
    from PIL import Image, ImageDraw, ImageFont

    FRAMES.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 14)
        font_title = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 28)
        font_sub = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
        font_sm = font
        font_title = font
        font_sub = font

    # Header bar
    draw.rounded_rectangle((24, 20, W - 24, 88), radius=14, fill=(19, 19, 28), outline=(38, 38, 54))
    draw.rounded_rectangle((36, 34, 110, 74), radius=8, fill=ACCENT)
    draw.text((52, 42), badge, fill=(255, 255, 255), font=font_sm)
    draw.text((130, 32), title, fill=FG, font=font_title)
    draw.text((130, 58), subtitle, fill=MUTED, font=font_sub)

    # Terminal panel
    draw.rounded_rectangle((24, 100, W - 24, H - 24), radius=14, fill=(14, 14, 22), outline=(38, 38, 54))

    max_cols = 78
    wrapped: list[str] = []
    for line in body.splitlines() or ["(no output)"]:
        if line.startswith("$ "):
            wrapped.append(line)
        else:
            wrapped.extend(textwrap.wrap(line, width=max_cols, replace_whitespace=False) or [""])

    y = 120
    for line in wrapped[:20]:
        color = ACCENT if line.startswith("$ ") else FG
        if line.startswith("✓"):
            color = GREEN
        elif line.startswith("✗") or "failed" in line.lower() or "error" in line.lower():
            color = RED
        draw.text((44, y), line[:120], fill=color, font=font)
        y += LINE_H
        if y > H - 40:
            draw.text((44, y), "…", fill=MUTED, font=font)
            break

    path = FRAMES / f"frame_{len(list(FRAMES.glob('*.png'))):03d}.png"
    img.save(path)
    return path


def make_video(frames: list[Path], out_mp4: Path, sec_per_frame: float = 4.0) -> None:
    if not frames:
        raise RuntimeError("no frames to encode")
    list_file = OUT_DIR / "frames.txt"
    with list_file.open("w") as f:
        for frame in frames:
            f.write(f"file '{frame}'\n")
            f.write(f"duration {sec_per_frame}\n")
        f.write(f"file '{frames[-1]}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            str(out_mp4),
        ],
        check=True,
        capture_output=True,
    )


def demo_section(title: str, subtitle: str, cmd: list[str], badge: str = "CLI") -> Path:
    display = "$ " + " ".join(cmd)
    print(f"\n=== {title} ===", flush=True)
    code, out = run(cmd)
    body = display + "\n\n" + out
    if code != 0 and "doctor" not in title.lower():
        body += f"\n\n(exit code {code})"
    return render_frame(title, subtitle, body, badge)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []

    # Title card
    frames.append(render_frame(
        "HydraBrain Demo",
        "Personal knowledge brain on HydraDB — zero local infra",
        "$ hydrabrain --help | head -20\n\n"
        "Commands: capture · ingest · sync · search · think · graph · web · serve",
        "INTRO",
    ))

    demos: list[tuple[str, str, list[str], str]] = [
        ("1. Status", "Check tenant + memory count", ["hydrabrain", "status"], "STATUS"),
        ("2. Doctor", "Health check: keys, connectivity, MCP", ["hydrabrain", "doctor"], "DOCTOR"),
        (
            "3. Capture",
            "Ingest a thought into the brain",
            [
                "hydrabrain", "capture",
                "HydraBrain demo session: testing capture, search, sync, and graph on 2026-06-22.",
                "--title", "Demo capture",
            ],
            "CAPTURE",
        ),
        (
            "4. Ingest",
            "Import markdown files",
            ["hydrabrain", "ingest", str(DEMO_NOTES / "project-alpha.md"), str(DEMO_NOTES / "meeting-notes.md")],
            "INGEST",
        ),
        (
            "5. Sync",
            "Bulk incremental directory sync",
            ["hydrabrain", "sync", str(DEMO_NOTES), "--dry-run"],
            "SYNC",
        ),
        (
            "6. Search",
            "Hybrid vector + BM25 + graph retrieval",
            ["hydrabrain", "search", "What is Project Alpha?", "-k", "3"],
            "SEARCH",
        ),
        (
            "7. Search #2",
            "Entity / meeting recall",
            ["hydrabrain", "search", "MCP tools and web UI goals", "-k", "3"],
            "SEARCH",
        ),
        (
            "8. Graph",
            "Explore knowledge graph connections",
            ["hydrabrain", "graph", "demo-capture"],
            "GRAPH",
        ),
    ]

    for title, subtitle, cmd, badge in demos:
        frames.append(demo_section(title, subtitle, cmd, badge))
        time.sleep(0.3)

    # Final status
    _, status_out = run(["hydrabrain", "status"])
    frames.append(render_frame(
        "9. Final Status",
        "Brain after demo ingestion",
        "$ hydrabrain status\n\n" + status_out,
        "DONE",
    ))

    out_mp4 = OUT_DIR / "hydrabrain-demo.mp4"
    make_video(frames, out_mp4, sec_per_frame=5.0)

    manifest = {
        "video": str(out_mp4),
        "frames": len(frames),
        "duration_sec": len(frames) * 5,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
