"""Testa a CADEIA de modelos do juiz de visao (apos trocar para 2.x flash).

Gera um frame de teste e chama trend_relevance_service._gemini_vision_judge
diretamente, imprimindo o resultado e o ultimo erro capturado. Nao imprime
segredos.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from app.services import trend_relevance_service as trs

print("[chain] modelos de visao:", trs._vision_model_chain())

# Frame de teste (azul) via ffmpeg.
try:
    import imageio_ffmpeg

    ff = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    ff = "ffmpeg"

tmp = tempfile.mkdtemp(prefix="diag_chain_")
img = os.path.join(tmp, "t.jpg")
subprocess.run(
    [ff, "-y", "-loglevel", "error", "-f", "lavfi",
     "-i", "color=c=blue:s=512x288", "-frames:v", "1", img],
    check=True, timeout=30,
)
with open(img, "rb") as f:
    data = f.read()
print("[frame] bytes:", len(data))

prompt = (
    "Look at the image. Reply ONLY JSON "
    '{"relevant": true|false, "confidence": 0-100, "reason": "short"}.'
)
raw = trs._gemini_vision_judge(prompt, [data])
print("[judge] raw:", repr(raw))
print("[judge] ultimo erro:", repr(trs._LAST_JUDGE_ERROR))
if raw:
    print("[judge] parse:", trs._parse_judge(raw))
    print("\n>>> RESULTADO: juiz de visao FUNCIONANDO.")
else:
    print("\n>>> RESULTADO: juiz ainda indisponivel — ver erro acima.")
