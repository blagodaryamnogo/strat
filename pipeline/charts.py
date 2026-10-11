"""SVG charts generated from analysis.json. The same SVG files are used by the web app and the PDF."""
import math
from html import escape

INK, MUTED, COPPER, GREEN, RED, GRID = "#1f2a44", "#6b6f76", "#b0703c", "#3f7d58", "#a4483e", "#e4ddd0"


def _empty(w, h, msg):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">'
            f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" fill="none" stroke="{GRID}"/>'
            f'<text x="{w/2}" y="{h/2}" text-anchor="middle" fill="{MUTED}" font-size="13">{escape(msg)}</text></svg>')


def _hl(c):
    """Headline score block (histogram or written-review sample); older analysis files lack it."""
    return c.get("headline") or {"nps": c["nps"], "alt_nps": c["alt_nps"], "volume": c["n"],
                                 "comparable": c["nps"] is not None and c.get("comparable", True)}


def _excluded(analysis):
    return [c["competitor"] for c in analysis["competitors"] if c["nps"] is not None and not _hl(c)["comparable"]]


def bar(analysis, key="nps", title="Review-Derived NPS (baseline)"):
    rows = [{"competitor": c["competitor"], key: _hl(c)[key]} for c in analysis["competitors"] if _hl(c)["comparable"] and _hl(c)[key] is not None]
    excl = _excluded(analysis)
    w, row_h, left, top = 640, 34, 170, 36
    h = top + row_h * max(len(rows), 1) + 34 + (18 if excl else 0)
    if not rows:
        return _empty(w, 160, "No scored reviews yet — collection blocked (see Methodology)")
    rows = sorted(rows, key=lambda c: -c[key])
    x0, span = left + (w - left - 30) / 2, (w - left - 30) / 2  # zero in the middle: -100..+100
    sx = lambda v: x0 + v / 100 * span
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">',
           f'<text x="0" y="18" font-size="13" font-weight="600" fill="{INK}">{escape(title)}</text>']
    for v in (-100, -50, 0, 50, 100):
        out.append(f'<line x1="{sx(v)}" x2="{sx(v)}" y1="{top-6}" y2="{h-28-(18 if excl else 0)}" stroke="{GRID if v else MUTED}" stroke-width="1"/>'
                   f'<text x="{sx(v)}" y="{h-12-(18 if excl else 0)}" font-size="10" text-anchor="middle" fill="{MUTED}">{v:+d}</text>')
    for i, c in enumerate(rows):
        y, v = top + i * row_h, c[key]
        color = GREEN if v >= 50 else COPPER if v >= 0 else RED
        xa, xb = sorted((sx(0), sx(v)))
        out.append(f'<text x="{left-10}" y="{y+row_h/2+4}" font-size="12" text-anchor="end" fill="{INK}">{escape(c["competitor"])}</text>'
                   f'<rect x="{xa}" y="{y+7}" width="{max(xb-xa,1)}" height="{row_h-14}" rx="2" fill="{color}"/>'
                   f'<text x="{xb+6 if v>=0 else xa-6}" y="{y+row_h/2+4}" font-size="12" font-weight="600" text-anchor="{"start" if v>=0 else "end"}" fill="{INK}">{v:+d}</text>')
    if excl:
        out.append(f'<text x="0" y="{h-4}" font-size="10" fill="{MUTED}">Not shown (retrieval cap set the star mix; NPS not comparable): {escape(", ".join(excl))}</text>')
    out.append("</svg>")
    return "".join(out)


