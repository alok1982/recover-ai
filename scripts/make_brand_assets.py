#!/usr/bin/env python3
"""Rebuild the RecoverAI brand assets from the approved logo (docs/brand/*_source.svg).

Outlines the glyphs with fontTools (Inter Bold, as approved) so the shipped SVGs need no installed fonts, then
renders the favicon / PWA / apple-touch PNGs with CairoSVG. Needs: pip install fonttools cairosvg pillow.
  python scripts/make_brand_assets.py [--font /path/to/Inter-VariableFont_opsz,wght.ttf]
"""
import argparse, io, pathlib
import cairosvg
from PIL import Image
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUB = ROOT / "frontend" / "public"
ap = argparse.ArgumentParser()
ap.add_argument("--font", default="/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf")
ARGS = ap.parse_args()
_cache: dict = {}


def run(text, x, y, size, w, ls=0.0):
    """Outline `text` at baseline (x, y); returns (svg path data, next x). Matches the approved preview's metrics."""
    if w not in _cache:
        _cache[w] = instantiateVariableFont(TTFont(ARGS.font), {"wght": w, "opsz": 14})
    f = _cache[w]; gs = f.getGlyphSet(); cmap = f.getBestCmap(); s = size / f["head"].unitsPerEm
    out = []
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x, y)))
        out.append(pen.getCommands()); x += f["hmtx"][g][0] * s + ls
    return "".join(out), x


ARROW = ('<g fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M24 94 L44 84 L58 90 L92 76"/><path d="M81 75 L93 75.5 L90 87"/></g>')
r, _ = run("R", 20, 66, 44, 700); a, _ = run("A", 51, 66, 44, 700); i, _ = run("I", 88, 66, 44, 700)
GLYPHS = f'<path fill="#FFFFFF" d="{r}"/><path fill="#F5A524" d="{a + i}"/>{ARROW}'
TILE = f'<rect x="4" y="4" width="112" height="112" rx="26" fill="#0F5E6B"/>{GLYPHS}'
rec, x = run("Recover", 138, 80, 58, 700, -1); ai, _ = run("AI", x, 80, 58, 700, -1)
svg = lambda vb, body: f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{vb.split()[2]}" height="{vb.split()[3]}"><title>RecoverAI</title>{body}</svg>\n'
mark = svg("0 0 120 120", TILE)
logo = svg("0 0 470 120", TILE + f'<path fill="#1F2A3A" d="{rec}"/><path fill="#0F5E6B" d="{ai}"/>')
dark = svg("0 0 470 120", TILE + f'<path fill="#FFFFFF" d="{rec}"/><path fill="#5FC4D2" d="{ai}"/>')
full = svg("0 0 120 120", f'<rect width="120" height="120" fill="#0F5E6B"/>{GLYPHS}')
maskable = svg("0 0 120 120", f'<rect width="120" height="120" fill="#0F5E6B"/><g transform="translate(60 60) scale(.84) translate(-60 -60)">{GLYPHS}</g>')

(PUB / "brand").mkdir(exist_ok=True)
for path, s in [(PUB / "brand/rai_mark.svg", mark), (PUB / "brand/rai_logo.svg", logo), (PUB / "brand/rai_logo_dark.svg", dark),
                (PUB / "favicon.svg", mark), (PUB / "icon.svg", mark), (ROOT / "backend/app/pdf/rai_logo.svg", logo)]:
    path.write_text(s)
png = lambda s, n, p: p.write_bytes(cairosvg.svg2png(bytestring=s.encode(), output_width=n, output_height=n))
png(mark, 32, PUB / "favicon-32.png"); png(full, 180, PUB / "apple-touch-icon.png")
png(mark, 192, PUB / "icon-192.png"); png(mark, 512, PUB / "icon-512.png"); png(maskable, 512, PUB / "icon-maskable-512.png")
Image.open(io.BytesIO(cairosvg.svg2png(bytestring=mark.encode(), output_width=48, output_height=48))).save(
    PUB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
print("brand assets written")
