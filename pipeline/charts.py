"""SVG charts generated from analysis.json. The same SVG files are used by the web app and the PDF."""
from html import escape

INK, MUTED, COPPER, GREEN, RED, GRID = "#1f2a44", "#6b6f76", "#b0703c", "#3f7d58", "#a4483e", "#e4ddd0"


def _empty(w, h, msg):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">'
            f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" fill="none" stroke="{GRID}"/>'
            f'<text x="{w/2}" y="{h/2}" text-anchor="middle" fill="{MUTED}" font-size="13">{escape(msg)}</text></svg>')


def bar(analysis, key="nps", title="Review-Derived NPS (baseline)"):
    rows = [c for c in analysis["competitors"] if c[key] is not None]
    w, row_h, left, top = 640, 34, 170, 36
    h = top + row_h * max(len(rows), 1) + 34
    if not rows:
        return _empty(w, 160, "No scored reviews yet — collection blocked (see Methodology)")
    rows = sorted(rows, key=lambda c: -c[key])
    x0, span = left + (w - left - 30) / 2, (w - left - 30) / 2  # zero in the middle: -100..+100
    sx = lambda v: x0 + v / 100 * span
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">',
           f'<text x="0" y="18" font-size="13" font-weight="600" fill="{INK}">{escape(title)}</text>']
    for v in (-100, -50, 0, 50, 100):
        out.append(f'<line x1="{sx(v)}" x2="{sx(v)}" y1="{top-6}" y2="{h-28}" stroke="{GRID if v else MUTED}" stroke-width="1"/>'
                   f'<text x="{sx(v)}" y="{h-12}" font-size="10" text-anchor="middle" fill="{MUTED}">{v:+d}</text>')
    for i, c in enumerate(rows):
        y, v = top + i * row_h, c[key]
        color = GREEN if v >= 50 else COPPER if v >= 0 else RED
        xa, xb = sorted((sx(0), sx(v)))
        out.append(f'<text x="{left-10}" y="{y+row_h/2+4}" font-size="12" text-anchor="end" fill="{INK}">{escape(c["competitor"])}</text>'
                   f'<rect x="{xa}" y="{y+7}" width="{max(xb-xa,1)}" height="{row_h-14}" rx="2" fill="{color}"/>'
                   f'<text x="{xb+6 if v>=0 else xa-6}" y="{y+row_h/2+4}" font-size="12" font-weight="600" text-anchor="{"start" if v>=0 else "end"}" fill="{INK}">{v:+d}</text>')
    out.append("</svg>")
    return "".join(out)


def scatter(analysis):
    rows = [c for c in analysis["competitors"] if c["nps"] is not None]
    w, h, l, r, t, b = 640, 360, 60, 20, 30, 50
    if not rows:
        return _empty(w, 200, "Loyalty vs. volume chart requires scored reviews")
    xmax = max(c["n"] for c in rows) * 1.15
    sx = lambda v: l + v / xmax * (w - l - r)
    sy = lambda v: t + (100 - v) / 200 * (h - t - b)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">',
           f'<text x="0" y="16" font-size="13" font-weight="600" fill="{INK}">Loyalty vs. review volume</text>']
    for v in (-100, -50, 0, 50, 100):
        out.append(f'<line x1="{l}" x2="{w-r}" y1="{sy(v)}" y2="{sy(v)}" stroke="{GRID}"/><text x="{l-8}" y="{sy(v)+4}" font-size="10" text-anchor="end" fill="{MUTED}">{v:+d}</text>')
    wd = analysis["wedge"]
    if "median_volume" in wd:
        out.append(f'<line x1="{sx(wd["median_volume"])}" x2="{sx(wd["median_volume"])}" y1="{t}" y2="{h-b}" stroke="{COPPER}" stroke-dasharray="4 4"/>'
                   f'<line x1="{l}" x2="{w-r}" y1="{sy(wd["median_nps"])}" y2="{sy(wd["median_nps"])}" stroke="{COPPER}" stroke-dasharray="4 4"/>'
                   f'<text x="{w-r-4}" y="{h-b-6}" font-size="10" text-anchor="end" fill="{COPPER}">wedge zone: high volume, below-median NPS</text>')
    for c in rows:
        x, y = sx(c["n"]), sy(c["nps"])
        right = x > w * 0.6
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{INK}"/><text x="{x-9 if right else x+9}" y="{y-8}" font-size="11" text-anchor="{"end" if right else "start"}" fill="{INK}">{escape(c["competitor"])} ({c["nps"]:+d}, n={c["n"]})</text>')
    out.append(f'<text x="{(l+w-r)/2}" y="{h-12}" font-size="11" text-anchor="middle" fill="{MUTED}">Written reviews retrieved &amp; scored (not total Amazon ratings)</text>'
               f'<text x="14" y="{(t+h-b)/2}" font-size="11" text-anchor="middle" fill="{MUTED}" transform="rotate(-90 14 {(t+h-b)/2})">Baseline review-derived NPS</text></svg>')
    return "".join(out)
