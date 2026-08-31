"""
ATLAS - Cliente para CONSISTENCIA DE PERSONAGEM (mesmo rosto/identidade em
toda cena) via Hugging Face Spaces (ZeroGPU) - GRATUITO.

Usa o espaco publico "InstantX/InstantID", que roda inferencia de verdade
em GPU compartilhada gratuita da Hugging Face (ZeroGPU) - confirmado via
`GET https://huggingface.co/api/spaces/InstantX/InstantID`
(runtime.hardware.current == "zero-a10g", NAO e wrapper de API paga).

Como funciona: recebe UMA imagem de referencia do rosto do personagem +
um prompt descrevendo a cena/pose nova, e devolve uma imagem NOVA com a
MESMA identidade facial (rosto, formato, cor dos olhos) só que na cena/pose
pedida. Isso resolve o requisito de que Bela e Maria tem que ser SEMPRE a
mesma pessoa (so roupas/acessorios podem mudar, nao o rosto) em toda a
serie - sem isso, cada cena gerada por texto-para-imagem puro daria uma
pessoa visualmente diferente.

A imagem de referencia de cada personagem e' gerada UMA UNICA VEZ (na
primeira vez que a serie roda) e fica salva permanentemente em
stories/_diario_<personagem>_reference.png - reaproveitada em TODOS os
episodios futuros, para sempre.

Limitacoes: mesma familia de limitacoes do backend de video (ZeroGPU e'
compartilhado, pode filar, pode cair). Sem fallback: se a consistencia de
personagem falhar apos tentativas, quem chama (teen_diary_service) aborta
o episodio (decisao explicita do produto - nunca publicar com o
personagem "errado").
"""

from __future__ import annotations

import os
import time
from typing import Optional


class CharacterConsistencyBackend:
    def __init__(self, log=None):
        self.log = log or (lambda m: print(m))
        self.space_id = (os.getenv("ATLAS_HF_CONSISTENCY_SPACE") or "InstantX/InstantID").strip()
        self.hf_token = (os.getenv("HF_TOKEN") or "").strip() or None
        self.num_steps = int(os.getenv("ATLAS_HF_CONSISTENCY_STEPS", "15"))
        self.identity_strength = float(os.getenv("ATLAS_HF_CONSISTENCY_IDENTITY", "0.85"))
        self.adapter_strength = float(os.getenv("ATLAS_HF_CONSISTENCY_ADAPTER", "0.75"))
        # depth_strength BAIXO de proposito: da liberdade para a pose/cena
        # mudar conforme o prompt (senao toda cena sairia com a MESMA
        # postura da foto de referencia, so mudando o fundo).
        self.depth_strength = float(os.getenv("ATLAS_HF_CONSISTENCY_DEPTH", "0.3"))
        self.guidance_scale = float(os.getenv("ATLAS_HF_CONSISTENCY_GUIDANCE", "5.0"))
        self.negative_prompt = os.getenv(
            "ATLAS_HF_CONSISTENCY_NEGATIVE",
            "(lowres, low quality, worst quality:1.2), (text:1.2), watermark, deformed, "
            "ugly, blurry, adult, mature, realistic photo, photorealistic",
        )
        self.timeout = float(os.getenv("ATLAS_HF_CONSISTENCY_TIMEOUT", "300"))
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
        if self._checked:
            return self._ok
        self._checked = True
        try:
            import gradio_client  # noqa: F401
        except Exception:
            self.log("[CONSISTENCY] biblioteca gradio_client nao instalada.")
            self._ok = False
            return False
        try:
            self._get_client()
            self._ok = True
            self.log(f"[CONSISTENCY] Conectado ao espaco '{self.space_id}' (Hugging Face, GPU gratuita).")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[CONSISTENCY] falha ao conectar em '{self.space_id}': {exc.__class__.__name__}: {exc}")
            self._ok = False
        return self._ok

    def generate(
        self,
        reference_image_path: str,
        scene_prompt: str,
        seed: Optional[int] = None,
        out_path: Optional[str] = None,
    ) -> Optional[str]:
        """Gera uma imagem NOVA (cena/pose descrita em scene_prompt) com a
        MESMA identidade facial da imagem de referencia. Retorna o caminho
        do arquivo baixado, ou None em qualquer falha (quem chama decide
        se tenta de novo ou aborta - sem fallback de identidade errada)."""
        if not self.available():
            return None

        from gradio_client import handle_file

        seed_value = seed if seed is not None else int(time.time() * 1000) % 2_147_483_647
        started = time.time()
        self.quota_reached = False
        try:
            client = self._get_client()
            result = client.predict(
                face_image_path=handle_file(reference_image_path),
                pose_image_path=handle_file(reference_image_path),
                prompt=scene_prompt,
                negative_prompt=self.negative_prompt,
                style_name="(No style)",
                num_steps=self.num_steps,
                identitynet_strength_ratio=self.identity_strength,
                adapter_strength_ratio=self.adapter_strength,
                canny_strength=0.0,
                depth_strength=self.depth_strength,
                controlnet_selection=["depth"],
                guidance_scale=self.guidance_scale,
                seed=seed_value,
                scheduler="EulerDiscreteScheduler",
                enhance_face_region=True,
                api_name="/generate_image",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            self.last_error = str(exc)
            self.quota_reached = "zerogpu quota" in self.last_error.lower() or "exceeded" in self.last_error.lower()
            self.log(
                f"[CONSISTENCY] geracao falhou apos {elapsed:.0f}s "
                f"({exc.__class__.__name__}: {str(exc)[:200]})."
            )
            return None

        image_ref = result[0] if isinstance(result, (list, tuple)) else result
        if isinstance(image_ref, dict):
            image_ref = image_ref.get("path") or image_ref.get("name")
        if not image_ref or not os.path.isfile(str(image_ref)):
            self.log("[CONSISTENCY] resposta sem arquivo de imagem valido.")
            return None

        elapsed = time.time() - started
        out_path = out_path or os.path.join(
            os.path.dirname(reference_image_path), f"consistent_{int(time.time())}.png"
        )
        try:
            import shutil

            shutil.copyfile(str(image_ref), out_path)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[CONSISTENCY] falha ao copiar a imagem gerada: {exc.__class__.__name__}")
            return None

        self.log(f"[CONSISTENCY] imagem gerada com identidade consistente em {elapsed:.0f}s.")
        return out_path
