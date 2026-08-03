"""Diagnostico do juiz de visao (Gemini) do gate de relevancia de trends.

Replica exatamente a chamada de _gemini_vision_judge, porem IMPRIME o erro real
(que o servico engole com `except Exception: continue`). Nao imprime segredos.

Uso:
  .\.venv-dash\Scripts\python.exe tools\diag_vision_judge.py
"""
import os
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, os.getcwd())

# Carrega o .env (sem imprimir segredos).
try:
    from dotenv import load_dotenv

    load_dotenv()
    print("[env] .env carregado via python-dotenv")
except Exception:
    # Fallback manual: le KEY=VALUE sem imprimir os valores.
    try:
        with open(".env", "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        print("[env] .env carregado manualmente")
    except Exception as e:
        print(f"[env] nao consegui carregar .env: {e}")

print("[env] GEMINI_API_KEY presente:", bool((os.getenv("GEMINI_API_KEY") or "").strip()))
print("[env] GOOGLE_API_KEY presente:", bool((os.getenv("GOOGLE_API_KEY") or "").strip()))
print("[env] GEMINI_MODEL:", os.getenv("GEMINI_MODEL"))
print("[env] GEMINI_MODEL_FALLBACK:", os.getenv("GEMINI_MODEL_FALLBACK"))

# 1) Gera um frame JPEG de teste com ffmpeg (imageio-ffmpeg).
try:
    import imageio_ffmpeg

    ff = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as e:
    print(f"[ffmpeg] imageio-ffmpeg indisponivel: {e}")
    ff = "ffmpeg"

tmp = tempfile.mkdtemp(prefix="diag_vision_")
img = os.path.join(tmp, "t.jpg")
try:
    subprocess.run(
        [ff, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=blue:s=512x288", "-frames:v", "1", img],
        check=True, timeout=30,
    )
    with open(img, "rb") as f:
        data = f.read()
    print("[frame] JPEG de teste:", len(data), "bytes")
except Exception as e:
    print(f"[frame] falha ao gerar JPEG de teste: {e}")
    data = None

# 2) Cliente Gemini do projeto.
try:
    from app.automation.authorized_broll_renderer import _gemini_client

    client = _gemini_client()
    print("[client] _gemini_client() ->", type(client).__name__ if client else None)
except Exception:
    print("[client] erro ao obter cliente:")
    traceback.print_exc()
    client = None

if client is None:
    print("\n>>> RESULTADO: cliente Gemini indisponivel (sem chave ou import falhou).")
    sys.exit(0)

# 3) Lista de modelos que o projeto tentaria.
models = []
for name in (
    os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    os.getenv("GEMINI_MODEL_FALLBACK", "gemini-flash-latest"),
):
    name = (name or "").strip()
    if name and name not in models:
        models.append(name)
print("[models] tentaria:", models)

# 4) Tenta importar types e montar contents (string + imagem).
try:
    from google.genai import types

    print("[types] google.genai.types OK; from_bytes:", hasattr(types.Part, "from_bytes"))
except Exception:
    print("[types] falha ao importar google.genai.types:")
    traceback.print_exc()
    types = None

prompt = (
    'You are a strict judge. Reply ONLY JSON '
    '{"relevant": true|false, "confidence": 0-100, "reason": "short"}.'
)

contents = [prompt]
if types is not None and data is not None:
    try:
        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        print("[contents] imagem anexada; itens:", len(contents))
    except Exception:
        print("[contents] falha em types.Part.from_bytes:")
        traceback.print_exc()

# 5) Chama cada modelo IMPRIMINDO o erro real.
for model in models:
    print(f"\n=== generate_content(model={model!r}) ===")
    try:
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config={
                "temperature": 0.0,
                "max_output_tokens": 300,
                "response_mime_type": "application/json",
            },
        )
        print("  resp.text:", repr(getattr(resp, "text", None)))
        pf = getattr(resp, "prompt_feedback", None)
        if pf:
            print("  prompt_feedback:", pf)
        cands = getattr(resp, "candidates", None)
        if cands:
            for i, c in enumerate(cands):
                print(f"  candidate[{i}].finish_reason:", getattr(c, "finish_reason", None))
    except Exception:
        print("  EXCECAO REAL:")
        traceback.print_exc()

# 6) Tenta listar modelos disponiveis (nomes validos), sem segredos.
print("\n=== modelos disponiveis na conta (client.models.list) ===")
try:
    count = 0
    for m in client.models.list():
        name = getattr(m, "name", None)
        actions = getattr(m, "supported_actions", None)
        print("  -", name, "|", actions)
        count += 1
        if count >= 40:
            print("  ... (cortado)")
            break
    if count == 0:
        print("  (nenhum modelo retornado)")
except Exception:
    print("  falha ao listar modelos:")
    traceback.print_exc()
