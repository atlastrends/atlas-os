"""Backend deterministico de cenas 3D do Diario da Bela."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BLENDER = (
    ROOT / "tools" / "blender-5.2.0-windows-x64" / "blender.exe"
)
DEFAULT_MASTER = (
    ROOT / "app" / "assets" / "teen_diary_3d" / "diario_master.blend"
)
DEFAULT_APPROVAL = (
    ROOT / "app" / "assets" / "teen_diary_3d" / "visual_approval.json"
)
DEFAULT_RENDER_SCRIPT = (
    ROOT / "app" / "blender" / "teen_diary_render.py"
)


class BlenderDiaryBackend:
    """Renderiza shots previsiveis a partir de assets 3D versionados."""

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or print
        self.blender = Path(
            os.getenv("ATLAS_BLENDER_EXE", str(DEFAULT_BLENDER))
        )
        self.master = Path(
            os.getenv("ATLAS_DIARY_BLEND_MASTER", str(DEFAULT_MASTER))
        )
        self.render_script = Path(
            os.getenv(
                "ATLAS_DIARY_BLEND_RENDER_SCRIPT",
                str(DEFAULT_RENDER_SCRIPT),
            )
        )
        self.approval = Path(
            os.getenv("ATLAS_DIARY_BLEND_APPROVAL", str(DEFAULT_APPROVAL))
        )
        self.timeout = int(os.getenv("ATLAS_BLENDER_RENDER_TIMEOUT", "1800"))

    def available(self) -> bool:
        if not self.blender.is_file():
            self.log(f"[BLENDER] executavel ausente: {self.blender}")
            return False
        if not self.master.is_file():
            self.log(
                "[BLENDER] arquivo mestre 3D ainda nao foi criado: "
                f"{self.master}"
            )
            return False
        if not self.render_script.is_file():
            self.log(f"[BLENDER] render script ausente: {self.render_script}")
            return False
        if not self.approval.is_file():
            self.log("[BLENDER] aprovação visual ausente; backend bloqueado.")
            return False
        try:
            approval = json.loads(self.approval.read_text(encoding="utf-8"))
        except Exception as exc:
            self.log(
                f"[BLENDER] aprovação visual inválida ({exc.__class__.__name__})."
            )
            return False
        if approval.get("approved") is not True:
            self.log(
                "[BLENDER] master 3D ainda reprovado visualmente; "
                "geração de episódios bloqueada."
            )
            return False
        return self.validate_assets()

    def validate_assets(self) -> bool:
        """Pede ao próprio Blender que valide o contrato do .blend mestre."""
        command = [
            str(self.blender),
            "--enable-autoexec",
            str(self.master),
            "--enable-autoexec",
            "--background",
            "--python",
            str(self.render_script),
            "--",
            "--validate-only",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            self.log(
                "[BLENDER] assets 3D incompletos: "
                f"{(result.stderr or result.stdout)[-1000:]}"
            )
            return False
        return True

    def render_scene(
        self,
        shot: dict,
        out_path: str,
        duration: float,
    ) -> Optional[str]:
        if not self.available():
            return None

        output = Path(out_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        shot_path = output.with_suffix(".shot.json")
        part_path = output.with_suffix(".part.mp4")
        frames_dir = output.parent / f"{output.stem}.frames"
        payload = {
            **shot,
            "duration": float(duration),
            "fps": int(os.getenv("ATLAS_DIARY_BLEND_FPS", "24")),
            "width": int(os.getenv("ATLAS_DIARY_BLEND_WIDTH", "540")),
            "height": int(os.getenv("ATLAS_DIARY_BLEND_HEIGHT", "960")),
        }
        shot_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        command = [
            str(self.blender),
            str(self.master),
            "--background",
            "--python",
            str(self.render_script),
            "--",
            "--shot",
            str(shot_path),
            "--output-dir",
            str(frames_dir),
            "--resume-frame",
            "1",
        ]
        total_frames = max(
            2,
            round(float(payload["duration"]) * int(payload["fps"])),
        )
        existing_frames = sorted(frames_dir.glob("frame_*.png"))
        if existing_frames:
            numbers = []
            for frame in existing_frames:
                try:
                    numbers.append(int(frame.stem.rsplit("_", 1)[1]))
                except (IndexError, ValueError):
                    numbers = []
                    break
            contiguous = (
                numbers == list(range(1, len(numbers) + 1))
                and len(numbers) < total_frames
            )
            if contiguous:
                command[-1] = str(len(numbers) + 1)
                self.log(
                    f"[BLENDER] retomando {output.name} no frame "
                    f"{len(numbers) + 1}/{total_frames}."
                )
            elif len(numbers) >= total_frames:
                command[-1] = str(total_frames + 1)
            else:
                shutil.rmtree(frames_dir, ignore_errors=True)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            first_frame = frames_dir / "frame_0001.png"
            last_frame = frames_dir / f"frame_{total_frames:04d}.png"
            if (
                result.returncode != 0
                or not first_frame.is_file()
                or not last_frame.is_file()
            ):
                self.log(
                    "[BLENDER] render falhou: "
                    f"{(result.stderr or result.stdout)[-1500:]}"
                )
                return None
            fps = int(payload["fps"])
            ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE")
            if not ffmpeg:
                import imageio_ffmpeg

                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            encode = subprocess.run(
                [
                    ffmpeg, "-y", "-v", "error",
                    "-framerate", str(fps),
                    "-i", str(frames_dir / "frame_%04d.png"),
                    "-c:v", "libx264", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(part_path),
                ],
                capture_output=True,
                timeout=300,
            )
            if encode.returncode != 0 or not part_path.is_file():
                self.log(
                    "[BLENDER] encode FFmpeg falhou: "
                    f"{encode.stderr.decode('utf-8', 'ignore')[-1000:]}"
                )
                return None
            os.replace(part_path, output)
            self.log(f"[BLENDER] cena 3D renderizada: {output}")
            shutil.rmtree(frames_dir, ignore_errors=True)
            return str(output)
        finally:
            for temp in (shot_path, part_path):
                try:
                    temp.unlink()
                except OSError:
                    pass
