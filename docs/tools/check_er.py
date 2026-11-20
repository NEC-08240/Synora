"""Check docs/er-diagram.mmd against docs/database/database-design.md (section 4 tables, section 2 stores).
Usage: python docs/tools/check_er.py   (exit code 1 on any mismatch)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
doc = (ROOT / "docs/database/database-design.md").read_text(encoding="utf-8")
mmd = (ROOT / "docs/er-diagram.mmd").read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from gen_er import STORES, parse  # noqa: E402

errors = []
ents, rels = parse(ROOT / "docs/er-diagram.mmd")

# section 4: entity -> [(attr, type, constraint)]
sec4 = doc[doc.index("## 4. Entity Definitions"):doc.index("## 5. Integrity")]
spec = {}
for m in re.finditer(r"#### (\w+)\n\| Attribute.*?\n\|---.*?\n((?:\|.*\n)+)", sec4):
    rows = []
    for ln in m.group(2).strip().splitlines():
        c = [x.strip() for x in ln.strip("|").split("|")]
        rows.append((c[0], c[1], c[2]))
    spec[m.group(1)] = rows

if set(spec) != set(ents):
    errors.append(f"entity set differs: doc-only={set(spec)-set(ents)} er-only={set(ents)-set(spec)}")
for n in sorted(set(spec) & set(ents)):
    d = [(a, t.replace(" ", "")) for a, t, _ in spec[n]]
    e = [(a, t.replace(" ", "")) for t, a, *_ in ents[n]]
    # normalise: doc type "NVARCHAR(MAX)" etc. vs diagram identical strings
    if [a for a, _ in d] != [a for a, _ in e]:
        errors.append(f"{n}: attribute list/order differs\n  doc={[a for a,_ in d]}\n  er ={[a for a,_ in e]}")
        continue
    for (a, dt), (_, et) in zip(d, e):
        if dt.upper() != et.upper():
            errors.append(f"{n}.{a}: type doc={dt} er={et}")
    for (a, _, cons), (_, _, _k, key, _nt) in zip(spec[n], [(0, 0, 0, x[2], x[3]) for x in ents[n]]):
        # keys: PK / FK in doc constraint text must appear in diagram key tag
        has_pk, has_fk = bool(re.search(r"\bPK\b", cons)), "FK" in cons
        tag = key or ""
        if has_pk != ("PK" in tag) or has_fk != ("FK" in tag):
            errors.append(f"{n}.{a}: key doc='{cons}' er='{tag}'")

# section 2: store membership
sec2 = doc[doc.index("## 2. DFD Data Store Mapping"):doc.index("## 3. Entity List")]
for title, _c, _t, rows in STORES:
    store = title.split()[0]
    in_gen = {n for r in rows for n in r}
    line = re.search(rf"\*\*{store}[^\n]*|\|\s*{store}\b[^\n]*", sec2)
    if not line:
        errors.append(f"{store} not found in section 2")
        continue
    for n in in_gen:
        if n not in line.group(0):
            errors.append(f"{n} not listed under {store} in section 2")

# every relationship endpoint exists
for a, _la, _ra, b, _lab in rels:
    for n in (a, b):
        if n not in ents:
            errors.append(f"relationship references unknown entity {n}")

print(f"entities in doc={len(spec)} er={len(ents)} relationships={len(rels)}")
print("OK" if not errors else "\n".join(errors))
sys.exit(1 if errors else 0)
