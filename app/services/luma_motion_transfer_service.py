from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from app.publishing.base import project_root
from app.services.public_tunnel_service import ensure_public_base_url


LUMA_API_BASE = "https://api.lumalabs.ai/dream-machine/v1"
_TERMINAL_STATES = {"completed", "failed"}


@dataclass(frozen=True)
class LumaMotionResult:
    generation_id: str
    output_url: str
    output_path: str


class LumaMotionTransferService:
    def __init__(
        self,
        api_key: str | None = None,
        log: Callable[[str], None] | None = None,
    ):
        configured_key = os.getenv("LUMA_API_KEY") if api_key is None else api_key
        self.api_key = (configured_key or "").strip()
        self.log = log or (lambda message: None)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError(
                "LUMA_API_KEY nao configurada. Crie uma chave em "
                "https://platform.lumalabs.ai/."
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _public_copy(local_path: str, name: str) -> tuple[Path, str]:
        source = Path(local_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        public_dir = (
            Path(project_root())
            / "stories"
            / "_visual_tests"
            / "_luma_motion_inputs"
        )
        public_dir.mkdir(parents=True, exist_ok=True)
        target = public_dir / f"{name}{source.suffix.lower()}"
        shutil.copyfile(source, target)
        base_url = ensure_public_base_url()
        if not base_url:
            raise RuntimeError("URL publica HTTPS indisponivel para o Luma.")
        relative = target.relative_to(Path(project_root())).as_posix()
        return target, f"{base_url}/media/{relative}"

    def submit(
        self,
        *,
        guide_video_path: str,
        first_frame_path: str,
        prompt: str,
        mode: str = "adhere_1",
        model: str = "ray-2",
    ) -> str:
        if mode not in {
            "adhere_1",
            "adhere_2",
            "adhere_3",
            "flex_1",
            "flex_2",
            "flex_3",
        }:
            raise ValueError(f"Modo Luma nao permitido para piloto: {mode}")
        stamp = str(int(time.time()))
        _video_copy, video_url = self._public_copy(
            guide_video_path, f"guide_{stamp}"
        )
        _frame_copy, frame_url = self._public_copy(
            first_frame_path, f"frame_{stamp}"
        )
        payload = {
            "generation_type": "modify_video",
            "media": {"url": video_url},
            "first_frame": {"url": frame_url},
            "model": model,
            "mode": mode,
            "prompt": prompt,
        }
        self.log(
            f"[LUMA] Enviando piloto {model}/{mode}: "
            f"guide={video_url}, frame={frame_url}"
        )
        response = requests.post(
            f"{LUMA_API_BASE}/generations/video/modify",
            headers=self._headers(),
            json=payload,
            timeout=90,
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Luma submit HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        generation_id = str(response.json().get("id") or "")
        if not generation_id:
            raise RuntimeError("Luma nao retornou generation id.")
        return generation_id

    def wait(
        self,
        generation_id: str,
        *,
        timeout_seconds: int = 1800,
        poll_seconds: int = 8,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = requests.get(
                f"{LUMA_API_BASE}/generations/{generation_id}",
                headers=self._headers(),
                timeout=45,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Luma poll HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )
            data = response.json()
            state = str(data.get("state") or "")
            self.log(f"[LUMA] {generation_id}: {state}")
            if state == "completed":
                output_url = str((data.get("assets") or {}).get("video") or "")
                if not output_url:
                    raise RuntimeError("Luma concluiu sem URL de video.")
                return output_url
            if state == "failed":
                raise RuntimeError(
                    f"Luma falhou: {data.get('failure_reason') or data}"
                )
            time.sleep(poll_seconds)
        raise TimeoutError(f"Luma excedeu {timeout_seconds}s: {generation_id}")

    @staticmethod
    def download(output_url: str, output_path: str) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        with requests.get(output_url, stream=True, timeout=(30, 300)) as response:
            response.raise_for_status()
            with temp.open("wb") as file:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        file.write(chunk)
        if temp.stat().st_size < 1000:
            temp.unlink(missing_ok=True)
            raise RuntimeError("Download Luma vazio ou incompleto.")
        temp.replace(target)

    def run(
        self,
        *,
        guide_video_path: str,
        first_frame_path: str,
        prompt: str,
        output_path: str,
        mode: str = "adhere_1",
        model: str = "ray-2",
    ) -> LumaMotionResult:
        generation_id = self.submit(
            guide_video_path=guide_video_path,
            first_frame_path=first_frame_path,
            prompt=prompt,
            mode=mode,
            model=model,
        )
        output_url = self.wait(generation_id)
        self.download(output_url, output_path)
        return LumaMotionResult(generation_id, output_url, output_path)

    @staticmethod
    def save_request_manifest(
        path: str,
        *,
        guide_video_path: str,
        first_frame_path: str,
        prompt: str,
        mode: str,
        model: str,
    ) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "guide_video_path": guide_video_path,
                    "first_frame_path": first_frame_path,
                    "prompt": prompt,
                    "mode": mode,
                    "model": model,
                    "requires_luma_api_key": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
