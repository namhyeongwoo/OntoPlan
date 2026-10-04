"""Build the interactive Overview and World model figures from the slide sources in figures/.

Each slide is exported to SVG by LibreOffice, which keeps one group per slide shape:

    soffice --headless --convert-to svg overview.pptx      # with latinLnBrk="0" in the slide XML

This script keeps LibreOffice's shapes, re-lays out every text box the way PowerPoint does
(LibreOffice wraps lines differently), re-encodes the embedded pictures as WebP, crops the slide
to its content, and tags each shape with the figure part it belongs to. The result is written to
docs/static/data/figures.js as window.ONTOPLAN_FIGURES.

    python docs/scripts/build_figures.py --lo-dir <dir with overview.svg, world_model.svg> --font-dir <dir>
"""
import argparse
import base64
import io
import json
import re
import zipfile
from pathlib import Path

import uharfbuzz as hb
from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SVG_NS = "http://www.w3.org/2000/svg"
NS = {"s": SVG_NS, "ooo": "http://xml.openoffice.org/svg/export",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
EMU = 360  # EMU per LibreOffice unit (1/100 mm)
PX_PER_UNIT = 0.11  # raster resolution for embedded pictures (about 2x the displayed size)
WRAP_SLACK = 1.03  # PowerPoint fits slightly more per line than the font advances suggest

FONTS = {  # family in the slide -> (CSS family, weight, font file for measuring)
    "프리젠테이션 4 Regular": ("Freesentation", 400, "Freesentation-4Regular.ttf"),
    "프리젠테이션 5 Medium": ("Freesentation", 500, "Freesentation-5Medium.ttf"),
    "프리젠테이션 6 SemiBold": ("Freesentation", 600, "Freesentation-6SemiBold.ttf"),
    "프리젠테이션 7 Bold": ("Freesentation", 700, "Freesentation-7Bold.ttf"),
    "Cascadia Code SemiLight, monospace": ("Cascadia Code", 350, "CascadiaCode-SemiLight.ttf"),
}

# Shapes (by position in the slide's shape list) that make up each part of a figure
PARTS = {
    "overview": {
        "instruction": [4, 8, 26, 27, 28, 97, 115],
        "route-se": [40, 41, 42, 43, 44, 45, 46, 84, 92, 103],
        "scene-query": [0, 47, 48, 49, 50, 51, 85, 107],
        "scene-query-tool": [75, 79, 80, 81, 112],
        "discovered": [52, 53, 54, 55, 56, 57, 58, 108, 114],
        "ask-user": [11, 12, 13, 14, 15, 59, 86, 104],
        "answer": [5, 29, 30, 31, 32, 87, 98],
        "route-tf": [16, 17, 18, 19, 20, 21, 60, 88, 93, 105],
        "formalize": [61, 62, 63, 64, 65, 66, 67, 68, 69, 89, 94, 95, 96, 106],
        "pddl-plan": [1, 70, 71, 72, 73, 74, 90, 109],
        "pddl-plan-tool": [76, 78, 82, 83, 111],
        "final-plan": [22, 23, 24, 25, 110, 116, 117],
        "approve": [6, 33, 34, 35, 36, 91, 99],
        "world-model": [37, 38, 77, 113],
    },
    "world_model": {
        "ask": [193, 194, 195, 196, 197],
        "tell": [198, 199, 200, 201, 202, 203],
        "sparql": [3, 4],
        "schema": [7, 10] + list(range(11, 51)) + list(range(98, 108)),
        "axioms": [9] + list(range(51, 98)) + [170],
        "static": [108, 109, 188] + list(range(112, 134)) + [167, 168, 169] + list(range(172, 180)) + [187],
        "dynamic": [110, 111, 189] + list(range(134, 167)) + list(range(180, 187)),
        "reasoner": [190, 191, 192, 205],
    },
}
# Parts that also light up when another part is active
LINKED = {
    "overview": {},
    "world_model": {"ask": ["sparql"], "tell": ["sparql"], "reasoner": ["inferred", "axioms"]},
}
# Sub-parts that LINKED can refer to
SUBPARTS = {
    "overview": {},
    "world_model": {"inferred": [144, 152, 153, 155, 159, 160]},
}
# Shapes that stay visible with every part (frames, timeline, figure titles)
BASE = {"overview": [2, 3, 7, 9, 10, 39, 100, 101, 102], "world_model": [0, 1, 2, 5, 6, 8, 171, 204, 206, 207]}


class Measure:
    def __init__(self, font_dir):
        self.fonts = {}
        for fam, (_, _, fname) in FONTS.items():
            blob = hb.Blob.from_file_path(str(font_dir / fname))
            font = hb.Font(hb.Face(blob))
            self.fonts[fam] = (font, font.face.upem)

    def width(self, text, family, size, spacing=0.0):
        font, upem = self.fonts[family]
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, {"kern": True, "liga": True})
        return sum(p.x_advance for p in buf.glyph_positions) / upem * size + spacing * len(text)


