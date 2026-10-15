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
  * 77 coding ligatures in the style of JetBrains Mono (→ ⇒ ≤ ≠ ≡ ◇ ▷ ...), same width
    as the characters they replace
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
# Coding ligatures in the style of JetBrains Mono: arrows, comparisons and a few operators
# become symbols (→ ⇒ ≤ ≠ ◇ ▷ ...), the rest keep their characters with tighter spacing
# and aligned heights. Every ligature keeps the width of the characters it replaces: the
# last character becomes the ligature glyph, drawn leftwards over the previous cells, and
# the others become empty spacers. The rules go in "calt" (contextual alternates), which
# editors and ligature-aware terminals enable by default.
#
# Left out on purpose: anything with "||", "[|", "|]", "|-" or "-|" (htop meters and its
# ASCII process tree), and ligatures containing "|" are skipped next to "|", "[" or "]";
# "#" sequences (Markdown headings); "--" (command-line flags).

LIGATURES = {
    # arrows: a shaft of "-", "=" or "~" with optional heads ("<", ">") and tail ("|")
    "->": "arrow", "-->": "arrow", "<-": "arrow", "<--": "arrow", "<->": "arrow",
    "<-->": "arrow", "|->": "arrow", "=>": "arrow", "==>": "arrow", "<==": "arrow",
    "<=>": "arrow", "<==>": "arrow", "|=>": "arrow", "~>": "arrow", "~~>": "arrow",
    "<~": "arrow", "<~~": "arrow", "<~>": "arrow", "~~": "arrow",
    # symbols
    "<=": "less_equal", ">=": "greater_equal", "!=": "not_equal", "!==": "not_equal",
    "==": "bars", "===": "bars", "<>": "diamond", "|>": "triangle", "<|": "triangle",
    "<|>": "triangle",
    # characters kept, spacing and heights adjusted
    "::": "tight", ":::": "tight", ":=": "tight", "=:": "tight", "::=": "tight",
    "<:": "tight", ":<": "tight", ":>": "tight", ">:": "tight", "..": "tight",
    "...": "tight", "..<": "tight", "..=": "tight", "?.": "tight", "??": "tight",
    "?:": "tight", "?=": "tight", "!!": "tight", ";;": "tight", "&&": "tight",
    "++": "tight", "+++": "tight", "//": "tight", "///": "tight", "/*": "tight",
    "*/": "tight", "/**": "tight", "<<": "tight", ">>": "tight", "<<<": "tight",
    ">>>": "tight", "<<=": "tight", ">>=": "tight", "<*": "tight", "<*>": "tight",
    "*>": "tight", "<$": "tight", "<$>": "tight", "$>": "tight", "<+": "tight",
    "<+>": "tight", "+>": "tight", "</": "tight", "/>": "tight", "</>": "tight",
    "{{": "tight", "}}": "tight", "<!--": "tight",
}
LIGATURE_TIGHTEN = 0.5    # in "tight" ligatures gaps shrink to this fraction,
LIGATURE_MIN_GAP = 0.8    # but not below this fraction of the "|" stem
# === as three light, airy bars (proportions after JetBrains Mono's):
TRIPLE_BAR_WEIGHT = 0.75  # bar thickness, relative to an "=" bar
TRIPLE_BAR_GAP = 3.0      # gap between bars, relative to their thickness
# Sizes relative to half the height of ">" (h) and the cell width (w), measured from
# JetBrains Mono's ligatures (centre-line sizes; the stroke adds a little outside):
ARROW_HEAD = (1.0, 1.0)           # → arrowhead: half-height × h, depth × h
DOUBLE_ARROW_HEAD = (1.05, 1.55)  # ⇒ arrowhead: longer arms for a sharper tip
ARROW_STYLE = "open"              # → heads: "open" chevron, "filled" triangle, "barbed" ➤
DOUBLE_ARROW_STYLE = "open"       # ⇒ heads, same choices
ARROW_NOTCH = 0.35                # "barbed": how far the back of the head is cut in
LESS_EQUAL = (0.95, 1.0, 0.85)    # ≤ ≥: chevron half-height × h, width × w, bar drop × h
DIAMOND = (1.0, 0.72)             # ◇: half-height × h, half-width × w
TRIANGLE = (1.45, 1.05)           # ▷: half-height × h, width × w
NOT_EQUAL = (1.25, 0.35)          # ≠ slash: half-height × h, horizontal run per unit height
WAVE_AMPLITUDE = 0.25             # ~~ waves: amplitude × h


