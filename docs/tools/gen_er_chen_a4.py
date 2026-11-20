"""Two A4-landscape report views of the Chen ER master (same 20 entities / 35 relationships).

View 1 = D1 + D2 entities, View 2 = D3 + D4 + D5 entities. A relationship that crosses the split is drawn in BOTH views;
the entity on the other page appears as a dashed "reference" box (name + page), not as a new entity.
Usage: python docs/tools/gen_er_chen_a4.py   (needs elkjs via ELKJS_DIR and Edge for PNG)
"""
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

sys.path.insert(0, str(Path(__file__).parent))
import gen_er_chen as C  # noqa: E402
from gen_er import parse  # noqa: E402
from gen_er_academic import DASHED, render_png, short_label  # noqa: E402

OUT = C.OUT
OVAL_H, GAP = 30, 16
FS_ATTR, FS_REL, FS_ENT = 13, 13, 17
VIEWS = [
    ("a4-d1-d2", 1, "D1 User & Access + D2 Course Content", {0, 1}),
    ("a4-d3-d4-d5", 2, "D3 Assessment + D4 Submission + D5 Analytics", {2, 3, 4}),
]


def ow(t):
    return max(60, len(t) * 7.6 + 14)


def zone(n):
    return C.STORE_IDX[C.STORE_OF[n][0]]


