"""
ATLAS - Cliente para geracao de VIDEO com movimento real via Hugging Face
Spaces (ZeroGPU) - GRATUITO, sem precisar de GPU propria.

Usa o espaco publico "Lightricks/ltx-video-distilled" (LTX-Video 13B
destilado), que roda inferencia de verdade em GPU compartilhada gratuita da
propria Hugging Face (ZeroGPU) - NAO e um wrapper de API paga. Confirmado
lendo o codigo-fonte do espaco (app.py) antes de implementar este cliente.

Limitacoes REAIS deste caminho (por ser um recurso compartilhado e gratis):
  - Cada chamada tem no MAXIMO 60-75 segundos de GPU alocada (limite do
    proprio ZeroGPU) - por isso mantemos duracao curta e qualidade "rapida"
    (sem o passo de upscale, mais lento) por padrao.
  - Pode haver FILA de espera (outros usuarios usando o mesmo espaco
    publico) - as vezes rapido, as vezes demorado. Timeout generoso, mas
    finito.
  - O espaco pode cair, mudar de nome ou ser descontinuado a qualquer
    momento (e mantido pela comunidade/Lightricks, nao pelo ATLAS).

Por tudo isso, este backend e best-effort MAS SEM fallback de imagem
parada: se ele falhar (mesmo apos tentativas), quem chama
(teen_diary_service) tenta o proximo backend disponivel na cadeia (ex.:
ComfyUI local) e, se nenhum funcionar, ABORTA a geracao do episodio (nao
publica nada com imagem estatica) - por decisao explicita do produto, todo
video publicado deve ter movimento real.

Uma conta gratuita da Hugging Face (sem cartao de credito) + um token de
acesso ("read") aumenta a prioridade na fila de espera. Sem token, ainda
funciona, mas com menos prioridade. Configurar em HF_TOKEN no .env.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Optional


class HFSpacesVideoBackend:
    def __init__(self, log=None):
        self.log = log or (lambda m: print(m))
        self.space_id = (os.getenv("ATLAS_HF_VIDEO_SPACE") or "Lightricks/ltx-video-distilled").strip()
        self.hf_token = (os.getenv("HF_TOKEN") or "").strip() or None
        self.duration = float(os.getenv("ATLAS_HF_VIDEO_DURATION", "3.0"))
        self.width = int(os.getenv("ATLAS_HF_VIDEO_WIDTH", "480"))
        self.height = int(os.getenv("ATLAS_HF_VIDEO_HEIGHT", "832"))
        self.improve_texture = (
            os.getenv("ATLAS_HF_VIDEO_IMPROVE_TEXTURE", "false").strip().lower()
            in ("1", "true", "yes", "on", "sim")
        )
        self.timeout = float(os.getenv("ATLAS_HF_VIDEO_TIMEOUT", "300"))
        self.negative_prompt = os.getenv(
            "ATLAS_HF_VIDEO_NEGATIVE_PROMPT",
            "worst quality, inconsistent motion, blurry, jittery, distorted, "
            "static, still image, deformed, extra limbs, watermark, text",
        )
        self._client = None
        self._checked = False
        self._ok = False
        self.last_error = ""
        self.quota_reached = False

    def _get_client(self):
        if self._client is not None:
            return self._client
        from gradio_client import Client

        self._client = Client(self.space_id, token=self.hf_token)
        return self._client

    def available(self) -> bool:
        """Confere (uma vez por processo) se conseguimos conectar ao
        espaco. NAO garante que a geracao vai funcionar (fila/GPU podem
        falhar depois) - so confirma que o espaco existe e respondeu."""
        if self._checked:
            return self._ok
        self._checked = True
        try:
            import gradio_client  # noqa: F401
        except Exception:
            self.log("[VIDEO HF] biblioteca gradio_client nao instalada; usando fallback (zoom/pan).")
            self._ok = False
            return False
        try:
            self._get_client()
            self._ok = True
            self.log(
                f"[VIDEO HF] Conectado ao espaco '{self.space_id}' (Hugging Face, GPU "
                "compartilhada gratuita)."
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO HF] falha ao conectar em '{self.space_id}': {exc.__class__.__name__}: {exc}")
            self._ok = False
        return self._ok

    def generate(
        self,
        image_path: str,
        motion_prompt: str,
        seed: Optional[int] = None,
        out_path: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> Optional[str]:
        """Gera um clipe curto de video (image-to-video) via HF Spaces.
        Retorna o caminho local do .mp4 baixado, ou None em qualquer falha
        (fila cheia, timeout, espaco fora do ar etc.) - o chamador (sem
        fallback de imagem parada) decide se tenta de novo ou aborta."""
        if not self.available():
            return None

        from gradio_client import handle_file

        seed_value = seed if seed is not None else int(time.time() * 1000) % (2**32 - 1)
        requested_duration = duration if duration is not None else self.duration
        started = time.time()
        self.quota_reached = False
        try:
            client = self._get_client()
            result = client.predict(
                prompt=motion_prompt,
                negative_prompt=self.negative_prompt,
                input_image_filepath=handle_file(image_path),
                input_video_filepath=None,
                height_ui=self.height,
                width_ui=self.width,
                mode="image-to-video",
                duration_ui=max(0.3, min(8.5, requested_duration)),
                ui_frames_to_use=9,
                seed_ui=seed_value,
                randomize_seed=seed is None,
                ui_guidance_scale=3.0,
                improve_texture_flag=self.improve_texture,
                api_name="/image_to_video",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            self.last_error = str(exc)
            self.quota_reached = "zerogpu quota" in self.last_error.lower() or "exceeded" in self.last_error.lower()
            self.log(
                f"[VIDEO HF] geracao falhou apos {elapsed:.0f}s ({exc.__class__.__name__}: "
                f"{str(exc)[:200]})."
            )
            return None

        # result = (video_path_or_dict, used_seed)
        video_ref = result[0] if isinstance(result, (list, tuple)) else result
        video_path = video_ref.get("video") if isinstance(video_ref, dict) else video_ref
        if isinstance(video_path, dict):
            video_path = video_path.get("path") or video_path.get("name")

        if not video_path or not os.path.isfile(str(video_path)):
            self.log("[VIDEO HF] resposta sem arquivo de video valido.")
            return None

        elapsed = time.time() - started
        out_path = out_path or os.path.join(
            os.path.dirname(image_path), f"hf_video_{int(time.time())}.mp4"
        )
        try:
            shutil.copyfile(str(video_path), out_path)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[VIDEO HF] falha ao copiar o video baixado: {exc.__class__.__name__}")
            return None

        self.log(f"[VIDEO HF] cena gerada com sucesso em {elapsed:.0f}s (GPU gratuita compartilhada).")
        return out_path