def scatter(analysis):
    rows = [{"competitor": c["competitor"], "nps": _hl(c)["nps"], "n": _hl(c)["volume"]} for c in analysis["competitors"] if _hl(c)["comparable"]]
    excl = _excluded(analysis)
    hist = analysis.get("primary_metric") == "histogram"
    w, h, l, r, t, b = 640, 300 + (16 if excl else 0), 60, 20, 30, 50 + (16 if excl else 0)
    if not rows:
        return _empty(w, 200, "Loyalty vs. volume chart requires scored reviews")
    lo, hi = min(c["n"] for c in rows), max(c["n"] for c in rows)
    use_log = lo > 0 and hi / lo > 30  # rating totals span orders of magnitude
    if use_log:
        a0, a1 = math.log10(lo) - 0.15, math.log10(hi) + 0.15
        sx = lambda v: l + (math.log10(v) - a0) / (a1 - a0) * (w - l - r)
    else:
        xmax = hi * 1.15
        sx = lambda v: l + v / xmax * (w - l - r)
    # y range fitted to the data (multiples of 10, always including the median line), so close scores stay readable
    ys = [c["nps"] for c in rows] + ([analysis["wedge"]["median_nps"]] if "median_nps" in analysis["wedge"] else [])
    y0 = max(-100, math.floor((min(ys) - 8) / 10) * 10)
    y1 = min(100, math.ceil((max(ys) + 8) / 10) * 10)
    if y1 - y0 < 30:
        y1 = min(100, y0 + 30); y0 = y1 - 30
    sy = lambda v: t + (y1 - v) / (y1 - y0) * (h - t - b)
    ticks = [v for v in range(-100, 101, 10 if y1 - y0 <= 60 else 50) if y0 <= v <= y1]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">',
           f'<text x="0" y="16" font-size="13" font-weight="600" fill="{INK}">Loyalty vs. review volume</text>']
    for v in ticks:
        out.append(f'<line x1="{l}" x2="{w-r}" y1="{sy(v)}" y2="{sy(v)}" stroke="{GRID}"/><text x="{l-8}" y="{sy(v)+4}" font-size="11" text-anchor="end" fill="{MUTED}">{v:+d}</text>')
    wd = analysis["wedge"]
    if "median_volume" in wd:
        out.append(f'<line x1="{sx(wd["median_volume"])}" x2="{sx(wd["median_volume"])}" y1="{t}" y2="{h-b}" stroke="{COPPER}" stroke-dasharray="4 4"/>'
                   f'<line x1="{l}" x2="{w-r}" y1="{sy(wd["median_nps"])}" y2="{sy(wd["median_nps"])}" stroke="{COPPER}" stroke-dasharray="4 4"/>'
                   f'<text x="{w-r-4}" y="{h-b-6}" font-size="10" text-anchor="end" fill="{COPPER}">wedge zone: high volume, below-median NPS</text>')
    placed = []  # label boxes already drawn: (x0, y0, x1, y1)
    for c in sorted(rows, key=lambda c: c["n"]):
        x, y = sx(c["n"]), sy(c["nps"])
        right = x > w * 0.6
        text = f'{c["competitor"]} ({c["nps"]:+d}, {"ratings" if hist else "n"}={c["n"]:,})'
        tw = len(text) * 6.0
        box = None
        for dy in (-8, 18, -24, 34):  # above, below, further above, further below
            bx0 = x - 9 - tw if right else x + 9
            cand = (bx0, y + dy - 11, bx0 + tw, y + dy + 3)
            if not any(cand[0] < q[2] and q[0] < cand[2] and cand[1] < q[3] and q[1] < cand[3] for q in placed):
                box = (cand, dy); break
        box = box or (cand, dy)
        placed.append(box[0])
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{INK}"/><text x="{x-9 if right else x+9}" y="{y+box[1]}" font-size="11" text-anchor="{"end" if right else "start"}" fill="{INK}">{escape(text)}</text>')
    if excl:
        out.append(f'<text x="0" y="{h-4}" font-size="10" fill="{MUTED}">Not plotted (capped samples, NPS not comparable): {escape(", ".join(excl))}</text>')
    out.append(f'<text x="{(l+w-r)/2}" y="{h-12-(16 if excl else 0)}" font-size="11" text-anchor="middle" fill="{MUTED}">'
               f'{"Total Amazon ratings (log scale)" if hist and use_log else "Total Amazon ratings" if hist else "Written reviews retrieved &amp; scored (not total Amazon ratings)"}</text>'
               f'<text x="14" y="{(t+h-b)/2}" font-size="11" text-anchor="middle" fill="{MUTED}" transform="rotate(-90 14 {(t+h-b)/2})">{"Baseline NPS (Amazon star histogram)" if hist else "Baseline review-derived NPS"}</text></svg>')
    return "".join(out)