def build(ents, rels, mine, page_of):
    """ELK graph for one view. Returns (graph, meta, view_rels, ghosts)."""
    vrels = [(i, r) for i, r in enumerate(rels) if zone(r[0]) in mine or zone(r[3]) in mine]
    ghosts = sorted({n for _i, r in vrels for n in (r[0], r[3]) if zone(n) not in mine})
    nodes = [n for n in ents if zone(n) in mine] + ghosts
    ports = {n: {"E": 0, "W": 0} for n in nodes}
    for _i, (a, _l, _r, b, _lab) in vrels:
        ports[a]["E"] += 1
        ports[b]["W"] += 1
    meta, kids = {}, {}
    for n in nodes:
        gh = n in ghosts
        al = [] if gh else C.shown(ents, n)
        top, bot = al[: (len(al) + 1) // 2], al[(len(al) + 1) // 2:]
        rw = lambda r: sum(ow(a) for a, _ in r) + 8 * max(len(r) - 1, 0)  # noqa: E731
        label = f"{n}  (p.{page_of[n]})" if gh else n
        w = max(150, len(label) * 10.5 + 24, rw(top), rw(bot))
        band = max(54, 22 * max(ports[n]["E"], ports[n]["W"]) + 12)
        h = band if gh else (OVAL_H + GAP + band + (GAP + OVAL_H if bot else 0))
        y0 = 0 if gh else OVAL_H + GAP
        meta[n] = dict(w=w, h=h, band=band, y0=y0, top=top, bot=bot, ghost=gh, label=label)
        kids[n] = {"id": n, "width": w, "height": h, "ports": [],
                   "layoutOptions": {"elk.portConstraints": "FIXED_POS"}}
    used = {n: {"E": 0, "W": 0} for n in nodes}

    def port(n, side, pid):
        m, k = meta[n], used[n][side]
        used[n][side] += 1
        y = m["y0"] + (k + 0.5) * m["band"] / ports[n][side]
        kids[n]["ports"].append({"id": pid, "x": m["w"] if side == "E" else 0, "y": y, "width": 0, "height": 0,
                                 "layoutOptions": {"elk.port.side": "EAST" if side == "E" else "WEST"}})
        return pid

    dia, edges = [], []
    for i, (a, _l, _r, b, lab) in vrels:
        t = short_label(lab)
        dia.append({"id": f"d{i}", "width": max(96, len(t) * 8 + 44), "height": 52})
        edges.append({"id": f"ea{i}", "sources": [port(a, "E", f"pa{i}")], "targets": [f"d{i}"]})
        edges.append({"id": f"eb{i}", "sources": [f"d{i}"], "targets": [port(b, "W", f"pb{i}")]})
    return {"id": "root", "children": list(kids.values()) + dia, "edges": edges}, meta, vrels, ghosts


def opts():
    o = C.base_opts()
    o.update({"elk.spacing.nodeNode": "14", "elk.layered.spacing.nodeNodeBetweenLayers": "22",
              "elk.padding": "[top=110,left=16,bottom=16,right=16]"})
    return o


def score(lay):
    s, cr, hits = C.quality(lay)
    w, h = lay["width"], lay["height"]
    # target the printable area ratio (277 x 190 mm = 1.46); canvas must stay small so text prints large
    return cr * 25 + hits * 1000 + w * h / 8e2 + abs(w / h - 1.46) * 1500, cr, hits


def render(lay, meta, vrels, ents, title, page, path):
    W, H = lay["width"], lay["height"]
    nd = {c["id"]: c for c in lay["children"]}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'font-family="Segoe UI, Arial, sans-serif"><rect width="100%" height="100%" fill="#fff"/>',
         f'<text x="16" y="30" font-size="22" font-weight="700" fill="#111">Synora V1 ER diagram (Chen), page {page} of 2: '
         f'{esc(title)}</text>',
         f'<g font-size="13" fill="#222"><rect x="16" y="44" width="30" height="16" fill="#fff" stroke="#222"/>'
         f'<text x="54" y="57">entity</text><ellipse cx="128" cy="52" rx="18" ry="9" fill="#fff" stroke="#222"/>'
         f'<text x="152" y="57">attribute (<tspan text-decoration="underline">underlined</tspan> = primary key)</text>'
         f'<path d="M430 52 l18 -10 l18 10 l-18 10 z" fill="#fff" stroke="#222"/><text x="474" y="57">relationship</text>'
         f'<text x="566" y="57">1 / N = cardinality</text>'
         f'<rect x="700" y="44" width="30" height="16" fill="#f3f3f3" stroke="#666" stroke-dasharray="4 3"/>'
         f'<text x="738" y="57">entity on the other page (p.N)</text>'
         f'<line x1="930" y1="52" x2="970" y2="52" stroke="#555" stroke-dasharray="5 3"/>'
         f'<text x="978" y="57">created / authored / assigned / graded by</text></g>']
    zx = 16
    for z, (zt, col, tint, _r) in enumerate(C.STORES):
        if z in {zone(n) for n in meta if not meta[n]["ghost"]}:
            o.append(f'<rect x="{zx}" y="72" width="16" height="16" fill="{tint}" stroke="{col}" stroke-width="2"/>'
                     f'<text x="{zx + 22}" y="85" font-size="15" font-weight="700" fill="{col}">{esc(zt)}</text>')
            zx += 56 + len(zt) * 8.5
    for e in lay["edges"]:
        i = int(e["id"][2:])
        pl = C.polyline(e)
        dash = short_label(rels_all[i][4]) in DASHED
        o.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pl)}" fill="none" stroke="#555" '
                 f'stroke-width="1.5"{" stroke-dasharray=\"6 4\"" if dash else ""}/>')
        if e["id"].startswith("ea"):
            (x, y), tx, anc, txt = pl[0], pl[0][0] + 8, "start", "1"
        else:
            (x, y), tx, anc, txt = pl[-1], pl[-1][0] - 8, "end", "1" if i == 16 else "N"
        o.append(f'<text x="{tx:.1f}" y="{y - 5:.1f}" font-size="15" font-weight="700" fill="#c00" text-anchor="{anc}">{txt}</text>')
    for n, m in meta.items():
        x, y = nd[n]["x"], nd[n]["y"]
        ry, rh = y + m["y0"], m["band"]
        if m["ghost"]:
            o.append(f'<rect x="{x:.1f}" y="{ry:.1f}" width="{m["w"]}" height="{rh:.1f}" fill="#f3f3f3" stroke="#666" '
                     f'stroke-width="1.6" stroke-dasharray="6 4"/><text x="{x + m["w"] / 2:.1f}" y="{ry + rh / 2 + 5:.1f}" '
                     f'font-size="{FS_ENT - 1}" text-anchor="middle" fill="#444">{esc(m["label"])}</text>')
            continue
        _s, col, tint = C.STORE_OF[n]
        for row, ry0, sgn in ((m["top"], y, 1), (m["bot"], y + m["h"] - OVAL_H, -1)):
            tot = sum(ow(a) for a, _ in row) + 8 * (len(row) - 1)
            cx = x + (m["w"] - tot) / 2
            for a, pk in row:
                w = ow(a)
                ex, ey = cx + w / 2, ry0 + OVAL_H / 2
                o.append(f'<line x1="{ex:.1f}" y1="{ey + sgn * OVAL_H / 2:.1f}" x2="{min(max(ex, x + 8), x + m["w"] - 8):.1f}" '
                         f'y2="{ry if sgn == 1 else ry + rh:.1f}" stroke="#777" stroke-width="1"/>'
                         f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" rx="{w / 2:.1f}" ry="{OVAL_H / 2}" fill="#fff" stroke="{col}" '
                         f'stroke-width="1.4"/><text x="{ex:.1f}" y="{ey + 4.5:.1f}" font-size="{FS_ATTR}" text-anchor="middle" '
                         f'fill="#111"{" text-decoration=\"underline\" font-weight=\"600\"" if pk else ""}>{esc(a)}</text>')
                cx += w + 8
        o.append(f'<rect x="{x:.1f}" y="{ry:.1f}" width="{m["w"]}" height="{rh:.1f}" fill="{tint}" stroke="{col}" stroke-width="2.2"/>'
                 f'<text x="{x + m["w"] / 2:.1f}" y="{ry + rh / 2 + 6:.1f}" font-size="{FS_ENT}" font-weight="700" '
                 f'text-anchor="middle" fill="#111">{esc(n)}</text>')
    for i, _r in vrels:
        d = nd[f"d{i}"]
        cx, cy, w = d["x"] + d["width"] / 2, d["y"] + 26, d["width"]
        o.append(f'<path d="M{cx - w / 2:.1f} {cy:.1f} L{cx:.1f} {cy - 26:.1f} L{cx + w / 2:.1f} {cy:.1f} L{cx:.1f} {cy + 26:.1f} Z" '
                 f'fill="#fff" stroke="#222" stroke-width="1.5"/><text x="{cx:.1f}" y="{cy + 4.5:.1f}" font-size="{FS_REL}" '
                 f'text-anchor="middle" fill="#111">{esc(short_label(rels_all[i][4]))}</text>')
    o.append("</svg>")
    path.write_text("\n".join(o), encoding="utf-8")
    return W, H


