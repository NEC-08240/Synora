"""Chen-notation academic ER diagram for Synora V1 (20 entities, 35 relationships).

Reads docs/er-diagram.mmd (locked master), writes docs/er-diagram-chen.{json,svg,png}.
Rectangle = entity, oval = attribute (underlined = PK), diamond = relationship.
FK columns are annotated under each diamond (Chen has no FK ovals); "1"/"N" = cardinality.
Usage: python docs/tools/gen_er_chen.py   (needs elkjs: ELKJS_DIR, Edge for PNG)
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

sys.path.insert(0, str(Path(__file__).parent))
from gen_er import STORES, parse  # noqa: E402
from gen_er_academic import DASHED, render_png, short_label  # noqa: E402

# Conceptual view: PK plus 1-2 descriptive attributes. FK columns are NOT drawn (the relationship carries them).
SIMPLE = {"Roles": ["RoleName"], "Users": ["Name", "Email"], "Batches": ["Name"], "FacultyAssignments": [],
          "Subjects": ["Title"], "Topics": ["Title"], "Lessons": ["Title"], "LessonResources": ["ResourceType"],
          "Activities": ["Title", "ActivityType"], "QuizQuestions": ["QuestionText"], "QuizOptions": ["OptionText"],
          "TestCases": ["ExpectedOutput"], "SqlTaskSpecs": ["ExpectedResult"], "PracticeDrafts": ["Content"],
          "Submissions": ["AttemptNo", "Score"], "SubmissionAnswers": [], "TestCaseResults": ["Passed"],
          "LearningActivity": ["EventType"], "StudentProgress": ["AggregateScorePct"], "Recommendations": ["RuleCode"]}

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs"
ELKJS = os.environ.get("ELKJS_DIR") or str(Path(os.environ.get("TEMP", "/tmp")) / "mmd/node_modules/elkjs")
STORE_OF = {n: (s[0].split()[0], s[1], s[2]) for s in STORES for r in s[3] for n in r}
STORE_IDX = {s[0].split()[0]: i for i, s in enumerate(STORES)}

# FK column(s) on the child entity for each relationship, in .mmd order. Verified by check_er_chen.py.
FK_COLS = ["RoleId", "BatchId", "CreatedBy", "BatchId", "SubjectId", "FacultyId", "AssignedBy", "SubjectId",
           "CreatedBy", "TopicId", "LessonId", "TopicId", "CreatedBy", "ActivityId", "QuestionId", "ActivityId",
           "ActivityId", "StudentId", "ActivityId", "StudentId", "ActivityId", "GradedBy", "SubmissionId",
           "QuestionId", "QuestionId+OptionId", "SubmissionId", "TestCaseId", "StudentId", "LessonId",
           "ActivityId", "StudentId", "TopicId", "StudentId", "TopicId", "ActivityId"]
NULLABLE = {1, 21, 28, 29, 34}
OVAL_H, GAP, FS = 22, 14, 11.5


def attrs_of(ents, name):
    """PK attrs first, then the academic non-key attributes."""
    rows = ents[name]
    pk = [a for _t, a, k, _n in rows if k and "PK" in k]
    return pk, [a for a in SIMPLE[name] if a not in pk]


def shown(ents, name):
    """Ovals to draw: composite PK collapses into one oval so the diagram has no FK-looking attributes."""
    pk, other = attrs_of(ents, name)
    return [(" + ".join(pk), True)] + [(a, False) for a in other]


def ow(text):
    return max(60, len(text) * 6.7 + 14)


def build(ents, rels):
    """Entity clusters (rect + ovals) and the ELK graph. Returns (graph, meta)."""
    ports = {n: {"E": 0, "W": 0} for n in ents}
    for a, _l, _r, b, _lab in rels:
        ports[a]["E"] += 1
        ports[b]["W"] += 1
    meta, kids = {}, []
    for n in ents:
        pk = attrs_of(ents, n)[0]
        al = shown(ents, n)
        top, bot = al[: (len(al) + 1) // 2], al[(len(al) + 1) // 2:]
        roww = lambda r: sum(ow(a) for a, _ in r) + 8 * max(len(r) - 1, 0)  # noqa: E731
        w = max(100, len(n) * 8.6 + 18, roww(top), roww(bot))
        band = max(50, 20 * max(ports[n]["E"], ports[n]["W"]) + 12)
        h = OVAL_H + GAP + band + (GAP + OVAL_H if bot else 0)
        y0 = OVAL_H + GAP
        meta[n] = dict(w=w, h=h, band=band, y0=y0, top=top, bot=bot, pk=pk)
        pl, cnt = [], {"E": 0, "W": 0}
        for side in ("E", "W"):
            pass
        kids.append({"id": n, "width": w, "height": h, "ports": [], "layoutOptions": {
            "elk.portConstraints": "FIXED_POS", "elk.partitioning.partition": str(STORE_IDX[STORE_OF[n][0]])}})
    edges, dia = [], []
    used = {n: {"E": 0, "W": 0} for n in ents}

    def port(n, side, pid):
        m = meta[n]
        k = used[n][side]
        used[n][side] += 1
        tot = ports[n][side]
        y = m["y0"] + (k + 0.5) * m["band"] / tot
        kids_by = next(c for c in kids if c["id"] == n)
        kids_by["ports"].append({"id": pid, "x": m["w"] if side == "E" else 0, "y": y, "width": 0, "height": 0,
                                 "layoutOptions": {"elk.port.side": "EAST" if side == "E" else "WEST"}})
        return pid

    for i, (a, _l, _r, b, lab) in enumerate(rels):
        t = short_label(lab)
        dw, dh = max(80, len(t) * 6.6 + 40), 48
        dia.append({"id": f"d{i}", "width": dw, "height": dh, "layoutOptions": {
            "elk.partitioning.partition": str(STORE_IDX[STORE_OF[a][0]])}})
        pa, pb = port(a, "E", f"pa{i}"), port(b, "W", f"pb{i}")
        edges.append({"id": f"ea{i}", "sources": [pa], "targets": [f"d{i}"]})
        edges.append({"id": f"eb{i}", "sources": [f"d{i}"], "targets": [pb]})
    return {"id": "root", "children": kids + dia, "edges": edges}, meta


def base_opts():
    return {"elk.algorithm": "layered", "elk.edgeRouting": "ORTHOGONAL", "elk.spacing.nodeNode": "14",
            "elk.layered.spacing.nodeNodeBetweenLayers": "26", "elk.spacing.edgeNode": "14",
            "elk.spacing.edgeEdge": "10", "elk.layered.spacing.edgeEdgeBetweenLayers": "10",
            "elk.layered.spacing.edgeNodeBetweenLayers": "14", "elk.direction": "RIGHT",
            "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP", "elk.layered.thoroughness": "30",
            "elk.padding": "[top=95,left=12,bottom=12,right=12]"}


def run_elk(graph, variants):
    env = dict(os.environ, ELKJS_DIR=ELKJS)
    p = subprocess.run(["node", str(Path(__file__).parent / "elk_layout.js")], env=env, text=True,
                       input=json.dumps({"graph": graph, "variants": variants}), capture_output=True, check=True)
    return json.loads(p.stdout)


def polyline(e):
    s = e["sections"][0]
    return [(s["startPoint"]["x"], s["startPoint"]["y"])] + [(p["x"], p["y"]) for p in s.get("bendPoints", [])] + \
           [(s["endPoint"]["x"], s["endPoint"]["y"])]


def segs(pl):
    return list(zip(pl, pl[1:]))


def cross(s, t):
    (a, b), (c, d) = s, t
    if (a[0] == b[0]) == (c[0] == d[0]):
        return False
    v, h = (s, t) if a[0] == b[0] else (t, s)
    x, y = v[0][0], h[0][1]
    return min(h[0][0], h[1][0]) < x < max(h[0][0], h[1][0]) and min(v[0][1], v[1][1]) < y < max(v[0][1], v[1][1])


def quality(lay):
    nodes = {c["id"]: c for c in lay["children"]}
    edges = {e["id"]: segs(polyline(e)) for e in lay["edges"]}
    ids, cr = list(edges), 0
    for i, ea in enumerate(ids):
        for eb in ids[i + 1:]:
            cr += sum(cross(s, t) for s in edges[ea] for t in edges[eb])
    hits = 0
    for e in lay["edges"]:
        own = {e["sources"][0].split("pa")[-1].split("pb")[-1]}
        ends = {e["sources"][0], e["targets"][0]}
        for nid, nd in nodes.items():
            if nid in ends or any(p["id"] in ends for p in nd.get("ports", [])):
                continue
            x0, y0, x1, y1 = nd["x"] + 1, nd["y"] + 1, nd["x"] + nd["width"] - 1, nd["y"] + nd["height"] - 1
            for (a, b) in edges[e["id"]]:
                if max(a[0], b[0]) > x0 and min(a[0], b[0]) < x1 and max(a[1], b[1]) > y0 and min(a[1], b[1]) < y1:
                    hits += 1
    w, h = lay["width"], lay["height"]
    length = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for sg in edges.values() for a, b in sg)
    return cr * 25 + hits * 1000 + length / 40 + w * h / 8e3 + abs(w / h - 1.6) * 1500, cr, hits


def variants():
    out = []
    for part in ("true", "false"):
        for place in ("NETWORK_SIMPLEX", "BRANDES_KOEPF"):
            for seed in range(1, 26):
              for lay in ("NETWORK_SIMPLEX", "LONGEST_PATH"):
                out.append({"elk.layered.layering.strategy": lay,"elk.partitioning.activate": part, "elk.layered.nodePlacement.strategy": place,
                            "elk.randomSeed": str(seed)})
    return out


def render_svg(lay, meta, rels, ents, path):
    W, H = lay["width"], lay["height"] + 40
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'font-family="Segoe UI, Arial, sans-serif"><rect width="100%" height="100%" fill="#fff"/>',
         f'<text x="20" y="28" font-size="20" font-weight="700" fill="#111">Synora V1 — Entity-Relationship Diagram '
         f'(Chen notation): 20 entities, 35 relationships</text>']
    zones = ["D1 User & Access", "D2 Course Content", "D3 Assessment", "D4 Submission", "D5 Analytics"]
    zx = 20
    for z in range(5):  # colour key; layout is relationship-driven, so zones are shown by colour, not bands
        o.append(f'<rect x="{zx}" y="62" width="16" height="16" fill="{STORES[z][2]}" stroke="{STORES[z][1]}" stroke-width="2"/>'
                 f'<text x="{zx + 22}" y="75" font-size="14" font-weight="700" fill="{STORES[z][1]}">{esc(zones[z])}</text>')
        zx += 60 + len(zones[z]) * 8
    lx = 20
    o.append(f'<g font-size="12" fill="#222"><rect x="{lx}" y="38" width="30" height="16" fill="#fff" stroke="#222"/>'
             f'<text x="{lx + 38}" y="51">entity</text><ellipse cx="{lx + 100}" cy="46" rx="16" ry="8" fill="#fff" stroke="#222"/>'
             f'<text x="{lx + 122}" y="51">attribute (<tspan text-decoration="underline">underlined</tspan> = primary key)</text>'
             f'<path d="M{lx + 340} 46 l16 -9 l16 9 l-16 9 z" fill="#fff" stroke="#222"/><text x="{lx + 378}" y="51">relationship</text>'
             f'<text x="{lx + 470}" y="51">1 / N = cardinality</text><line x1="{lx + 600}" y1="46" x2="{lx + 640}" y2="46" '
             f'stroke="#555" stroke-dasharray="5 3"/><text x="{lx + 648}" y="51">created / authored / assigned / graded by</text></g>')
    ox = 0
    nodes = {c["id"]: c for c in lay["children"]}
    # edges first
    for e in lay["edges"]:
        kind = int(e["id"][2:])
        dashed = short_label(rels[kind][4]) in DASHED
        pts = " ".join(f"{x:.1f},{y + ox:.1f}" for x, y in polyline(e))
        o.append(f'<polyline points="{pts}" fill="none" stroke="#555" stroke-width="1.2"'
                 f'{" stroke-dasharray=\"5 3\"" if dashed else ""}/>')
        # cardinality next to the entity end: ea -> start (parent), eb -> end (child)
        pl = polyline(e)
        i = int(e["id"][2:])
        if e["id"].startswith("ea"):
            (x, y), side, txt = pl[0], "E", "1"
        else:
            (x, y), side, txt = pl[-1], "W", "1" if (i == 16) else "N"
        tx = x + 7 if side == "E" else x - 7
        o.append(f'<text x="{tx:.1f}" y="{y - 4:.1f}" font-size="12" font-weight="700" fill="#c00" '
                 f'text-anchor="{"start" if side == "E" else "end"}">{txt}</text>')
    for n, m in meta.items():
        nd = nodes[n]
        x, y = nd["x"], nd["y"]
        _s, col, tint = STORE_OF[n]
        ry, rh = y + m["y0"], m["band"]
        for row, ry0, sgn in ((m["top"], y, 1), (m["bot"], y + m["h"] - OVAL_H, -1)):
            tot = sum(ow(a) for a, _ in row) + 8 * (len(row) - 1)
            cx = x + (m["w"] - tot) / 2
            for a, ispk in row:
                w = ow(a)
                ex, ey = cx + w / 2, ry0 + OVAL_H / 2
                ty = ry if sgn == 1 else ry + rh
                o.append(f'<line x1="{ex:.1f}" y1="{ey + sgn * OVAL_H / 2:.1f}" x2="{min(max(ex, x + 6), x + m["w"] - 6):.1f}" '
                         f'y2="{ty:.1f}" stroke="#777" stroke-width="0.9"/>')
                o.append(f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" rx="{w / 2:.1f}" ry="{OVAL_H / 2}" fill="#fff" '
                         f'stroke="{col}" stroke-width="1.2"/><text x="{ex:.1f}" y="{ey + 3.5:.1f}" font-size="{FS}" '
                         f'text-anchor="middle" fill="#111"{" text-decoration=\"underline\" font-weight=\"600\"" if ispk else ""}>'
                         f'{esc(a)}</text>')
                cx += w + 8
        o.append(f'<rect x="{x:.1f}" y="{ry:.1f}" width="{m["w"]}" height="{rh:.1f}" fill="{tint}" stroke="{col}" '
                 f'stroke-width="2"/><text x="{x + m["w"] / 2:.1f}" y="{ry + rh / 2 + 4:.1f}" font-size="15" '
                 f'font-weight="700" text-anchor="middle" fill="#111">{esc(n)}</text><text x="{x + m["w"] - 4:.1f}" '
                 f'y="{ry + 11:.1f}" font-size="10" text-anchor="end" fill="{col}" font-weight="700">{STORE_OF[n][0]}</text>')
    for i, (a, _l, _r, b, lab) in enumerate(rels):
        nd = nodes[f"d{i}"]
        cx, cy, w = nd["x"] + nd["width"] / 2, nd["y"] + 24, nd["width"]
        o.append(f'<path d="M{cx - w / 2:.1f} {cy:.1f} L{cx:.1f} {cy - 24:.1f} L{cx + w / 2:.1f} {cy:.1f} '
                 f'L{cx:.1f} {cy + 24:.1f} Z" fill="#fff" stroke="#222" stroke-width="1.3"/>'
                 f'<text x="{cx:.1f}" y="{cy + 3.5:.1f}" font-size="11.5" text-anchor="middle" fill="#111">'
                 f'{esc(short_label(lab))}</text>')
    o.append("</svg>")
    path.write_text("\n".join(o), encoding="utf-8")
    return W, H


def main():
    ents, rels = parse(OUT / "er-diagram.mmd")
    assert len(ents) == 20 and len(rels) == 35 and len(FK_COLS) == 35
    graph, meta = build(ents, rels)
    res = run_elk(graph, [{**base_opts(), **v} for v in variants()])
    best = None
    for r in res:
        if "layout" not in r:
            continue
        s, cr, hits = quality(r["layout"])
        if best is None or s < best[0]:
            best = (s, cr, hits, r)
    s, cr, hits, r = best
    lay = r["layout"]
    print(f"best: crossings={cr} box_hits={hits} canvas={lay['width']:.0f}x{lay['height']:.0f}")
    W, H = render_svg(lay, meta, rels, ents, OUT / "er-diagram-chen.svg")
    render_png(OUT / "er-diagram-chen.svg", OUT / "er-diagram-chen.png", int(W), int(H), 2)
    (OUT / "er-diagram-chen.json").write_text(json.dumps({"rels": [[a, b, short_label(l), FK_COLS[i]]
                                               for i, (a, _x, _y, b, l) in enumerate(rels)]}, indent=1), "utf-8")


if __name__ == "__main__":
    main()
