"""Render docs/er-diagram.mmd into docs/er-diagram.svg, grouped by DFD store D1-D5.

Usage: python docs/tools/gen_er.py docs/er-diagram.mmd docs/er-diagram.svg
The .mmd is the single source for entities, columns and relationships; only the
layout (STORES) is defined here. Edges are routed orthogonally through the gutters
between rows and through side lanes so no line crosses an entity box.
"""
import re
import sys
from xml.sax.saxutils import escape as esc

STORES = [  # (title, colour, tint, rows of entity names)
    ("D1 User Data", "#0f766e", "#ecfdf5", [["Roles", "Users", "Batches", "FacultyAssignments"]]),
    ("D2 Course Content", "#4338ca", "#eef2ff", [["Subjects", "Topics", "Lessons", "LessonResources"]]),
    ("D3 Assessment Data", "#b45309", "#fffbeb",
     [["Activities", "QuizQuestions", "QuizOptions"], ["TestCases", "SqlTaskSpecs"]]),
    ("D4 Submission Data", "#be123c", "#fff1f2",
     [["PracticeDrafts", "Submissions", "SubmissionAnswers", "TestCaseResults"]]),
    ("D5 Analytics Data", "#6d28d9", "#f5f3ff", [["LearningActivity", "StudentProgress", "Recommendations"]]),
]
BW, ROW, HEAD, GAP, MARGIN, LANE = 400, 21, 30, 130, 270, 13
TRACK, GUT_BASE, STORE_HEAD, TOP = 14, 36, 46, 100
DASHED = ("created", "authored", "assigned by", "graded")
CARD = {"||": "1", "|o": "0..1", "o|": "0..1", "o{": "0..*", "}o": "0..*", "|{": "1..*", "}|": "1..*"}


def parse(path):
    src = open(path, encoding="utf-8").read()
    ents, rels = {}, []
    for m in re.finditer(r"^\s{4}(\w+) \{\n(.*?)^\s{4}\}", src, re.S | re.M):
        rows = []
        for ln in m.group(2).strip().splitlines():
            g = re.match(r'\s*(\S+)\s+(\w+)(?:\s+(PK, FK|PK|FK|UK))?(?:\s+"([^"]*)")?', ln).groups()
            rows.append(g)
        ents[m.group(1)] = rows
    for m in re.finditer(r'^\s{4}(\w+) ([|o}{]{2})--([|o}{]{2}) (\w+) : "?([^"\n]*)"?', src, re.M):
        rels.append(m.groups())
    return ents, rels


def wrap(text, n=17):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur] if cur else lines


