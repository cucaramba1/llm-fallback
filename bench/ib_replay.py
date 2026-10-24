"""Реплей разбора Idea Bot бесплатными моделями на готовых идеях (только чтение ideas.db и vault)."""
import asyncio, json, sqlite3, sys, time
from pathlib import Path
ROOT = Path("/Users/cucaramba/Claude Code")
sys.path.insert(0, str(ROOT / "idea-bot")); sys.path.insert(0, str(ROOT / "tools" / "llm_fallback"))
import llm_fallback as lf
from ideabot import brain as B
from ideabot.config import load_settings
from ideabot.models import Incoming
from ideabot.vault.index import build_index, render_for_prompt

model = sys.argv[1]
out = Path(sys.argv[2])
mode = sys.argv[3]
s = load_settings()
index = build_index(s)
seen = {"prompt_chars": 0}

async def fake_claude(s_, prompt, *, system, schema=None, tools=(), add_dirs=(), timeout):
    seen["prompt_chars"] = len(prompt) + len(system)
    return await lf.run_router(prompt, system=system, schema=schema, timeout=timeout, model=model)

B.run_claude = fake_claude
brain = B.Brain(s)
db = sqlite3.connect(f"file:{ROOT}/idea-bot/data/ideas.db?mode=ro", uri=True)
rows = db.execute("select id,payload,analysis from ideas where analysis is not null order by id").fetchall()
res = []
for id_, payload, ana in rows:
    ref = json.loads(ana)
    inc = Incoming.from_json(payload)
    rec = {"id": id_, "ref_type": ref.get("type"), "ref_theme": ref.get("theme"), "ref_score": ref.get("score"),
           "ref_links": [l["l2"] if isinstance(l, dict) else l for l in ref.get("links", [])]}
    t0 = time.time()
    try:
        if mode == "pick":
            a = B.validate(ref, index, s, [], [])
            names = [l["l2"] for l in ref.get("links", []) if isinstance(l, dict) and l["l2"] in index.l2]
            got = asyncio.run(brain.pick_l3(a, names, index))
            rl = {l["l2"]: l.get("l3") for l in ref.get("links", []) if isinstance(l, dict)}
            rec.update(ok=True, pairs=[(l.l2, l.l3, rl.get(l.l2)) for l in got])
            raise StopIteration
        a = asyncio.run(brain.analyze(inc, index))
        rec.update(ok=True, type=a.type, theme=a.theme, score=a.score, links=[l.l2 for l in a.links],
                   body_len=len(a.body_md), ref_body_len=len(ref.get("body_md", "")), title=a.title)
    except StopIteration:
        pass
    except Exception as e:
        rec.update(ok=False, err=str(e)[:200])
    rec["prompt_chars"] = seen["prompt_chars"]; rec["sec"] = round(time.time() - t0, 1)
    res.append(rec)
    print(json.dumps(rec, ensure_ascii=False)[:300], flush=True)
    time.sleep(8)
out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
