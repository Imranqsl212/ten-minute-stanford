import json
from pathlib import Path

import pandas as pd
import pytest

from ten_minute_stanford.analysis import (
    build_component_schedule_summaries,
    build_component_transition_summary,
    build_high_enrollment_transitions,
    build_potential_pairs,
    build_student_survey_summary,
    build_subject_transition_feasibility,
)

ROOT = Path(__file__).resolve().parents[1]


def test_student_survey_summary_counts_multiple_mode_selections() -> None:
    responses = pd.read_csv(ROOT / "reporting/student_survey_responses.csv").fillna("")

    summary = build_student_survey_summary(responses).set_index("metric")

    assert summary.loc["reported_late", "count"] == 14
    assert summary.loc["close_call", "count"] == 6
    assert summary.loc["never_late", "count"] == 7
    assert summary.loc["late_or_close_call", "count"] == 20
    assert summary.loc["selected_walking", "count"] == 21
    assert summary.loc["selected_biking", "count"] == 11
    assert summary.loc["selected_e-scooter", "count"] == 5
    assert summary.loc["reported_concrete_consequence", "count"] == 11
    assert summary.loc["missed_class_content", "count"] == 6
    assert summary.loc["course_choice_effect", "count"] == 2
    assert summary.loc["skipped_adjacent_activity", "count"] == 3
    assert summary.loc["reported_late", "denominator"] == 27
    assert summary.loc["reported_concrete_consequence", "denominator"] == 23


def test_only_exact_ten_minute_gap_is_paired() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Autumn",
                "day": "Mon",
                "class_number": "1",
                "course_number": "A 1",
                "component": "LEC",
                "enrolled": 10,
                "date_start": pd.Timestamp("2025-09-22"),
                "date_end": pd.Timestamp("2025-12-05"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "A",
            },
            {
                "term": "Autumn",
                "day": "Mon",
                "class_number": "2",
                "course_number": "B 1",
                "component": "LEC",
                "enrolled": 10,
                "date_start": pd.Timestamp("2025-09-22"),
                "date_end": pd.Timestamp("2025-12-05"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "B",
            },
            {
                "term": "Autumn",
                "day": "Mon",
                "class_number": "3",
                "course_number": "C 1",
                "component": "LEC",
                "enrolled": 10,
                "date_start": pd.Timestamp("2025-09-22"),
                "date_end": pd.Timestamp("2025-12-05"),
                "start_minutes": 635,
                "end_minutes": 685,
                "facility_id": "C",
            },
        ]
    )
    routes = pd.DataFrame(
        [
            {
                "origin_facility_id": "A",
                "destination_facility_id": "B",
                "route_distance_meters": 700,
                "connected": True,
                "origin_snap_meters": 0,
                "destination_snap_meters": 0,
            }
        ]
    )
    pairs = build_potential_pairs(meetings, routes)
    assert len(pairs) == 1
    assert pairs.iloc[0]["destination_class_number"] == "2"
    assert bool(pairs.iloc[0]["within_10min_3_0mph"]) is True


def test_repeated_date_blocks_count_once_for_the_same_class_pair() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "1",
                "course_number": "A 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-05"),
                "date_end": pd.Timestamp("2026-03-13"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "A",
            },
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "2",
                "course_number": "B 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-07"),
                "date_end": pd.Timestamp("2026-01-07"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "B",
            },
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "2",
                "course_number": "B 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-02-04"),
                "date_end": pd.Timestamp("2026-02-04"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "B",
            },
        ]
    )
    routes = pd.DataFrame(
        [
            {
                "origin_facility_id": "A",
                "destination_facility_id": "B",
                "route_distance_meters": 700,
                "connected": True,
            }
        ]
    )

    pairs = build_potential_pairs(meetings, routes)

    assert len(pairs) == 1
    assert pairs.attrs["recurring_pair_rows_collapsed"] == 1


def test_repeated_class_pair_with_different_facilities_is_not_collapsed() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "1",
                "course_number": "A 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-07"),
                "date_end": pd.Timestamp("2026-01-07"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "A",
            },
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "1",
                "course_number": "A 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-02-04"),
                "date_end": pd.Timestamp("2026-02-04"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "C",
            },
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "2",
                "course_number": "B 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-01"),
                "date_end": pd.Timestamp("2026-03-13"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "B",
            },
        ]
    )
    routes = pd.DataFrame(
        [
            {
                "origin_facility_id": "A",
                "destination_facility_id": "B",
                "route_distance_meters": 700,
                "connected": True,
            },
            {
                "origin_facility_id": "C",
                "destination_facility_id": "B",
                "route_distance_meters": 900,
                "connected": True,
            },
        ]
    )

    pairs = build_potential_pairs(meetings, routes)

    assert len(pairs) == 2
    assert pairs.attrs["recurring_pair_rows_collapsed"] == 0