class Measures:
    """Stroke weights and positions taken from the font's own glyphs."""

    def __init__(self, g):
        self.adv = g.advance(ord("="))
        self.axis = plus_bar_center(g)
        _, y0, _, y1 = bounds(g.raw(ord("-")))
        self.thin = y1 - y0  # hyphen thickness: single arrows, waves
        bars = sorted((bounds(c) for c in contours(g.raw(ord("=")))), key=lambda b: b[1])
        self.bar = bars[0][3] - bars[0][1]  # "=" bar thickness: double arrows, ≤ ≠ ◇ ▷
        self.bar_gap = bars[1][1] - bars[0][3]
        self.margin = bars[0][0]  # side bearing of "=": where arrows start and end
        _, y0, _, y1 = bounds(g.raw(ord(">")))
        self.h = (y1 - y0) / 2
        self.wave = WAVE_AMPLITUDE * self.h


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


def rect(x0, y0, x1, y1):
    return polygon([(x0, y0), (x0, y1), (x1, y1), (x1, y0)])


def points_of(rec):
    return [pt for _, args in rec for pt in args]


def union(recs):
    result = None
    for rec in recs:
        path = to_path(rec)
        result = path if result is None else pathops.op(result, path, pathops.PathOp.UNION)
    return pathops.op(result, pathops.Path(), pathops.PathOp.UNION, clockwise=True)


def clip(rec, region):
    return from_path(pathops.op(to_path(rec), region, pathops.PathOp.INTERSECTION))


def flat(recs):
    return [op for rec in recs for op in rec]


def stroke(points, width, closed=False):
    """Outline of a polyline drawn with a pen of the given width, mitred corners."""
    h, n = width / 2, len(points)

    def unit(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy)
        return dx / d, dy / d

    left, right = [], []
    for i, (x, y) in enumerate(points):
        ins = unit(points[i - 1], points[i]) if closed or i > 0 else None
        outs = unit(points[i], points[(i + 1) % n]) if closed or i < n - 1 else None
        normals = [(-d[1], d[0]) for d in (ins, outs) if d]
        mx, my = sum(v[0] for v in normals), sum(v[1] for v in normals)
        m = math.hypot(mx, my)
        mx, my = mx / m, my / m
        k = h / (mx * normals[0][0] + my * normals[0][1])
        left.append((x + mx * k, y + my * k))
        right.append((x - mx * k, y - my * k))
    if not closed:
        return polygon(left + right[::-1])
    outer, inner = sorted((left, right), key=lambda p: -area(bounds(polygon(p))))
    return from_path(pathops.op(to_path(polygon(outer)), to_path(polygon(inner)),
                                pathops.PathOp.DIFFERENCE))


def chevron(tip, direction, half_height, depth, width):
    """Open arrowhead pointing right (direction=1) or left (-1): its outer corner lands on
    `tip`, and the arm ends are cut upright `depth` behind it."""
    tx, ty = tip
    miter = width / 2 / math.sin(math.atan2(half_height, depth))
    vx = tx - direction * miter  # centre-line vertex, so the outer corner is at the tip
    back = vx - direction * depth * 1.5
    arms = stroke([(back, ty + half_height * 1.5), (vx, ty), (back, ty - half_height * 1.5)], width)
    cut = tx - direction * depth
    return clip(arms, to_path(rect(cut, -10 ** 4, cut + direction * 10 ** 4, 10 ** 4)))


def arrowhead(tip, direction, half_height, depth, width, style):
    """Head of a single arrow: an open chevron, or a solid "filled"/"barbed" triangle."""
    if style == "open":
        return chevron(tip, direction, half_height, depth, width)
    tx, ty = tip
    back = tx - direction * depth
    pts = [(tx, ty), (back, ty + half_height)]
    if style == "barbed":
        pts.append((tx - direction * depth * (1 - ARROW_NOTCH), ty))
    pts.append((back, ty - half_height))
    return polygon(pts)


def placed(g, ch, cell):
    """Glyph outline as stored (upright or slanted), moved into the given cell."""
    return transformed(g.raw(ord(ch)), (1, 0, 0, 1, cell * g.advance(ord(ch)), 0))


def joined_bars(g, ch, first, last):
    """Bars of "-" or "=" in cells first..last merged into continuous bars."""
    adv = g.advance(ord(ch))
    return [polygon(convex_hull([(x + dx, y) for dx in (first * adv, last * adv)
                                 for x, y in points_of(bar)]))
            for bar in contours(g.raw(ord(ch)))]


