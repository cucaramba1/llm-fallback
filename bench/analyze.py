import glob
import json
import os

SP = os.path.dirname(os.path.abspath(__file__))
for path in sorted(glob.glob(f"{SP}/res_*.jsonl")):
    rs = [json.loads(l) for l in open(path)]
    n = len(rs)
    ok = [r for r in rs if r.get("json_ok")]
    errs = [r for r in rs if r.get("err")]
    written = [r for r in ok if r["status"] in ("written", "draft")]
    rej = [r for r in ok if r["status"] == "rejected"]
    th = sum(r["theme"] == r["ref_theme"] for r in written)
    kd = sum(r["kind"] == r["ref_kind"] for r in written)
    # purposes: совпадение по пересечению (Jaccard >= 0.5) с эталонными
    def jac(r):
        a, b = set(r["purposes"]), set((r["ref_purposes"] or "").split(","))
        return len(a & b) / max(1, len(a | b))
    pu = sum(jac(r) >= 0.5 for r in written)
    # решение «брать»: модель не skip на written и skip на rejected
    take_ok = sum(not r["skip"] for r in written)
    rej_skip = sum(r["skip"] for r in rej)
    avg = sum(r["sec"] for r in rs) / max(1, n)
    print(f"{os.path.basename(path)}: n={n} json_ok={len(ok)} err={len(errs)} avg={avg:.1f}s")
    if written:
        w = len(written)
        print(f"  written({w}): тема={th/w:.0%} вид={kd/w:.0%} purposes>=0.5={pu/w:.0%} не-skip={take_ok/w:.0%}")
    if rej:
        print(f"  rejected({len(rej)}): модель сама скипнула={rej_skip/len(rej):.0%}")
    if errs:
        print("  err пример:", errs[0]["err"][:150])