def test_same_class_number_pair_is_counted_then_excluded() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "1",
                "course_number": "A 1",
                "component": "DIS",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-07"),
                "date_end": pd.Timestamp("2026-03-11"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "A",
            },
            {
                "term": "Winter",
                "day": "Wed",
                "class_number": "1",
                "course_number": "A 1",
                "component": "DIS",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-07"),
                "date_end": pd.Timestamp("2026-03-11"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "A",
            },
        ]
    )
    routes = pd.DataFrame(
        [
            {
                "origin_facility_id": "A",
                "destination_facility_id": "A",
                "route_distance_meters": 0,
                "connected": True,
            }
        ]
    )

    pairs = build_potential_pairs(meetings, routes)

    assert pairs.empty
    assert pairs.attrs["pair_date_rows_before_same_class_exclusion"] == 1
    assert pairs.attrs["same_class_number_pair_rows_excluded"] == 1


def test_published_time_slots_and_bicycle_scenarios_cover_the_denominator() -> None:
    summary = json.loads((ROOT / "reports/generated/analysis_summary.json").read_text())
    slots = pd.read_csv(ROOT / "reports/generated/tables/time_slot_summary.csv")
    weekday_slots = pd.read_csv(ROOT / "reports/generated/tables/weekday_time_slot_summary.csv")
    bicycles = pd.read_csv(ROOT / "reports/generated/tables/bicycle_speed_summary.csv")

    assert len(slots) == summary["distinct_passing_period_time_slots"] == 25
    assert len(weekday_slots) == summary["distinct_weekday_time_slots"] == 92
    assert slots["potential_meeting_pairs"].sum() == summary["potential_adjacent_meeting_pairs"]
    assert (
        weekday_slots["potential_meeting_pairs"].sum()
        == summary["potential_adjacent_meeting_pairs"]
    )
    assert (slots["next_start_minutes"] - slots["origin_end_minutes"]).eq(10).all()
    eight_mph = bicycles.loc[bicycles["bicycle_speed_mph"].eq(8.0)].iloc[0]
    assert eight_mph["share_within_10_minutes"] == pytest.approx(
        summary["eight_mph_bicycle_share_within_10_minutes"]
    )


def test_published_course_cases_span_the_modeled_range() -> None:
    cases = pd.read_csv(ROOT / "reports/generated/tables/course_transition_cases.csv")

    assert list(cases["case_type"]) == [
        "Near the median",
        "Near the limit",
        "Above the limit",
        "Longest modeled example",
    ]
    assert (cases["next_start_minutes"] - cases["origin_end_minutes"]).eq(10).all()
    assert list(cases["within_10min_3mph"].astype(bool)) == [True, True, False, False]
    assert cases["margin_minutes_3mph"].tolist() == pytest.approx(10 - cases["walk_minutes_3_0mph"])


def test_overlapping_date_ranges_require_a_shared_weekday() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Winter",
                "day": "Mon",
                "class_number": "1",
                "course_number": "A 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-05"),
                "date_end": pd.Timestamp("2026-01-10"),
                "start_minutes": 570,
                "end_minutes": 620,
                "facility_id": "A",
            },
            {
                "term": "Winter",
                "day": "Mon",
                "class_number": "2",
                "course_number": "B 1",
                "component": "LEC",
                "enrolled": None,
                "date_start": pd.Timestamp("2026-01-10"),
                "date_end": pd.Timestamp("2026-01-12"),
                "start_minutes": 630,
                "end_minutes": 680,
                "facility_id": "B",
            },
        ]
    )
    routes = pd.DataFrame(
        [
            {
                "origin_facility_id": "A",
                "destination_facility_id": "B",
                "route_distance_meters": 700,
                "connected": True,
            }
        ]
    )

    pairs = build_potential_pairs(meetings, routes)

    assert pairs.empty


