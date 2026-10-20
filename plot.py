"""Redraw Public Citizen's "AI Lobbyists by Quarter and Year" from data/ai_lobbyists_by_quarter.csv.

Run get_data.py first. Writes
  figure.png            the reproduction, 2020-2025, in the style of the original
  figure_extension.png  the same count brought up to 2026, in The Economist's chart style
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator

ROOT = Path(__file__).resolve().parent
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# Public Citizen's published yearly totals (report Table 1), for the comparison printout only
PUBLISHED = {2020: 1311, 2021: 1269, 2022: 1332, 2023: 2210, 2024: 3101, 2025: 3570}

# Reports for a quarter are due on the 20th of the following month; quarters after this one
# are left off the extension because their reports are still coming in.
LAST_COMPLETE = (2026, "Q2")


def load():
    df = pd.read_csv(ROOT / "data" / "ai_lobbyists_by_quarter.csv")
    years = df[df.quarter == "Year"].set_index("year")
    quarters = df[df.quarter != "Year"].copy()
    quarters["x"] = [(y - 2020) * 5 + QUARTERS.index(q) for y, q in zip(quarters.year, quarters.quarter)]
    return years, quarters


def reproduction(years, quarters):
    """Bars for yearly totals, a line for quarterly totals, as in the report's Figure 1."""
    years = years.loc[2020:2025]
    quarters = quarters[quarters.year <= 2025]
    serif = ["Cambria", "Georgia", "DejaVu Serif"]
    fig, ax = plt.subplots(figsize=(9.6, 6.4), facecolor="white")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.88, bottom=0.2)
    fig.suptitle("Figure 1 – AI Lobbyists by Quarter and Year (2020 Through 2025)",
                 fontsize=14.5, fontweight="bold", color="#0e2241", y=0.955)

    top = max(4000, -(-years.lobbyists.max() * 1.08 // 500) * 500)
    ax.set_ylim(0, top)
    ax.set_xlim(-0.6, quarters.x.max() + 0.6)
    ax.yaxis.set_major_locator(MultipleLocator(500))
    ax.grid(axis="y", color="#e9ebf3", linewidth=0.8)
    for x in quarters.x:
        ax.axvline(x, color="#eef0f6", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#d9dbe3")
    ax.spines["bottom"].set_color("#d9dbe3")

    for year, row in years.iterrows():
        x0 = (year - 2020) * 5 - 0.5
        ax.add_patch(Rectangle((x0, 0), 4, row.lobbyists, facecolor="#c9d3ee", edgecolor="none", zorder=1))
        ax.text(x0 + 2, row.lobbyists + top * 0.035, f"{row.lobbyists:,}", ha="center", va="bottom",
                fontsize=11, family=serif, color="#222",
                bbox=dict(boxstyle="square,pad=0.6", facecolor="white", edgecolor="#e3e5ec"))
    ax.plot(quarters.x, quarters.lobbyists, color="black", linewidth=2.2, zorder=3)
    ax.plot(quarters.x, quarters.lobbyists, linestyle="none", marker="D", markersize=6.5,
            color="black", zorder=4)

    ax.set_xticks(quarters.x, quarters.quarter, family=serif, fontsize=10)
    ax.tick_params(axis="x", length=0, pad=6)
    ax.tick_params(axis="y", length=0, labelsize=11)
    for label in ax.get_yticklabels():
        label.set_family(serif)
    for year in years.index:
        ax.text((year - 2020) * 5 + 1.5, -top * 0.105, str(year), ha="center", va="top",
                fontsize=11, family=serif)
    fig.text(0.05, 0.035, "Source: reproduction from LDA.gov lobbying disclosure reports (LD-2), "
             "following Public Citizen’s method.", fontsize=12, style="italic", color="#222")
    fig.savefig(ROOT / "figure.png", dpi=200)
    plt.close(fig)


def extension(years, quarters):
    """Quarterly AI-issue lobbyists through the latest complete quarter, Economist style."""
    last_year, last_q = LAST_COMPLETE
    q = quarters[(quarters.year < last_year) | ((quarters.year == last_year)
                                                & (quarters.quarter.map(QUARTERS.index) <= QUARTERS.index(last_q)))]
    q = q.assign(t=q.year + q.quarter.map(QUARTERS.index) / 4 + 0.125)
    latest, base = q.iloc[-1], q[(q.year == 2022) & (q.quarter == last_q)].iloc[0]
    growth = latest.lobbyists / base.lobbyists

    red, blue, grid, ink, muted = "#e3120b", "#006ba2", "#b7c6cf", "#0c0c0c", "#595959"
    plt.rcParams["font.family"] = ["Segoe UI", "Arial", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(7.2, 5.0), facecolor="white")
    fig.subplots_adjust(left=0.05, right=0.9, top=0.75, bottom=0.21)
    fig.add_artist(Rectangle((0.05, 0.965), 0.045, 0.012, transform=fig.transFigure, color=red))
    fig.text(0.05, 0.9, "Lobbying on AI keeps climbing", fontsize=15, fontweight="bold", color=ink)
    fig.text(0.05, 0.845, "Federal lobbyists reporting work on AI issues*, by quarter",
             fontsize=10.5, color=ink)
    fig.text(0.05, 0.8, f"{latest.year} {latest.quarter}: {latest.lobbyists:,}, "
             f"{growth:.1f}× the level in {base.year} {base.quarter}", fontsize=10.5, color=muted)

    ax.plot(q.t, q.lobbyists, color=blue, linewidth=2.6, solid_capstyle="round")
    ax.plot(latest.t, latest.lobbyists, "o", color=blue, markersize=6)
    ax.annotate(f"{latest.lobbyists:,}", (latest.t, latest.lobbyists), xytext=(-8, 8),
                textcoords="offset points", ha="right", fontsize=10, fontweight="bold", color=ink)
    ax.set_xlim(2020, last_year + 0.75)
    ax.set_ylim(0, -(-q.lobbyists.max() * 1.08 // 1000) * 1000)
    ax.yaxis.set_major_locator(MultipleLocator(1000))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", length=0, labelsize=10, colors=ink, pad=4)
    ax.set_xticks(range(2020, last_year + 1), [str(y) for y in range(2020, last_year + 1)])
    ax.tick_params(axis="x", length=4, labelsize=10, colors=ink, color=ink)
    ax.grid(axis="y", color=grid, linewidth=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(ink)
    ax.set_axisbelow(True)

    fig.text(0.05, 0.075, "*Lobbying-activity text mentions artificial intelligence/AI, autonomous or automated "
             "vehicles and systems, data centers,\nlarge language models, facial recognition, machine learning or "
             f"deepfakes. Reports after {last_year} {last_q} are not yet all filed.", fontsize=8, color=muted)
    fig.text(0.05, 0.03, "Source: LDA.gov lobbying disclosure reports; method after Public Citizen, "
             "“Generative Influence” (2026)", fontsize=8, color=muted)
    fig.savefig(ROOT / "figure_extension.png", dpi=200)
    plt.close(fig)


def main():
    years, quarters = load()
    reproduction(years, quarters)
    extension(years, quarters)
    print("year  published  reproduced  difference")
    for year, value in PUBLISHED.items():
        ours = years.loc[year, "lobbyists"]
        print(f"{year}  {value:9,}  {ours:10,}  {(ours - value) / value:+10.1%}")
    print("wrote figure.png and figure_extension.png")


if __name__ == "__main__":
    main()
