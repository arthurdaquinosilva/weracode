#!/usr/bin/env python3
"""Customise BitstromWera Nerd Font (Bitstream Vera Sans Mono) using only its own outlines.

For every style and Nerd Font variant in source/ (output goes to fonts/):
  * slashed zero: Vera's dotted zero with the dot replaced by a diagonal stroke
  * hyphen / soft hyphen widened and centred on the "+" bar; en/em dash centred too
  * . , : ; dots enlarged so punctuation reads better at small sizes
  * asterisk enlarged and lowered toward the middle of lowercase letters
  * ~ centred on the "+" bar
  * { } given the same height as ( ) and [ ]
  * underscore rebuilt as a bar that overhangs its cell, so "__" joins into one line
  * taller line height (S/M/L presets), with box-drawing, block and Powerline glyphs
    stretched to keep filling the cell
  * coding ligatures (-> => == != >= :: // ...), same width as the characters they replace
  * italic flag fixed in head.macStyle for the Obliques
  * family renamed (the Bitstream Vera license requires modified versions to be renamed)

Every changed glyph is derived from the font's own glyphs; nothing is copied from other fonts.

Usage: python3 build.py [--line S|M|L|vera] [--family NAME] [--out DIR]
Requires: pip install fonttools skia-pathops
"""
import argparse
import math
import re
import sys
from pathlib import Path

import pathops
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram

HERE = Path(__file__).resolve().parent

# (ascent, descent) in 2048 UPM. Vera's own is 1901/483; the others add 100/200/400 each side.
LINE = {"vera": (1901, 483), "S": (2001, 583), "M": (2101, 683), "L": (2301, 883)}
VERA_ASC, VERA_DESC = LINE["vera"]
# Glyphs that must fill the whole line cell: stretched vertically with the line height.
STRETCH_RANGES = [(0x2500, 0x259F), (0xE0A0, 0xE0A3), (0xE0B0, 0xE0D7)]

HYPHEN_WIDTH = 0.6        # of the advance width
DOT_SCALE = 1.25          # . , : ;
ASTERISK_SCALE = 1.15
ASTERISK_CENTER_Y = 920   # Vera's sits at ~1053, near the cap height
SLASH_WEIGHT = 0.85       # zero slash thickness, relative to the "|" stem
UNDERSCORE_OVERHANG = 20  # units past each side of the cell

# Longest first, so "===" wins over "==". "||" is deliberately left out: htop draws its
# meters with "|", and "|>" is skipped after another "|" for the same reason.
LIGATURES = ["<!--", "<=>", "-->", "===", "!==", "->", "=>", "<-", "==", "!=", ">=", "<=",
             "::", "...", "&&", "//", "/*", "*/", "|>", "<>", "++", "--"]
ARROWS = {"->", "-->", "<-", "=>", "<=>"}
LIGATURE_TIGHTEN = 0.5    # gaps between the parts of a ligature shrink to this fraction,
LIGATURE_MIN_GAP = 0.8    # but not below this fraction of the "|" stem


# --- outline helpers -------------------------------------------------------------------

def outline(glyphset, name):
    pen = DecomposingRecordingPen(glyphset)
    glyphset[name].draw(pen)
    return pen.value


def replay(rec, pen):
    for op, args in rec:
        getattr(pen, op)(*args)


def contours(rec):
    out, cur = [], []
    for op, args in rec:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            out.append(cur)
            cur = []
    return out


def bounds(rec):
    pen = BoundsPen(None)
    replay(rec, pen)
    return pen.bounds


def transformed(rec, matrix):
    pen = RecordingPen()
    replay(rec, TransformPen(pen, matrix))
    return pen.value


def scale_about(sx, sy, cx, cy, dx=0, dy=0):
    return (sx, 0, 0, sy, cx - sx * cx + dx, cy - sy * cy + dy)