def triple_bars(g, first, last):
    """Three bars across cells first..last, so strict === reads differently from ==."""
    bars = [bounds(bar) for bar in contours(g.raw(ord("=")))]
    x0, y0 = min(b[0] for b in bars), min(b[1] for b in bars)
    x1, y1 = max(b[2] for b in bars), max(b[3] for b in bars)
    adv = g.advance(ord("="))
    thickness = (bars[0][3] - bars[0][1]) * TRIPLE_BAR_WEIGHT
    gap = thickness * TRIPLE_BAR_GAP
    top = (y0 + y1) / 2 + 1.5 * thickness + gap
    left, right = x0 + first * adv, x1 + last * adv
    return [rect(left, top - k * (thickness + gap) - thickness, right, top - k * (thickness + gap))
            for k in range(3)]


def wave(m, x0, x1):
    """A "~" line from x0 to x1, starting and ending on the axis."""
    period = m.adv
    halves = max(1, round(2 * (x1 - x0) / period))
    steps = halves * 12
    pts = [(x0 + (x1 - x0) * i / steps,
            m.axis + m.wave * math.sin(math.pi * halves * i / steps)) for i in range(steps + 1)]
    return stroke(pts, m.thin)


def arrow(g, m, seq):
    n = len(seq)
    left, right = m.margin, n * m.adv - m.margin
    shaft = next(c for c in seq if c in "-=~")
    width = m.bar if shaft == "=" else m.thin
    hh, depth = DOUBLE_ARROW_HEAD if shaft == "=" else ARROW_HEAD
    hh, depth = hh * m.h, depth * m.h
    shapes, hulls = [], []
    open_x = [-10 ** 4, 10 ** 4]  # shafts may run freely between the heads' open sides
    style = DOUBLE_ARROW_STYLE if shaft == "=" else ARROW_STYLE
    if seq[0] == "<":
        shapes.append(arrowhead((left, m.axis), -1, hh, depth, width, style))
        open_x[0] = left + depth
    if seq[-1] == ">":
        shapes.append(arrowhead((right, m.axis), 1, hh, depth, width, style))
        open_x[1] = right - depth
    hulls = [polygon(convex_hull(points_of(s))) for s in shapes]
    start = left
    if seq[0] == "|":  # maps-to tail: ↦ ⤇
        shapes.append(rect(left, m.axis - hh, left + width, m.axis + hh))
        start = left + width / 2
    if shaft == "-":
        lines = [rect(start, m.axis - width / 2, right, m.axis + width / 2)]
    elif shaft == "=":
        offset = (m.bar_gap + m.bar) / 2
        lines = [rect(start, m.axis + dy - width / 2, right, m.axis + dy + width / 2)
                 for dy in (-offset, offset)]
    else:
        lines = [wave(m, start, right)]
    region = to_path(rect(open_x[0], -10 ** 4, open_x[1], 10 ** 4))
    for hull in hulls:
        region = pathops.op(region, to_path(hull), pathops.PathOp.UNION)
    return shapes + [clip(line, region) for line in lines]


def less_equal(m, seq):
    """≤ / ≥: a chevron with a bar under it parallel to its lower arm."""
    direction = -1 if seq[0] == "<" else 1
    hh, w, drop = LESS_EQUAL[0] * m.h, LESS_EQUAL[1] * m.adv, LESS_EQUAL[2] * m.h
    cy = m.axis + drop / 2
    tip_x = m.adv + direction * w / 2
    end_x = tip_x - direction * w
    head = chevron((tip_x, cy), direction, hh, w, m.bar)
    # lower arm runs from the tip to (end_x, cy - hh); the bar is that line moved down
    dx, dy = end_x - tip_x, -hh
    line = stroke([(tip_x - dx * 0.5, cy - drop - dy * 0.5),
                   (tip_x + dx * 1.5, cy - drop + dy * 1.5)], m.bar)
    x0, x1 = sorted((tip_x, end_x))
    return [head, clip(line, to_path(rect(x0, -10 ** 4, x1, 10 ** 4)))]


def not_equal(g, m, seq):
    """≠ (2 cells) and its three-bar form for !== (3 cells)."""
    n = len(seq)
    bars = triple_bars(g, 0, 2) if n == 3 else joined_bars(g, "=", 0, 1)
    # the slash always sticks out past the bars, however tall === is
    top = max(bounds(bar)[3] for bar in bars)
    half = max(NOT_EQUAL[0] * m.h, top - m.axis + 0.3 * m.h)
    cx, run = n * m.adv / 2, half * NOT_EQUAL[1]
    slash = stroke([(cx - run * 1.5, m.axis - half * 1.5), (cx + run * 1.5, m.axis + half * 1.5)], m.bar)
    return bars + [clip(slash, to_path(rect(-10 ** 4, m.axis - half, 10 ** 4, m.axis + half)))]


