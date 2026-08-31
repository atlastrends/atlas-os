from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.luma_motion_transfer_service import LumaMotionTransferService
from app.core.env_loader import load_env


EPISODE = ROOT / "stories" / "_visual_tests" / "first_episode_120s"
MANIFEST = EPISODE / "luma_motion_pilot.json"
load_env()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Testa Luma Modify Video/Adhere com um guia literal de 5s."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida e exibe a requisicao sem consumir creditos.",
    )
    args = parser.parse_args()

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in ("guide_video_path", "first_frame_path", "prompt", "mode", "model"):
        if not str(data.get(key) or "").strip():
            raise RuntimeError(f"Campo ausente no manifesto Luma: {key}")
    for key in ("guide_video_path", "first_frame_path"):
        if not Path(data[key]).is_file():
            raise FileNotFoundError(data[key])

    if args.dry_run:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    service = LumaMotionTransferService(log=print)
    output_path = EPISODE / "luma_motion_pilot_adhere.mp4"
    result = service.run(
        guide_video_path=data["guide_video_path"],
        first_frame_path=data["first_frame_path"],
        prompt=data["prompt"],
        output_path=str(output_path),
        mode=data["mode"],
        model=data["model"],
    )
    print(
        json.dumps(
            {
                "generation_id": result.generation_id,
                "output_url": result.output_url,
                "output_path": result.output_path,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
