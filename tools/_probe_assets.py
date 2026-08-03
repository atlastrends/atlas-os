"""Read-only: dump caption/description/narration + background provenance for a
few recent assets so we can see if audio/description matches the subject."""
import json
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def _p(label, value, limit=300):
    text = "" if value is None else str(value)
    print(f"   {label}: {text[:limit]!r}")


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for aid in (406, 405, 404, 403):
        row = con.execute(
            "SELECT id,kind,external_key,title,topic,video_path,metadata_path,payload "
            "FROM video_assets WHERE id=?",
            (aid,),
        ).fetchone()
        if not row:
            print(f"asset#{aid}: NOT FOUND\n")
            continue
        print(f"=== asset#{row['id']} [{row['kind']}] external_key={row['external_key']!r} ===")
        _p("title", row["title"])
        _p("topic", row["topic"])
        _p("video_path", row["video_path"])
        _p("metadata_path", row["metadata_path"])
        payload = {}
        if row["payload"]:
            try:
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            except Exception as exc:
                print(f"   payload parse error: {exc}")
        if isinstance(payload, dict):
            for key in ("narration", "script", "caption", "description", "hook", "trend_source", "background", "broll", "media_provenance"):
                if key in payload:
                    _p(f"payload.{key}", payload[key], 400)
            plats = payload.get("platforms")
            if isinstance(plats, dict):
                for pname, pv in plats.items():
                    if isinstance(pv, dict):
                        _p(f"platforms.{pname}.caption", pv.get("caption"), 200)
        print()
    con.close()


if __name__ == "__main__":
    main()