class Glyphs:
    """Read/write access to one font's glyphs, working in upright (un-slanted) space."""

    def __init__(self, font):
        self.font = font
        self.cmap = font.getBestCmap()
        self.gs = font.getGlyphSet()
        self.slant = math.tan(math.radians(-font["post"].italicAngle))

    def raw(self, cp):
        """Outline of a codepoint as stored ("|" and "+" are upright even in the Obliques)."""
        return outline(self.gs, self.cmap[cp])

    def get(self, cp):
        """Outline of a codepoint with the italic slant removed."""
        return transformed(outline(self.gs, self.cmap[cp]), (1, 0, -self.slant, 1, 0, 0))

    def advance(self, cp):
        return self.font["hmtx"][self.cmap[cp]][0]

    def put(self, cp, rec, slanted=True):
        """Store an upright outline for cp, re-applying the slant unless slanted=False."""
        name = self.cmap[cp]
        if slanted:
            rec = transformed(rec, (1, 0, self.slant, 1, 0, 0))
        set_glyph(self.font, name, lambda pen: replay(rec, pen), self.font["hmtx"][name][0])


def set_glyph(font, name, draw, advance):
    """Store a simple (decomposed, unhinted) glyph drawn by `draw(pen)`."""
    pen = TTGlyphPen(None)
    draw(Cu2QuPen(pen, max_err=1, reverse_direction=False))
    glyph = pen.glyph()
    glyph.program = ttProgram.Program()
    glyph.program.fromBytecode(b"")
    glyf = font["glyf"]
    glyf[name] = glyph
    glyph.recalcBounds(glyf)
    font["hmtx"][name] = (advance, getattr(glyph, "xMin", 0))
    if glyph.numberOfContours:
        head = font["head"]
        head.xMin, head.yMin = min(head.xMin, glyph.xMin), min(head.yMin, glyph.yMin)
        head.xMax, head.yMax = max(head.xMax, glyph.xMax), max(head.yMax, glyph.yMax)


def to_path(rec):
    path = pathops.Path()
    replay(rec, path.getPen())
    return path


def from_path(path):
    pen = RecordingPen()
    path.draw(pen)
    return pen.value


# --- glyph edits -----------------------------------------------------------------------

def stem_width(g):
    x0, _, x1, _ = bounds(g.raw(ord("|")))
    return x1 - x0


def plus_bar_center(g):
    # The horizontal arm of "+" spans the full glyph width; its y-range is the math axis.
    points = [pt for op, args in g.raw(ord("+")) for pt in args]
    xmin = min(x for x, _ in points)
    ys = [y for x, y in points if x == xmin]
    return (min(ys) + max(ys)) / 2


def slashed_zero(g):
    parts = sorted(contours(g.get(ord("0"))), key=lambda c: -area(bounds(c)))
    outer, inner = parts[0], parts[1]  # parts[2] is Vera's centre dot, dropped
    ix0, iy0, ix1, iy1 = bounds(inner)
    # Diagonal stroke through the counter, bottom-left to top-right, extended past the
    # walls and then clipped to the outer contour so it only fills the counter.
    (ax, ay), (bx, by) = (ix0, iy0), (ix1, iy1)
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    ax, ay, bx, by = ax - ux * 200, ay - uy * 200, bx + ux * 200, by + uy * 200
    half = stem_width(g) * SLASH_WEIGHT / 2
    nx, ny = -uy * half, ux * half
    band = [("moveTo", ((ax + nx, ay + ny),)), ("lineTo", ((bx + nx, by + ny),)),
            ("lineTo", ((bx - nx, by - ny),)), ("lineTo", ((ax - nx, ay - ny),)), ("closePath", ())]
    ring = pathops.op(to_path(outer), to_path(inner), pathops.PathOp.DIFFERENCE)
    slash = pathops.op(to_path(band), to_path(outer), pathops.PathOp.INTERSECTION)
    result = pathops.op(ring, slash, pathops.PathOp.UNION, clockwise=True)
    g.put(ord("0"), from_path(result))


def area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def dashes(g):
    axis = plus_bar_center(g)
    for cp in (0x2D, 0xAD, 0x2010, 0x2011):
        if cp not in g.cmap:
            continue
        rec = g.get(cp)
        x0, y0, x1, y1 = bounds(rec)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sx = HYPHEN_WIDTH * g.advance(cp) / (x1 - x0)
        g.put(cp, transformed(rec, scale_about(sx, 1, cx, cy, g.advance(cp) / 2 - cx, axis - cy)))
    for cp in (0x2013, 0x2014, 0x7E):
        rec = g.get(cp)
        _, y0, _, y1 = bounds(rec)
        g.put(cp, transformed(rec, (1, 0, 0, 1, 0, axis - (y0 + y1) / 2)))


