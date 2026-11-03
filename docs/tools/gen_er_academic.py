"""Build the guide-facing academic ER diagram from the technical docs/er-diagram.mmd.

Writes docs/er-diagram-academic.mmd (filtered view: PK/FK + a few descriptive attributes, short labels),
docs/er-diagram-academic.svg and docs/er-diagram-academic.png.
Layout and orthogonal routing come from ELK (docs/tools/elk_layout.js); many layout variants are tried and the
one with the fewest line crossings is drawn. Needs node and elkjs (set ELKJS_DIR, default $TEMP/mmd/node_modules/elkjs).
Do not hand-edit the generated .mmd: change ACADEMIC / LABELS below and re-run.
Usage: python docs/tools/gen_er_academic.py
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as esc

sys.path.insert(0, str(Path(__file__).parent))
from gen_er import STORES, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TECH = ROOT / "docs/er-diagram.mmd"
OUT = ROOT / "docs"

# Non-key attributes shown in the academic view. PK and FK attributes are always shown.
ACADEMIC = {
    "Roles": ["RoleName"], "Users": ["Name", "Email", "Status"], "Batches": ["Name", "AcademicYear"],
    "FacultyAssignments": [], "Subjects": ["Title", "Status"], "Topics": ["Title", "OrderIndex"],
    "Lessons": ["Title", "ContentBody"], "LessonResources": ["ResourceType", "Url"],
    "Activities": ["Title", "ActivityType", "IsGraded", "MaxScore"], "QuizQuestions": ["QuestionText", "Points"],
    "QuizOptions": ["OptionText", "IsCorrect"], "TestCases": ["InputData", "ExpectedOutput"],
    "SqlTaskSpecs": ["SetupScript", "ExpectedResult"], "PracticeDrafts": ["Content"],
    "Submissions": ["AttemptNo", "Status", "Score"], "SubmissionAnswers": [], "TestCaseResults": ["Passed"],
    "LearningActivity": ["EventType", "OccurredAt"], "StudentProgress": ["AggregateScorePct"],
    "Recommendations": ["RuleCode"],
}
LABELS = {"student belongs to": "belongs to", "owns (cascade)": "owns"}
DASHED = ("created by", "authored by", "assigned by", "graded by")  # audit links to Users
CW, HEAD, RH, PAD, FONT = 186, 24, 17, 6, 12.5
LABEL_H = 15
STORE_OF = {n: (s[0].split()[0], s[1]) for s in STORES for r in s[3] for n in r}
STORE_NAME = {s[0].split()[0]: s[0] for s in STORES}


def short_label(lab):
    lab = LABELS.get(lab.strip(), lab.strip())
    return LABELS.get(re.sub(r"\s*\(.*?\)", "", lab).strip(), re.sub(r"\s*\(.*?\)", "", lab).strip())


def cards(ents):
    out = {}
    for n, rows in ents.items():
        keep = [(t, a, k) for t, a, k, _ in rows if (k and ("PK" in k or "FK" in k)) or a in ACADEMIC[n]]
        out[n] = [(t, a, k if k and ("PK" in k or "FK" in k) else None) for t, a, k in keep]
    return out


def emit_mmd(view, rels, path):
    lines = ["erDiagram"]
    for n, rows in view.items():
        lines.append(f"    {n} {{")
        for t, a, k in rows:
            lines.append(f"        {t} {a}" + (f" {k}" if k else ""))
        lines.append("    }")
    for a, la, ra, b, lab in rels:
        lines.append(f'    {a} {la}--{ra} {b} : "{short_label(lab)}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def elk_graph(view, rels):
    kids = [{"id": n, "width": CW, "height": HEAD + RH * len(r) + PAD} for n, r in view.items()]
    edges = []
    for i, (a, _la, _ra, b, lab) in enumerate(rels):
        t = short_label(lab)
        edges.append({"id": f"e{i}", "sources": [a], "targets": [b],
                      "labels": [{"text": t, "width": len(t) * 6.4 + 6, "height": LABEL_H}]})
    base = {"elk.algorithm": "layered", "elk.edgeRouting": "ORTHOGONAL",
            "elk.spacing.nodeNode": "34", "elk.layered.spacing.nodeNodeBetweenLayers": "64",
            "elk.spacing.edgeNode": "20", "elk.spacing.edgeEdge": "14",
            "elk.layered.spacing.edgeEdgeBetweenLayers": "14", "elk.layered.spacing.edgeNodeBetweenLayers": "20",
            "elk.spacing.edgeLabel": "3", "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
            "elk.layered.thoroughness": "40", "elk.padding": "[top=10,left=10,bottom=10,right=10]"}
    return {"id": "root", "layoutOptions": base, "children": kids, "edges": edges}


def variants():
    out = []
    for direction in ("RIGHT", "DOWN"):
        for wrap in ("OFF",):
            for place in ("NETWORK_SIMPLEX", "BRANDES_KOEPF"):
                for seed in range(1, 41):
                    v = {"elk.direction": direction, "elk.layered.nodePlacement.strategy": place,
                         "elk.randomSeed": str(seed), "elk.aspectRatio": "1.5"}
                    if wrap != "OFF":
                        v["elk.layered.wrapping.strategy"] = wrap
                    out.append(v)
    return out


def run_elk(graph):
    d = os.environ.get("ELKJS_DIR") or str(Path(tempfile.gettempdir()) / "mmd/node_modules/elkjs")
    env = dict(os.environ, ELKJS_DIR=d)
    p = subprocess.run(["node", str(Path(__file__).parent / "elk_layout.js")], env=env, capture_output=True,
                       text=True, input=json.dumps({"graph": graph, "variants": variants()}), check=True)
    return [r for r in json.loads(p.stdout) if "layout" in r]


def polyline(e):
    s = e["sections"][0]
    return [(s["startPoint"]["x"], s["startPoint"]["y"])] + [(b["x"], b["y"]) for b in s.get("bendPoints", [])] + \
           [(s["endPoint"]["x"], s["endPoint"]["y"])]


def segs(pl):
    return list(zip(pl, pl[1:]))


def crosses(s1, s2):
    (a, b), (c, d) = s1, s2
    h1, h2 = abs(a[1] - b[1]) < 0.5, abs(c[1] - d[1]) < 0.5
    if h1 == h2:
        return False
    if h2:
        (a, b), (c, d) = (c, d), (a, b)  # make s1 horizontal
    y, x = a[1], c[0]
    return min(a[0], b[0]) + 1 < x < max(a[0], b[0]) - 1 and min(c[1], d[1]) + 1 < y < max(c[1], d[1]) - 1


def quality(layout):
    nodes = {c["id"]: c for c in layout["children"]}
    pls = [polyline(e) for e in layout["edges"]]
    cross = sum(1 for i in range(len(pls)) for j in range(i + 1, len(pls))
                for s1 in segs(pls[i]) for s2 in segs(pls[j]) if crosses(s1, s2))
    hits = 0
    for pl in pls:
        for (a, b) in segs(pl):
            for c in nodes.values():
                x0, y0, x1, y1 = c["x"] + 1, c["y"] + 1, c["x"] + c["width"] - 1, c["y"] + c["height"] - 1
                if min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0:
                    hits += 1
    ratio = layout["width"] / layout["height"]
    length = sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for pl in pls for a, b in segs(pl))
    score = cross * 10 + hits * 1000 + length / 120 + 260 * abs(math.log(ratio / 1.4)) + layout["width"] / 60
    return score, cross, hits


def sym(x, y, dx, dy, s):
    """Crow's-foot marker at (x,y) on a node border; (dx,dy) points away from the node. s = Mermaid symbol."""
    px, py = -dy, dx
    opt, many = "o" in s, ("{" in s or "}" in s)
    o, ink = [], 'stroke="#1e293b" stroke-width="1.6" fill="none"'

    def ln(d1, w1, d2, w2):
        o.append(f'<line x1="{x+dx*d1+px*w1:.1f}" y1="{y+dy*d1+py*w1:.1f}" x2="{x+dx*d2+px*w2:.1f}" '
                 f'y2="{y+dy*d2+py*w2:.1f}" {ink}/>')

    def bar(d):
        ln(d, -5, d, 5)

    def circ(d):
        o.append(f'<circle cx="{x+dx*d:.1f}" cy="{y+dy*d:.1f}" r="4.2" fill="#fff" stroke="#1e293b" stroke-width="1.6"/>')
    if many:
        ln(13, 0, 0, 0)
        ln(13, 0, 0, 6)
        ln(13, 0, 0, -6)
        circ(18) if opt else bar(17)
    else:
        bar(8)
        circ(16) if opt else bar(13)
    return "".join(o)


