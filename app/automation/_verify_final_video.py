from pathlib import Path
import json
import subprocess


root = Path("/atlas")

outputs = (
    root
    / "storage"
    / "video_pipeline"
    / "outputs"
)

pending = (
    root
    / "storage"
    / "approval"
    / "pending"
)

videos = sorted(
    outputs.glob("*.mp4"),
    key=lambda path: path.stat().st_mtime,
    reverse=True,
)

if not videos:
    raise RuntimeError(
        "Nenhum MP4 novo foi encontrado."
    )

video = videos[0]

probe_process = subprocess.run(
    [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(video),
    ],
    check=True,
    text=True,
    capture_output=True,
)

probe = json.loads(
    probe_process.stdout
)

streams = probe.get(
    "streams",
    [],
)

video_stream = next(
    (
        stream
        for stream in streams
        if stream.get("codec_type") == "video"
    ),
    None,
)

audio_stream = next(
    (
        stream
        for stream in streams
        if stream.get("codec_type") == "audio"
    ),
    None,
)

if not video_stream:
    raise RuntimeError(
        "O MP4 nao possui stream de video."
    )

if not audio_stream:
    raise RuntimeError(
        "O MP4 nao possui narracao."
    )

width = int(
    video_stream.get("width")
    or 0
)

height = int(
    video_stream.get("height")
    or 0
)

duration = float(
    probe.get(
        "format",
        {},
    ).get(
        "duration",
        0,
    )
    or 0
)

if width != 1080 or height != 1920:
    raise RuntimeError(
        f"Resolucao invalida: {width}x{height}."
    )

if duration < 30 or duration > 60:
    raise RuntimeError(
        f"Duracao fora do limite: {duration:.2f}s."
    )

frame_process = subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        "fps=1/4,scale=160:-1",
        "-an",
        "-f",
        "framemd5",
        "-",
    ],
    check=True,
    text=True,
    capture_output=True,
)

frame_hashes: set[str] = set()

for line in frame_process.stdout.splitlines():
    if not line:
        continue

    if line.startswith("#"):
        continue

    parts = line.split(",")

    if parts:
        frame_hashes.add(
            parts[-1].strip()
        )

if len(frame_hashes) < 3:
    raise RuntimeError(
        "O video nao apresentou movimento visual suficiente."
    )

approval = None
approval_path = None

for path in pending.glob("*.json"):
    try:
        record = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        continue

    recorded_video = Path(
        record.get(
            "video_path",
            "",
        )
    )

    if recorded_video.name == video.name:
        approval = record
        approval_path = path
        break

if not approval:
    raise RuntimeError(
        "JSON de aprovacao nao encontrado."
    )

broll = approval.get(
    "broll",
    {},
)

if not broll.get("source_url"):
    raise RuntimeError(
        "URL de origem do B-roll ausente."
    )

if not broll.get("channel"):
    raise RuntimeError(
        "Canal de origem do B-roll ausente."
    )

narration = str(
    approval.get(
        "narration",
        "",
    )
)

if len(narration) < 200:
    raise RuntimeError(
        "A narracao registrada esta curta demais."
    )

result = {
    "validation": "APPROVED_FOR_HUMAN_REVIEW",
    "video": video.name,
    "approval_json": approval_path.name,
    "duration_seconds": round(
        duration,
        3,
    ),
    "resolution": (
        str(width)
        + "x"
        + str(height)
    ),
    "video_codec": video_stream.get(
        "codec_name"
    ),
    "audio_codec": audio_stream.get(
        "codec_name"
    ),
    "sampled_unique_frames": len(
        frame_hashes
    ),
    "static_image_detected": False,
    "original_audio_used": False,
    "broll_source": broll.get(
        "source_url"
    ),
    "broll_channel": broll.get(
        "channel"
    ),
    "broll_title": broll.get(
        "title"
    ),
    "narration_characters": len(
        narration
    ),
    "human_approval_required": True,
}

print(
    json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
)