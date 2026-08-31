"""Valida automaticamente o episódio 3D de prova concluído."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg


def inspect_video(path: Path) -> dict:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    info = probe.stderr
    duration_match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info
    )
    resolution_match = re.search(
        r"Video:.*?(\d{3,5})x(\d{3,5})", info
    )
    duration = None
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    resolution = None
    if resolution_match:
        resolution = [
            int(resolution_match.group(1)),
            int(resolution_match.group(2)),
        ]
    decode = subprocess.run(
        [
            ffmpeg, "-v", "error", "-i", str(path),
            "-frames:v", "1", "-f", "null", "-",
        ],
        capture_output=True,
        timeout=60,
    )
    return {
        "file": path.name,
        "size": path.stat().st_size,
        "duration": duration,
        "resolution": resolution,
        "has_video": "Video:" in info,
        "has_audio": "Audio:" in info,
        "first_frame_decodes": decode.returncode == 0,
    }


def main(folder: Path) -> int:
    story_path = folder / "story.json"
    story = json.loads(story_path.read_text(encoding="utf-8"))
    videos = {
        lang: inspect_video(folder / filename)
        for lang, filename in story["videos"].items()
    }
    checks = {
        "scene_count_10_16": 10 <= int(story["scenes"]) <= 16,
        "both_languages": set(videos) == {"en", "pt"},
        "duration_60_90": all(
            data["duration"] is not None
            and 60 <= data["duration"] <= 90
            for data in videos.values()
        ),
        "vertical_resolution": all(
            data["resolution"] == [1080, 1920]
            for data in videos.values()
        ),
        "audio_video_present": all(
            data["has_audio"]
            and data["has_video"]
            and data["first_frame_decodes"]
            for data in videos.values()
        ),
        "affiliate_links_present": bool(
            story.get("affiliate_caption_en")
            and story.get("affiliate_caption_pt")
            and story.get("affiliate_products")
        ),
        "no_partial_files": not any(folder.glob("*.part.mp4")),
        "rendered_scene_files": all(
            len(list(folder.glob(f"scene*_{lang}_blender.mp4")))
            == int(story["scenes"])
            for lang in ("en", "pt")
        ),
    }
    report = {
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "folder": str(folder),
        "videos": videos,
        "checks": checks,
        "passed": all(checks.values()),
    }
    (folder / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("uso: validate_diary_proof.py <pasta>")
    raise SystemExit(main(Path(sys.argv[1])))
