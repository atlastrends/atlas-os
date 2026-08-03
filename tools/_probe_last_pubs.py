"""Read-only diagnostic: list the most recent publications joined with video
assets, so we can see what was actually posted (reel vs affiliate) and whether
the title matches the video file. Safe to delete."""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = """
        SELECT p.id AS pid, p.platform, p.status, p.created_at, p.external_url,
               p.video_asset_id AS aid, va.kind AS vkind, va.title, va.topic,
               va.video_path
        FROM publications p
        JOIN video_assets va ON va.id = p.video_asset_id
        ORDER BY p.created_at DESC
        LIMIT 16
    """
    for r in con.execute(q):
        path = (r["video_path"] or "")
        fname = path.replace("\\", "/").rsplit("/", 1)[-1]
        title = (r["title"] or "")[:50]
        topic = (r["topic"] or "")[:40]
        print(
            f'pub#{r["pid"]:<4} {r["platform"]:<9} {r["status"]:<11} '
            f'{str(r["created_at"])[:19]}  asset#{r["aid"]:<4} {r["vkind"]:<9} '
            f'\n     title = {title!r}\n     topic = {topic!r}\n     file  = {fname[:55]!r}'
        )
    con.close()


if __name__ == "__main__":
    main()