def test_component_summaries_keep_lecture_and_discussion_denominators_separate() -> None:
    meetings = pd.DataFrame(
        [
            {
                "component": "LEC",
                "class_number": "1",
                "enrolled": 100,
                "start_minutes": 630,
                "day": "Mon",
            },
            {
                "component": "LEC",
                "class_number": "1",
                "enrolled": 100,
                "start_minutes": 630,
                "day": "Wed",
            },
            {
                "component": "DIS",
                "class_number": "2",
                "enrolled": 20,
                "start_minutes": 990,
                "day": "Thu",
            },
            {
                "component": "SEM",
                "class_number": "3",
                "enrolled": 15,
                "start_minutes": 720,
                "day": "Tue",
            },
        ]
    )

    time_summary, day_summary = build_component_schedule_summaries(meetings)

    lecture = time_summary[time_summary["component"].eq("LEC")]
    discussion = time_summary[time_summary["component"].eq("DIS")]
    assert lecture["section_listing_meeting_day_rows"].sum() == 2
    assert discussion["section_listing_meeting_day_rows"].sum() == 1
    assert lecture["share_of_component_rows"].sum() == pytest.approx(1)
    assert discussion["share_of_component_rows"].sum() == pytest.approx(1)
    assert (
        day_summary.loc[
            day_summary["component"].eq("DIS") & day_summary["day"].eq("Thu"),
            "reported_enrollment_seat_instances",
        ].iloc[0]
        == 20
    )


def test_high_enrollment_transitions_are_unique_across_weekdays() -> None:
    pairs = pd.DataFrame(
        [
            {
                "term": "Winter",
                "day": day,
                "origin_course_number": "A 1",
                "origin_component": "LEC",
                "origin_facility_id": "A",
                "origin_label": "Alpha Hall",
                "origin_end_minutes": 620,
                "origin_enrolled": 150,
                "destination_course_number": "B 1",
                "destination_component": "LEC",
                "destination_facility_id": "B",
                "destination_label": "Beta Hall",
                "next_start_minutes": 630,
                "destination_enrolled": 120,
                "route_distance_meters": 900,
                "walk_minutes_3_0mph": 11.2,
            }
            for day in ("Mon", "Wed")
        ]
    )

    result = build_high_enrollment_transitions(pairs, threshold=100)

    assert len(result) == 1
    assert result.iloc[0]["days"] == "Mon / Wed"
    assert result.iloc[0]["weekday_count"] == 2
    assert result.iloc[0]["smaller_reported_enrollment"] == 120
    assert bool(result.iloc[0]["within_10min_3mph"]) is False


def test_component_transition_summary_uses_pair_denominators() -> None:
    rows = []
    for index, (origin, destination, minutes) in enumerate(
        (
            ("LEC", "LEC", 12.0),
            ("LEC", "DIS", 8.0),
            ("DIS", "LEC", 7.0),
            ("DIS", "DIS", 5.0),
        )
    ):
        rows.append(
            {
                "origin_component": origin,
                "destination_component": destination,
                "origin_class_number": str(index),
                "origin_facility_id": f"O{index}",
                "destination_facility_id": f"D{index}",
                "route_distance_meters": minutes * 3 * 1609.344 / 60,
                "walk_minutes_3_0mph": minutes,
                "within_10min_3_0mph": minutes <= 10,
            }
        )

    result = build_component_transition_summary(pd.DataFrame(rows)).set_index(
        ["origin_component", "destination_component"]
    )

    assert result["potential_meeting_pairs"].sum() == 4
    assert result.loc[("LEC", "LEC"), "share_over_10min_3mph"] == 1
    assert result.loc[("DIS", "DIS"), "share_within_10min_3mph"] == 1


def test_subject_transition_summary_attributes_cross_listings_without_additivity() -> None:
    pairs = pd.DataFrame(
        [
            {
                "origin_subject_codes": "CS / LINGUIST",
                "destination_subject_codes": "MATH",
                "within_10min_3_0mph": False,
                "walk_minutes_3_0mph": 12.0,
            },
            {
                "origin_subject_codes": "CS",
                "destination_subject_codes": "HISTORY / CS",
                "within_10min_3_0mph": True,
                "walk_minutes_3_0mph": 5.0,
            },
        ]
    )
    subject_catalog = pd.DataFrame(
        {
            "subject_code": ["CS", "LINGUIST", "MATH", "HISTORY"],
            "subject_name": ["Computer Science", "Linguistics", "Mathematics", "History"],
        }
    )
    locations = pd.DataFrame(
        {
            "subject_code": subject_catalog["subject_code"],
            "facility_rank_within_subject": 1,
            "total_mapped_meeting_day_rows": [2, 1, 1, 1],
            "total_distinct_class_sections": [2, 1, 1, 1],
            "facility_label": ["A", "A", "B", "C"],
            "share_of_subject_mapped_rows": [0.5, 1.0, 1.0, 1.0],
        }
    )

    result = build_subject_transition_feasibility(pairs, locations, subject_catalog).set_index(
        "subject_code"
    )

    assert result.loc["CS", "potential_outgoing_pairs"] == 2
    assert result.loc["CS", "outgoing_share_over_10min_3mph"] == pytest.approx(0.5)
    assert result.loc["MATH", "incoming_share_over_10min_3mph"] == 1
    assert result["potential_outgoing_pairs"].sum() == 3
