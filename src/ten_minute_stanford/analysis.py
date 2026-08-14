from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from .campus_map import USABLE_MATCH_STATUSES, is_queryable_room
from .config import (
    BICYCLE_SPEEDS_MPH,
    PROCESSED_DIR,
    REPORT_DIR,
    REPORTING_DIR,
    TABLE_DIR,
    WALKING_SPEEDS_MPH,
    WEEKDAYS,
)
from .interactive import create_interactive_payload

COMPONENT_LABELS = {"LEC": "Lecture", "DIS": "Discussion"}
TIME_BIN_EDGES = (0, 630, 720, 870, 990, 1441)
TIME_BIN_LABELS = (
    "Before 10:30 a.m.",
    "10:30-11:59 a.m.",
    "Noon-2:29 p.m.",
    "2:30-4:29 p.m.",
    "4:30 p.m. or later",
)
LARGE_ENROLLMENT_THRESHOLD = 100
SURVEY_METRICS = (
    (
        "reported_late",
        "Said distance had made them late",
        "late_response",
        ("Yes, once or twice.", "Yes, multiple times."),
    ),
    (
        "close_call",
        "Said it had been close",
        "late_response",
        ("No, but it's been close.",),
    ),
    (
        "never_late",
        "Said distance had never made them late",
        "late_response",
        ("No, never.",),
    ),
)


def facility_label(row: pd.Series) -> str:
    room = str(row.get("representative_room", "")).strip()
    address = str(row.get("address", "")).strip()
    official = str(row.get("official_label", "")).strip()
    building_match = re.search(r"bldg\.?\s*([A-Za-z0-9-]+)", address, re.IGNORECASE)
    if building_match:
        return f"Building {building_match.group(1).upper()}"
    descriptive_words = ("auditorium", "building", "center", "hall", "library", "sciences")
    if official and (
        not any(character.isdigit() for character in official)
        or any(word in official.casefold() for word in descriptive_words)
    ):
        label = _display_case(official)
        return label.replace("Sapp Center For Science Teaching And Learning", "Sapp Center")
    numeric_match = re.match(r"^(\d{1,3})[-/]", room)
    if numeric_match:
        return f"Building {numeric_match.group(1)}"
    named_match = re.match(r"^(.+?)\s+(?:[A-Z]?\d{2,4}[A-Z]?)$", room, re.IGNORECASE)
    if named_match:
        return _display_case(named_match.group(1).strip())
    return _display_case(room) if room else str(row.get("facility_id", ""))


def _display_case(value: str) -> str:
    label = value.title()
    replacements = {
        "Aoerc": "AOERC",
        "Gsb": "GSB",
        "Mcclelland": "McClelland",
        "Mccullough": "McCullough",
        "Mcmurtry": "McMurtry",
        "Y2E2": "Y2E2",
    }
    for source, destination in replacements.items():
        label = label.replace(source, destination)
    return label


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.casefold().isin({"true", "1", "yes"})


def _weighted_share(values: pd.Series, weights: pd.Series) -> float:
    if float(weights.sum()) == 0:
        return math.nan
    return float(np.average(values.astype(float), weights=weights.astype(float)))


def _sum_with_missing(values: pd.Series) -> float:
    return float(values.sum(min_count=1))


def build_student_survey_summary(responses: pd.DataFrame) -> pd.DataFrame:
    required = {
        "respondent_id",
        "late_response",
        "frustrating_route",
        "travel_modes",
        "other_thoughts",
        "expanded_followup",
        "transition_may_exceed_10min",
        "impact_category",
        "reported_exact_ten_minute_gap",
        "source_batch",
    }
    missing = required - set(responses.columns)
    if missing:
        raise ValueError(f"Student survey is missing columns: {sorted(missing)}")
    if responses.empty or responses["respondent_id"].duplicated().any():
        raise ValueError("Student survey must contain unique respondent IDs")

    allowed_batches = {
        "prior_project_response",
        "google_sheet_legacy_questionnaire",
        "google_sheet_expanded_questionnaire",
    }
    unknown_batches = set(responses["source_batch"]) - allowed_batches
    if unknown_batches:
        raise ValueError(f"Student survey has unknown source batches: {unknown_batches}")

    denominator = len(responses)
    rows: list[dict[str, Any]] = []
    for metric, label, column, accepted in SURVEY_METRICS:
        count = int(responses[column].isin(accepted).sum())
        rows.append(
            {
                "metric": metric,
                "label": label,
                "count": count,
                "denominator": denominator,
                "share": count / denominator,
                "notes": "Mutually exclusive response category",
            }
        )

    late_or_close = int(
        responses["late_response"]
        .isin(
            (
                "Yes, once or twice.",
                "Yes, multiple times.",
                "No, but it's been close.",
            )
        )
        .sum()
    )
    rows.append(
        {
            "metric": "late_or_close_call",
            "label": "Reported lateness or a close call",
            "count": late_or_close,
            "denominator": denominator,
            "share": late_or_close / denominator,
            "notes": "Combines the two yes responses and the close-call response",
        }
    )

    selected_modes = (
        responses["travel_modes"]
        .fillna("")
        .map(lambda value: {mode.strip() for mode in str(value).split(",") if mode.strip()})
    )
    for mode in ("Walking", "Biking", "E-scooter"):
        count = int(
            selected_modes.map(lambda modes, selected_mode=mode: selected_mode in modes).sum()
        )
        rows.append(
            {
                "metric": f"selected_{mode.casefold()}",
                "label": f"Selected {mode.casefold()}",
                "count": count,
                "denominator": denominator,
                "share": count / denominator,
                "notes": "Respondents could select more than one mode",
            }
        )

    followup = responses[_as_bool(responses["expanded_followup"])].copy()
    if followup.empty:
        raise ValueError("Student survey contains no expanded follow-up responses")
    followup_denominator = len(followup)
    impact_categories = {
        "none_reported",
        "missed_class_content",
        "course_choice",
        "skipped_adjacent_activity",
    }
    unknown_categories = set(followup["impact_category"]) - impact_categories
    if unknown_categories:
        raise ValueError(f"Student survey has unknown impact categories: {unknown_categories}")

    followup_rows = (
        (
            "transition_may_exceed_10min",
            "Reported a usual transition time or range extending beyond ten minutes",
            int(_as_bool(followup["transition_may_exceed_10min"]).sum()),
            "Self-reported estimate; does not imply the respondent had a ten-minute gap",
        ),
        (
            "reported_exact_ten_minute_gap",
            "Explicitly reported a current ten-minute class gap",
            int(_as_bool(followup["reported_exact_ten_minute_gap"]).sum()),
            "Based on the respondent's free-text course-pair answer",
        ),
        (
            "reported_concrete_consequence",
            "Described a concrete consequence beyond arrival time",
            int(followup["impact_category"].ne("none_reported").sum()),
            "Manually coded from the expanded impact question",
        ),
        (
            "missed_class_content",
            "Reported missing class content or an announcement",
            int(followup["impact_category"].eq("missed_class_content").sum()),
            "Mutually exclusive manually coded impact category",
        ),
        (
            "course_choice_effect",
            "Reported that distance affected a course choice",
            int(followup["impact_category"].eq("course_choice").sum()),
            "Mutually exclusive manually coded impact category",
        ),
        (
            "skipped_adjacent_activity",
            "Reported skipping office hours, a study group or lunch",
            int(followup["impact_category"].eq("skipped_adjacent_activity").sum()),
            "Mutually exclusive manually coded impact category",
        ),
    )
    for metric, label, count, notes in followup_rows:
        rows.append(
            {
                "metric": metric,
                "label": label,
                "count": count,
                "denominator": followup_denominator,
                "share": count / followup_denominator,
                "notes": notes,
            }
        )
    return pd.DataFrame(rows)


