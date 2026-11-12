"""Shape a line of text with HarfBuzz and return it as SVG path data."""

from __future__ import annotations

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen


def text_path(text, font_file, size, variations=None, tracking=0.0, digits=2):
    """Return ``(d, width, ascent_of_caps)`` for ``text`` set at ``size`` px, baseline at y=0."""
    blob = hb.Blob.from_file_path(font_file)
    face = hb.Face(blob)
    font = hb.Font(face)
    if variations:
        font.set_variations(variations)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    k = size / face.upem
    x = 0.0
    parts = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        pen = SVGPathPen(None, ntos=lambda v: f"{round(v, digits):g}")
        tpen = TransformPen(pen, (k, 0, 0, -k, x + pos.x_offset * k, -pos.y_offset * k))
        font.draw_glyph_with_pen(info.codepoint, tpen)
        d = pen.getCommands()
        if d:
            parts.append(d)
        x += pos.x_advance * k + tracking
    x -= tracking
    ext = font.get_glyph_extents(font.get_nominal_glyph(ord("H")))
    cap = ext.y_bearing * k if ext else size * 0.72
    return "".join(parts), x, cap