def dots(g):
    for cp in (0x2E, 0x2C, 0x3A, 0x3B):
        cx = g.advance(cp) / 2
        out = []
        for c in contours(g.get(cp)):
            _, y0, _, y1 = bounds(c)
            # Dots on the baseline grow from the baseline; raised dots grow from their centre.
            cy = 0 if y0 < 100 else (y0 + y1) / 2
            out += transformed(c, scale_about(DOT_SCALE, DOT_SCALE, cx, cy))
        g.put(cp, out)


def asterisk(g):
    rec = g.get(0x2A)
    x0, y0, x1, y1 = bounds(rec)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    g.put(0x2A, transformed(rec, scale_about(ASTERISK_SCALE, ASTERISK_SCALE, cx, cy,
                                             g.advance(0x2A) / 2 - cx, ASTERISK_CENTER_Y - cy)))


def braces(g):
    _, top_lo, _, top_hi = bounds(g.get(0x5B))  # "[" sets the bracket height
    for cp in (0x7B, 0x7D):
        rec = g.get(cp)
        _, y0, _, y1 = bounds(rec)
        sy = (top_hi - top_lo) / (y1 - y0)
        g.put(cp, transformed(rec, (1, 0, 0, sy, 0, top_lo - sy * y0)))


def underscore(g):
    adv = g.advance(0x5F)
    thickness = stem_width(g) * 0.9
    top = -stem_width(g)
    x0, x1 = -UNDERSCORE_OVERHANG, adv + UNDERSCORE_OVERHANG
    bar = [("moveTo", ((x0, top - thickness),)), ("lineTo", ((x0, top),)), ("lineTo", ((x1, top),)),
           ("lineTo", ((x1, top - thickness),)), ("closePath", ())]
    g.put(0x5F, bar, slanted=False)  # Vera's oblique underscore is upright too


def stretch_cells(font, asc, desc):
    if (asc, desc) == (VERA_ASC, VERA_DESC):
        return 0
    scale = (asc + desc) / (VERA_ASC + VERA_DESC)
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    names = {name for cp, name in cmap.items() if any(lo <= cp <= hi for lo, hi in STRETCH_RANGES)}
    recs = {name: outline(gs, name) for name in names}
    # y' = (y + VERA_DESC) * scale - desc : maps the old cell [-483, 1901] onto the new one
    matrix = (1, 0, 0, scale, 0, -desc + VERA_DESC * scale)
    for name, rec in recs.items():
        set_glyph(font, name, lambda pen, rec=rec: replay(rec, TransformPen(pen, matrix)),
                  font["hmtx"][name][0])
    return len(recs)


# --- ligatures -------------------------------------------------------------------------
#
# Each ligature keeps the width of the characters it replaces: the last character becomes
# the ligature glyph, drawn leftwards over the previous cells, and the others become empty
# spacers. The rules go in "calt" (contextual alternates), which editors and ligature-aware
# terminals enable by default.

def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]
    return half(pts) + half(reversed(pts))


def polygon(points):
    return ([("moveTo", (points[0],))] + [("lineTo", (p,)) for p in points[1:]]
            + [("closePath", ())])


def points_of(rec):
    return [pt for _, args in rec for pt in args]


def union(recs):
    result = None
    for rec in recs:
        path = to_path(rec)
        result = path if result is None else pathops.op(result, path, pathops.PathOp.UNION)
    return pathops.op(result, pathops.Path(), pathops.PathOp.UNION, clockwise=True)


def flat(recs):
    return [op for rec in recs for op in rec]


def placed(g, ch, cell):
    """Glyph outline as stored (upright or slanted), moved into the given cell."""
    return transformed(g.raw(ord(ch)), (1, 0, 0, 1, cell * g.advance(ord(ch)), 0))


