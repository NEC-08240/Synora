"""Check the Chen ER diagram against the locked master (docs/er-diagram.mmd) and database-design.md.
Usage: python docs/tools/check_er_chen.py   (exit 1 on any mismatch)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_er import parse  # noqa: E402
from gen_er_chen import FK_COLS, attrs_of, shown  # noqa: E402

D = Path(__file__).resolve().parents[1]
ents, rels = parse(D / "er-diagram.mmd")
svg = (D / "er-diagram-chen.svg").read_text(encoding="utf-8")
meta = json.loads((D / "er-diagram-chen.json").read_text(encoding="utf-8"))["rels"]
design = (D / "database/database-design.md").read_text(encoding="utf-8")
errs = []

names = re.findall(r'font-size="15" font-weight="700" text-anchor="middle" fill="#111">(\w+)</text>', svg)
if sorted(names) != sorted(ents) or len(names) != 20:
    errs.append(f"entities in SVG {len(names)} vs master {len(ents)}: {set(ents) ^ set(names)}")
if len(re.findall(r'L[\d.]+ [\d.]+ L[\d.]+ [\d.]+ Z" fill="#fff"', svg)) != 35:
    errs.append("diamond count != 35")
for n in ents:
    if f"### {n}" not in design and f"`{n}`" not in design:
        errs.append(f"{n} missing from database-design.md")
for i, (a, la, ra, b, lab) in enumerate(rels):
    if meta[i][:2] != [a, b]:
        errs.append(f"rel {i}: {meta[i][:2]} != {[a, b]}")
    fk = {x for _t, x, k, _n in ents[b] if k and "FK" in k}
    if not set(FK_COLS[i].split("+")) <= fk:
        errs.append(f"rel {i} {a}->{b}: FK {FK_COLS[i]} not an FK on {b}")
    expect = "1:1" if (a, b) == ("Activities", "SqlTaskSpecs") else "1:N"
    if expect == "1:1" and ra != "o|":
        errs.append(f"rel {i} master cardinality {la}--{ra} is not 1:1")
    if expect == "1:N" and ra not in ("o{", "|{"):
        errs.append(f"rel {i} master cardinality {la}--{ra} is not 1:N")
for n in ents:
    pk, other = attrs_of(ents, n)
    cols = {a for _t, a, _k, _n in ents[n]}
    if not pk or not set(pk + other) <= cols:
        errs.append(f"{n}: PK/attr mismatch {pk} {other}")
    pk_oval = shown(ents, n)[0][0]
    if f"text-decoration=\"underline\" font-weight=\"600\">{pk_oval}<" not in svg:
        errs.append(f"{n}: PK oval {pk_oval} not underlined")
    if any(f">{k}</text><" in svg and k in other for k in ()):
        pass
for bad in ("Course", "BatchEnrollment", "Conversation", "HiddenTestCase", "QuizAnswerOption"):
    if re.search(rf">{bad}<", svg):
        errs.append(f"excluded entity {bad} present")
print("entities=%d relationships=%d" % (len(names), len(rels)), "OK" if not errs else "FAIL")
print("\n".join(errs))
sys.exit(1 if errs else 0)
