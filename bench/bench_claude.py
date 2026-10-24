"""Замер Claude-моделей (haiku/sonnet) на записях Reels Radar, текст без кадров. Запуск: bench_claude.py <model> <out.jsonl> <stride>"""
import asyncio, json, os, sqlite3, sys, tempfile
from pathlib import Path
ROOT = Path("/Users/cucaramba/Claude Code")
sys.path.insert(0, str(ROOT / "reels-radar"))
model, out, stride = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
os.environ["CLAUDE_BATCH_MODEL"] = model
from reels_radar.claude import run_claude  # noqa: E402
from reels_radar.config import load_themes  # noqa: E402
from reels_radar.vision import SCHEMA, SYSTEM, build_prompt, validate  # noqa: E402

class S:
    claude_bin = "/Users/cucaramba/.npm-global/bin/claude"
    data_dir = Path(tempfile.mkdtemp())
    claude_timeout = 300

themes = load_themes(ROOT / "reels-radar")
db = sqlite3.connect(f"file:{ROOT}/reels-radar/data/radar.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
rows = db.execute("select * from items where status in ('written','rejected','draft') order by code").fetchall()[::stride]
done = {json.loads(l)["code"] for l in out.open()} if out.exists() else set()
sem = asyncio.Semaphore(3)

async def one(r, f):
    if r["code"] in done:
        return
    prompt = build_prompt(r["code"], r["caption"], r["transcript"] or "", r["ocr_text"] or "", [], themes, r["folder"])
    rec = {"code": r["code"], "status": r["status"], "decision": r["decision"], "ref_theme": r["theme"],
           "ref_kind": r["kind"], "ref_purposes": r["purposes"], "model": model}
    async with sem:
        try:
            raw = await run_claude(S, prompt, system=SYSTEM, schema=SCHEMA, timeout=300)
            v = validate(raw, themes)
            rec.update(json_ok=True, theme=v.theme, kind=v.kind, purposes=v.purposes, skip=v.skip, title=v.title)
        except Exception as e:  # noqa: BLE001
            rec.update(json_ok=False, err=str(e)[:200])
    f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()

async def main():
    with out.open("a") as f:
        await asyncio.gather(*(one(r, f) for r in rows))

asyncio.run(main())
