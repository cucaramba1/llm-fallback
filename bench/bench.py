"""Замер бесплатных моделей на реальных записях Reels Radar (только чтение radar.db, без кадров).

Запуск: python bench.py <model> <out.jsonl>
"""
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/Users/cucaramba/Claude Code")
sys.path.insert(0, str(ROOT / "reels-radar"))
sys.path.insert(0, str(ROOT / 'tools' / 'llm_fallback'))
import llm_fallback as lf  # noqa: E402
from reels_radar.config import load_themes  # noqa: E402
from reels_radar.vision import SCHEMA, SYSTEM, build_prompt, validate  # noqa: E402

model, out = sys.argv[1], Path(sys.argv[2])
themes = load_themes(ROOT / "reels-radar")
key = sqlite3.connect(f"file:{ROOT}/freellmapi/server/data/freeapi.db?mode=ro", uri=True).execute(
    "select value from settings where key='unified_api_key'").fetchone()[0]
db = sqlite3.connect(f"file:{ROOT}/reels-radar/data/radar.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
rows = db.execute("select * from items where status in ('written','rejected','draft') order by code").fetchall()
done = set()
if out.exists():
    done = {json.loads(l)["code"] for l in out.open()}

hint = "\n\nОтветь ТОЛЬКО JSON без markdown-ограждений, строго по схеме:\n" + json.dumps(SCHEMA, ensure_ascii=False)


def call(prompt: str) -> tuple[str, str]:
    body = json.dumps({"model": model, "max_tokens": 4000, "temperature": 0,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt + hint}]}).encode()
    err = ""
    for attempt in range(12):
        rq = urllib.request.Request("http://127.0.0.1:3001/v1/chat/completions", body,
                                    {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        wait = 10 * (attempt + 1)
        try:
            with urllib.request.urlopen(rq, timeout=180) as r:
                return json.load(r)["choices"][0]["message"].get("content") or "", ""
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="ignore")
            err = f"{e.code} {body_txt[:200]}"
            m = re.search(r'"retryAtMs":(\d+)', body_txt)
            if e.code == 429 and m:
                wait = min(1000, max(5, int(m.group(1)) / 1000 - time.time() + 5))
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
        time.sleep(wait)
    return "", err


with out.open("a") as f:
    for r in rows:
        if r["code"] in done:
            continue
        prompt = build_prompt(r["code"], r["caption"], r["transcript"] or "", r["ocr_text"] or "", [], themes, r["folder"])
        t0 = time.time()
        txt, err = call(prompt)
        if not txt:
            print('skip', r['code'], err[:120], flush=True)
            continue
        rec = {"code": r["code"], "status": r["status"], "decision": r["decision"], "ref_theme": r["theme"],
               "ref_kind": r["kind"], "ref_purposes": r["purposes"], "sec": round(time.time() - t0, 1), "err": err}
        if txt:
            m = re.search(r"\{.*\}", txt, re.S)
            try:
                raw = json.loads(m.group(0), strict=False) if m else None
            except ValueError:
                raw = None
            rec["json_ok"] = isinstance(raw, dict) and lf.conforms(raw, SCHEMA)
            if rec["json_ok"]:
                v = validate(raw, themes)
                rec.update(theme=v.theme, raw_theme=raw.get("theme"), kind=v.kind, purposes=v.purposes,
                           skip=v.skip, title=v.title, summary=v.summary[:300])
        else:
            rec["json_ok"] = False
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        time.sleep(4)
