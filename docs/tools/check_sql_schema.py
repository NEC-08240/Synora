"""Compare a LIVE SQL Server schema (columns, order, types, nullability) with database-design.md section 4.
Usage: python docs/tools/check_sql_schema.py "localhost\\SQL2022" SynoraV1   (needs sqlcmd + Windows auth)
Exit code 1 on any mismatch. Nullability: doc says "NOT NULL"/PK => NOT NULL, "NULL" => NULL;
FK columns without an explicit mark are reported as unchecked, not failed.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
server, db = sys.argv[1], sys.argv[2]
doc = (ROOT / "docs/database/database-design.md").read_text(encoding="utf-8")
sec4 = doc[doc.index("## 4. Entity Definitions"):doc.index("## 5. Integrity")]
spec = {}
for m in re.finditer(r"#### (\w+)\n\| Attribute.*?\n\|---.*?\n((?:\|.*\n)+)", sec4):
    spec[m.group(1)] = [[x.strip() for x in ln.strip("|").split("|")] for ln in m.group(2).strip().splitlines()]

q = ("SET NOCOUNT ON; SELECT t.name, c.name, ty.name, c.max_length, c.precision, c.scale, c.is_nullable "
     "FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id "
     "JOIN sys.types ty ON ty.user_type_id=c.user_type_id ORDER BY t.name, c.column_id")
out = subprocess.run(["sqlcmd", "-S", server, "-E", "-C", "-d", db, "-h", "-1", "-W", "-s", "|", "-Q", q],
                     capture_output=True, text=True, check=True).stdout
live = {}
for ln in out.splitlines():
    p = ln.split("|")
    if len(p) != 7:
        continue
    t, c, ty, ml, pr, sc, nul = p
    ml, pr, sc = int(ml), int(pr), int(sc)
    if ty == "nvarchar":
        ty = "NVARCHAR(MAX)" if ml == -1 else f"NVARCHAR({ml // 2})"
    elif ty == "decimal":
        ty = f"DECIMAL({pr},{sc})"
    else:
        ty = ty.upper()
    live.setdefault(t, []).append((c, ty, nul == "1"))

errs, unchecked = [], 0
if set(live) != set(spec):
    errs.append(f"table set differs: doc-only={set(spec) - set(live)} live-only={set(live) - set(spec)}")
for t in sorted(set(live) & set(spec)):
    if [c for c, *_ in live[t]] != [r[0] for r in spec[t]]:
        errs.append(f"{t}: column list/order differs\n  doc ={[r[0] for r in spec[t]]}\n  live={[c for c, *_ in live[t]]}")
        continue
    for (c, ty, nullable), r in zip(live[t], spec[t]):
        if ty != r[1].replace(" ", "").upper():
            errs.append(f"{t}.{c}: type doc={r[1]} live={ty}")
        cons = r[2].upper()
        if "NOT NULL" in cons or re.match(r"^PK", cons):
            want = False
        elif re.search(r"(^|[ ,])NULL\b", cons):
            want = True
        else:
            unchecked += 1
            continue
        if nullable != want:
            errs.append(f"{t}.{c}: nullable doc={want} live={nullable}")
n_cols = sum(len(v) for v in live.values())
print(f"tables doc={len(spec)} live={len(live)}; columns live={n_cols}; nullability unchecked={unchecked}")
print("\n".join(errs) if errs else "OK")
sys.exit(1 if errs else 0)