def slide_shapes(pptx):
    """bodyPr and paragraph properties of each top-level shape, in slide order."""
    with zipfile.ZipFile(pptx) as z:
        tree = etree.fromstring(z.read("ppt/slides/slide1.xml"))
    sp_tree = tree.find(".//p:cSld/p:spTree", NS)
    shapes = []
    for el in sp_tree:
        tag = etree.QName(el).localname
        if tag not in ("sp", "cxnSp", "pic", "grpSp", "graphicFrame"):
            continue
        info = {"tag": tag}
        off, ext = el.find(".//a:xfrm/a:off", NS), el.find(".//a:xfrm/a:ext", NS)
        if off is not None:
            info["box"] = [int(off.get("x")) / EMU, int(off.get("y")) / EMU,
                           int(ext.get("cx")) / EMU, int(ext.get("cy")) / EMU]
        body = el.find(".//p:txBody/a:bodyPr", NS)
        if body is not None:
            info["wrap"] = body.get("wrap", "square") != "none"
            info["anchor"] = body.get("anchor", "t")
            info["ins"] = [int(body.get(k, d)) / EMU for k, d in
                           (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720))]
            # character spacing by typeface (LibreOffice drops it in the SVG export)
            spc = {}
            for rpr in el.iter("{%s}rPr" % NS["a"]):
                latin = rpr.find("a:latin", NS)
                if rpr.get("spc") and latin is not None:
                    spc[latin.get("typeface")] = int(rpr.get("spc")) / 100 * 2540 / 72
            info["spc"] = spc
            paras = []
            for p in el.findall(".//p:txBody/a:p", NS):
                text = "".join(t.text or "" for t in p.iter("{%s}t" % NS["a"]))
                ppr = p.find("a:pPr", NS)
                paras.append({"text": text, "algn": (ppr.get("algn") if ppr is not None else None) or "l"})
            info["paras"] = paras
        shapes.append(info)
    return shapes


def relayout_text(g, shape, measure):
    text_el = g.find("s:text", NS)
    if text_el is None:
        return
    lo_paras = text_el.findall("s:tspan[@class='TextParagraph']", NS)
    paras = [p for p in shape["paras"] if p["text"].strip()]
    holder = etree.Element("holder")
    box, ins = shape["box"], shape["ins"]
    avail = box[2] - ins[0] - ins[2] if shape["wrap"] else float("inf")
    lines_out = []  # (y, x, anchor, runs)

    def spacing(family):
        return shape["spc"].get(family.split(",")[0], 0.0)

    old_h = new_h = 0.0
    for k, lp in enumerate(lo_paras):
        fam0, size0 = lp.get("font-family"), float(lp.get("font-size").rstrip("px"))
        positions = lp.findall("s:tspan[@class='TextPosition']", NS)
        if not positions:
            continue
        algn = paras[k]["algn"] if k < len(paras) else "l"
        # Runs of the paragraph, with LibreOffice's line breaks removed
        runs = []
        for pos in positions:
            for span in pos:
                if span.text is None:
                    continue
                fam = span.get("font-family", fam0)
                size = float(span.get("font-size", "%gpx" % size0).rstrip("px"))
                runs.append([span.text, fam, size, span.get("fill")])
        ys = [float(p.get("y")) for p in positions]
        xs = [float(p.get("x")) for p in positions]
        pitch = (ys[1] - ys[0]) if len(ys) > 1 else 1.2 * max(r[2] for r in runs)
        # Greedy word wrap with kerned widths, as PowerPoint does
        tokens = []
        for text, fam, size, fill in runs:
            for piece in re.findall(r"\S+|\s+", text):
                tokens.append((piece, fam, size, fill))
        lines, cur, cur_w = [], [], 0.0
        for tok in tokens:
            w = measure.width(tok[0], tok[1], tok[2], spacing(tok[1]))
            if tok[0].isspace():
                cur.append(tok); cur_w += w; continue
            if cur and cur_w + w > avail * WRAP_SLACK:
                while cur and cur[-1][0].isspace():
                    cur.pop()
                lines.append(cur); cur, cur_w = [], 0.0
            cur.append(tok); cur_w += w
        while cur and cur[-1][0].isspace():
            cur.pop()
        if cur:
            lines.append(cur)
        old_start, new_start = old_h, new_h
        old_h += pitch * len(ys)
        new_h += pitch * len(lines)
        for j, line in enumerate(lines):
            if algn == "ctr":
                x, anchor = box[0] + ins[0] + (box[2] - ins[0] - ins[2]) / 2, "middle"
            elif algn == "r":
                x, anchor = box[0] + box[2] - ins[2], "end"
            else:
                x, anchor = xs[min(j, len(xs) - 1)], None
            lines_out.append((ys[0] + (new_start - old_start) + pitch * j, x, anchor, line))
    shift = {"t": 0.0, "ctr": -(new_h - old_h) / 2, "b": -(new_h - old_h)}.get(shape["anchor"], 0.0)
    for y, x, anchor, line in lines_out:
        t = etree.SubElement(holder, "{%s}text" % SVG_NS)
        t.set("x", "%g" % round(x))
        t.set("y", "%g" % round(y + shift))
        if anchor:
            t.set("text-anchor", anchor)
        # merge neighbouring tokens with the same style
        merged = []
        for piece, fam, size, fill in line:
            if merged and merged[-1][1:] == [fam, size, fill]:
                merged[-1][0] += piece
            else:
                merged.append([piece, fam, size, fill])
        for piece, fam, size, fill in merged:
            css, weight, _ = FONTS[fam]
            s = etree.SubElement(t, "{%s}tspan" % SVG_NS)
            s.set("font-family", css)
            s.set("font-weight", str(weight))
            s.set("font-size", "%g" % size)
            if fill:
                s.set("fill", fill)
            if spacing(fam):
                s.set("letter-spacing", "%g" % round(spacing(fam), 1))
            s.text = piece
    g.remove(text_el)
    for t in list(holder):
        g.append(t)


