"""Configuracoes do robo de direct (lidas de variaveis de ambiente).

No Render voce cadastra essas variaveis na aba "Environment". NADA de senha
fica no codigo. Os valores abaixo sao so os "padroes" quando a variavel nao
existe.
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# --- Meta (Instagram / Facebook) ---
META_APP_SECRET = _env("META_APP_SECRET")
META_ACCESS_TOKEN = _env("META_ACCESS_TOKEN")
# Voce inventa esse valor e coloca IGUAL aqui e no painel do Meta.
META_VERIFY_TOKEN = _env("META_VERIFY_TOKEN", "atlas-bot-verify")
GRAPH_VERSION = _env("META_GRAPH_VERSION", "v21.0")

# --- IA (Groq) ---
GROQ_API_KEY = _env("GROQ_API_KEY")
GROQ_MODEL = _env("GROQ_MODEL", "llama-3.1-8b-instant")

# --- Lista de produtos (gerada pela bio, publicada no GitHub Pages) ---
PRODUCTS_JSON_URL = _env(
    "PRODUCTS_JSON_URL",
    "https://atlastrends.github.io/atlas-os/produtos.json",
)
PRODUCTS_TTL_SECONDS = int(_env("PRODUCTS_TTL_SECONDS", "300") or "300")

# --- Contato por email (quando a IA nao souber responder) ---
SUPPORT_EMAIL = _env("SUPPORT_EMAIL", "atlastrendbr@gmail.com")

GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
