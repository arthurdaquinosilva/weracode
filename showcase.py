"""Render the README showcase image from the built fonts.

Usage: python3 showcase.py [FONT_DIR] [OUT.png]   (needs Pillow built with libraqm)
"""
import re
import sys
from PIL import Image, ImageDraw, ImageFont

FONTS = sys.argv[1] if len(sys.argv) > 1 else "fonts"
OUT = sys.argv[2] if len(sys.argv) > 2 else "images/showcase.png"
X = 2  # render at 2x for sharp display on Retina screens
RAQM = ImageFont.Layout.RAQM


def font(style, size):
    return ImageFont.truetype(f"{FONTS}/WeraCodeNerdFontMono-{style}.ttf", size * X, layout_engine=RAQM)


C = dict(bg="#0d1016", card="#161a22", panel="#1b2029", line="#262c37", fg="#d6dbe4",
         muted="#7d8697", comment="#5f6a7d", keyword="#c792ea", string="#c3e88d",
         number="#f78c6c", func="#82aaff", type="#ffcb6b", op="#89ddff", accent="#82aaff")

KEYWORDS = {"const", "let", "for", "if", "return", "continue", "type", "export", "function",
            "null", "true", "false", "of", "async", "await", "new"}
TOKEN = re.compile(r"(?P<comment>//.*)|(?P<string>\"[^\"]*\")|(?P<number>\b\d+\b)"
                   r"|(?P<word>[A-Za-z_]\w*)|(?P<op>[=<>!&|?:+\-*/%~^]+)|(?P<other>.)")


def tokens(line):
    out = []
    for m in TOKEN.finditer(line):
        kind, text = m.lastgroup, m.group()
        if kind == "word":
            after = line[m.end():m.end() + 1]
            kind = ("keyword" if text in KEYWORDS else "type" if text[0].isupper()
                    else "func" if after == "(" else "fg")
        elif kind == "other":
            kind = "fg"
        out.append((m.start(), text, kind))
    return out


CODE = [
    "// Ligatures keep the grid: every one is exactly as wide as its characters",
    "type Task = { id: number; done: boolean; owner?: string };",
    "",
    "export const pending = (tasks: Task[]): Task[] =>",
    "  tasks.filter((t) => !t.done && t.id >= 0);",
    "",
    "for (let i = 0; i <= limit; i++) {",
    "  if (cache[i] === null || next !== prev) continue;",
    "  owner = task.owner ?? \"nobody\";",
    "  total += count << 2 | flags;",
    "}",
]

LIGS = ["->", "=>", "==>", "<=>", "<=", ">=", "!=", "==", "===", "!==", "|>", "<|", "::",
        ":=", "..", "...", "?.", "??", "&&", "++", "//", "/*", "<<", ">>", "</>", "~>"]

W = 900
img = Image.new("RGB", (W * X, 10), C["bg"])  # height fixed below
draw = ImageDraw.Draw(img)


def text(x, y, s, style="Regular", size=15, color="fg", calt=True):
    f = font(style, size)
    draw.text((x * X, y * X), s, font=f, fill=C.get(color, color),
              features=["calt"] if calt else ["-calt"])
    return f.getlength(s, features=["calt"] if calt else ["-calt"]) / X


def layout(H):
    global img, draw
    img = Image.new("RGB", (W * X, H * X), C["bg"])
    draw = ImageDraw.Draw(img)

    pad = 40
    card = (pad, pad, W - pad, H - pad)
    draw.rounded_rectangle([v * X for v in card], radius=16 * X, fill=C["card"])
    x0, y = pad + 36, pad + 34

    # title
    text(x0, y, "WeraCode Nerd Font", "Bold", 30, "fg")
    y += 46
    text(x0, y, "Bitstream Vera Sans Mono, refined for code: slashed zero, bigger punctuation,",
         size=13, color="muted")
    y += 20
    text(x0, y, "77 grid-aligned ligatures and every Nerd Font icon.", size=13, color="muted")
    y += 40

    # powerline prompt
    size, f = 14, font("Regular", 14)
    cell = f.getlength("a") / X
    segs = [("#82aaff", "#0d1016", " "), ("#2a3140", "#d6dbe4", " ~/weracode "),
            ("#c3e88d", "#0d1016", " main  ")]
    x = x0
    h = 24
    for i, (bgc, fgc, s) in enumerate(segs):
        w = len(s) * cell + cell
        draw.rectangle([x * X, (y - 3) * X, (x + w) * X, (y - 3 + h) * X], fill=bgc)
        text(x + cell / 2, y, s, size=size, color=fgc)
        x += w
        nxt = segs[i + 1][0] if i + 1 < len(segs) else C["card"]
        draw.rectangle([x * X, (y - 3) * X, (x + cell) * X, (y - 3 + h) * X], fill=nxt)
        text(x, y - 0.5, "", size=size, color=bgc)
        x += cell
    text(x + cell, y, "         ",
         size=size, color="muted")
    y += 42

    # code panel
    size = 15
    f = font("Regular", size)
    cell, lh = f.getlength("a") / X, 25
    panel_h = len(CODE) * lh + 28
    draw.rounded_rectangle([x0 * X, y * X, (W - pad - 36) * X, (y + panel_h) * X],
                           radius=10 * X, fill=C["panel"])
    yy = y + 16
    for n, line in enumerate(CODE, 1):
        text(x0 + 14, yy, f"{n:>2}", size=size, color="#3d4554")
        cx = x0 + 14 + 4 * cell
        for col, s, kind in tokens(line):
            text(cx + col * cell, yy, s, "Oblique" if kind == "comment" else "Regular", size, kind)
        yy += lh
    y += panel_h + 34

    # ligature table: typed vs rendered
    text(x0, y, "LIGATURES", "Bold", 11, "muted")
    y += 24
    per_row, colw = 13, (W - 2 * pad - 72) / 13
    for r in range(0, len(LIGS), per_row):
        for i, seq in enumerate(LIGS[r:r + per_row]):
            cx = x0 + i * colw
            text(cx, y, seq, size=16, color="op")
            text(cx, y + 26, seq, size=16, color="comment", calt=False)
        y += 64
    y += 10

    # glyph details
    text(x0, y, "DETAILS", "Bold", 11, "muted")
    y += 26
    x = x0
    for s, label in [("0O", "slashed zero"), ("1lI", "distinct"), (";,:.", "square dots"),
                     ("__init__", "joined"), ("{}[]()", "even heights")]:
        w = text(x, y, s, size=22, color="fg")
        text(x, y + 34, label, size=11, color="muted")
        x += max(w, len(label) * 7) + 34
    y += 58
    x = x0
    for style in ["Regular", "Bold", "Oblique", "BoldOblique"]:
        w = text(x, y, {"BoldOblique": "Bold Oblique"}.get(style, style), style, 15, "accent")
        x += w + 26
    return y + 54 + pad


H = layout(2000)
layout(int(H))
img.save(OUT, optimize=True)
print(img.size)
