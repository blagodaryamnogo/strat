"""Log-log experience-curve chart, shared by the app and the PDF report."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator  # noqa: E402

from analysis import Analysis, equation_text, fmt_b, fmt_num, fmt_pct, fmt_r2  # noqa: E402

INK = "#1f2933"
MUTED = "#616e7c"
POINT = "#1f5f8b"
LINE = "#c0392b"


def _tick(x, _pos):
    return fmt_num(x, 3)


def experience_curve_figure(an: Analysis):
    rows = an.regression_rows
    reg = an.regression
    x = np.array([r["cum_units"] for r in rows])
    y = np.array([r["unit_cost"] for r in rows])

    fig, ax = plt.subplots(figsize=(7.5, 4.3), dpi=110)
    ax.scatter(x, y, s=36, color=POINT, zorder=3, label="Observed periods")
    xs = np.geomspace(x.min(), x.max(), 100)
    ax.plot(xs, reg.a * xs ** (-reg.b), color=LINE, lw=1.8, zorder=2,
            label=f"Fitted: {equation_text(reg)}")
    for r, xi, yi in ((rows[0], x[0], y[0]), (rows[-1], x[-1], y[-1])):
        ax.annotate(r["period"], (xi, yi), textcoords="offset points", xytext=(6, 6),
                    fontsize=8, color=MUTED)

    ax.set_xscale("log")
    ax.set_yscale("log")
    for axis, values in ((ax.xaxis, x), (ax.yaxis, y)):
        decades = np.log10(values.max() / values.min())
        subs = (1.0, 2.0, 5.0) if decades > 1.2 else (1.0, 1.5, 2.0, 3.0, 5.0, 7.0)
        axis.set_major_locator(LogLocator(base=10, subs=subs))
        axis.set_major_formatter(FuncFormatter(_tick))
        axis.set_minor_formatter(FuncFormatter(lambda *_: ""))
    unit = an.unit_definition or "units"
    ax.set_xlabel(f"Cumulative units since start of window ({unit}, log scale)", color=INK)
    ax.set_ylabel(f"Unit COGS ({an.currency} per unit, log scale)", color=INK)
    ax.set_title(f"{an.company} ({an.ticker}) — experience curve, {an.date_range}", fontsize=11,
                 color=INK, loc="left")
    ax.text(0.98, 0.97,
            f"Learning rate {fmt_pct(reg.learning_rate)}\nb = {fmt_b(reg.b)}   R² = {fmt_r2(reg.r2)}\n"
            f"n = {reg.n} {an.frequency} observations",
            transform=ax.transAxes, ha="right", va="top", fontsize=9, color=INK,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#cbd2d9"))
    ax.grid(True, which="major", color="#e4e7eb", lw=0.8)
    ax.grid(True, which="minor", color="#f2f4f6", lw=0.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower left", fontsize=8, frameon=False)
    fig.tight_layout()
    return fig


def figure_png(fig, dpi: int = 200) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