def joined_bars(g, ch, first, last, start=None, end=None):
    """Bars of "-" or "=" in cells first..last merged into continuous bars. start/end
    optionally stretch them to reach an x position (an arrowhead tip)."""
    bars = []
    for i, bar in enumerate(contours(g.raw(ord(ch)))):
        x0, _, x1, _ = bounds(bar)
        shifts = [first * g.advance(ord(ch)), last * g.advance(ord(ch))]
        if start is not None:
            shifts[0] = start - x0
        if end is not None:
            shifts[1] = end - x1
        pts = [(x + dx, y) for dx in shifts for x, y in points_of(bar)]
        bars.append(polygon(convex_hull(pts)))
    return bars


def arrow(g, seq):
    """->  -->  <-  =>  <=> : a shaft of "-" or "=" bars running into the arrowheads."""
    n, shaft = len(seq), "=" if "=" in seq else "-"
    heads, start, end = [], None, None
    allowed_x = [-10 ** 5, 10 ** 5]  # shaft is kept between the heads' open sides ...
    hulls = []                        # ... or inside a head's outline
    if seq[0] == "<":
        head = placed(g, "<", 0)
        heads.append(head)
        hulls.append(polygon(convex_hull(points_of(head))))
        x0, _, x1, _ = bounds(head)
        start = x0
        allowed_x[0] = min(x for x, _ in points_of(head) if x > (x0 + x1) / 2)
    if seq[-1] == ">":
        head = placed(g, ">", n - 1)
        heads.append(head)
        hulls.append(polygon(convex_hull(points_of(head))))
        x0, _, x1, _ = bounds(head)
        end = x1
        allowed_x[1] = max(x for x, _ in points_of(head) if x < (x0 + x1) / 2)
    first = 1 if seq[0] == "<" else 0
    last = n - 2 if seq[-1] == ">" else n - 1
    bars = joined_bars(g, shaft, first, last, start, end)
    box = polygon([(allowed_x[0], -10 ** 4), (allowed_x[0], 10 ** 4),
                   (allowed_x[1], 10 ** 4), (allowed_x[1], -10 ** 4)])
    region = to_path(box)
    for hull in hulls:
        region = pathops.op(region, to_path(hull), pathops.PathOp.UNION)
    clipped = [from_path(pathops.op(to_path(bar), region, pathops.PathOp.INTERSECTION))
               for bar in bars]
    return heads + clipped


def ligature_parts(g, seq):
    """The ligature as a list of parts, each a list of shapes (a glyph or a bar); parts are
    later moved closer together, then all shapes are merged."""
    if seq in ARROWS:
        return [arrow(g, seq)]
    parts, i = [], 0
    while i < len(seq):
        j = i
        while j + 1 < len(seq) and seq[j + 1] == seq[i] and seq[i] in "=-":
            j += 1
        if j > i:
            parts.append(joined_bars(g, seq[i], i, j))  # == === -- run
        else:
            parts.append([placed(g, seq[i], i)])
        i = j + 1
    return parts


def tighten(g, parts):
    """Shrink the gaps between parts, keeping the group centred where it was."""
    if len(parts) == 1:
        return parts[0]
    min_gap = stem_width(g) * LIGATURE_MIN_GAP
    boxes = [bounds(flat(p)) for p in parts]
    shift, shifts = 0, [0]
    for a, b in zip(boxes, boxes[1:]):
        gap = b[0] - a[2]
        shift += max(gap * LIGATURE_TIGHTEN, min(gap, min_gap)) - gap
        shifts.append(shift)
    old_center = (boxes[0][0] + boxes[-1][2]) / 2
    new_center = (boxes[0][0] + boxes[-1][2] + shifts[-1]) / 2
    out = []
    for part, dx in zip(parts, shifts):
        out += [transformed(shape, (1, 0, 0, 1, dx + old_center - new_center, 0)) for shape in part]
    return out