def main():
    global rels_all
    ents, rels_all = parse(OUT / "er-diagram.mmd")
    assert len(ents) == 20 and len(rels_all) == 35
    page_of = {n: p for _s, p, _t, z in VIEWS for n in ents if zone(n) in z}
    info = {}
    for slug, page, title, mine in VIEWS:
        graph, meta, vrels, ghosts = build(ents, rels_all, mine, page_of)
        vs = [{**opts(), "elk.layered.nodePlacement.strategy": pl, "elk.layered.layering.strategy": ly,
               "elk.randomSeed": str(sd)}
              for pl in ("NETWORK_SIMPLEX", "BRANDES_KOEPF") for ly in ("NETWORK_SIMPLEX", "LONGEST_PATH")
              for sd in range(1, 41)]
        best = min(((score(r["layout"]), r["layout"]) for r in C.run_elk(graph, vs) if "layout" in r), key=lambda t: t[0][0])
        (s, cr, hits), lay = best
        W, H = render(lay, meta, vrels, ents, title, page, OUT / f"er-diagram-chen-{slug}.svg")
        render_png(OUT / f"er-diagram-chen-{slug}.svg", OUT / f"er-diagram-chen-{slug}.png", int(W), int(H), 3)
        pt = FS_ATTR * 277 / W / 0.3528
        print(f"{slug}: rels={len(vrels)} ghosts={ghosts} crossings={cr} hits={hits} canvas={W:.0f}x{H:.0f} "
              f"attr text on A4 ~{pt:.1f}pt")
        info[slug] = {"relationships": [i for i, _ in vrels], "reference_entities": ghosts}
    (OUT / "er-diagram-chen-a4.json").write_text(json.dumps(info, indent=1), "utf-8")


if __name__ == "__main__":
    main()
