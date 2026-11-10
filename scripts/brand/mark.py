"""Geometry of the Aj Crew gem mark, shared by every asset the kit builds."""

from __future__ import annotations

# Six facets of a brilliant cut seen from the side, on a 1024 x 1024 canvas.
T1, T2 = (372.0, 306.0), (652.0, 306.0)  # table edge
GL, GR = (232.0, 452.0), (792.0, 452.0)  # girdle ends
G1, G2 = (400.0, 452.0), (624.0, 452.0)  # girdle, under the table
C = (512.0, 792.0)  # culet

FACETS = {
    "crown_left": [GL, T1, G1],
    "table": [T1, T2, G2, G1],
    "crown_right": [T2, GR, G2],
    "pav_left": [GL, G1, C],
    "pav_center": [G1, G2, C],
    "pav_right": [G2, GR, C],
}
ORDER = ["crown_left", "table", "crown_right", "pav_left", "pav_center", "pav_right"]


def _area(poly):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1])) / 2


def inset(poly, d):
    """Shrink a convex polygon by ``d`` on every side."""
    if _area(poly) < 0:
        poly = poly[::-1]
    n = len(poly)
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / length, dx / length  # inward normal for a CCW polygon (y down flips it)
        lines.append(((x1 + nx * d, y1 + ny * d), (dx, dy)))
    out = []
    for i in range(n):
        (p, r), (q, s) = lines[i - 1], lines[i]
        cross = r[0] * s[1] - r[1] * s[0]
        t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
        out.append((p[0] + t * r[0], p[1] + t * r[1]))
    return out


def facet_paths(gap=9.0, scale=1.0, dx=0.0, dy=0.0, digits=1):
    """SVG path data per facet, each pulled in by half the gap between facets."""
    paths = {}
    for name in ORDER:
        pts = inset(FACETS[name], gap / 2)
        d = (
            "M"
            + "L".join(
                f"{round(x * scale + dx, digits):g} {round(y * scale + dy, digits):g}"
                for x, y in pts
            )
            + "Z"
        )
        paths[name] = d
    return paths


def outline_path(scale=1.0, dx=0.0, dy=0.0, digits=1):
    pts = [GL, T1, T2, GR, C]
    return (
        "M"
        + "L".join(
            f"{round(x * scale + dx, digits):g} {round(y * scale + dy, digits):g}" for x, y in pts
        )
        + "Z"
    )