def render_svg(layout, view, rels, path):
    M, TOP, LEG = 28, 74, 78
    W, H = layout["width"] + 2 * M, layout["height"] + TOP + LEG + M
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'font-family="Segoe UI, Arial, sans-serif"><rect width="{W:.0f}" height="{H:.0f}" fill="#fff"/>',
         f'<text x="{W/2:.0f}" y="34" font-size="26" font-weight="700" text-anchor="middle" fill="#0f172a">'
         'Synora V1 Entity-Relationship Diagram</text>',
         f'<text x="{W/2:.0f}" y="58" font-size="13.5" text-anchor="middle" fill="#475569">'
         '20 entities, Microsoft SQL Server. Academic view: keys and main attributes only. '
         'Full column list, data types and constraints: docs/database/database-design.md</text>',
         f'<g transform="translate({M},{TOP})">']
    nodes = {c["id"]: c for c in layout["children"]}
    edges = layout["edges"]
    for e, (a, la, ra, b, lab) in zip(edges, rels):
        pl = polyline(e)
        dash = ' stroke-dasharray="6 4"' if any(k in lab for k in DASHED) else ""
        o.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pl) +
                 f'" fill="none" stroke="#475569" stroke-width="1.5"{dash} stroke-linejoin="round"/>')
        for pt, nxt, s in ((pl[0], pl[1], la), (pl[-1], pl[-2], ra)):
            L = math.hypot(nxt[0] - pt[0], nxt[1] - pt[1]) or 1
            o.append(sym(pt[0], pt[1], (nxt[0] - pt[0]) / L, (nxt[1] - pt[1]) / L, s))
    for e in edges:
        for lb in e.get("labels", []):
            o.append(f'<text x="{lb["x"]+lb["width"]/2:.1f}" y="{lb["y"]+lb["height"]-3:.1f}" font-size="11.5" '
                     f'font-style="italic" fill="#0f172a" text-anchor="middle" stroke="#fff" stroke-width="4" '
                     f'paint-order="stroke">{esc(lb["text"])}</text>')
    for n, c in nodes.items():
        sid, col = STORE_OF[n]
        x, y, w, h = c["x"], c["y"], c["width"], c["height"]
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="#fff" stroke="{col}" stroke-width="2"/>')
        o.append(f'<path d="M{x},{y+HEAD} V{y+4} Q{x},{y} {x+4},{y} H{x+w-4} Q{x+w},{y} {x+w},{y+4} V{y+HEAD} Z" fill="{col}"/>')
        o.append(f'<text x="{x+8}" y="{y+17}" font-size="14" font-weight="700" fill="#fff">{n}</text>')
        o.append(f'<text x="{x+w-8}" y="{y+17}" font-size="11" fill="#fff" opacity="0.85" text-anchor="end">{sid}</text>')
        for i, (_t, a, k) in enumerate(view[n]):
            ry = y + HEAD + i * RH
            if i % 2:
                o.append(f'<rect x="{x+1}" y="{ry}" width="{w-2}" height="{RH}" fill="#f8fafc"/>')
            pk = k and "PK" in k
            deco = ' font-weight="700" text-decoration="underline"' if pk else ""
            o.append(f'<text x="{x+8}" y="{ry+13}" font-size="{FONT}"{deco} fill="#0f172a">{a}</text>')
            if k:
                o.append(f'<text x="{x+w-8}" y="{ry+13}" font-size="11" font-weight="700" fill="{col}" '
                         f'text-anchor="end">{k}</text>')
    o.append("</g>")
    ly = TOP + layout["height"] + 26
    x = M
    o.append(f'<text x="{x}" y="{ly}" font-size="12.5" font-weight="700" fill="#0f172a">Notation</text>')
    for lbl, s in (("exactly one", "||"), ("zero or one", "|o"), ("zero or many", "o{")):
        o.append(sym(x + 90, ly - 4, 1, 0, s).replace("1.6", "1.6"))
        o.append(f'<line x1="{x+90}" y1="{ly-4}" x2="{x+150}" y2="{ly-4}" stroke="#475569" stroke-width="1.5"/>')
        o.append(f'<text x="{x+158}" y="{ly}" font-size="12" fill="#0f172a">{lbl}</text>')
        x += 215
    o.append(f'<line x1="{x}" y1="{ly-4}" x2="{x+50}" y2="{ly-4}" stroke="#475569" stroke-width="1.5" '
             f'stroke-dasharray="6 4"/><text x="{x+58}" y="{ly}" font-size="12" fill="#0f172a">'
             'audit link to Users (created / assigned / graded by)</text>')
    o.append(f'<text x="{M}" y="{ly+26}" font-size="12" fill="#0f172a"><tspan font-weight="700" '
             f'text-decoration="underline">Underlined</tspan> = PK primary key, FK = foreign key. '
             f'Colour and tag = DFD data store:</text>')
    x = M + 480
    for sid, name in STORE_NAME.items():
        col = next(s[1] for s in STORES if s[0].startswith(sid))
        o.append(f'<rect x="{x}" y="{ly+14}" width="14" height="14" rx="2" fill="{col}"/>'
                 f'<text x="{x+20}" y="{ly+26}" font-size="12" fill="#0f172a">{esc(name)}</text>')
        x += 180
    o.append("</svg>")
    path.write_text("\n".join(o), encoding="utf-8")
    return W, H