def ligatures(g):
    font, cmap = g.font, g.cmap
    names = [[cmap[ord(c)] for c in seq] for seq in LIGATURES]
    order = font.getGlyphOrder()
    new = []
    for seq, gnames in zip(LIGATURES, names):
        base = "_".join(gnames)
        new += [base + ".liga", base + ".spacer"]
    font.setGlyphOrder(order + new)

    fea = ["languagesystem DFLT dflt;", "languagesystem latn dflt;"]
    for k, (seq, gnames) in enumerate(zip(LIGATURES, names)):
        adv = g.advance(ord(seq[-1]))
        liga, spacer = "_".join(gnames) + ".liga", "_".join(gnames) + ".spacer"
        # Shapes are merged whole (not contour by contour) so counters like those of "&" stay open.
        shapes = tighten(g, ligature_parts(g, seq))
        path = union([transformed(shape, (1, 0, 0, 1, -(len(seq) - 1) * adv, 0)) for shape in shapes])
        set_glyph(font, liga, lambda pen, path=path: path.draw(pen), adv)
        set_glyph(font, spacer, lambda pen: None, adv)

        first, rest = gnames[0], " ".join(gnames[1:])
        fea.append(f"lookup liga{k} {{")
        # Not inside a longer run of the same characters ("====", "---", "///").
        fea.append(f"  ignore sub {first} {first}' {rest};")
        fea.append(f"  ignore sub {first}' {rest} {gnames[-1]};")
        if seq == "|>":
            fea.append("  ignore sub bar bar' greater;")
        for i, name in enumerate(gnames):
            back = " ".join([spacer] * i)
            ahead = " ".join(gnames[i + 1:])
            fea.append(f"  sub {back} {name}' {ahead} by {spacer if i < len(gnames) - 1 else liga};")
        fea.append(f"}} liga{k};")
    fea.append("feature calt {")
    fea += [f"  lookup liga{k};" for k in range(len(LIGATURES))]
    fea.append("} calt;")
    addOpenTypeFeaturesFromString(font, "\n".join(fea), tables=["GSUB"])
    return len(LIGATURES)


# --- font ------------------------------------------------------------------------------

def patch(src, dst, family, line):
    # recalcBBoxes=False: some Nerd icons have stale stored bounds, and recomputing them
    # would shift those icons by a unit. Glyphs we write get exact bounds in set_glyph().
    font = TTFont(src, recalcBBoxes=False)
    g = Glyphs(font)
    # Edits read the original outlines, so order matters only where one edit measures a
    # glyph another changes ("|" and "+" are never changed; "[" is not changed).
    slashed_zero(g)
    dashes(g)
    dots(g)
    asterisk(g)
    braces(g)
    underscore(g)
    ligatures(g)  # after the edits above: ligatures are built from the edited glyphs
    asc, desc = LINE[line]
    stretched = stretch_cells(font, asc, desc)

    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = asc, -desc, 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, -desc, 0
    os2.usWinAscent, os2.usWinDescent = asc, desc
    # The original Obliques set the italic bit in OS/2 but not in head.macStyle; macOS uses
    # macStyle to link styles into one family.
    if os2.fsSelection & 1:
        font["head"].macStyle |= 0b10

    for rec in font["name"].names:
        text = rec.toUnicode()
        if rec.nameID in (1, 3, 4, 16, 18, 21):
            text = text.replace("BitstromWera", family)
        elif rec.nameID == 6:
            text = text.replace("BitstromWera", family.replace(" ", ""))
        elif rec.nameID == 5:
            text += f";{family} (slashed zero, punctuation and line height adjustments)"
        elif rec.nameID == 13:
            text += ("\r\n\r\nModified from Bitstream Vera Sans Mono (Nerd Fonts patched): slashed "
                     "zero, adjusted punctuation and line height.")
        rec.string = text

    # Point/contour maxima for the new glyphs (stored bounds are left alone, see above).
    font["maxp"].recalc(font)
    font.save(dst)
    return stretched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--line", choices=list(LINE), default="S", help="line height preset, or vera")
    ap.add_argument("--family", default="WeraCode", help="new family name (must not contain Bitstream/Vera)")
    ap.add_argument("--out", default=str(HERE / "fonts"))
    args = ap.parse_args()
    if re.search(r"bitstream|vera", args.family, re.I):
        sys.exit("The Bitstream Vera license forbids 'Bitstream' or 'Vera' in a modified font's name.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for src in sorted((HERE / "source").glob("BitstromWeraNerdFont*-*.ttf")):
        dst = out / src.name.replace("BitstromWera", args.family.replace(" ", ""))
        stretched = patch(src, dst, args.family, args.line)
        print(f"{dst.name}: 10 glyphs reshaped, {stretched} stretched")


if __name__ == "__main__":
    main()
