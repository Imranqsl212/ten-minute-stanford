from __future__ import annotations

import math
import textwrap

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

from .config import FIGURE_DIR, PROCESSED_DIR, TABLE_DIR

CARDINAL = "#8C1515"
TEAL = "#007C83"
GOLD = "#D6A756"
INK = "#1F1F1F"
MUTED = "#6B6B6B"
GRID = "#E7E2DC"
PAPER = "#FBFAF7"


def set_style() -> None:
    mpl.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titleweight": "bold",
            "axes.titlesize": 17,
            "axes.labelcolor": MUTED,
            "text.color": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.edgecolor": GRID,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.hashsalt": "ten-minute-stanford",
        }
    )


def save_figure(fig: plt.Figure, name: str) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / f"{name}.png", dpi=220, bbox_inches="tight")
    svg_path = FIGURE_DIR / f"{name}.svg"
    fig.savefig(svg_path, bbox_inches="tight", metadata={"Date": None})
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_text.splitlines()) + "\n",
        encoding="utf-8",
    )
    plt.close(fig)


def add_headline(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_title(title, loc="left", pad=38)
    ax.text(
        0,
        1.015,
        subtitle,
        transform=ax.transAxes,
        color=MUTED,
        va="bottom",
    )


def feasibility_by_speed() -> None:
    frame = pd.read_csv(TABLE_DIR / "speed_summary.csv")
    labels = [f"{speed:g} mph" for speed in frame["walking_speed_mph"]]
    no_overhead = frame["share_within_10_minutes"] * 100
    overhead = frame["share_within_10_minutes_with_2min_overhead"] * 100
    y = np.arange(len(frame))

    fig, ax = plt.subplots(figsize=(9.5, 5.3))
    height = 0.32
    ax.barh(y + height / 2, no_overhead, height=height, color=TEAL, label="Route only")
    ax.barh(
        y - height / 2,
        overhead,
        height=height,
        color=GOLD,
        label="Two minutes reserved for buildings",
    )
    for index, value in enumerate(no_overhead):
        ax.text(value + 1, index + height / 2, f"{value:.0f}%", va="center", weight="bold")
    for index, value in enumerate(overhead):
        ax.text(value + 1, index - height / 2, f"{value:.0f}%", va="center", weight="bold")
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Share of potential adjacent-block meeting pairings")
    add_headline(
        ax,
        "The ten-minute result depends on walking speed",
        "Reserving two minutes for buildings changes the answer again.",
    )
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right")
    ax.text(
        0,
        -0.17,
        "Source: Stanford ExploreCourses, Stanford Campus Map and OpenStreetMap contributors. "
        "Pairings are hypothetical, not observed student trips.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "feasibility_by_speed")


def route_time_cdf() -> None:
    frame = pd.read_csv(TABLE_DIR / "route_time_distribution.csv")
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    ax.plot(
        frame["route_minutes_3mph"],
        frame["cumulative_share"] * 100,
        color=CARDINAL,
        linewidth=3,
    )
    ax.axvline(10, color=INK, linestyle="--", linewidth=1.3)
    share_at_ten = frame.loc[frame["route_minutes_3mph"] <= 10, "cumulative_share"].max()
    ax.scatter([10], [share_at_ten * 100], color=CARDINAL, s=55, zorder=4)
    ax.annotate(
        f"{share_at_ten:.0%} at 10 minutes",
        xy=(10, share_at_ten * 100),
        xytext=(12, max(8, share_at_ten * 100 - 20)),
        arrowprops={"arrowstyle": "-", "color": MUTED},
        weight="bold",
    )
    ax.set_xlim(left=0)
    ax.set_ylim(0, 101)
    ax.set_xlabel("Estimated walking-network time at 3 mph")
    ax.set_ylabel("Cumulative share of potential pairings")
    add_headline(
        ax,
        f"At 3 mph, {1 - share_at_ten:.0%} of possible transitions exceed ten minutes",
        "Walking-network estimates exclude time spent inside buildings.",
    )
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.text(
        0,
        -0.17,
        "Route estimates exclude time inside buildings. Source: ExploreCourses, Stanford Campus Map and OpenStreetMap contributors.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "route_time_cdf")


def building_matrix() -> None:
    usage = pd.read_csv(TABLE_DIR / "building_usage.csv").head(18)
    routes = pd.read_csv(PROCESSED_DIR / "route_distances.csv")
    labels = usage["facility_label"].tolist()
    ids = usage["facility_id"].tolist()
    relevant = routes[
        routes["origin_facility_id"].isin(ids)
        & routes["destination_facility_id"].isin(ids)
        & routes["connected"]
    ].copy()
    relevant["walk_minutes_3mph"] = relevant["route_distance_meters"] / (3 * 1609.344 / 60)
    matrix = relevant.pivot_table(
        index="origin_facility_id",
        columns="destination_facility_id",
        values="walk_minutes_3mph",
        aggfunc="first",
    ).reindex(index=ids, columns=ids)

    fig, ax = plt.subplots(figsize=(11.5, 10))
    image = ax.imshow(matrix.to_numpy(), cmap="YlOrRd", vmin=0, vmax=16, aspect="equal")
    ax.set_xticks(range(len(labels)), labels, rotation=55, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    add_headline(
        ax,
        "Walking time among the busiest mapped class locations",
        "Estimated minutes at 3 mph. Darker cells exceed the ten-minute window.",
    )
    for row in range(len(labels)):
        for column in range(len(labels)):
            value = matrix.iat[row, column]
            if pd.notna(value):
                ax.text(
                    column,
                    row,
                    f"{value:.0f}",
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white" if value >= 10 else INK,
                )
    colorbar = fig.colorbar(image, ax=ax, shrink=0.72, pad=0.02)
    colorbar.set_label("Estimated minutes")
    ax.set_xlabel("Destination")
    ax.set_ylabel("Origin")
    ax.text(
        0,
        -0.27,
        "Busiest means unique weekly room-time meetings in the published schedule, not students. "
        "Source: ExploreCourses, Campus Map, OpenStreetMap contributors.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "building_time_matrix")


def campus_risk_map() -> None:
    risk = pd.read_csv(TABLE_DIR / "building_risk.csv")
    edges = pd.read_csv(PROCESSED_DIR / "walk_edges.csv")
    longitude_padding = max(0.004, (risk["longitude"].max() - risk["longitude"].min()) * 0.12)
    latitude_padding = max(0.003, (risk["latitude"].max() - risk["latitude"].min()) * 0.12)
    west = risk["longitude"].min() - longitude_padding
    east = risk["longitude"].max() + longitude_padding
    south = risk["latitude"].min() - latitude_padding
    north = risk["latitude"].max() + latitude_padding
    visible_edges = edges[
        edges[["from_longitude", "to_longitude"]].max(axis=1).ge(west)
        & edges[["from_longitude", "to_longitude"]].min(axis=1).le(east)
        & edges[["from_latitude", "to_latitude"]].max(axis=1).ge(south)
        & edges[["from_latitude", "to_latitude"]].min(axis=1).le(north)
    ]
    segments = visible_edges[
        ["from_longitude", "from_latitude", "to_longitude", "to_latitude"]
    ].to_numpy()
    segments = segments.reshape((-1, 2, 2))

    fig, ax = plt.subplots(figsize=(10, 8.5))
    collection = LineCollection(segments, colors="#D8D5CF", linewidths=0.35, alpha=0.55)
    ax.add_collection(collection)
    sizes = 18 + 85 * np.sqrt(
        risk["potential_next_meeting_pairs"] / risk["potential_next_meeting_pairs"].max()
    )
    scatter = ax.scatter(
        risk["longitude"],
        risk["latitude"],
        c=risk["share_over_10min_3mph"] * 100,
        s=sizes,
        cmap="YlOrRd",
        vmin=0,
        vmax=100,
        edgecolor="white",
        linewidth=0.6,
        alpha=0.95,
        zorder=3,
    )
    label_rows = risk.nlargest(6, "potential_next_meeting_pairs")
    label_offsets = {
        "Building 160": (24, 24),
        "Lathrop Library": (22, -16),
        "Building 200": (-22, -16),
        "Building 260": (-8, -24),
        "Sapp Center": (14, 12),
        "Building 380": (-18, -16),
    }
    for row in label_rows.itertuples(index=False):
        x_offset, y_offset = label_offsets.get(row.origin_label, (12, 12))
        ax.annotate(
            row.origin_label,
            (row.longitude, row.latitude),
            xytext=(x_offset, y_offset),
            textcoords="offset points",
            fontsize=7.5,
            weight="bold",
            ha="left" if x_offset > 0 else "right",
        )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect(1 / math.cos(math.radians(float(risk["latitude"].mean()))))
    ax.set_axis_off()
    add_headline(
        ax,
        "Some starting points leave fewer next classes within reach",
        "Color shows the share of possible next meetings beyond ten minutes at 3 mph; size shows pairing count.",
    )
    colorbar = fig.colorbar(scatter, ax=ax, shrink=0.7, pad=0.02)
    colorbar.set_label("Potential pairings over 10 minutes (%)")
    ax.text(
        0,
        -0.035,
        "Map data (ODbL): OpenStreetMap contributors, openstreetmap.org/copyright. "
        "Schedule: Stanford ExploreCourses. Coordinates: Stanford Campus Map. Not an accessibility map.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "campus_transition_risk")


def constrained_routes() -> None:
    frame = pd.read_csv(TABLE_DIR / "top_constrained_routes.csv").head(12).copy()
    if frame.empty:
        return
    frame["route"] = frame["origin_label"] + "  →  " + frame["destination_label"]
    frame = frame.sort_values("walk_minutes_3_0mph")
    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(frame["route"], frame["walk_minutes_3_0mph"], color=CARDINAL)
    ax.axvline(10, color=INK, linestyle="--", linewidth=1.2)
    for bar, minutes, pairs in zip(
        bars,
        frame["walk_minutes_3_0mph"],
        frame["potential_meeting_pairs"],
        strict=False,
    ):
        ax.text(
            minutes + 0.2,
            bar.get_y() + bar.get_height() / 2,
            f"{minutes:.1f} min · {int(pairs):,} possible pairs",
            va="center",
            fontsize=8.5,
        )
    ax.set_xlim(0, max(16, frame["walk_minutes_3_0mph"].max() + 5))
    ax.set_xlabel("Estimated walking-network time at 3 mph")
    ax.set_title("Frequently available pairings that cross the ten-minute line")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.text(
        0,
        -0.12,
        "Pairs join unique scheduled room-time meetings ten minutes apart; they do not show co-enrollment.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "frequent_constrained_routes")


def mode_comparison() -> None:
    walking = pd.read_csv(TABLE_DIR / "speed_summary.csv")
    bicycle = pd.read_csv(TABLE_DIR / "bicycle_speed_summary.csv")
    walk = walking.loc[walking["walking_speed_mph"].eq(3)].iloc[0]
    bike = bicycle.loc[bicycle["bicycle_speed_mph"].eq(8)].iloc[0]
    labels = ["Walk at 3 mph", "Bicycle at 8 mph"]
    route_only = [
        walk["share_within_10_minutes"] * 100,
        bike["share_within_10_minutes"] * 100,
    ]
    with_handling = [
        walk["share_within_10_minutes_with_2min_overhead"] * 100,
        bike["share_within_10_minutes_with_2min_handling"] * 100,
    ]
    x = np.arange(len(labels))
    width = 0.34
    fig, ax = plt.subplots(figsize=(9.5, 5.3))
    left = ax.bar(x - width / 2, route_only, width, color=TEAL, label="Route only")
    right = ax.bar(
        x + width / 2,
        with_handling,
        width,
        color=GOLD,
        label="Two minutes reserved",
    )
    for bars in (left, right):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.2,
                f"{bar.get_height():.1f}%",
                ha="center",
                weight="bold",
            )
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 106)
    ax.set_ylabel("Share of potential adjacent meeting pairings")
    add_headline(
        ax,
        "A bicycle changes the modeled reach of ten minutes",
        "Speeds and two-minute handling allowances are sensitivity assumptions, not observed behavior.",
    )
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5))
    ax.text(
        0,
        -0.18,
        "Bicycle routes exclude stairs and honor mapped access and one-way tags. "
        "They do not include bike parking or walking a bike. Source: ExploreCourses, "
        "Stanford Campus Map and OpenStreetMap contributors.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "walking_bicycle_comparison")


def time_slot_feasibility() -> None:
    frame = pd.read_csv(TABLE_DIR / "time_slot_summary.csv")
    speed_summary = pd.read_csv(TABLE_DIR / "speed_summary.csv")
    overall = float(
        speed_summary.loc[speed_summary["walking_speed_mph"].eq(3), "share_within_10_minutes"].iloc[
            0
        ]
        * 100
    )
    frame = frame.nlargest(12, "potential_meeting_pairs").sort_values(
        "origin_end_minutes", ascending=False
    )
    values = frame["walk_share_within_10min_3mph"] * 100
    colors = [TEAL if value >= overall else GOLD for value in values]
    fig, ax = plt.subplots(figsize=(10, 7.2))
    bars = ax.barh(frame["passing_period"], values, color=colors)
    ax.axvline(overall, color=MUTED, linestyle="--", linewidth=1.1)
    ax.text(
        overall,
        len(frame) - 0.15,
        f"overall {overall:.1f}%",
        color=MUTED,
        ha="center",
        fontsize=8,
    )
    for bar, value, pair_count in zip(bars, values, frame["potential_meeting_pairs"], strict=False):
        ax.text(
            value + 0.6,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}% · {int(pair_count):,} pairs",
            va="center",
            fontsize=8.2,
            weight="bold",
        )
    ax.set_xlim(0, 106)
    ax.set_xlabel("Share within ten minutes at 3 mph")
    add_headline(
        ax,
        "The answer changes across actual course passing periods",
        "Twelve busiest end-to-start slots in the published Winter 2026 schedule.",
    )
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.text(
        0,
        -0.13,
        "Pair counts join all schedule-compatible meetings in each slot; they do not show "
        "co-enrollment. Source: Stanford ExploreCourses XML API, Stanford Campus Map and "
        "OpenStreetMap contributors.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "time_slot_feasibility")


def component_schedule_patterns() -> None:
    time_frame = pd.read_csv(TABLE_DIR / "component_time_summary.csv")
    day_frame = pd.read_csv(TABLE_DIR / "component_day_summary.csv")
    transition_frame = pd.read_csv(TABLE_DIR / "component_transition_summary.csv").sort_values(
        "transition_order"
    )
    components = (("LEC", "Lecture", TEAL), ("DIS", "Discussion", GOLD))
    time_labels = (
        "Before\n10:30",
        "10:30-\n11:59",
        "Noon-\n2:29",
        "2:30-\n4:29",
        "4:30 or\nlater",
    )
    day_labels = ("Mon", "Tue", "Wed", "Thu", "Fri")

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.8))
    width = 0.36
    for axis, frame, order_column, labels in (
        (axes[0], time_frame, "time_bin_order", time_labels),
        (axes[1], day_frame, "weekday_order", day_labels),
    ):
        x = np.arange(len(labels))
        for component_index, (component, label, color) in enumerate(components):
            values = (
                frame[frame["component"].eq(component)]
                .sort_values(order_column)["share_of_component_rows"]
                .to_numpy()
                * 100
            )
            offset = (component_index - 0.5) * width
            axis.bar(x + offset, values, width=width, label=label, color=color)
        axis.set_xticks(x, labels)
        axis.set_ylim(0, 42)
        axis.set_ylabel("Share of component meeting-day rows")
        axis.grid(axis="y", color=GRID, linewidth=0.8)
        axis.set_axisbelow(True)
    axes[0].set_title("Start time", loc="left", fontsize=12)
    axes[1].set_title("Weekday", loc="left", fontsize=12)
    axes[1].legend(frameon=False, loc="upper left")
    transition_values = transition_frame["share_within_10min_3mph"] * 100
    transition_bars = axes[2].bar(
        transition_frame["transition_label"].str.replace(" to ", "\n→\n", regex=False),
        transition_values,
        color=(TEAL, TEAL, GOLD, GOLD),
        width=0.68,
    )
    for bar, value, count in zip(
        transition_bars,
        transition_values,
        transition_frame["potential_meeting_pairs"],
        strict=True,
    ):
        axes[2].text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.4,
            f"{value:.1f}%\nn={int(count):,}",
            ha="center",
            va="bottom",
            fontsize=8.3,
            weight="bold",
        )
    axes[2].axhline(100, color=GRID, linewidth=0.8)
    axes[2].set_ylim(0, 108)
    axes[2].set_ylabel("Share of possible pairs within ten minutes")
    axes[2].set_title("Modeled walking fit at 3 mph", loc="left", fontsize=12)
    axes[2].grid(axis="y", color=GRID, linewidth=0.8)
    axes[2].set_axisbelow(True)
    fig.suptitle(
        "Component timing changes the mix of possible ten-minute trips",
        x=0.055,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.055,
        0.91,
        "Winter 2026 in-person section listings and all schedule-compatible LEC/DIS meeting pairs.",
        color=MUTED,
    )
    fig.text(
        0.055,
        -0.01,
        "Rows and pairs represent published schedule combinations, not unique or co-enrolled students. "
        "Route estimates use Stanford Campus Map destinations and OpenStreetMap paths.",
        color=MUTED,
        fontsize=8.5,
    )
    fig.subplots_adjust(top=0.8, bottom=0.18, left=0.055, right=0.98, wspace=0.32)
    save_figure(fig, "component_schedule_patterns")

    mobile_fig, mobile_axes = plt.subplots(3, 1, figsize=(6.2, 13.2))
    for axis, frame, order_column, labels in (
        (mobile_axes[0], time_frame, "time_bin_order", time_labels),
        (mobile_axes[1], day_frame, "weekday_order", day_labels),
    ):
        x = np.arange(len(labels))
        for component_index, (component, label, color) in enumerate(components):
            values = (
                frame[frame["component"].eq(component)]
                .sort_values(order_column)["share_of_component_rows"]
                .to_numpy()
                * 100
            )
            offset = (component_index - 0.5) * width
            axis.bar(x + offset, values, width=width, label=label, color=color)
        axis.set_xticks(x, labels)
        axis.set_ylim(0, 42)
        axis.set_ylabel("Share of meeting-day rows")
        axis.tick_params(axis="both", labelsize=11)
        axis.grid(axis="y", color=GRID, linewidth=0.8)
        axis.set_axisbelow(True)
    mobile_axes[0].set_title("Start time", loc="left", fontsize=12)
    mobile_axes[0].legend(frameon=False, loc="upper right")
    mobile_axes[1].set_title("Weekday", loc="left", fontsize=12)
    mobile_transition_bars = mobile_axes[2].bar(
        transition_frame["transition_label"].str.replace(" to ", "\n→\n", regex=False),
        transition_values,
        color=(TEAL, TEAL, GOLD, GOLD),
        width=0.68,
    )
    for bar, value, count in zip(
        mobile_transition_bars,
        transition_values,
        transition_frame["potential_meeting_pairs"],
        strict=True,
    ):
        mobile_axes[2].text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}%\nn={int(count):,}",
            ha="center",
            va="bottom",
            fontsize=8.4,
            weight="bold",
        )
    mobile_axes[2].set_ylim(0, 108)
    mobile_axes[2].set_ylabel("Share within ten minutes")
    mobile_axes[2].tick_params(axis="both", labelsize=11)
    mobile_axes[2].set_title("Modeled walking fit at 3 mph", loc="left", fontsize=12)
    mobile_axes[2].grid(axis="y", color=GRID, linewidth=0.8)
    mobile_axes[2].set_axisbelow(True)
    mobile_fig.suptitle(
        "Component timing changes the mix\nof possible ten-minute trips",
        x=0.13,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    mobile_fig.text(
        0.13,
        0.91,
        "Winter 2026 schedule rows and compatible LEC/DIS meeting pairs.",
        color=MUTED,
    )
    mobile_fig.text(
        0.13,
        0.015,
        "Schedule combinations, not unique or co-enrolled students.\n"
        "Sources: Stanford ExploreCourses, Stanford Campus Map and OpenStreetMap contributors.",
        color=MUTED,
        fontsize=8.2,
    )
    mobile_fig.subplots_adjust(top=0.86, bottom=0.12, left=0.13, right=0.97, hspace=0.52)
    save_figure(mobile_fig, "component_schedule_patterns_mobile")


def department_location_concentration() -> None:
    frame = pd.read_csv(TABLE_DIR / "department_location_summary.csv")
    feasibility = pd.read_csv(TABLE_DIR / "subject_transition_feasibility.csv")
    top = frame[frame["facility_rank_within_subject"].eq(1)].nlargest(
        15, "total_mapped_meeting_day_rows"
    )
    top = top.merge(
        feasibility[
            [
                "subject_code",
                "potential_outgoing_pairs",
                "outgoing_share_over_10min_3mph",
            ]
        ],
        on="subject_code",
        how="left",
        validate="one_to_one",
    ).sort_values("total_mapped_meeting_day_rows")
    labels = [
        textwrap.fill(f"{row.subject_name} ({row.subject_code})", width=28)
        for row in top.itertuples(index=False)
    ]
    concentration_values = top["share_of_subject_mapped_rows"] * 100
    risk_values = top["outgoing_share_over_10min_3mph"] * 100

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(13.5, 9.2),
        sharey=True,
        gridspec_kw={"width_ratios": (1.35, 1)},
    )
    concentration_bars = axes[0].barh(labels, concentration_values, color=TEAL)
    for bar, row, value in zip(
        concentration_bars,
        top.itertuples(index=False),
        concentration_values,
        strict=True,
    ):
        axes[0].text(
            value + 1,
            bar.get_y() + bar.get_height() / 2,
            f"{row.facility_label} · {value:.0f}%",
            va="center",
            fontsize=8.5,
            weight="bold",
        )
    risk_bars = axes[1].barh(labels, risk_values, color=CARDINAL)
    for bar, value, count in zip(
        risk_bars,
        risk_values,
        top["potential_outgoing_pairs"],
        strict=True,
    ):
        axes[1].text(
            value + 0.6,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}% · n={int(count):,}",
            va="center",
            fontsize=8.2,
            weight="bold",
        )
    axes[0].set_xlim(0, 112)
    axes[1].set_xlim(0, 44)
    axes[0].set_xlabel("Share of mapped rows at top facility")
    axes[1].set_xlabel("Share of outgoing pairs over ten minutes")
    axes[0].set_title("Campus concentration", loc="left", fontsize=12)
    axes[1].set_title("Modeled route risk at 3 mph", loc="left", fontsize=12)
    fig.suptitle(
        "Subject areas face different campus footprints and route mixes",
        x=0.24,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.24,
        0.91,
        "The 15 largest mapped subject areas; outgoing pairs connect a meeting to every compatible next meeting.",
        color=MUTED,
    )
    for axis in axes:
        axis.grid(axis="x", color=GRID, linewidth=0.8)
        axis.set_axisbelow(True)
    fig.text(
        0.24,
        0.025,
        "Subject codes can represent departments, programs or curricular areas. Cross-listed meetings are attributed to each published "
        "subject; pair totals across subjects therefore do not sum to the campus total. Unmapped rooms are excluded.",
        color=MUTED,
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.24, right=0.97, top=0.8, bottom=0.12, wspace=0.2)
    save_figure(fig, "department_location_concentration")

    mobile_labels = top["subject_code"].astype(str).tolist()
    mobile_fig, mobile_ax = plt.subplots(figsize=(6.2, 12.5))
    y = np.arange(len(top))
    height = 0.34
    concentration_bars = mobile_ax.barh(
        y + height / 2,
        concentration_values,
        height=height,
        color=TEAL,
        label="Rows at top facility",
    )
    risk_bars = mobile_ax.barh(
        y - height / 2,
        risk_values,
        height=height,
        color=CARDINAL,
        label="Outgoing pairs over ten minutes",
    )
    for bars, values in (
        (concentration_bars, concentration_values),
        (risk_bars, risk_values),
    ):
        for bar, value in zip(bars, values, strict=True):
            mobile_ax.text(
                value + 1,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.0f}%",
                va="center",
                fontsize=8.2,
                weight="bold",
            )
    mobile_ax.set_yticks(y, mobile_labels)
    mobile_ax.tick_params(axis="y", labelsize=12)
    mobile_ax.tick_params(axis="x", labelsize=10.5)
    mobile_ax.set_xlim(0, 108)
    mobile_ax.set_xlabel("Share")
    mobile_ax.grid(axis="x", color=GRID, linewidth=0.8)
    mobile_ax.set_axisbelow(True)
    mobile_ax.legend(frameon=False, loc="lower right")
    add_headline(
        mobile_ax,
        "Subject areas face different route mixes",
        "The 15 largest mapped subject areas; modeled walking at 3 mph.",
    )
    mobile_ax.text(
        0,
        -0.075,
        "Teal shows campus concentration; red directly tests possible outgoing routes.\n"
        "Cross-listed subject totals are not additive.",
        transform=mobile_ax.transAxes,
        color=MUTED,
        fontsize=8.2,
    )
    mobile_fig.subplots_adjust(left=0.23, right=0.97, top=0.88, bottom=0.1)
    save_figure(mobile_fig, "department_location_concentration_mobile")