def reencode_images(g):
    for img in g.iter("{%s}image" % SVG_NS):
        href = img.get("{http://www.w3.org/1999/xlink}href")
        if not href or not href.startswith("data:image"):
            continue
        raw = base64.b64decode(href.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        w = max(48, round(float(img.get("width")) * PX_PER_UNIT))
        h = max(1, round(w * im.height / im.width))
        if w < im.width:
            im = im.resize((w, h), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82, method=6)
        img.attrib.pop("{http://www.w3.org/1999/xlink}href")
        img.set("href", "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode())


def build(name, lo_svg, pptx, measure):
    tree = etree.parse(str(lo_svg))
    page = tree.xpath('//s:g[@class="Page" and @ooo:name="page1"]', namespaces=NS)[0]
    kids = list(page)
    shapes = slide_shapes(pptx)
    assert len(kids) == len(shapes), (len(kids), len(shapes))
    part_of = {}
    for part, idx in PARTS[name].items():
        for i in idx:
            part_of[i] = part
    sub_of = {}
    for part, idx in SUBPARTS[name].items():
        for i in idx:
            sub_of[i] = part
    x0 = y0 = float("inf"); x1 = y1 = float("-inf")
    root = etree.Element("{%s}svg" % SVG_NS, nsmap={None: SVG_NS})
    for i, (kid, shape) in enumerate(zip(kids, shapes)):
        g = kid[0]
        bb = g.find("s:rect[@class='BoundingBox']", NS)
        bx, by, bw, bh = (float(bb.get(a)) for a in ("x", "y", "width", "height"))
        x0, y0, x1, y1 = min(x0, bx), min(y0, by), max(x1, bx + bw), max(y1, by + bh)
        if i in part_of and shape["tag"] != "cxnSp":
            # keep the bounding box as an invisible hover target, so a part reacts across its gaps
            bb.set("class", "hit")
            bb.set("pointer-events", "all")
        else:
            g.remove(bb)
        if shape.get("paras"):
            relayout_text(g, shape, measure)
        reencode_images(g)
        out = etree.SubElement(root, "{%s}g" % SVG_NS)
        out.set("class", "fs")
        if i in part_of:
            out.set("data-part", part_of[i])
        elif i not in BASE[name]:
            raise SystemExit("%s: shape %d is in no part" % (name, i))
        if i in sub_of:
            out.set("data-sub", sub_of[i])
        for child in list(g):
            out.append(child)
    pad = 120
    root.set("viewBox", "%d %d %d %d" % (x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad))
    root.set("class", "figsvg")
    root.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    root.set("fill-rule", "evenodd")
    root.set("stroke-linejoin", "round")
    s = etree.tostring(root, encoding="unicode")
    s = re.sub(r"\s(ooo|presentation|smil|anim):[\w-]+=\"[^\"]*\"", "", s)
    s = re.sub(r">\s*\n\s*<", "><", s)
    s = re.sub(r"(\d+\.\d{1,})", lambda m: "%g" % round(float(m.group(1)), 1), s)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-dir", type=Path, required=True, help="LibreOffice SVG exports")
    ap.add_argument("--font-dir", type=Path, required=True,
                    help="TTF files of Freesentation 5-7 and Cascadia Code SemiLight, for measuring text")
    args = ap.parse_args()
    measure = Measure(args.font_dir)
    figs = {}
    for name in ("overview", "world_model"):
        figs[name] = {"svg": build(name, args.lo_dir / (name + ".svg"), ROOT / "figures" / (name + ".pptx"), measure),
                      "linked": LINKED[name]}
    out = ROOT / "docs/static/data/figures.js"
    out.write_text("/* Generated by docs/scripts/build_figures.py from figures/*.pptx */\n"
                   "window.ONTOPLAN_FIGURES = " + json.dumps(figs, ensure_ascii=False) + ";\n")
    print(out, out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
