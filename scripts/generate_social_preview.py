from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "reports" / "generated" / "analysis_summary.json"
OUTPUT_PATH = ROOT / "site" / "social-preview.png"


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    share = round(summary["three_mph_share_within_10_minutes"] * 100)
    pair_count = summary["potential_adjacent_meeting_pairs"]

    fig = plt.figure(figsize=(12.8, 6.4), dpi=100, facecolor="#FBFAF7")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    for position in [0.04, 0.12, 0.2, 0.28, 0.36, 0.44, 0.52, 0.6, 0.68, 0.76, 0.84, 0.92]:
        ax.axvline(position, color="#8C1515", alpha=0.035, linewidth=0.8)
    for position in [0.08, 0.2, 0.32, 0.44, 0.56, 0.68, 0.8, 0.92]:
        ax.axhline(position, color="#8C1515", alpha=0.035, linewidth=0.8)

    route_x = [0.03, 0.14, 0.25, 0.38, 0.5, 0.61, 0.72, 0.88, 0.97]
    route_y = [0.18, 0.28, 0.23, 0.4, 0.36, 0.53, 0.5, 0.69, 0.66]
    ax.plot(route_x, route_y, color="#007C83", alpha=0.22, linewidth=3)
    ax.scatter(route_x, route_y, s=35, color="#007C83", alpha=0.32, edgecolors="none")

    ax.add_patch(Rectangle((0.665, 0.11), 0.285, 0.78, facecolor="#8C1515", linewidth=0))
    ax.add_patch(Rectangle((0.64, 0.14), 0.025, 0.72, facecolor="#171717", linewidth=0))

    fig.text(
        0.065,
        0.86,
        "STANFORD SCHEDULE ANALYSIS  /  WINTER 2026",
        color="#8C1515",
        fontsize=14,
        fontfamily="DejaVu Sans",
        fontweight="bold",
    )
    fig.text(
        0.06,
        0.68,
        "Ten minutes\nbetween classes.",
        color="#171717",
        fontsize=48,
        linespacing=0.92,
        fontfamily="DejaVu Serif",
        fontweight="bold",
    )
    fig.text(
        0.065,
        0.27,
        "How far does that get you\nat Stanford?",
        color="#3F3B38",
        fontsize=25,
        linespacing=1.15,
        fontfamily="DejaVu Serif",
    )
    fig.text(
        0.805,
        0.59,
        f"{share}%",
        ha="center",
        color="white",
        fontsize=78,
        fontfamily="DejaVu Serif",
        fontweight="bold",
    )
    fig.text(
        0.805,
        0.42,
        "within 10 minutes\nat 3 mph",
        ha="center",
        color="white",
        fontsize=19,
        linespacing=1.25,
        fontfamily="DejaVu Sans",
        fontweight="bold",
    )
    fig.text(
        0.805,
        0.22,
        f"{pair_count:,} possible routes",
        ha="center",
        color="#F2D9D5",
        fontsize=12,
        fontfamily="DejaVu Sans",
    )
    fig.text(
        0.065,
        0.075,
        "ExploreCourses  +  Stanford Campus Map  +  OpenStreetMap",
        color="#66615D",
        fontsize=12,
        fontfamily="DejaVu Sans",
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, facecolor=fig.get_facecolor(), dpi=100)
    plt.close(fig)
    print(f"Social preview written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