def high_enrollment_transitions() -> None:
    frame = pd.read_csv(TABLE_DIR / "high_enrollment_transitions.csv")
    within = frame["within_10min_3mph"].astype(str).str.casefold().eq("true")

    fig, ax = plt.subplots(figsize=(9.8, 6.4))
    ax.scatter(
        frame.loc[within, "smaller_reported_enrollment"],
        frame.loc[within, "walk_minutes_3_0mph"],
        color=TEAL,
        alpha=0.58,
        s=42,
        label="Within ten modeled minutes",
    )
    ax.scatter(
        frame.loc[~within, "smaller_reported_enrollment"],
        frame.loc[~within, "walk_minutes_3_0mph"],
        color=CARDINAL,
        alpha=0.75,
        s=48,
        label="Above ten modeled minutes",
    )
    ax.axhline(10, color=INK, linestyle="--", linewidth=1.2)

    labels = pd.concat(
        [frame.head(1), frame.loc[~within].head(3)], ignore_index=True
    ).drop_duplicates(["origin_course_number", "destination_course_number", "walk_minutes_3_0mph"])

    def short_course(value: str) -> str:
        first = value.split(" / ")[0]
        return f"{first}+" if " / " in value else first

    offsets = ((10, 10), (10, -18), (10, 10), (-80, 12))
    for offset, row in zip(offsets, labels.itertuples(index=False), strict=False):
        ax.annotate(
            f"{short_course(row.origin_course_number)} → "
            f"{short_course(row.destination_course_number)}",
            (row.smaller_reported_enrollment, row.walk_minutes_3_0mph),
            xytext=offset,
            textcoords="offset points",
            fontsize=8,
            weight="bold",
            arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.7},
        )
    threshold = int(frame["enrollment_screen_threshold"].iloc[0])
    ax.set_xlabel("Smaller of the two reported meeting enrollments")
    ax.set_ylabel("Estimated walking-network minutes at 3 mph")
    add_headline(
        ax,
        "Some large-section pairings still cross the ten-minute line",
        f"Different-building schedule combinations where both meetings report at least {threshold} enrolled.",
    )
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right")
    ax.text(
        0,
        -0.16,
        "The smaller enrollment is not co-enrollment or an estimate of route traffic. Each point is one unique "
        "course-time-building combination. Sources: Stanford ExploreCourses, Campus Map and OpenStreetMap contributors.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    save_figure(fig, "high_enrollment_transitions")


def create_all_visuals() -> None:
    set_style()
    feasibility_by_speed()
    route_time_cdf()
    building_matrix()
    campus_risk_map()
    constrained_routes()
    mode_comparison()
    time_slot_feasibility()
    component_schedule_patterns()
    department_location_concentration()
    high_enrollment_transitions()
