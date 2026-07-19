import os
import json
from datetime import datetime, timezone


class MetadataStorageService:
    def __init__(self):
        self.output_dir = "output_metadata"
        os.makedirs(self.output_dir, exist_ok=True)

    def _safe_get(self, data: dict, key: str, default=None):
        if not isinstance(data, dict):
            return default
        return data.get(key, default)

    def _utc_now(self):
        return datetime.now(timezone.utc).isoformat()

    def _normalize_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return [value]

    def _build_payload(
        self,
        content_id: int,
        topic: str,
        language: str,
        country_code: str,
        performance_score,
        source: str,
        video_path: str,
        metadata: dict
    ):
        """
        Monta o pacote final que será usado no upload automático.
        """
        now = self._utc_now()

        metadata = metadata or {}

        script_text = self._safe_get(metadata, "script") or self._safe_get(metadata, "voiceover") or self._safe_get(metadata, "narration") or ""
        voice_name = self._safe_get(metadata, "voice_name") or self._safe_get(metadata, "voice") or self._safe_get(metadata, "tts_voice") or ""
        content_type = self._safe_get(metadata, "content_type") or "short_form_video"

        estimated_words = self._safe_get(metadata, "estimated_words")
        if estimated_words is None and isinstance(script_text, str):
            estimated_words = len(script_text.split())

        estimated_seconds = self._safe_get(metadata, "estimated_seconds")
        if estimated_seconds is None:
            estimated_seconds = self._safe_get(metadata, "duration_seconds")
        if estimated_seconds is None:
            estimated_seconds = None

        hashtags = self._normalize_list(self._safe_get(metadata, "hashtags", []))
        youtube_tags = self._normalize_list(self._safe_get(metadata, "youtube_tags", []))

        platform_versions = self._safe_get(metadata, "platform_versions", {})
        if not isinstance(platform_versions, dict):
            platform_versions = {}

        return {
            "content_id": content_id,
            "topic": topic,
            "language": language,
            "country_code": country_code,
            "performance_score": performance_score,
            "trend_source": source,
            "video_path": video_path,
            "created_at_utc": now,

            "content": {
                "type": content_type,
                "topic": topic,
                "language": language,
                "country_code": country_code,
                "source": source,
                "video_path": video_path,
                "voice_name": voice_name,
                "script": script_text,
                "estimated_words": estimated_words,
                "estimated_seconds": estimated_seconds,
                "base_hashtags": hashtags
            },

            "platform_versions": platform_versions,

            "platforms": {
                "youtube": {
                    "ready": True,
                    "title": self._safe_get(metadata, "youtube_title"),
                    "description": self._safe_get(metadata, "youtube_description"),
                    "tags": youtube_tags,
                    "hashtags": hashtags,
                    "privacy_status": "private",
                    "made_for_kids": False,
                    "category_id": "25",
                    "orientation": "vertical",
                    "format": "shorts"
                },
                "tiktok": {
                    "ready": True,
                    "caption": self._safe_get(metadata, "tiktok_caption"),
                    "hashtags": hashtags,
                    "privacy_level": "SELF_ONLY",
                    "format": "vertical"
                },
                "instagram": {
                    "ready": True,
                    "caption": self._safe_get(metadata, "instagram_caption"),
                    "hashtags": hashtags,
                    "media_type": "REELS",
                    "format": "vertical"
                },
                "facebook": {
                    "ready": True,
                    "caption": self._safe_get(metadata, "facebook_caption"),
                    "hashtags": hashtags,
                    "media_type": "REELS",
                    "format": "vertical"
                }
            },

            "metadata": metadata,

            "compliance": {
                "ai_generated": self._safe_get(metadata, "ai_generated", True),
                "format": self._safe_get(metadata, "format", "vertical_1080x1920"),
                "made_for_shorts": self._safe_get(metadata, "made_for_shorts", True),
                "needs_human_review_before_public_upload": True,
                "originality_notes": self._safe_get(metadata, "originality_notes", ""),
                "safety_notes": self._safe_get(metadata, "safety_notes", "")
            },

            "production": {
                "render_engine": self._safe_get(metadata, "render_engine", "atlas"),
                "audio_engine": self._safe_get(metadata, "audio_engine", "edge_tts"),
                "video_engine": self._safe_get(metadata, "video_engine", "moviepy"),
                "asset_source": self._safe_get(metadata, "asset_source", "youtube_search"),
                "rendered_at_utc": now
            },

            "upload_status": {
                "youtube": {
                    "uploaded": False,
                    "uploaded_at_utc": None,
                    "platform_video_id": None,
                    "url": None,
                    "error": None
                },
                "tiktok": {
                    "uploaded": False,
                    "uploaded_at_utc": None,
                    "platform_video_id": None,
                    "url": None,
                    "error": None
                },
                "instagram": {
                    "uploaded": False,
                    "uploaded_at_utc": None,
                    "platform_video_id": None,
                    "url": None,
                    "error": None
                },
                "facebook": {
                    "uploaded": False,
                    "uploaded_at_utc": None,
                    "platform_video_id": None,
                    "url": None,
                    "error": None
                }
            },

            "audit": {
                "saved_at_utc": now,
                "updated_at_utc": now,
                "schema_version": 2
            }
        }

    def save_metadata(
        self,
        content_id: int,
        topic: str,
        language: str,
        country_code: str,
        performance_score,
        source: str,
        video_path: str,
        metadata: dict
    ):
        """
        Salva a metadata em output_metadata/metadata_ID.json.
        """
        try:
            payload = self._build_payload(
                content_id=content_id,
                topic=topic,
                language=language,
                country_code=country_code,
                performance_score=performance_score,
                source=source,
                video_path=video_path,
                metadata=metadata
            )

            file_path = os.path.join(
                self.output_dir,
                f"metadata_{content_id}.json"
            )

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    payload,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(f"💾 [METADATA STORAGE] Metadata salva em: {file_path}")
            return file_path

        except Exception as e:
            print(f"❌ [METADATA STORAGE] Erro ao salvar metadata do conteúdo {content_id}: {e}")
            return None

    def load_metadata(self, content_id: int):
        """
        Lê a metadata salva de um conteúdo específico.
        Será útil para o futuro serviço de upload.
        """
        file_path = os.path.join(
            self.output_dir,
            f"metadata_{content_id}.json"
        )

        if not os.path.exists(file_path):
            print(f"⚠️ [METADATA STORAGE] Arquivo não encontrado: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            print(f"❌ [METADATA STORAGE] Erro ao ler metadata {content_id}: {e}")
            return None

    def update_upload_status(
        self,
        content_id: int,
        platform: str,
        uploaded: bool,
        platform_video_id: str = None,
        url: str = None,
        error: str = None
    ):
        """
        Atualiza status de upload no JSON.
        Será usado quando criarmos o uploader automático.
        """
        payload = self.load_metadata(content_id)

        if not payload:
            return False

        platform = str(platform or "").lower().strip()

        if platform not in payload.get("upload_status", {}):
            print(f"⚠️ [METADATA STORAGE] Plataforma inválida: {platform}")
            return False

        payload["upload_status"][platform]["uploaded"] = uploaded
        payload["upload_status"][platform]["platform_video_id"] = platform_video_id
        payload["upload_status"][platform]["url"] = url
        payload["upload_status"][platform]["error"] = error

        if uploaded:
            payload["upload_status"][platform]["uploaded_at_utc"] = self._utc_now()
        else:
            payload["upload_status"][platform]["uploaded_at_utc"] = None

        if isinstance(payload, dict):
            payload.setdefault("audit", {})
            payload["audit"]["updated_at_utc"] = self._utc_now()

        file_path = os.path.join(
            self.output_dir,
            f"metadata_{content_id}.json"
        )

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    payload,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(f"✅ [METADATA STORAGE] Status de upload atualizado: {platform} | content_id={content_id}")
            return True

        except Exception as e:
            print(f"❌ [METADATA STORAGE] Erro ao atualizar status de upload: {e}")
            return False

    def list_pending_uploads(self, platform: str = None):
        """
        Lista conteúdos ainda não enviados.
        Se platform for informado, filtra por uma plataforma específica.
        """
        pending = []

        try:
            files = [
                f for f in os.listdir(self.output_dir)
                if f.startswith("metadata_") and f.endswith(".json")
            ]

            for filename in files:
                file_path = os.path.join(self.output_dir, filename)

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                except Exception:
                    continue

                upload_status = payload.get("upload_status", {})

                if platform:
                    platform_key = platform.lower().strip()

                    if platform_key not in upload_status:
                        continue

                    if not upload_status[platform_key].get("uploaded", False):
                        pending.append(payload)

                else:
                    for platform_name, status in upload_status.items():
                        if not status.get("uploaded", False):
                            pending.append(payload)
                            break

            return pending

        except Exception as e:
            print(f"❌ [METADATA STORAGE] Erro ao listar uploads pendentes: {e}")
            return []