def diamond(m):
    hh, hw = DIAMOND[0] * m.h, DIAMOND[1] * m.adv
    cx = m.adv
    return [stroke([(cx - hw, m.axis), (cx, m.axis + hh), (cx + hw, m.axis), (cx, m.axis - hh)],
                   m.bar, closed=True)]


def triangles(m, seq):
    """▷ |>, ◁ <|, and ◁▷ <|> sharing their upright side."""
    hh, w = TRIANGLE[0] * m.h, TRIANGLE[1] * m.adv
    cx = len(seq) * m.adv / 2
    shapes = []
    for direction in ([1] if seq == "|>" else [-1] if seq == "<|" else [-1, 1]):
        base = cx if seq == "<|>" else cx - direction * w / 2
        tip = base + direction * w
        shapes.append(stroke([(base, m.axis - hh), (base, m.axis + hh), (tip, m.axis)],
                             m.bar, closed=True))
    return shapes


def tight_parts(g, m, seq):
    """Characters kept, as parts to be moved closer; colons and asterisks next to = < >
    are centred on the axis, like the operators they belong to."""
    parts, i = [], 0
    while i < len(seq):
        j = i
        while j + 1 < len(seq) and seq[j + 1] == seq[i] and seq[i] in "=-":
            j += 1
        if j > i:
            parts.append(joined_bars(g, seq[i], i, j))  # the "--" of "<!--"
        else:
            shape = placed(g, seq[i], i)
            if (seq[i] == ":" and set(seq) & set("=<>")) or (seq[i] == "*" and set(seq) & set("<>")):
                _, y0, _, y1 = bounds(shape)
                shape = transformed(shape, (1, 0, 0, 1, 0, m.axis - (y0 + y1) / 2))
            parts.append([shape])
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


def ligature_shapes(g, m, seq):
    kind = LIGATURES[seq]
    if kind == "arrow":
        return arrow(g, m, seq)
    if kind in ("less_equal", "greater_equal"):
        return less_equal(m, seq)
    if kind == "not_equal":
        return not_equal(g, m, seq)
    if kind == "bars":
        return triple_bars(g, 0, 2) if seq == "===" else joined_bars(g, "=", 0, 1)
    if kind == "diamond":
        return diamond(m)
    if kind == "triangle":
        return triangles(m, seq)
    return tighten(g, tight_parts(g, m, seq))


def ligatures(g):
    font, cmap, m = g.font, g.cmap, Measures(g)
    seqs = sorted(LIGATURES, key=len, reverse=True)  # longest first: "===" before "=="
    names = [[cmap[ord(c)] for c in seq] for seq in seqs]
    font.setGlyphOrder(font.getGlyphOrder() + [f"{'_'.join(n)}.{s}" for n in names
                                               for s in ("liga", "spacer")])

    fea = ["languagesystem DFLT dflt;", "languagesystem latn dflt;",
           "@htop = [bar bracketleft bracketright];"]
    for k, (seq, gnames) in enumerate(zip(seqs, names)):
        adv = g.advance(ord(seq[-1]))
        liga, spacer = "_".join(gnames) + ".liga", "_".join(gnames) + ".spacer"
        shift = (1, 0, 0, 1, -(len(seq) - 1) * adv, 0)
        # Shapes are merged whole (not contour by contour) so counters like those of "&" stay open.
        path = union([transformed(s, shift) for s in ligature_shapes(g, m, seq)])
        set_glyph(font, liga, lambda pen, path=path: path.draw(pen), adv)
        set_glyph(font, spacer, lambda pen: None, adv)

        first, rest = gnames[0], " ".join(gnames[1:])
        fea.append(f"lookup liga{k} {{")
        # Not inside a longer run of the same characters ("====", "---", "///").
        fea.append(f"  ignore sub {first} {first}' {rest};")
        fea.append(f"  ignore sub {first}' {rest} {gnames[-1]};")
        if "|" in seq:
            fea.append(f"  ignore sub @htop {first}' {rest};")
            fea.append(f"  ignore sub {first}' {rest} @htop;")
        for i, name in enumerate(gnames):
            back = " ".join([spacer] * i)
            ahead = " ".join(gnames[i + 1:])
            fea.append(f"  sub {back} {name}' {ahead} by {spacer if i < len(gnames) - 1 else liga};")
        fea.append(f"}} liga{k};")
    fea.append("feature calt {")
    fea += [f"  lookup liga{k};" for k in range(len(seqs))]
    fea.append("} calt;")
    addOpenTypeFeaturesFromString(font, "\n".join(fea), tables=["GSUB"])
    return len(seqs)


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
