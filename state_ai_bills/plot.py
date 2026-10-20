"""Draw the first figure from data/ncsl_ai_bills.csv (run get_data.py first).

(a) AI bills per session year, 2019 onward, and how many were enacted.
(b) The latest year's bills by NCSL topic, and how many were enacted.

Writes figures/fig1_state_ai_bills.png and .svg.
"""

from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import blended_transform_factory

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FIGURES = ROOT / "figures"

# Light-mode chart tokens. The two blues are steps 550 and 250 of one ramp, so the
# enacted share reads as a darker part of the same bar.
SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
ENACTED, NOT_ENACTED = "#1c5cab", "#86b6ef"

PX = 1 / 96  # one screen pixel, in inches
BAR_PX, RADIUS_PX, GAP_PX = 24, 4, 2

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": BASELINE,
    "axes.linewidth": 0.75,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "svg.fonttype": "none",
})


def units_per_inch(ax):
    """Data units per inch along x and y for an axes whose limits are already set."""
    fig_w, fig_h = ax.figure.get_size_inches()
    box = ax.get_position()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    return abs(x1 - x0) / (box.width * fig_w), abs(y1 - y0) / (box.height * fig_h)


def draw_bar(ax, pos, start, end, thickness, color, round_end, horizontal=False):
    """One bar segment from start to end on the value axis, centred on pos.

    With round_end, the data end gets 4px rounded corners; the baseline end stays square.
    """
    per_x, per_y = units_per_inch(ax)
    per_value, per_pos = (per_x, per_y) if horizontal else (per_y, per_x)
    rv = min(RADIUS_PX * PX * per_value, (end - start) / 2) if round_end else 0
    rp = min(RADIUS_PX * PX * per_pos, thickness / 2) if round_end else 0
    a, b = pos - thickness / 2, pos + thickness / 2
    pts = [(start, a), (end - rv, a), (end, a), (end, a + rp), (end, b - rp), (end, b),
           (end - rv, b), (start, b), (start, a)]
    codes = [MplPath.MOVETO, MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3, MplPath.LINETO,
             MplPath.CURVE3, MplPath.CURVE3, MplPath.LINETO, MplPath.CLOSEPOLY]
    verts = pts if horizontal else [(p, v) for v, p in pts]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none", zorder=2))


def draw_split_bar(ax, pos, enacted, introduced, thickness, horizontal=False):
    """A bar as long as `introduced`, its first `enacted` units in the darker blue."""
    per_x, per_y = units_per_inch(ax)
    gap = GAP_PX * PX * (per_x if horizontal else per_y)
    if enacted:
        draw_bar(ax, pos, 0, enacted, thickness, ENACTED, enacted == introduced, horizontal)
    if introduced > enacted:
        start = enacted + gap if enacted else 0
        draw_bar(ax, pos, start, introduced, thickness, NOT_ENACTED, True, horizontal)


def style_axes(ax, value_axis):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis=value_axis, color=GRID, linewidth=0.75)
    ax.tick_params(length=0, labelsize=8.5)
    ax.set_facecolor(SURFACE)


