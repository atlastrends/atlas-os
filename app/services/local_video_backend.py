"""
ATLAS - Cliente generico para geracao de VIDEO local via ComfyUI.

Diferente do backend de IMAGEM (Automatic1111-compat, API fixa e simples),
o ComfyUI usa "workflows" (grafos de nos) que variam conforme os modelos e
custom nodes instalados. Por isso este cliente e GENERICO: recebe um
workflow em formato API (JSON exportado do ComfyUI) com TOKENS de
substituicao (ex.: "__POSITIVE_PROMPT__"), troca os tokens pelos valores
reais desta cena, envia para a fila do ComfyUI, espera terminar e baixa o
video gerado.

Isso permite ao usuario montar/ajustar o workflow (que modelo de video usar,
quantos frames, resolucao etc.) diretamente na interface do ComfyUI - sem
precisar mexer neste codigo - e so exportar o workflow em "API format" para
o arquivo apontado por ATLAS_LOCAL_VIDEO_WORKFLOW.

Ver docs/DELL_G15_VIDEO_SETUP.md para o guia completo de instalacao no
notebook com GPU dedicada (ex.: Dell G15 / RTX 3060).

NENHUMA parte do ATLAS depende deste modulo para funcionar: se
ATLAS_LOCAL_VIDEO_URL nao estiver configurado, ou o ComfyUI nao responder,
ou a geracao falhar, o chamador (teen_diary_service) cai automaticamente
para o modo de imagem parada + zoom/pan (Ken Burns) - nunca quebra.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import requests


class ComfyUIVideoBackend:
    def __init__(self, log=None):
        self.log = log or (lambda m: print(m))
        self.base_url = (os.getenv("ATLAS_LOCAL_VIDEO_URL") or "").strip().rstrip("/")
        workflow_path = (os.getenv("ATLAS_LOCAL_VIDEO_WORKFLOW") or "").strip()
        self.workflow_path = workflow_path or str(
            Path(__file__).resolve().parent.parent
            / "assets" / "comfyui_workflows" / "teen_diary_wan21_i2v.json"
        )
        self.timeout = float(os.getenv("ATLAS_LOCAL_VIDEO_TIMEOUT", "600"))
        self.frames = int(os.getenv("ATLAS_LOCAL_VIDEO_FRAMES", "65"))
        self.fps = int(os.getenv("ATLAS_LOCAL_VIDEO_FPS", "16"))
        self.width = int(os.getenv("ATLAS_LOCAL_VIDEO_WIDTH", "480"))
        self.height = int(os.getenv("ATLAS_LOCAL_VIDEO_HEIGHT", "832"))
        self._checked = False
        self._ok = False
        self._workflow_template: Optional[str] = None

    # ------------------------------------------------------------
    def available(self) -> bool:
        """Confere (uma vez por processo) se o ComfyUI esta de pe e se o
        arquivo de workflow existe. Timeout curto para nao travar a
        geracao quando nao estiver configurado/acessivel."""
        if not self.base_url:
            return False
        if self._checked:
            return self._ok
        self._checked = True
        if not os.path.isfile(self.workflow_path):
            self.log(
                f"[VIDEO LOCAL] Workflow nao encontrado em {self.workflow_path}; "
                "usando fallback (zoom/pan)."
            )
            self._ok = False
            return False
        try:
            resp = requests.get(f"{self.base_url}/system_stats", timeout=4)
            self._ok = resp.status_code == 200
        except Exception:
            self._ok = False
        if self._ok:
            self.log(f"[VIDEO LOCAL] ComfyUI detectado em {self.base_url} (GPU local).")
        else:
            self.log(
                f"[VIDEO LOCAL] ComfyUI nao respondeu em {self.base_url}; "
                "usando fallback (zoom/pan)."
            )
        return self._ok

    def _load_template(self) -> str:
        if self._workflow_template is None:
            with open(self.workflow_path, encoding="utf-8") as fh:
                self._workflow_template = fh.read()
        return self._workflow_template

    def _upload_image(self, image_path: str) -> Optional[str]:
        """Envia a imagem-chave da cena para o ComfyUI e retorna o nome do
        arquivo (usado depois no workflow como imagem de entrada)."""
        try:
            with open(image_path, "rb") as fh:
                files = {"image": (os.path.basename(image_path), fh, "image/png")}
                resp = requests.post(
                    f"{self.base_url}/upload/image", files=files, timeout=60
                )
            if resp.status_code != 200:
                self.log(f"[VIDEO LOCAL] upload de imagem falhou: HTTP {resp.status_code}")
                return None
            data = resp.json()
            return data.get("name")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO LOCAL] upload de imagem deu excecao: {exc.__class__.__name__}")
            return None

    def generate(
        self,
        image_path: str,
        motion_prompt: str,
        seed: Optional[int] = None,
        out_path: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> Optional[str]:
        """Gera um clipe de video curto (image-to-video) a partir da imagem
        chave da cena + descricao de movimento. Retorna o caminho local do
        .mp4 gerado, ou None em qualquer falha (o chamador decide o que
        fazer - hoje, sem fallback de imagem parada, uma falha aqui aborta
        a geracao do episodio)."""
        if not self.available():
            return None

        image_name = self._upload_image(image_path)
        if not image_name:
            return None

        seed = seed if seed is not None else int(time.time() * 1000) % 2_147_483_647
        frames = max(1, int(round(duration * self.fps))) if duration else self.frames

        try:
            template = self._load_template()
            filled = (
                template
                .replace("__POSITIVE_PROMPT__", json.dumps(motion_prompt)[1:-1])
                .replace("__IMAGE_FILENAME__", json.dumps(image_name)[1:-1])
                .replace("__SEED__", str(seed))
                .replace("__FRAMES__", str(frames))
                .replace("__FPS__", str(self.fps))
                .replace("__WIDTH__", str(self.width))
                .replace("__HEIGHT__", str(self.height))
            )
            workflow = json.loads(filled)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO LOCAL] falha ao preparar o workflow: {exc.__class__.__name__}: {exc}")
            return None

        client_id = uuid.uuid4().hex
        try:
            resp = requests.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
                timeout=30,
            )
            if resp.status_code != 200:
                self.log(f"[VIDEO LOCAL] /prompt HTTP {resp.status_code}: {resp.text[:300]}")
                return None
            prompt_id = resp.json().get("prompt_id")
            if not prompt_id:
                self.log("[VIDEO LOCAL] ComfyUI nao devolveu prompt_id.")
                return None
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO LOCAL] falha ao enviar workflow: {exc.__class__.__name__}")
            return None

        started = time.time()
        output_info = None
        while time.time() - started < self.timeout:
            time.sleep(2.0)
            try:
                hist_resp = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=15)
                if hist_resp.status_code != 200:
                    continue
                hist = hist_resp.json().get(prompt_id)
                if not hist:
                    continue
                status = (hist.get("status") or {}).get("completed")
                outputs = hist.get("outputs") or {}
                if status or outputs:
                    for node_output in outputs.values():
                        for key in ("videos", "gifs", "images"):
                            items = node_output.get(key) or []
                            if items:
                                output_info = items[0]
                                break
                        if output_info:
                            break
                    if output_info or status:
                        break
            except Exception:  # noqa: BLE001
                continue
        else:
            self.log(f"[VIDEO LOCAL] tempo esgotado ({self.timeout:.0f}s) esperando o ComfyUI.")
            return None

        if not output_info:
            self.log("[VIDEO LOCAL] ComfyUI terminou mas nao encontrei o video na saida.")
            return None

        try:
            params = {
                "filename": output_info.get("filename"),
                "subfolder": output_info.get("subfolder", ""),
                "type": output_info.get("type", "output"),
            }
            view_resp = requests.get(f"{self.base_url}/view", params=params, timeout=60)
            if view_resp.status_code != 200:
                self.log(f"[VIDEO LOCAL] /view HTTP {view_resp.status_code}")
                return None
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO LOCAL] falha ao baixar o video: {exc.__class__.__name__}")
            return None

        out_path = out_path or os.path.join(
            os.path.dirname(image_path), f"video_{uuid.uuid4().hex[:8]}.mp4"
        )
        with open(out_path, "wb") as fh:
            fh.write(view_resp.content)
        return out_path