def render_png(svg, png, w, h, scale=2):
    exe = next((p for p in (shutil.which("msedge"), shutil.which("chrome"),
                            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Google\Chrome\Application\chrome.exe") if p and Path(p).exists()), None)
    if not exe:
        raise SystemExit("no Edge/Chrome found for PNG rendering")
    subprocess.run([exe, "--headless", "--disable-gpu", "--hide-scrollbars", f"--window-size={int(w)},{int(h)}",
                    f"--force-device-scale-factor={scale}", f"--screenshot={png}", svg.resolve().as_uri()],
                   check=True, capture_output=True)


def main():
    ents, rels = parse(TECH)
    view = cards(ents)
    emit_mmd(view, rels, OUT / "er-diagram-academic.mmd")
    results = run_elk(elk_graph(view, rels))
    best = min(results, key=lambda r: quality(r["layout"])[0])
    score, cross, hits = quality(best["layout"])
    print(f"{len(results)} layouts tried; best {best['variant']}\n crossings={cross} box_hits={hits} "
          f"size={best['layout']['width']:.0f}x{best['layout']['height']:.0f}")
    W, H = render_svg(best["layout"], view, rels, OUT / "er-diagram-academic.svg")
    render_png(OUT / "er-diagram-academic.svg", OUT / "er-diagram-academic.png", W, H)
    print(f"canvas {W:.0f}x{H:.0f}")


if __name__ == "__main__":
    main()
