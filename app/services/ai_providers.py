# ============================================================
# ATLAS OS - ai_providers.py
# Cadeia multi-provedor para geracao de TEXTO (protocolo OpenAI).
#
# Quando Groq e Gemini estouram a cota (429), o motor cai para OpenAI
# (ChatGPT), OpenRouter, DeepSeek, Mistral, Cerebras ou Together — o que
# tiver chave no .env. Assim a producao NAO trava. Todos esses provedores
# falam o mesmo protocolo (chat.completions), entao usamos o SDK da OpenAI
# mudando so a base_url + a chave.
# ============================================================

import os

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


# (label, env da chave, base_url [None = api.openai.com], env dos modelos, modelos padrao)
_PROVIDER_SPECS = [
    ("OpenAI", "OPENAI_API_KEY", None,
        "ATLAS_OPENAI_MODELS", ["gpt-4o-mini", "gpt-4o"]),
    ("OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
        "ATLAS_OPENROUTER_MODELS", ["meta-llama/llama-3.3-70b-instruct"]),
    ("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1",
        "ATLAS_DEEPSEEK_MODELS", ["deepseek-chat"]),
    ("Mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1",
        "ATLAS_MISTRAL_MODELS", ["mistral-small-latest", "mistral-large-latest"]),
    ("Cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1",
        "ATLAS_CEREBRAS_MODELS", ["llama-3.3-70b"]),
    ("Together", "TOGETHER_API_KEY", "https://api.together.xyz/v1",
        "ATLAS_TOGETHER_MODELS", ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]),
    ("SambaNova", "SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1",
        "ATLAS_SAMBANOVA_MODELS", ["Meta-Llama-3.3-70B-Instruct"]),
]


def _models_from_env(env_name: str, defaults: list) -> list:
    raw = os.getenv(env_name, "")
    if raw and raw.strip():
        return [m.strip() for m in raw.split(",") if m.strip()]
    return list(defaults)


def build_extra_providers(engine_label: str = "AI") -> list:
    """Monta a lista de provedores extras (alem de Groq/Gemini) que tem chave.

    Retorna: [{"label": str, "client": OpenAI, "models": [str, ...]}]
    Cada provedor so entra se a sua *_API_KEY existir no ambiente/.env.
    """
    providers: list = []

    if OpenAI is None:
        return providers

    for label, key_env, base_url, models_env, default_models in _PROVIDER_SPECS:
        key = os.getenv(key_env)
        if not key or not key.strip():
            continue

        try:
            if base_url:
                client = OpenAI(api_key=key.strip(), base_url=base_url)
            else:
                client = OpenAI(api_key=key.strip())
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ [{engine_label}] Falha ao iniciar provedor {label}: {exc}")
            continue

        models = _models_from_env(models_env, default_models)
        providers.append({"label": label, "client": client, "models": models})
        print(f"✅ [{engine_label}] Provedor extra pronto: {label} ({', '.join(models)})")

    return providers


# Modelos de VISAO (multimodais) por provedor — usados pelo juiz de visao quando
# o Gemini fica sem cota. So provedores/modelos que ENXERGAM imagem.
_VISION_SPECS = [
    ("OpenAI", "OPENAI_API_KEY", None,
        "ATLAS_OPENAI_VISION_MODELS", ["gpt-4o-mini", "gpt-4o"]),
    ("OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
        "ATLAS_OPENROUTER_VISION_MODELS", ["openai/gpt-4o-mini"]),
]


def build_vision_providers(engine_label: str = "AI") -> list:
    """Como build_extra_providers, mas so com modelos que ENXERGAM imagem
    (gpt-4o etc.), para o juiz de visao usar quando o Gemini estiver sem cota."""
    providers: list = []

    if OpenAI is None:
        return providers

    for label, key_env, base_url, models_env, default_models in _VISION_SPECS:
        key = os.getenv(key_env)
        if not key or not key.strip():
            continue

        try:
            if base_url:
                client = OpenAI(api_key=key.strip(), base_url=base_url)
            else:
                client = OpenAI(api_key=key.strip())
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ [{engine_label}] Falha ao iniciar visao {label}: {exc}")
            continue

        models = _models_from_env(models_env, default_models)
        providers.append({"label": label, "client": client, "models": models})
        print(f"✅ [{engine_label}] Visao extra pronta: {label} ({', '.join(models)})")

    return providers