def main(src, dst):
    ents, rels = parse(src)
    assert len(ents) == 20 and len(rels) >= 30, (len(ents), len(rels))
    rows = [(si, r) for si, s in enumerate(STORES) for r in s[3]]
    row_of = {n: i for i, (_, r) in enumerate(rows) for n in r}
    store_of = {n: si for si, r in rows for n in r}
    width = 2 * MARGIN + 4 * BW + 3 * GAP
    box = {}  # name -> [x, y, w, h]
    for i, (_, r) in enumerate(rows):
        total = len(r) * BW + (len(r) - 1) * GAP
        x = (width - total) / 2
        for n in r:
            box[n] = [x, 0, BW, HEAD + ROW * len(ents[n])]
            x += BW + GAP
    order = {n: k for _, r in rows for k, n in enumerate(r)}

    # ---- plan edges -------------------------------------------------------
    plans = []
    for a, la, ra, b, lab in rels:
        ia, ib = row_of[a], row_of[b]
        flip = (ia, order[a]) > (ib, order[b])
        if flip:
            a, b, la, ra = b, a, ra, la
            ia, ib = ib, ia
        plans.append(dict(a=a, b=b, lab=lab,
                          ia=ia, ib=ib, la=la, ra=ra, flip=flip))
    # recompute cardinalities in original orientation after any swap
    for p, (a0, la0, ra0, b0, _) in zip(plans, rels):
        p["card_a"] = CARD[la0] if p["a"] == a0 else CARD[ra0]
        p["card_b"] = CARD[ra0] if p["b"] == b0 else CARD[la0]
        p["kind"] = ("adj" if p["ia"] == p["ib"] and abs(order[p["a"]] - order[p["b"]]) == 1
                     else "same" if p["ia"] == p["ib"] else "down")
    left_n = right_n = 0
    for p in plans:
        cx = (box[p["a"]][0] + box[p["b"]][0]) / 2 + BW / 2
        p["lane"] = None
        if p["kind"] == "down" and p["ib"] > p["ia"] + 1:
            if cx < width / 2:
                p["lane"] = MARGIN - 40 - LANE * left_n
                left_n += 1
            else:
                p["lane"] = width - MARGIN + 40 + LANE * right_n
                right_n += 1
    assert left_n < 17 and right_n < 17, (left_n, right_n)

    # ---- ports ------------------------------------------------------------
    def center(n):
        return box[n][0] + BW / 2
    side_ports = {}  # (name, 'top'|'bottom') -> list of (sortkey, plan, end)
    for p in plans:
        if p["kind"] == "adj":
            continue
        sa = "bottom"
        sb = "top" if p["kind"] == "down" else "bottom"
        tgt_a = p["lane"] if p["lane"] else center(p["b"])
        tgt_b = p["lane"] if p["lane"] else center(p["a"])
        side_ports.setdefault((p["a"], sa), []).append((tgt_a, p, "a"))
        side_ports.setdefault((p["b"], sb), []).append((tgt_b, p, "b"))
    for (n, side), lst in side_ports.items():
        lst.sort(key=lambda t: t[0])
        for k, (_, p, end) in enumerate(lst):
            p[end + "x"] = box[n][0] + BW * (k + 1) / (len(lst) + 1)
            p[end + "side"] = side

    # ---- gutter tracks (interval colouring) -------------------------------
    gut = {}  # gutter index g (below row g) -> list of [x1, x2, plan, key]
    for p in plans:
        if p["kind"] == "adj":
            continue
        if p["kind"] == "same":
            gut.setdefault(p["ia"], []).append([min(p["ax"], p["bx"]), max(p["ax"], p["bx"]), p, "t1"])
        elif p["lane"] is None:
            gut.setdefault(p["ia"], []).append([min(p["ax"], p["bx"]), max(p["ax"], p["bx"]), p, "t1"])
        else:
            gut.setdefault(p["ia"], []).append([min(p["ax"], p["lane"]), max(p["ax"], p["lane"]), p, "t1"])
            gut.setdefault(p["ib"] - 1, []).append([min(p["bx"], p["lane"]), max(p["bx"], p["lane"]), p, "t2"])
    ntracks = {}
    for g, segs in gut.items():
        segs.sort(key=lambda s: s[0])
        ends = []
        for s in segs:
            for t, e in enumerate(ends):
                if s[0] > e + 6:
                    ends[t] = s[1]
                    s[2][s[3]] = t
                    break
            else:
                s[2][s[3]] = len(ends)
                ends.append(s[1])
        ntracks[g] = len(ends)

    # ---- vertical layout --------------------------------------------------
    y = TOP + STORE_HEAD
    store_y = {}
    track_base = {}
    for i, (si, r) in enumerate(rows):
        if i == 0 or rows[i - 1][0] != si:
            store_y[si] = [y - STORE_HEAD, 0]
        h = max(box[n][3] for n in r)
        for n in r:
            box[n][1] = y
        y += h
        store_y[si][1] = y + 14
        gh = GUT_BASE + TRACK * ntracks.get(i, 0)
        track_base[i] = y + 14 + 12
        y += gh
        if i + 1 < len(rows) and rows[i + 1][0] != si:
            y += STORE_HEAD
    height = y

    # ---- draw -------------------------------------------------------------
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Arial, sans-serif">',
         f'<rect width="{width}" height="{height}" fill="#fff"/>',
         f'<text x="{width/2}" y="40" font-size="32" font-weight="700" text-anchor="middle">'
         'Synora V1 Entity-Relationship Diagram (Microsoft SQL Server, 20 entities)</text>',
         f'<text x="{width/2}" y="70" font-size="16" text-anchor="middle" fill="#475569">'
         'Grouped by DFD data store D1-D5. Source: docs/database/database-design.md. '
         'Red = cardinality (1, 0..1, 0..*). Dashed = ownership/audit FK to Users. '
         'PK primary key, FK foreign key, UK unique constraint.</text>']
    for si, (title, col, tint, _) in enumerate(STORES):
        a, b = store_y[si]
        o.append(f'<rect x="20" y="{a}" width="{width-40}" height="{b-a}" rx="10" fill="{tint}" '
                 f'stroke="{col}" stroke-width="1.5" opacity="0.6"/>')
    lines, texts = [], []

    def seg(pts, p):
        d = ' stroke-dasharray="7 4"' if any(k in p["lab"] for k in DASHED) else ""
        lines.append('<polyline points="' + " ".join(f"{x:.1f},{yy:.1f}" for x, yy in pts) +
                     f'" fill="none" stroke="#334155" stroke-width="1.6"{d}/>')

    def card(x, yy, t, anchor="middle"):
        texts.append(f'<text x="{x:.1f}" y="{yy:.1f}" font-size="12.5" font-weight="700" fill="#b91c1c" '
                     f'text-anchor="{anchor}" stroke="#fff" stroke-width="4" paint-order="stroke">{t}</text>')

    def label(x, yy, t, size=12):
        for k, ln in enumerate(wrap(t)):
            texts.append(f'<text x="{x:.1f}" y="{yy + k * (size + 2):.1f}" font-size="{size}" fill="#0f172a" '
                         f'text-anchor="middle" stroke="#fff" stroke-width="4" paint-order="stroke">{esc(ln)}</text>')

    adj_idx = {}
    for p in plans:
        a, b = p["a"], p["b"]
        if p["kind"] == "adj":
            k = adj_idx.get((a, b), 0)
            adj_idx[(a, b)] = k + 1
            ya = box[a][1] + HEAD + 14 + 28 * k
            xa, xb = box[a][0] + BW, box[b][0]
            if box[b][0] < box[a][0]:
                xa, xb = box[a][0], box[b][0] + BW
            seg([(xa, ya), (xb, ya)], p)
            s = 1 if xb > xa else -1
            card(xa + s * 5, ya - 6, p["card_a"], "start" if s > 0 else "end")
            card(xb - s * 5, ya - 6, p["card_b"], "end" if s > 0 else "start")
            label((xa + xb) / 2, ya + 18, p["lab"], 11)
            continue
        ya = box[a][1] + box[a][3]
        t1 = track_base[p["ia"]] + TRACK * p["t1"]
        if p["kind"] == "same":
            yb = box[b][1] + box[b][3]
            seg([(p["ax"], ya), (p["ax"], t1), (p["bx"], t1), (p["bx"], yb)], p)
            card(p["ax"] + 4, ya + 13, p["card_a"], "start")
            card(p["bx"] + 4, yb + 13, p["card_b"], "start")
            label((p["ax"] + p["bx"]) / 2, t1 - 3, p["lab"], 11)
            continue
        yb = box[b][1]
        if p["lane"] is None:
            seg([(p["ax"], ya), (p["ax"], t1), (p["bx"], t1), (p["bx"], yb)], p)
            mid = (p["ax"] + p["bx"]) / 2
        else:
            t2 = track_base[p["ib"] - 1] + TRACK * p["t2"]
            seg([(p["ax"], ya), (p["ax"], t1), (p["lane"], t1), (p["lane"], t2), (p["bx"], t2), (p["bx"], yb)], p)
            mid = (p["ax"] + p["lane"]) / 2
        card(p["ax"] + 4, ya + 13, p["card_a"], "start")
        card(p["bx"] + 4, yb - 6, p["card_b"], "start")
        label(mid, t1 - 3, p["lab"], 11)
    o += lines
    for n, (x, yy, w, h) in box.items():
        col = STORES[store_of[n]][1]
        tint = STORES[store_of[n]][2]
        o.append(f'<rect x="{x}" y="{yy}" width="{w}" height="{h}" rx="4" fill="#fff" stroke="{col}" stroke-width="2"/>')
        o.append(f'<rect x="{x}" y="{yy}" width="{w}" height="{HEAD}" rx="4" fill="{col}"/>')
        o.append(f'<text x="{x+w/2}" y="{yy+21}" font-size="17" font-weight="700" fill="#fff" '
                 f'text-anchor="middle">{n}</text>')
        for i, (typ, name, key, note) in enumerate(ents[n]):
            ry = yy + HEAD + i * ROW
            if i % 2:
                o.append(f'<rect x="{x+1}" y="{ry}" width="{w-2}" height="{ROW}" fill="{tint}"/>')
            bold = ' font-weight="700"' if key and "PK" in key else ""
            o.append(f'<text x="{x+8}" y="{ry+15}" font-size="13"{bold}>{esc(name)}</text>')
            o.append(f'<text x="{x+135}" y="{ry+15}" font-size="11.5" fill="#475569">{esc(typ)}</text>')
            if key:
                o.append(f'<text x="{x+w-8}" y="{ry+15}" font-size="11.5" font-weight="700" fill="{col}" '
                         f'text-anchor="end">{key}</text>')
            if note:
                note = note.replace(", ", ",")
                o.append(f'<text x="{x+w-8-(40 if key else 0)}" y="{ry+15}" font-size="8.8" fill="#64748b" '
                         f'text-anchor="end">{esc(note)}</text>')
    for si, (title, col, _, _) in enumerate(STORES):
        a, _b = store_y[si]
        texts.append(f'<text x="36" y="{a+30}" font-size="22" font-weight="700" fill="{col}" '
                     f'stroke="#fff" stroke-width="4" paint-order="stroke">{esc(title)}</text>')
    o += texts + ["</svg>"]
    open(dst, "w", encoding="utf-8").write("\n".join(o))
    print(width, height, len(ents), len(rels))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
