import json
from pathlib import Path

import pandas as pd
import pytest

from ten_minute_stanford.interactive import (
    _reconstruct_path,
    _shortest_path_tree,
    weighted_scenario_share,
)

ROOT = Path(__file__).resolve().parents[1]


def test_shortest_path_tree_reconstructs_route() -> None:
    graph = {
        1: {2: 2.0, 3: 9.0},
        2: {1: 2.0, 3: 3.0},
        3: {1: 9.0, 2: 3.0},
    }

    distances, previous = _shortest_path_tree(graph, 1, {3})

    assert distances[3] == 5.0
    assert _reconstruct_path(previous, 1, 3) == [1, 2, 3]


def test_weighted_scenario_share_uses_pair_counts() -> None:
    pairs = pd.DataFrame(
        {
            "route_distance_meters": [100.0, 1000.0],
            "potential_meeting_pairs": [9, 1],
        }
    )

    share = weighted_scenario_share(
        pairs,
        passing_period_minutes=10,
        walking_speed_mph=3,
        building_overhead_minutes=0,
    )

    assert share == pytest.approx(0.9)


def test_interactive_payload_matches_published_analysis() -> None:
    payload = json.loads(
        (ROOT / "reports/generated/interactive/route_explorer.json").read_text()
    )
    summary = json.loads(
        (ROOT / "reports/generated/analysis_summary.json").read_text()
    )
    pair_summary = pd.read_csv(
        ROOT / "reports/generated/tables/building_pair_summary.csv"
    )

    assert payload["metadata"]["facility_count"] == 75
    assert payload["metadata"]["route_count"]["walking_undirected"] == 2850
    assert payload["metadata"]["route_count"]["bicycle_directed"] == 5625
    assert payload["metadata"]["terms"] == summary["terms"]
    assert (
        payload["metadata"]["potential_adjacent_meeting_pairs"]
        == summary["potential_adjacent_meeting_pairs"]
    )

    featured = pair_summary[
        (pair_summary["origin_facility_id"] == "08-350")
        & (pair_summary["destination_facility_id"] == "04-720")
    ].iloc[0]
    route = payload["routes"]["walk"]["04-720|08-350"]
    assert route["distance_meters"] == pytest.approx(
        featured["route_distance_meters"], abs=0.1
    )

    ten_minute_scenario = next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["passing_period_minutes"] == 10
        and scenario["walking_speed_mph"] == 3
        and scenario["building_overhead_minutes"] == 0
    )
    assert ten_minute_scenario["share_feasible"] == pytest.approx(
        summary["three_mph_share_within_10_minutes"]
    )

    scenario_table = pd.read_csv(
        ROOT / "reports/generated/tables/passing_period_scenarios.csv"
    )
    payload_scenarios = pd.DataFrame(payload["scenarios"])
    sort_columns = [
        "passing_period_minutes",
        "walking_speed_mph",
        "building_overhead_minutes",
    ]
    scenario_columns = [
        *sort_columns,
        "available_route_minutes",
        "feasible_pairs",
        "total_pairs",
        "share_feasible",
    ]
    pd.testing.assert_frame_equal(
        scenario_table[scenario_columns]
        .sort_values(sort_columns)
        .reset_index(drop=True),
        payload_scenarios[scenario_columns]
        .sort_values(sort_columns)
        .reset_index(drop=True),
        check_dtype=False,
    )

    fifteen_minute_scenario = next(
        scenario
        for scenario in payload["scenarios"]
        if scenario["passing_period_minutes"] == 15
        and scenario["walking_speed_mph"] == 3
        and scenario["building_overhead_minutes"] == 0
    )
    assert fifteen_minute_scenario["share_feasible"] == pytest.approx(
        weighted_scenario_share(
            pair_summary,
            passing_period_minutes=15,
            walking_speed_mph=3,
            building_overhead_minutes=0,
        )
    )

    assert payload["modes"]["bike"]["directional_routes"] is True
    assert "08-350|04-720" in payload["routes"]["bike"]
    assert "04-720|08-350" in payload["routes"]["bike"]
