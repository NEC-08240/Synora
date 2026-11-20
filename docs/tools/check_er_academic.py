"""Validate docs/er-diagram-academic.mmd against the technical docs/er-diagram.mmd (the master).
Checks: same 20 entities, identical 35 relationships (endpoints, symbols), all PK/FK kept with same tags,
every attribute is a subset of the master's. Exits 1 on any mismatch. Usage: python docs/tools/check_er_academic.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_er import parse  # noqa: E402

D = Path(__file__).resolve().parents[2] / "docs"
te, tr = parse(D / "er-diagram.mmd")
ae, ar = parse(D / "er-diagram-academic.mmd")
bad = []
if set(te) != set(ae):
    bad.append(f"entity set differs: {set(te) ^ set(ae)}")
pkfk = lambda k: ",".join(x for x in re.split(r"[ ,]+", k or "") if x in ("PK", "FK"))  # UK tags dropped by design
key = lambda r: (r[0], r[1], r[2], r[3])  # noqa: E731
if sorted(map(key, tr)) != sorted(map(key, ar)):
    bad.append("relationship endpoints/cardinalities differ")
for n in te:
    tm = {a: k for _t, a, k, _ in te[n]}
    am = {a: k for _t, a, k, _ in ae.get(n, [])}
    for a, k in am.items():
        if a not in tm or pkfk(k) != pkfk(tm[a]):
            bad.append(f"{n}.{a} not in master or key tag differs")
    for a, k in tm.items():
        if k and ("PK" in k or "FK" in k) and a not in am:
            bad.append(f"{n}.{a} ({k}) key column missing from academic view")
print(f"entities {len(ae)}/{len(te)} relationships {len(ar)}/{len(tr)}", "OK" if not bad else "FAIL")
print("\n".join(bad))
sys.exit(1 if bad else 0)
