from pathlib import Path
import re
import py_compile


root = Path("/atlas")
pipeline_path = root / "app/automation/real_amazon_pipeline.py"

database_replacement = (
    root / "app/automation/_database_replacement.txt"
).read_text(encoding="utf-8")

run_replacement = (
    root / "app/automation/_run_pipeline_replacement.txt"
).read_text(encoding="utf-8")

source = pipeline_path.read_text(encoding="utf-8")

source, database_count = re.subn(
    r"(?ms)^def find_database_products\(.*?(?=^def discover_products\()",
    lambda match: database_replacement,
    source,
    count=1,
)

if database_count != 1:
    print("AVISO: find_database_products nao foi localizada.")

source, run_count = re.subn(
    r"(?ms)^def run_pipeline\(.*?(?=^def main\()",
    lambda match: run_replacement,
    source,
    count=1,
)

if run_count != 1:
    raise RuntimeError(
        "Nao foi possivel substituir run_pipeline."
    )

source = source.replace(
    '"voice": "pt-BR-FranciscaNeural"',
    '"voice": "pt-BR-AntonioNeural"',
)

source = source.replace(
    '"voice": "en-US-JennyNeural"',
    '"voice": "en-US-GuyNeural"',
)

old_voice = '''        "--voice", MARKETS[product.marketplace_code]["voice"],
        "--text", text,
'''

new_voice = '''        "--voice", MARKETS[product.marketplace_code]["voice"],
        "--rate", "+5%",
        "--pitch", "-2Hz",
        "--text", text,
'''

if old_voice in source:
    source = source.replace(
        old_voice,
        new_voice,
        1,
    )

pipeline_path.write_text(
    source,
    encoding="utf-8",
)

py_compile.compile(
    str(pipeline_path),
    doraise=True,
)

py_compile.compile(
    str(
        root
        / "app/automation/authorized_broll_renderer.py"
    ),
    doraise=True,
)

print("PATCH_PIPELINE=OK")
print("SINTAXE=OK")