def _read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    meetings = pd.read_csv(PROCESSED_DIR / "meetings.csv", parse_dates=["date_start", "date_end"])
    room_lookup = pd.read_csv(PROCESSED_DIR / "room_lookup.csv")
    facilities = pd.read_csv(PROCESSED_DIR / "facilities.csv")
    routes = pd.read_csv(PROCESSED_DIR / "route_distances.csv")
    bike_routes = pd.read_csv(PROCESSED_DIR / "bike_route_distances.csv")
    return meetings, room_lookup, facilities, routes, bike_routes


def build_potential_pairs(
    meetings: pd.DataFrame,
    routes: pd.DataFrame,
    bike_routes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    meetings = meetings.copy()
    if "subject_codes" not in meetings:
        meetings["subject_codes"] = ""
    origin = meetings[
        [
            "term",
            "day",
            "class_number",
            "course_number",
            "subject_codes",
            "component",
            "enrolled",
            "date_start",
            "date_end",
            "end_minutes",
            "facility_id",
        ]
    ].copy()
    origin["next_start_minutes"] = origin["end_minutes"] + 10
    origin = origin.rename(
        columns={
            "class_number": "origin_class_number",
            "course_number": "origin_course_number",
            "subject_codes": "origin_subject_codes",
            "component": "origin_component",
            "enrolled": "origin_enrolled",
            "date_start": "origin_date_start",
            "date_end": "origin_date_end",
            "end_minutes": "origin_end_minutes",
            "facility_id": "origin_facility_id",
        }
    )

    destination = meetings[
        [
            "term",
            "day",
            "class_number",
            "course_number",
            "subject_codes",
            "component",
            "enrolled",
            "date_start",
            "date_end",
            "start_minutes",
            "facility_id",
        ]
    ].copy()
    destination = destination.rename(
        columns={
            "class_number": "destination_class_number",
            "course_number": "destination_course_number",
            "subject_codes": "destination_subject_codes",
            "component": "destination_component",
            "enrolled": "destination_enrolled",
            "date_start": "destination_date_start",
            "date_end": "destination_date_end",
            "start_minutes": "next_start_minutes",
            "facility_id": "destination_facility_id",
        }
    )

    pairs = origin.merge(destination, on=["term", "day", "next_start_minutes"], how="inner")
    overlap_start = pairs[["origin_date_start", "destination_date_start"]].max(axis=1)
    overlap_end = pairs[["origin_date_end", "destination_date_end"]].min(axis=1)
    weekday_number = pairs["day"].map(dict(zip(WEEKDAYS, range(len(WEEKDAYS)), strict=True)))
    days_to_shared_meeting = (weekday_number - overlap_start.dt.weekday) % 7
    first_shared_meeting = overlap_start + pd.to_timedelta(days_to_shared_meeting, unit="D")
    has_shared_meeting = first_shared_meeting <= overlap_end
    same_class_number = pairs["origin_class_number"] == pairs["destination_class_number"]
    pair_date_rows_before_same_class_exclusion = int(has_shared_meeting.sum())
    same_class_number_rows_excluded = int((has_shared_meeting & same_class_number).sum())
    pairs = pairs[has_shared_meeting & ~same_class_number].copy()
    pair_rows_before_recurrence_deduplication = len(pairs)
    pairs = pairs.drop_duplicates(
        subset=[
            "term",
            "day",
            "origin_class_number",
            "destination_class_number",
            "origin_facility_id",
            "destination_facility_id",
            "origin_end_minutes",
            "next_start_minutes",
        ]
    )
    candidate_count = len(pairs)
    pairs = pairs.merge(
        routes,
        on=["origin_facility_id", "destination_facility_id"],
        how="left",
        validate="many_to_one",
    )
    pairs = pairs[pairs["connected"] == True].copy()  # noqa: E712
    pairs = pairs.dropna(subset=["route_distance_meters"])
    if bike_routes is not None:
        bike_columns = bike_routes[
            [
                "origin_facility_id",
                "destination_facility_id",
                "route_distance_meters",
                "connected",
            ]
        ].rename(
            columns={
                "route_distance_meters": "bike_route_distance_meters",
                "connected": "bike_connected",
            }
        )
        pairs = pairs.merge(
            bike_columns,
            on=["origin_facility_id", "destination_facility_id"],
            how="left",
            validate="many_to_one",
        )
    pairs.attrs["candidate_count_before_routing"] = candidate_count
    pairs.attrs["recurring_pair_rows_collapsed"] = (
        pair_rows_before_recurrence_deduplication - candidate_count
    )
    pairs.attrs["same_class_number_pair_rows_excluded"] = same_class_number_rows_excluded
    pairs.attrs["pair_date_rows_before_same_class_exclusion"] = (
        pair_date_rows_before_same_class_exclusion
    )
    for speed in WALKING_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        meters_per_minute = speed * 1609.344 / 60
        minutes = pairs["route_distance_meters"] / meters_per_minute
        pairs[f"walk_minutes_{suffix}mph"] = minutes
        pairs[f"within_10min_{suffix}mph"] = minutes <= 10
        pairs[f"within_10min_{suffix}mph_with_2min_overhead"] = minutes <= 8
    if bike_routes is not None:
        for speed in BICYCLE_SPEEDS_MPH:
            suffix = str(speed).replace(".", "_")
            meters_per_minute = speed * 1609.344 / 60
            minutes = pairs["bike_route_distance_meters"] / meters_per_minute
            pairs[f"bike_minutes_{suffix}mph"] = minutes
            pairs[f"bike_within_10min_{suffix}mph"] = pairs["bike_connected"].fillna(False) & (
                minutes <= 10
            )
            pairs[f"bike_within_10min_{suffix}mph_with_2min_overhead"] = pairs[
                "bike_connected"
            ].fillna(False) & (minutes <= 8)
    return pairs


def _clock_label(minutes: int | float) -> str:
    hour, minute = divmod(int(minutes), 60)
    suffix = "a.m." if hour < 12 else "p.m."
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def build_component_schedule_summaries(
    meetings: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = meetings[meetings["component"].isin(COMPONENT_LABELS)].copy()
    rows["enrolled"] = pd.to_numeric(rows["enrolled"], errors="coerce")
    rows["time_bin"] = pd.cut(
        rows["start_minutes"],
        bins=TIME_BIN_EDGES,
        labels=TIME_BIN_LABELS,
        right=False,
    )
    rows["day"] = pd.Categorical(rows["day"], categories=WEEKDAYS, ordered=True)

    time_summary = (
        rows.groupby(["component", "time_bin"], observed=False)
        .agg(
            section_listing_meeting_day_rows=("class_number", "size"),
            distinct_class_sections=("class_number", "nunique"),
            reported_enrollment_seat_instances=("enrolled", _sum_with_missing),
        )
        .reset_index()
    )
    day_summary = (
        rows.groupby(["component", "day"], observed=False)
        .agg(
            section_listing_meeting_day_rows=("class_number", "size"),
            distinct_class_sections=("class_number", "nunique"),
            reported_enrollment_seat_instances=("enrolled", _sum_with_missing),
        )
        .reset_index()
    )
    for frame in (time_summary, day_summary):
        frame["component_label"] = frame["component"].map(COMPONENT_LABELS)
        totals = frame.groupby("component")["section_listing_meeting_day_rows"].transform("sum")
        frame["share_of_component_rows"] = frame["section_listing_meeting_day_rows"] / totals

    time_summary["time_bin_order"] = time_summary["time_bin"].cat.codes
    time_summary["time_bin"] = time_summary["time_bin"].astype(str)
    time_summary = time_summary.sort_values(["component", "time_bin_order"])
    day_summary["weekday_order"] = day_summary["day"].cat.codes
    day_summary["day"] = day_summary["day"].astype(str)
    day_summary = day_summary.sort_values(["component", "weekday_order"])
    return time_summary, day_summary


def build_component_transition_summary(pairs: pd.DataFrame) -> pd.DataFrame:
    rows = pairs[
        pairs["origin_component"].isin(COMPONENT_LABELS)
        & pairs["destination_component"].isin(COMPONENT_LABELS)
    ].copy()
    rows["over_10min_3mph"] = ~rows["within_10min_3_0mph"]
    rows["building_pair"] = (
        rows["origin_facility_id"].astype(str)
        + " -> "
        + rows["destination_facility_id"].astype(str)
    )
    summary = rows.groupby(["origin_component", "destination_component"], as_index=False).agg(
        potential_meeting_pairs=("origin_class_number", "size"),
        pairs_within_10min_3mph=("within_10min_3_0mph", "sum"),
        pairs_over_10min_3mph=("over_10min_3mph", "sum"),
        distinct_building_pairs=("building_pair", "nunique"),
        median_route_minutes_3mph=("walk_minutes_3_0mph", "median"),
        p90_route_minutes_3mph=(
            "walk_minutes_3_0mph",
            lambda values: values.quantile(0.9),
        ),
    )
    summary["share_within_10min_3mph"] = (
        summary["pairs_within_10min_3mph"] / summary["potential_meeting_pairs"]
    )
    summary["share_over_10min_3mph"] = (
        summary["pairs_over_10min_3mph"] / summary["potential_meeting_pairs"]
    )
    summary["origin_component_label"] = summary["origin_component"].map(COMPONENT_LABELS)
    summary["destination_component_label"] = summary["destination_component"].map(COMPONENT_LABELS)
    summary["transition_label"] = (
        summary["origin_component"] + " to " + summary["destination_component"]
    )
    order = {
        ("LEC", "LEC"): 0,
        ("LEC", "DIS"): 1,
        ("DIS", "LEC"): 2,
        ("DIS", "DIS"): 3,
    }
    summary["transition_order"] = [
        order[(origin, destination)]
        for origin, destination in zip(
            summary["origin_component"],
            summary["destination_component"],
            strict=True,
        )
    ]
    return summary.sort_values("transition_order").reset_index(drop=True)


def _subject_direction_summary(pairs: pd.DataFrame, direction: str) -> pd.DataFrame:
    subject_column = f"{direction}_subject_codes"
    rows = pairs[[subject_column, "within_10min_3_0mph", "walk_minutes_3_0mph"]].copy()
    rows["subject_code"] = rows[subject_column].fillna("").astype(str).str.split(" / ")
    rows = rows.explode("subject_code")
    rows["subject_code"] = rows["subject_code"].str.strip()
    rows = rows[rows["subject_code"].ne("")].copy()
    rows["over_10min_3mph"] = ~rows["within_10min_3_0mph"]
    prefix = "outgoing" if direction == "origin" else "incoming"
    summary = rows.groupby("subject_code", as_index=False).agg(
        **{
            f"potential_{prefix}_pairs": ("subject_code", "size"),
            f"{prefix}_pairs_within_10min_3mph": (
                "within_10min_3_0mph",
                "sum",
            ),
            f"{prefix}_pairs_over_10min_3mph": ("over_10min_3mph", "sum"),
            f"{prefix}_median_route_minutes_3mph": (
                "walk_minutes_3_0mph",
                "median",
            ),
            f"{prefix}_p90_route_minutes_3mph": (
                "walk_minutes_3_0mph",
                lambda values: values.quantile(0.9),
            ),
        }
    )
    summary[f"{prefix}_share_within_10min_3mph"] = (
        summary[f"{prefix}_pairs_within_10min_3mph"] / summary[f"potential_{prefix}_pairs"]
    )
    summary[f"{prefix}_share_over_10min_3mph"] = (
        summary[f"{prefix}_pairs_over_10min_3mph"] / summary[f"potential_{prefix}_pairs"]
    )
    return summary


def build_subject_transition_feasibility(
    pairs: pd.DataFrame,
    department_location_summary: pd.DataFrame,
    subject_catalog: pd.DataFrame,
) -> pd.DataFrame:
    outgoing = _subject_direction_summary(pairs, "origin")
    incoming = _subject_direction_summary(pairs, "destination")
    summary = outgoing.merge(incoming, on="subject_code", how="outer")
    top_facilities = department_location_summary[
        department_location_summary["facility_rank_within_subject"].eq(1)
    ][
        [
            "subject_code",
            "total_mapped_meeting_day_rows",
            "total_distinct_class_sections",
            "facility_label",
            "share_of_subject_mapped_rows",
        ]
    ].rename(
        columns={
            "facility_label": "top_facility_label",
            "share_of_subject_mapped_rows": "top_facility_share",
        }
    )
    summary = summary.merge(top_facilities, on="subject_code", how="left", validate="one_to_one")
    summary = summary.merge(
        subject_catalog[["subject_code", "subject_name"]],
        on="subject_code",
        how="left",
        validate="one_to_one",
    )
    summary["subject_name"] = summary["subject_name"].fillna(summary["subject_code"])
    count_columns = [
        column
        for column in summary.columns
        if column.startswith("potential_") or "pairs_within" in column or "pairs_over" in column
    ]
    summary[count_columns] = summary[count_columns].fillna(0).astype(int)
    return summary.sort_values(
        ["total_mapped_meeting_day_rows", "subject_code"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)


def build_department_location_summary(
    mapped_listings: pd.DataFrame,
    facilities: pd.DataFrame,
    subject_catalog: pd.DataFrame,
) -> pd.DataFrame:
    rows = mapped_listings.merge(
        facilities[["facility_id", "facility_label"]],
        on="facility_id",
        how="left",
        validate="many_to_one",
    )
    rows = rows.merge(
        subject_catalog,
        left_on="subject_query",
        right_on="subject_code",
        how="left",
        validate="many_to_one",
    )
    rows["subject_code"] = rows["subject_code"].fillna(rows["subject_query"])
    rows["subject_name"] = rows["subject_name"].fillna(rows["subject_query"])
    rows["enrolled"] = pd.to_numeric(rows["enrolled"], errors="coerce")

    locations = rows.groupby(
        [
            "subject_code",
            "subject_name",
            "facility_id",
            "facility_label",
            "latitude",
            "longitude",
        ],
        as_index=False,
    ).agg(
        section_listing_meeting_day_rows=("class_number", "size"),
        distinct_class_sections_at_facility=("class_number", "nunique"),
        reported_enrollment_seat_instances=("enrolled", _sum_with_missing),
    )
    totals = rows.groupby(["subject_code", "subject_name"], as_index=False).agg(
        total_mapped_meeting_day_rows=("class_number", "size"),
        total_distinct_class_sections=("class_number", "nunique"),
        total_reported_enrollment_seat_instances=(
            "enrolled",
            _sum_with_missing,
        ),
    )
    locations = locations.merge(
        totals, on=["subject_code", "subject_name"], how="left", validate="many_to_one"
    )
    locations["share_of_subject_mapped_rows"] = (
        locations["section_listing_meeting_day_rows"] / locations["total_mapped_meeting_day_rows"]
    )
    locations = locations.sort_values(
        [
            "total_mapped_meeting_day_rows",
            "subject_code",
            "section_listing_meeting_day_rows",
            "facility_label",
        ],
        ascending=[False, True, False, True],
    )
    locations["facility_rank_within_subject"] = locations.groupby("subject_code").cumcount() + 1
    return locations


def build_high_enrollment_transitions(
    pairs: pd.DataFrame,
    *,
    threshold: int = LARGE_ENROLLMENT_THRESHOLD,
) -> pd.DataFrame:
    candidates = pairs[
        pairs["origin_facility_id"].ne(pairs["destination_facility_id"])
        & pairs["origin_enrolled"].ge(threshold)
        & pairs["destination_enrolled"].ge(threshold)
    ].copy()
    group_columns = [
        "term",
        "origin_course_number",
        "origin_component",
        "origin_facility_id",
        "origin_label",
        "origin_end_minutes",
        "origin_enrolled",
        "destination_course_number",
        "destination_component",
        "destination_facility_id",
        "destination_label",
        "next_start_minutes",
        "destination_enrolled",
        "route_distance_meters",
        "walk_minutes_3_0mph",
    ]
    weekday_order = dict(zip(WEEKDAYS, range(len(WEEKDAYS)), strict=True))
    result = candidates.groupby(group_columns, as_index=False, dropna=False).agg(
        days=(
            "day",
            lambda values: " / ".join(sorted(set(values.astype(str)), key=weekday_order.get)),
        ),
        weekday_count=("day", "nunique"),
    )
    result["origin_enrolled"] = result["origin_enrolled"].astype(int)
    result["destination_enrolled"] = result["destination_enrolled"].astype(int)
    result["smaller_reported_enrollment"] = result[["origin_enrolled", "destination_enrolled"]].min(
        axis=1
    )
    result["within_10min_3mph"] = result["walk_minutes_3_0mph"] <= 10
    result["passing_period"] = result.apply(
        lambda row: (
            f"{_clock_label(row['origin_end_minutes'])} to "
            f"{_clock_label(row['next_start_minutes'])}"
        ),
        axis=1,
    )
    result["enrollment_screen_threshold"] = threshold
    result = result.sort_values(
        [
            "smaller_reported_enrollment",
            "walk_minutes_3_0mph",
            "origin_course_number",
            "destination_course_number",
        ],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)
    result["enrollment_rank"] = result.index + 1
    return result


def build_time_slot_summary(
    mapped: pd.DataFrame, pairs: pd.DataFrame, *, include_weekday: bool
) -> pd.DataFrame:
    pair_groups = ["origin_end_minutes", "next_start_minutes"]
    meeting_origin_groups = ["end_minutes"]
    meeting_destination_groups = ["start_minutes"]
    if include_weekday:
        pair_groups.insert(0, "day")
        meeting_origin_groups.insert(0, "day")
        meeting_destination_groups.insert(0, "day")

    pair_summary = (
        pairs.groupby(pair_groups, as_index=False)
        .agg(
            potential_meeting_pairs=("origin_class_number", "count"),
            walk_share_within_10min_3mph=("within_10min_3_0mph", "mean"),
            walk_median_minutes_3mph=("walk_minutes_3_0mph", "median"),
            walk_p90_minutes_3mph=("walk_minutes_3_0mph", lambda values: values.quantile(0.9)),
            bike_share_within_10min_8mph=("bike_within_10min_8_0mph", "mean"),
            bike_median_minutes_8mph=("bike_minutes_8_0mph", "median"),
        )
        .sort_values(pair_groups)
    )
    origin_summary = (
        mapped.groupby(meeting_origin_groups, as_index=False)
        .agg(
            origin_physical_meetings=("class_number", "count"),
            origin_meetings_with_reported_enrollment=("enrolled", "count"),
            reported_enrollment_leaving=("enrolled", _sum_with_missing),
        )
        .rename(columns={"end_minutes": "origin_end_minutes"})
    )
    destination_summary = (
        mapped.groupby(meeting_destination_groups, as_index=False)
        .agg(
            destination_physical_meetings=("class_number", "count"),
            destination_meetings_with_reported_enrollment=("enrolled", "count"),
            reported_enrollment_arriving=("enrolled", _sum_with_missing),
        )
        .rename(columns={"start_minutes": "next_start_minutes"})
    )
    origin_keys = ["origin_end_minutes"]
    destination_keys = ["next_start_minutes"]
    if include_weekday:
        origin_keys.insert(0, "day")
        destination_keys.insert(0, "day")
    result = pair_summary.merge(origin_summary, on=origin_keys, how="left")
    result = result.merge(destination_summary, on=destination_keys, how="left")
    result["passing_period"] = result.apply(
        lambda row: (
            f"{_clock_label(row['origin_end_minutes'])} to "
            f"{_clock_label(row['next_start_minutes'])}"
        ),
        axis=1,
    )
    if include_weekday:
        result["weekday_order"] = result["day"].map(
            dict(zip(WEEKDAYS, range(len(WEEKDAYS)), strict=True))
        )
        result = result.sort_values(
            ["weekday_order", "origin_end_minutes", "next_start_minutes"]
        ).drop(columns="weekday_order")
    return result


def build_course_transition_examples(pairs: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "term",
        "day",
        "origin_end_minutes",
        "next_start_minutes",
        "origin_course_number",
        "origin_class_number",
        "origin_label",
        "destination_course_number",
        "destination_class_number",
        "destination_label",
        "route_distance_meters",
        "walk_minutes_3_0mph",
        "bike_route_distance_meters",
        "bike_minutes_8_0mph",
    ]
    examples = pairs[columns].copy()
    examples["passing_period"] = examples.apply(
        lambda row: (
            f"{_clock_label(row['origin_end_minutes'])} to "
            f"{_clock_label(row['next_start_minutes'])}"
        ),
        axis=1,
    )
    examples = examples.sort_values(
        ["walk_minutes_3_0mph", "day", "origin_course_number"],
        ascending=[False, True, True],
    )
    examples = examples.drop_duplicates(
        [
            "day",
            "origin_end_minutes",
            "origin_course_number",
            "origin_label",
            "destination_course_number",
            "destination_label",
        ]
    )
    return examples.head(250)


def build_course_transition_cases(pairs: pd.DataFrame) -> pd.DataFrame:
    """Select reproducible course-level examples across the route-time range."""
    columns = [
        "term",
        "day",
        "origin_end_minutes",
        "next_start_minutes",
        "origin_course_number",
        "origin_class_number",
        "origin_facility_id",
        "origin_label",
        "destination_course_number",
        "destination_class_number",
        "destination_facility_id",
        "destination_label",
        "route_distance_meters",
        "walk_minutes_3_0mph",
        "bike_route_distance_meters",
        "bike_minutes_8_0mph",
    ]
    candidates = pairs.loc[
        pairs["origin_facility_id"] != pairs["destination_facility_id"], columns
    ].copy()

    def nearest(
        pool: pd.DataFrame,
        target_minutes: float,
        case_type: str,
    ) -> pd.Series:
        ranked = pool.assign(
            target_delta=(pool["walk_minutes_3_0mph"] - target_minutes).abs()
        ).sort_values(
            [
                "target_delta",
                "day",
                "origin_end_minutes",
                "origin_class_number",
                "destination_class_number",
            ]
        )
        selected = ranked.iloc[0].drop(labels="target_delta")
        selected["case_type"] = case_type
        return selected

    median_minutes = float(pairs["walk_minutes_3_0mph"].median())
    selected = [
        nearest(
            candidates[candidates["walk_minutes_3_0mph"] <= 8],
            median_minutes,
            "Near the median",
        ),
        nearest(
            candidates[candidates["walk_minutes_3_0mph"].between(9, 10)],
            9.5,
            "Near the limit",
        ),
        nearest(
            candidates[candidates["walk_minutes_3_0mph"].between(11.5, 12.5)],
            12,
            "Above the limit",
        ),
        nearest(
            candidates,
            float(candidates["walk_minutes_3_0mph"].max()),
            "Longest modeled example",
        ),
    ]
    cases = pd.DataFrame(selected)
    cases["passing_period"] = cases.apply(
        lambda row: (
            f"{_clock_label(row['origin_end_minutes'])} to "
            f"{_clock_label(row['next_start_minutes'])}"
        ),
        axis=1,
    )
    cases["within_10min_3mph"] = cases["walk_minutes_3_0mph"] <= 10
    cases["margin_minutes_3mph"] = 10 - cases["walk_minutes_3_0mph"]
    return cases[
        [
            "case_type",
            *columns,
            "passing_period",
            "within_10min_3mph",
            "margin_minutes_3mph",
        ]
    ]


def analyze() -> dict[str, Any]:
    meetings, room_lookup, facilities, routes, bike_routes = _read_inputs()
    subject_catalog = pd.read_csv(PROCESSED_DIR / "subject_catalog.csv")
    survey_responses = pd.read_csv(REPORTING_DIR / "student_survey_responses.csv").fillna("")
    survey_summary = build_student_survey_summary(survey_responses)
    meetings["cancelled"] = _as_bool(meetings["cancelled"])
    meetings["enrolled"] = pd.to_numeric(meetings["enrolled"], errors="coerce")

    room_lookup_columns = [
        "room",
        "match_status",
        "facility_id",
        "latitude",
        "longitude",
    ]
    merged = meetings.merge(room_lookup[room_lookup_columns], on="room", how="left")
    queryable_room = merged["room"].fillna("").astype(str).map(is_queryable_room)
    eligible = merged[
        (~merged["cancelled"])
        & (merged["modality"] == "In Person")
        & (merged["day"].isin(WEEKDAYS))
        & queryable_room
    ].copy()
    component_time_summary, component_day_summary = build_component_schedule_summaries(eligible)
    mapped_listings = eligible[
        eligible["match_status"].isin(USABLE_MATCH_STATUSES) & eligible["facility_id"].notna()
    ].copy()
    mapping_rate = len(mapped_listings) / len(eligible) if len(eligible) else math.nan
    physical_meeting_key = [
        "term",
        "day",
        "date_start",
        "date_end",
        "start_minutes",
        "end_minutes",
        "room",
        "facility_id",
    ]
    mapped_listings["section_listing_count"] = mapped_listings.groupby(physical_meeting_key)[
        "class_number"
    ].transform("nunique")
    mapped_listings["course_listings"] = mapped_listings.groupby(physical_meeting_key)[
        "course_number"
    ].transform(lambda values: " / ".join(dict.fromkeys(values.astype(str))))
    mapped_listings["subject_codes"] = mapped_listings.groupby(physical_meeting_key)[
        "subject_query"
    ].transform(lambda values: " / ".join(dict.fromkeys(values.astype(str))))
    mapped_listings["reported_enrollment_at_meeting"] = mapped_listings.groupby(
        physical_meeting_key
    )["enrolled"].transform(lambda values: values.sum(min_count=1))
    mapped_listings["reported_capacity_at_meeting"] = mapped_listings.groupby(physical_meeting_key)[
        "capacity"
    ].transform(lambda values: values.sum(min_count=1))
    mapped = (
        mapped_listings.sort_values([*physical_meeting_key, "course_number"])
        .drop_duplicates(subset=physical_meeting_key, keep="first")
        .copy()
    )
    mapped["course_number"] = mapped["course_listings"]
    mapped["enrolled"] = mapped["reported_enrollment_at_meeting"]
    mapped["capacity"] = mapped["reported_capacity_at_meeting"]

    facilities = facilities.copy()
    facilities["facility_label"] = facilities.apply(facility_label, axis=1)
    department_location_summary = build_department_location_summary(
        mapped_listings, facilities, subject_catalog
    )
    mapped = mapped.merge(
        facilities[["facility_id", "facility_label"]], on="facility_id", how="left"
    )

    building_usage = (
        mapped.groupby(["facility_id", "facility_label"], as_index=False)
        .agg(
            scheduled_meeting_day_rows=("class_number", "count"),
            represented_section_listings=("section_listing_count", "sum"),
            meetings_with_reported_enrollment=("enrolled", "count"),
            reported_enrollment_sum=("enrolled", _sum_with_missing),
        )
        .sort_values("scheduled_meeting_day_rows", ascending=False)
    )

    pairs = build_potential_pairs(mapped, routes, bike_routes)
    candidate_pair_count = int(pairs.attrs["candidate_count_before_routing"])
    recurring_pair_rows_collapsed = int(pairs.attrs["recurring_pair_rows_collapsed"])
    same_class_number_pair_rows_excluded = int(pairs.attrs["same_class_number_pair_rows_excluded"])
    pair_date_rows_before_same_class_exclusion = int(
        pairs.attrs["pair_date_rows_before_same_class_exclusion"]
    )
    label_map = facilities.set_index("facility_id")["facility_label"]
    pairs["origin_label"] = pairs["origin_facility_id"].map(label_map)
    pairs["destination_label"] = pairs["destination_facility_id"].map(label_map)
    component_transition_summary = build_component_transition_summary(pairs)
    subject_transition_feasibility = build_subject_transition_feasibility(
        pairs, department_location_summary, subject_catalog
    )
    high_enrollment_transitions = build_high_enrollment_transitions(pairs)

    pair_summary = pairs.groupby(
        [
            "origin_facility_id",
            "origin_label",
            "destination_facility_id",
            "destination_label",
        ],
        as_index=False,
    ).agg(
        potential_meeting_pairs=("origin_class_number", "count"),
        route_distance_meters=("route_distance_meters", "first"),
        bike_route_distance_meters=("bike_route_distance_meters", "first"),
        distinct_origin_meetings=("origin_class_number", "nunique"),
        distinct_destination_meetings=("destination_class_number", "nunique"),
    )
    for speed in WALKING_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        meters_per_minute = speed * 1609.344 / 60
        pair_summary[f"walk_minutes_{suffix}mph"] = (
            pair_summary["route_distance_meters"] / meters_per_minute
        )
        pair_summary[f"within_10min_{suffix}mph"] = pair_summary[f"walk_minutes_{suffix}mph"] <= 10
        pair_summary[f"within_10min_{suffix}mph_with_2min_overhead"] = (
            pair_summary[f"walk_minutes_{suffix}mph"] <= 8
        )
    for speed in BICYCLE_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        meters_per_minute = speed * 1609.344 / 60
        pair_summary[f"bike_minutes_{suffix}mph"] = (
            pair_summary["bike_route_distance_meters"] / meters_per_minute
        )
        pair_summary[f"bike_within_10min_{suffix}mph"] = (
            pair_summary[f"bike_minutes_{suffix}mph"] <= 10
        )
        pair_summary[f"bike_within_10min_{suffix}mph_with_2min_overhead"] = (
            pair_summary[f"bike_minutes_{suffix}mph"] <= 8
        )

    speed_rows: list[dict[str, Any]] = []
    for speed in WALKING_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        speed_rows.append(
            {
                "walking_speed_mph": speed,
                "share_within_10_minutes": float(pairs[f"within_10min_{suffix}mph"].mean()),
                "share_within_10_minutes_with_2min_overhead": float(
                    pairs[f"within_10min_{suffix}mph_with_2min_overhead"].mean()
                ),
                "median_route_minutes": float(pairs[f"walk_minutes_{suffix}mph"].median()),
                "p90_route_minutes": float(pairs[f"walk_minutes_{suffix}mph"].quantile(0.9)),
            }
        )
    speed_summary = pd.DataFrame(speed_rows)

    bicycle_speed_rows: list[dict[str, Any]] = []
    for speed in BICYCLE_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        bicycle_speed_rows.append(
            {
                "bicycle_speed_mph": speed,
                "share_within_10_minutes": float(pairs[f"bike_within_10min_{suffix}mph"].mean()),
                "share_within_10_minutes_with_2min_handling": float(
                    pairs[f"bike_within_10min_{suffix}mph_with_2min_overhead"].mean()
                ),
                "median_route_minutes": float(pairs[f"bike_minutes_{suffix}mph"].median()),
                "p90_route_minutes": float(pairs[f"bike_minutes_{suffix}mph"].quantile(0.9)),
            }
        )
    bicycle_speed_summary = pd.DataFrame(bicycle_speed_rows)

    route_distribution = (
        pair_summary.groupby("walk_minutes_3_0mph", as_index=False)
        .agg(potential_meeting_pairs=("potential_meeting_pairs", "sum"))
        .sort_values("walk_minutes_3_0mph")
        .rename(columns={"walk_minutes_3_0mph": "route_minutes_3mph"})
    )
    route_distribution["cumulative_pairs"] = route_distribution["potential_meeting_pairs"].cumsum()
    distribution_total = float(route_distribution["potential_meeting_pairs"].sum())
    route_distribution["cumulative_share"] = (
        route_distribution["cumulative_pairs"] / distribution_total
        if distribution_total
        else np.nan
    )

    building_risk = (
        pairs.assign(over_10min_3mph=~pairs["within_10min_3_0mph"])
        .groupby(["origin_facility_id", "origin_label"], as_index=False)
        .agg(
            potential_next_meeting_pairs=("origin_class_number", "count"),
            over_10min_pairs=("over_10min_3mph", "sum"),
            median_route_minutes_3mph=("walk_minutes_3_0mph", "median"),
        )
    )
    building_risk["share_over_10min_3mph"] = (
        building_risk["over_10min_pairs"] / building_risk["potential_next_meeting_pairs"]
    )
    building_risk = building_risk.merge(
        facilities[["facility_id", "latitude", "longitude"]],
        left_on="origin_facility_id",
        right_on="facility_id",
        how="left",
    ).drop(columns="facility_id")

    frequent_threshold = (
        max(10, int(pair_summary["potential_meeting_pairs"].quantile(0.75)))
        if not pair_summary.empty
        else 0
    )
    constrained = pair_summary[
        (pair_summary["walk_minutes_3_0mph"] > 10)
        & (pair_summary["potential_meeting_pairs"] >= frequent_threshold)
    ].copy()
    constrained = constrained.sort_values(
        ["potential_meeting_pairs", "walk_minutes_3_0mph"], ascending=[False, False]
    ).head(25)
    time_slots = build_time_slot_summary(mapped, pairs, include_weekday=False)
    weekday_time_slots = build_time_slot_summary(mapped, pairs, include_weekday=True)
    course_transition_examples = build_course_transition_examples(pairs)
    course_transition_cases = build_course_transition_cases(pairs)

    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    building_usage.to_csv(TABLE_DIR / "building_usage.csv", index=False)
    pair_summary.to_csv(TABLE_DIR / "building_pair_summary.csv", index=False)
    speed_summary.to_csv(TABLE_DIR / "speed_summary.csv", index=False)
    bicycle_speed_summary.to_csv(TABLE_DIR / "bicycle_speed_summary.csv", index=False)
    route_distribution.to_csv(TABLE_DIR / "route_time_distribution.csv", index=False)
    building_risk.to_csv(TABLE_DIR / "building_risk.csv", index=False)
    constrained.to_csv(TABLE_DIR / "top_constrained_routes.csv", index=False)
    time_slots.to_csv(TABLE_DIR / "time_slot_summary.csv", index=False)
    weekday_time_slots.to_csv(TABLE_DIR / "weekday_time_slot_summary.csv", index=False)
    course_transition_examples.to_csv(TABLE_DIR / "course_transition_examples.csv", index=False)
    course_transition_cases.to_csv(TABLE_DIR / "course_transition_cases.csv", index=False)
    component_time_summary.to_csv(TABLE_DIR / "component_time_summary.csv", index=False)
    component_day_summary.to_csv(TABLE_DIR / "component_day_summary.csv", index=False)
    component_transition_summary.to_csv(TABLE_DIR / "component_transition_summary.csv", index=False)
    department_location_summary.to_csv(TABLE_DIR / "department_location_summary.csv", index=False)
    subject_transition_feasibility.to_csv(
        TABLE_DIR / "subject_transition_feasibility.csv", index=False
    )
    high_enrollment_transitions.to_csv(TABLE_DIR / "high_enrollment_transitions.csv", index=False)
    survey_summary.to_csv(TABLE_DIR / "student_survey_summary.csv", index=False)

    survey_counts = survey_summary.set_index("metric")["count"]

    known_enrollment_rows = int(eligible["enrolled"].notna().sum())
    known_enrollment_total = float(eligible["enrolled"].sum(min_count=1))
    enrollment_mapping_rate = None
    if known_enrollment_rows and known_enrollment_total > 0:
        enrollment_mapping_rate = float(mapped_listings["enrolled"].sum()) / known_enrollment_total
    invalid_dates_path = PROCESSED_DIR / "invalid_meeting_dates_excluded.csv"
    invalid_times_path = PROCESSED_DIR / "invalid_meeting_times_excluded.csv"
    invalid_date_rows = len(pd.read_csv(invalid_dates_path)) if invalid_dates_path.exists() else 0
    invalid_time_rows = len(pd.read_csv(invalid_times_path)) if invalid_times_path.exists() else 0
    api_sections_path = PROCESSED_DIR / "explorecourses_api_sections.csv"
    api_verification_path = PROCESSED_DIR / "explorecourses_api_schedule_verification.csv"
    api_sections = pd.read_csv(api_sections_path) if api_sections_path.exists() else pd.DataFrame()
    api_verification = (
        pd.read_csv(api_verification_path) if api_verification_path.exists() else pd.DataFrame()
    )
    summary = {
        "unit_of_analysis": (
            "Potential ordered pairs of unique scheduled physical room-time meetings on the "
            "same weekday with exactly ten minutes between published times. Cross-listed "
            "records sharing a room, date range and time are counted once; repeated date "
            "blocks for the same ordered class-number pair, facility pair, weekday and time "
            "count once; rows pairing a class number with itself are excluded."
        ),
        "academic_year": str(meetings["academic_year"].iloc[0]),
        "terms": sorted(mapped["term"].dropna().unique().tolist()),
        "source_meeting_day_rows": len(meetings),
        "parsed_meeting_day_rows_before_validation": len(meetings),
        "invalid_term_date_rows_excluded": 0,
        "invalid_time_rows_excluded": 0,
        "mobile_html_term_date_anomalies": invalid_date_rows,
        "mobile_html_time_parse_anomalies": invalid_time_rows,
        "api_unique_sections": len(api_sections),
        "api_sections_with_reported_enrollment": (
            int(api_sections["enrolled"].notna().sum()) if not api_sections.empty else 0
        ),
        "mobile_html_meeting_rows_exactly_matching_api": (
            int(_as_bool(api_verification["api_schedule_match"]).sum())
            if not api_verification.empty
            else 0
        ),
        "mobile_html_meeting_schedule_match_rate": (
            float(_as_bool(api_verification["api_schedule_match"]).mean())
            if not api_verification.empty
            else None
        ),
        "eligible_physical_meeting_day_rows": len(eligible),
        "mapped_section_listing_day_rows": len(mapped_listings),
        "mapped_physical_meeting_day_rows": len(mapped),
        "cross_listing_rows_collapsed": len(mapped_listings) - len(mapped),
        "meeting_mapping_rate": mapping_rate,
        "enrollment_weighted_mapping_rate": enrollment_mapping_rate,
        "eligible_rows_with_reported_enrollment": known_enrollment_rows,
        "enrollment_reporting_rate": (
            known_enrollment_rows / len(eligible) if len(eligible) else None
        ),
        "unique_mapped_section_listings": int(mapped_listings["class_number"].nunique()),
        "unique_mapped_facilities": int(mapped["facility_id"].nunique()),
        "pair_date_rows_before_same_class_exclusion": (pair_date_rows_before_same_class_exclusion),
        "candidate_adjacent_meeting_pairs_before_routing": candidate_pair_count,
        "same_class_number_pair_rows_excluded": same_class_number_pair_rows_excluded,
        "recurring_pair_rows_collapsed": recurring_pair_rows_collapsed,
        "potential_adjacent_meeting_pairs": len(pairs),
        "pair_routing_coverage": (
            len(pairs) / candidate_pair_count if candidate_pair_count else None
        ),
        "unique_building_pairs": len(pair_summary),
        "same_building_pair_share": float(
            (pairs["origin_facility_id"] == pairs["destination_facility_id"]).mean()
        ),
        "walking_speed_results": speed_rows,
        "bicycle_speed_results": bicycle_speed_rows,
        "three_mph_share_within_10_minutes": float(pairs["within_10min_3_0mph"].mean()),
        "three_mph_share_within_10_minutes_with_2min_overhead": float(
            pairs["within_10min_3_0mph_with_2min_overhead"].mean()
        ),
        "three_mph_median_route_minutes": float(pairs["walk_minutes_3_0mph"].median()),
        "three_mph_p90_route_minutes": float(pairs["walk_minutes_3_0mph"].quantile(0.9)),
        "eight_mph_bicycle_share_within_10_minutes": float(
            pairs["bike_within_10min_8_0mph"].mean()
        ),
        "eight_mph_bicycle_share_within_10_minutes_with_2min_handling": float(
            pairs["bike_within_10min_8_0mph_with_2min_overhead"].mean()
        ),
        "eight_mph_bicycle_median_route_minutes": float(pairs["bike_minutes_8_0mph"].median()),
        "eight_mph_bicycle_p90_route_minutes": float(pairs["bike_minutes_8_0mph"].quantile(0.9)),
        "distinct_passing_period_time_slots": len(time_slots),
        "distinct_weekday_time_slots": len(weekday_time_slots),
        "lecture_component_meeting_day_rows": int((eligible["component"] == "LEC").sum()),
        "discussion_component_meeting_day_rows": int((eligible["component"] == "DIS").sum()),
        "lecture_median_start_minutes": float(
            eligible.loc[eligible["component"] == "LEC", "start_minutes"].median()
        ),
        "discussion_median_start_minutes": float(
            eligible.loc[eligible["component"] == "DIS", "start_minutes"].median()
        ),
        "lecture_share_starting_at_or_after_230pm": float(
            (eligible.loc[eligible["component"] == "LEC", "start_minutes"] >= 870).mean()
        ),
        "discussion_share_starting_at_or_after_230pm": float(
            (eligible.loc[eligible["component"] == "DIS", "start_minutes"] >= 870).mean()
        ),
        "lecture_share_on_thursday_or_friday": float(
            eligible.loc[eligible["component"] == "LEC", "day"].isin(["Thu", "Fri"]).mean()
        ),
        "discussion_share_on_thursday_or_friday": float(
            eligible.loc[eligible["component"] == "DIS", "day"].isin(["Thu", "Fri"]).mean()
        ),
        "lecture_discussion_transition_pairs": int(
            component_transition_summary["potential_meeting_pairs"].sum()
        ),
        "component_transition_results": component_transition_summary[
            [
                "origin_component",
                "destination_component",
                "potential_meeting_pairs",
                "pairs_over_10min_3mph",
                "share_within_10min_3mph",
                "share_over_10min_3mph",
                "median_route_minutes_3mph",
                "p90_route_minutes_3mph",
            ]
        ].to_dict(orient="records"),
        "subject_catalog_entries": len(subject_catalog),
        "subject_areas_with_transition_estimates": len(subject_transition_feasibility),
        "large_enrollment_screen_threshold": LARGE_ENROLLMENT_THRESHOLD,
        "large_enrollment_unique_different_building_pairs": len(high_enrollment_transitions),
        "large_enrollment_pairs_over_10min_3mph": int(
            (~high_enrollment_transitions["within_10min_3mph"]).sum()
        ),
        "large_enrollment_share_over_10min_3mph": float(
            (~high_enrollment_transitions["within_10min_3mph"]).mean()
        ),
        "student_survey_responses": len(survey_responses),
        "student_survey_linked_sheet_responses": int(
            survey_responses["source_batch"].str.startswith("google_sheet_").sum()
        ),
        "student_survey_prior_retained_responses": int(
            survey_responses["source_batch"].eq("prior_project_response").sum()
        ),
        "student_survey_reported_late": int(survey_counts["reported_late"]),
        "student_survey_close_call": int(survey_counts["close_call"]),
        "student_survey_never_late": int(survey_counts["never_late"]),
        "student_survey_late_or_close_call": int(survey_counts["late_or_close_call"]),
        "student_survey_selected_walking": int(survey_counts["selected_walking"]),
        "student_survey_selected_biking": int(survey_counts["selected_biking"]),
        "student_survey_selected_e_scooter": int(survey_counts["selected_e-scooter"]),
        "student_survey_expanded_followup_responses": int(
            survey_summary.loc[
                survey_summary["metric"].eq("reported_concrete_consequence"), "denominator"
            ].iloc[0]
        ),
        "student_survey_transition_may_exceed_10min": int(
            survey_counts["transition_may_exceed_10min"]
        ),
        "student_survey_reported_exact_ten_minute_gap": int(
            survey_counts["reported_exact_ten_minute_gap"]
        ),
        "student_survey_reported_concrete_consequence": int(
            survey_counts["reported_concrete_consequence"]
        ),
        "student_survey_missed_class_content": int(survey_counts["missed_class_content"]),
        "student_survey_course_choice_effect": int(survey_counts["course_choice_effect"]),
        "student_survey_skipped_adjacent_activity": int(
            survey_counts["skipped_adjacent_activity"]
        ),
        "frequent_route_threshold_pairs": frequent_threshold,
        "room_match_status_counts": {
            str(key): int(value)
            for key, value in room_lookup["match_status"].value_counts(dropna=False).items()
        },
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    create_interactive_payload(facilities, routes, bike_routes, pair_summary, summary)
    write_findings(summary, building_usage, constrained)
    return summary


def write_findings(
    summary: dict[str, Any], building_usage: pd.DataFrame, constrained: pd.DataFrame
) -> None:
    within = summary["three_mph_share_within_10_minutes"]
    overhead = summary["three_mph_share_within_10_minutes_with_2min_overhead"]
    bike_within = summary["eight_mph_bicycle_share_within_10_minutes"]
    bike_overhead = summary["eight_mph_bicycle_share_within_10_minutes_with_2min_handling"]
    top_buildings = ", ".join(building_usage.head(5)["facility_label"].astype(str))
    route_examples = []
    for row in constrained.head(5).itertuples(index=False):
        route_examples.append(
            f"- {row.origin_label} to {row.destination_label}: "
            f"{row.walk_minutes_3_0mph:.1f} estimated minutes; "
            f"{int(row.potential_meeting_pairs):,} potential meeting pairings."
        )
    text = f"""# Findings

## Scope

- Academic year: {summary["academic_year"]}.
- Terms: {", ".join(summary["terms"])}.
- XML API sections: {summary["api_unique_sections"]:,}.
- Mapped section-listing day rows: {summary["mapped_section_listing_day_rows"]:,}.
- Unique physical room-time meeting rows: {summary["mapped_physical_meeting_day_rows"]:,}.
- Cross-listed rows collapsed: {summary["cross_listing_rows_collapsed"]:,}.
- Unique mapped facilities: {summary["unique_mapped_facilities"]:,}.
- Potential adjacent-block meeting pairs with routes: {summary["potential_adjacent_meeting_pairs"]:,}.
- Distinct ten-minute time slots: {summary["distinct_passing_period_time_slots"]:,} ({summary["distinct_weekday_time_slots"]:,} weekday-slot combinations).
- Lecture/discussion meeting-day rows: {summary["lecture_component_meeting_day_rows"]:,} / {summary["discussion_component_meeting_day_rows"]:,}.
- Large-enrollment screen: {summary["large_enrollment_unique_different_building_pairs"]:,} unique combinations where both meetings report at least {summary["large_enrollment_screen_threshold"]:,} enrolled.

## Main result

At 3 mph and with no allowance for leaving or entering a building, {within:.1%} of the
potential physical-meeting pairings have an estimated walking-network route of
ten minutes or less. With a two-minute building overhead, that share falls to
{overhead:.1%}.

These are schedule pairings, not observed student trips. The XML API reports section
enrollment, but public data do not reveal co-enrollment, route choice, mobility needs,
departure delay or actual lateness. Every pairing is therefore weighted equally rather
than treated as a student flow.

At an assumed 8 mph, {bike_within:.1%} of the same potential pairs fit within ten
bicycle-route minutes. With a two-minute handling allowance, the share is
{bike_overhead:.1%}. These are sensitivity assumptions, not measured bicycle trips.

In the large-enrollment screen, {summary["large_enrollment_pairs_over_10min_3mph"]:,}
of {summary["large_enrollment_unique_different_building_pairs"]:,} unique
different-building combinations exceed ten modeled walking minutes at 3 mph.
The threshold shows that both meetings are large; it does not measure
co-enrollment or student traffic.

## Student reporting

The authors' {summary["student_survey_responses"]}-response convenience survey
includes {summary["student_survey_reported_late"]} respondents who said distance
had made them late and {summary["student_survey_close_call"]} who said it had
been close. Together, {summary["student_survey_late_or_close_call"]} reported
lateness or a close call. Among the
{summary["student_survey_expanded_followup_responses"]} respondents who received
the expanded questions, {summary["student_survey_reported_concrete_consequence"]}
described a concrete consequence beyond arrival time. This reporting cannot
estimate prevalence among Stanford students.

## Most-used mapped facilities

{top_buildings}.

## Frequent constrained examples

{chr(10).join(route_examples) if route_examples else "- No route met the reporting threshold."}

## Editorial interpretation

The analysis supports a story about the physical constraints embedded in the published
schedule. It does not support a claim about how many students are late or whether the
University caused any individual late arrival. Interviews and an official response are
required before publication.
"""
    (REPORT_DIR / "FINDINGS.md").write_text(text, encoding="utf-8")