def main():
    bills = pd.read_csv(DATA / "ncsl_ai_bills.csv", keep_default_na=False)
    bills["enacted"] = bills.status_group == "Enacted"
    latest = bills.year.max()
    years = bills.groupby("year").agg(introduced=("bill_id", "size"), enacted=("enacted", "sum"))

    topics = (bills[bills.year == latest].assign(topic=lambda d: d.topics.str.split("; "))
              .explode("topic"))
    untagged = (topics.topic == "").sum()
    topics = (topics[topics.topic != ""].groupby("topic")
              .agg(introduced=("bill_id", "size"), enacted=("enacted", "sum"))
              .sort_values(["introduced", "enacted"], ascending=False))

    retrieved = date.fromtimestamp(max(p.stat().st_mtime for p in (DATA / "raw").glob("ncsl_database_*.html")))
    retrieved = f"{retrieved:%b} {retrieved.day}, {retrieved.year}"

    fig = plt.figure(figsize=(12.8, 7.0), facecolor=SURFACE)
    fig.text(0.03, 0.955, f"AI bills in U.S. state legislatures, {years.index.min()}–{latest}",
             fontsize=15, fontweight="semibold", color=INK)
    fig.text(0.03, 0.918, "Full bar = every AI bill NCSL tracked in that session year; "
             "dark segment = bills enacted into law.", fontsize=9.5, color=INK_2)
    fig.legend(handles=[Patch(color=ENACTED, label="Enacted"),
                        Patch(color=NOT_ENACTED, label="Introduced, not enacted")],
               loc="upper left", bbox_to_anchor=(0.025, 0.905), ncol=2, frameon=False,
               fontsize=9, handlelength=1.1, handleheight=1.1, labelcolor=INK_2)

    # (a) bills per session year
    ax = fig.add_axes([0.085, 0.27, 0.36, 0.52])
    fig.text(0.03, 0.825, "a   Bills per session year", fontsize=11, fontweight="semibold", color=INK)
    style_axes(ax, "y")
    ax.set_xlim(years.index.min() - 0.6, latest + 0.6)
    ax.set_ylim(0, 1800)
    ax.set_yticks(range(0, 1501, 500))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xticks(years.index, [f"{y}*" if y == latest else str(y) for y in years.index],
                  color=INK_2, fontsize=9)
    thickness = BAR_PX * PX * units_per_inch(ax)[0]
    for year, row in years.iterrows():
        draw_split_bar(ax, year, row.enacted, row.introduced, thickness)
    # Exact counts as a small table under the axis
    below = blended_transform_factory(ax.transData, ax.transAxes)
    for y_axes, label, col in [(-0.12, "Introduced", "introduced"), (-0.19, "Enacted", "enacted")]:
        ax.text(-0.02, y_axes, label, transform=ax.transAxes, ha="right", va="center",
                fontsize=8.5, color=INK_2)
        for year, value in years[col].items():
            ax.text(year, y_axes, f"{value:,}", transform=below, ha="center", va="center",
                    fontsize=8.5, color=INK if col == "introduced" else INK_2)
    # Mark where NCSL's annual pages give way to its database
    switch = 2024.5
    if years.index.min() < switch < latest:
        ax.axvline(switch, ymax=0.97, color=BASELINE, linewidth=0.75, zorder=1)
        ax.text(switch - 0.1, 1760, "NCSL annual pages", ha="right", va="top", fontsize=7.5, color=MUTED)
        ax.text(switch + 0.1, 1760, "NCSL database", ha="left", va="top", fontsize=7.5, color=MUTED)

    # (b) latest year's bills by topic
    ax = fig.add_axes([0.655, 0.135, 0.315, 0.655])
    fig.text(0.505, 0.825, f"b   {latest} bills by topic", fontsize=11, fontweight="semibold", color=INK)
    fig.text(0.505, 0.8, "A bill can carry several topics. Labels: enacted / introduced.",
             fontsize=8.5, color=INK_2)
    style_axes(ax, "x")
    n = len(topics)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlim(0, topics.introduced.max() * 1.17)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_yticks(range(n - 1, -1, -1), topics.index, color=INK, fontsize=8.5)
    thickness = min(BAR_PX * PX * units_per_inch(ax)[1], 0.62)
    pad = 5 * PX * units_per_inch(ax)[0]
    for pos, (topic, row) in zip(range(n - 1, -1, -1), topics.iterrows()):
        draw_split_bar(ax, pos, row.enacted, row.introduced, thickness, horizontal=True)
        ax.text(row.introduced + pad, pos, f"{row.enacted} / {row.introduced}", va="center",
                fontsize=8, color=INK_2)

    fig.text(0.03, 0.03, "\n".join([
        "Source: NCSL annual AI legislation pages (2019–2024) and NCSL Artificial Intelligence "
        f"Legislation Database, powered by LexisNexis State Net (2025–{latest}); downloaded {retrieved}.",
        f"Covers the 50 states, DC and U.S. territories. *{latest} as of NCSL's latest monthly update; "
        "some bills are still pending. Adopted resolutions count as introduced, not enacted.",
        "The two sides of the line in (a) come from different NCSL products, so the 2024→2025 change mixes "
        f"growth with broader tracking (the Deepfake topic first appears in 2025). (b) omits {untagged:,} "
        f"{latest} bills with no topic yet.",
    ]), fontsize=7.5, color=MUTED, linespacing=1.5, va="bottom")

    FIGURES.mkdir(exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(FIGURES / f"fig1_state_ai_bills.{ext}", dpi=200, facecolor=SURFACE)
    print(f"wrote {FIGURES / 'fig1_state_ai_bills.png'} and .svg")


if __name__ == "__main__":
    main()
