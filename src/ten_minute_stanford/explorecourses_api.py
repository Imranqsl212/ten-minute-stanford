from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import pandas as pd

from .config import EXPLORE_BASE, PROCESSED_DIR, RAW_DIR
from .explorecourses import normalize_space, safe_filename
from .fetch import CachedFetcher

XML_VIEW = "xml-20200810"
FULL_DAY_TO_SHORT = {
    "Monday": "Mon",
    "Tuesday": "Tue",
    "Wednesday": "Wed",
    "Thursday": "Thu",
    "Friday": "Fri",
    "Saturday": "Sat",
    "Sunday": "Sun",
}


def _integer(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _api_term(academic_year: str, term: str) -> str:
    return f"{academic_year[:4]}-{academic_year[4:]} {term}"


def _source_url(subject: str, academic_year: str, term: str) -> str:
    params = {
        "view": XML_VIEW,
        "filter-coursestatus-Active": "on",
        "q": subject,
        f"filter-departmentcode-{subject}": "on",
        f"filter-term-{term}": "on",
        "academicYear": academic_year,
    }
    return f"{EXPLORE_BASE}/search?{urlencode(params)}"


def _parse_api_date(value: str | None) -> pd.Timestamp | None:
    cleaned = normalize_space(value or "")
    if not cleaned:
        return None
    try:
        return pd.Timestamp(datetime.strptime(cleaned, "%b %d, %Y").date())
    except ValueError:
        return None


def _parse_api_time(value: str | None) -> int | None:
    cleaned = normalize_space(value or "").upper()
    if not cleaned:
        return None
    for pattern in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def parse_explorecourses_xml(
    xml: str,
    *,
    academic_year: str,
    term: str,
    subject_query: str,
    source_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the public ExploreCourses XML view used by explore-courses-api."""
    root = ElementTree.fromstring(xml)
    expected_term = _api_term(academic_year, term)
    section_rows: list[dict[str, Any]] = []
    schedule_rows: list[dict[str, Any]] = []

    for course in root.findall(".//course"):
        course_subject = normalize_space(course.findtext("subject") or subject_query)
        course_code = normalize_space(course.findtext("code") or "")
        course_number = normalize_space(f"{course_subject} {course_code}")
        course_title = normalize_space(course.findtext("title") or "")
        for section in course.findall("./sections/section"):
            api_term = normalize_space(section.findtext("term") or "")
            if api_term != expected_term:
                continue
            class_number = normalize_space(section.findtext("classId") or "")
            if not class_number:
                continue
            enrolled = _integer(section.findtext("currentClassSize"))
            capacity = _integer(section.findtext("maxClassSize"))
            section_row = {
                "academic_year": academic_year,
                "term": term,
                "api_subject_query": subject_query,
                "api_course_number": course_number,
                "api_course_title": course_title,
                "class_number": class_number,
                "api_section_number": normalize_space(
                    section.findtext("sectionNumber") or ""
                ),
                "api_component": normalize_space(section.findtext("component") or ""),
                "enrolled": enrolled,
                "capacity": capacity,
                "waitlist": _integer(section.findtext("currentWaitlistSize")),
                "waitlist_capacity": _integer(section.findtext("maxWaitlistSize")),
                "enrollment_status": normalize_space(
                    section.findtext("enrollStatus") or ""
                ),
                "instruction_mode": normalize_space(
                    section.findtext("instructionMode") or ""
                ),
                "api_source_url": source_url,
            }
            section_rows.append(section_row)

            for schedule_index, schedule in enumerate(
                section.findall("./schedules/schedule"), start=1
            ):
                date_start = _parse_api_date(schedule.findtext("startDate"))
                date_end = _parse_api_date(schedule.findtext("endDate"))
                start_minutes = _parse_api_time(schedule.findtext("startTime"))
                end_minutes = _parse_api_time(schedule.findtext("endTime"))
                room = normalize_space(schedule.findtext("location") or "")
                day_text = normalize_space(schedule.findtext("days") or "")
                days = [
                    short
                    for full, short in FULL_DAY_TO_SHORT.items()
                    if re.search(rf"\b{re.escape(full)}\b", day_text)
                ]
                if (
                    date_start is None
                    or date_end is None
                    or start_minutes is None
                    or end_minutes is None
                    or start_minutes >= end_minutes
                ):
                    continue
                for day in days:
                    schedule_rows.append(
                        {
                            **section_row,
                            "api_schedule_index": schedule_index,
                            "date_start": date_start,
                            "date_end": date_end,
                            "day": day,
                            "start_time": normalize_space(
                                schedule.findtext("startTime") or ""
                            ),
                            "end_time": normalize_space(
                                schedule.findtext("endTime") or ""
                            ),
                            "start_minutes": start_minutes,
                            "end_minutes": end_minutes,
                            "room": room,
                        }
                    )
    return section_rows, schedule_rows


def _consistent_value(values: pd.Series) -> float | str | None:
    known = values.dropna().drop_duplicates()
    if known.empty:
        return None
    if len(known) > 1:
        raise ValueError(f"Conflicting ExploreCourses API values: {known.tolist()}")
    return known.iloc[0]


def collect_explorecourses_api(
    fetcher: CachedFetcher,
    *,
    subjects: list[str],
    academic_year: str,
    terms: tuple[str, ...],
    refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    all_sections: list[dict[str, Any]] = []
    all_schedules: list[dict[str, Any]] = []
    query_count = 0
    for term in terms:
        for index, subject in enumerate(subjects, start=1):
            params = {
                "view": XML_VIEW,
                "filter-coursestatus-Active": "on",
                "q": subject,
                f"filter-departmentcode-{subject}": "on",
                f"filter-term-{term}": "on",
                "academicYear": academic_year,
            }
            cache_path = (
                RAW_DIR
                / "explorecourses_xml"
                / academic_year
                / term
                / f"{safe_filename(subject)}.xml"
            )
            xml = fetcher.get_text(
                f"{EXPLORE_BASE}/search",
                cache_path,
                params=params,
                refresh=refresh,
            )
            query_count += 1
            sections, schedules = parse_explorecourses_xml(
                xml,
                academic_year=academic_year,
                term=term,
                subject_query=subject,
                source_url=_source_url(subject, academic_year, term),
            )
            all_sections.extend(sections)
            all_schedules.extend(schedules)
            if index % 25 == 0:
                print(
                    f"ExploreCourses XML API: {term} {index}/{len(subjects)} subjects, "
                    f"{len(all_sections):,} section rows"
                )

    raw_sections = pd.DataFrame(all_sections)
    schedules = pd.DataFrame(all_schedules)
    if raw_sections.empty:
        return raw_sections, schedules, {
            "xml_queries_fetched_or_cached": query_count,
            "api_section_rows": 0,
            "api_unique_sections": 0,
            "api_schedule_day_rows": 0,
        }

    duplicate_rows = len(raw_sections) - raw_sections[["term", "class_number"]].drop_duplicates().shape[0]
    value_columns = [
        "enrolled",
        "capacity",
        "waitlist",
        "waitlist_capacity",
        "enrollment_status",
        "instruction_mode",
    ]
    for column in value_columns:
        raw_sections.groupby(["term", "class_number"])[column].apply(_consistent_value)

    sections = (
        raw_sections.sort_values(
            ["term", "class_number", "api_subject_query", "api_course_number"]
        )
        .drop_duplicates(["term", "class_number"], keep="first")
        .reset_index(drop=True)
    )
    if not schedules.empty:
        schedules = (
            schedules.sort_values(
                ["term", "class_number", "day", "start_minutes", "api_subject_query"],
                na_position="last",
            )
            .drop_duplicates(
                [
                    "term",
                    "class_number",
                    "date_start",
                    "date_end",
                    "day",
                    "start_minutes",
                    "end_minutes",
                    "room",
                ],
                keep="first",
            )
            .reset_index(drop=True)
        )
    return sections, schedules, {
        "xml_queries_fetched_or_cached": query_count,
        "api_section_rows_before_crosslist_deduplication": len(raw_sections),
        "api_duplicate_section_rows_collapsed": duplicate_rows,
        "api_unique_sections": len(sections),
        "api_sections_with_reported_enrollment": int(sections["enrolled"].notna().sum()),
        "api_schedule_day_rows": len(schedules),
        "api_contract": (
            "Queries and field mappings follow jeremyephron/explore-courses-api; "
            "the project parses the current public XML response directly."
        ),
    }


def enrich_with_api(
    sections: pd.DataFrame,
    meetings: pd.DataFrame,
    api_sections: pd.DataFrame,
    api_schedules: pd.DataFrame,
    *,
    write_outputs: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Attach API enrollment fields and audit exact schedule agreement."""
    api_columns = [
        "term",
        "class_number",
        "enrolled",
        "capacity",
        "waitlist",
        "waitlist_capacity",
        "enrollment_status",
        "instruction_mode",
        "api_source_url",
    ]
    lookup = api_sections[api_columns].copy()
    enriched_sections = sections.drop(
        columns=["enrolled", "capacity"], errors="ignore"
    ).merge(lookup, on=["term", "class_number"], how="left", validate="one_to_one")
    enriched_meetings = meetings.drop(
        columns=["enrolled", "capacity"], errors="ignore"
    ).merge(lookup, on=["term", "class_number"], how="left", validate="many_to_one")
    enriched_sections["api_section_match"] = enriched_sections["api_source_url"].notna()
    enriched_meetings["api_section_match"] = enriched_meetings["api_source_url"].notna()

    key = [
        "term",
        "class_number",
        "date_start",
        "date_end",
        "day",
        "start_minutes",
        "end_minutes",
        "room",
    ]
    local_keys = enriched_meetings[key].copy()
    local_keys["date_start"] = pd.to_datetime(local_keys["date_start"])
    local_keys["date_end"] = pd.to_datetime(local_keys["date_end"])
    local_keys["room"] = local_keys["room"].fillna("").map(normalize_space)
    api_keys = api_schedules[key].copy() if not api_schedules.empty else pd.DataFrame(columns=key)
    if not api_keys.empty:
        api_keys["date_start"] = pd.to_datetime(api_keys["date_start"])
        api_keys["date_end"] = pd.to_datetime(api_keys["date_end"])
        api_keys["room"] = api_keys["room"].fillna("").map(normalize_space)
        api_keys = api_keys.drop_duplicates(key)
    verification = local_keys.merge(
        api_keys.assign(api_schedule_match=True), on=key, how="left", validate="many_to_one"
    )
    verification["api_schedule_match"] = verification["api_schedule_match"].eq(True)
    verification = verification.merge(
        enriched_meetings[["term", "class_number", "api_section_match"]].drop_duplicates(),
        on=["term", "class_number"],
        how="left",
        validate="many_to_one",
    )
    verification["verification_status"] = "exact_schedule_match"
    verification.loc[
        ~verification["api_section_match"], "verification_status"
    ] = "class_not_found_in_api"
    verification.loc[
        verification["api_section_match"] & ~verification["api_schedule_match"],
        "verification_status",
    ] = "class_found_schedule_changed_or_unmatched"

    if write_outputs:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        api_sections.to_csv(
            PROCESSED_DIR / "explorecourses_api_sections.csv", index=False
        )
        api_schedules.to_csv(
            PROCESSED_DIR / "explorecourses_api_schedules.csv", index=False
        )
        verification.to_csv(
            PROCESSED_DIR / "explorecourses_api_schedule_verification.csv",
            index=False,
        )
    section_match_count = int(enriched_sections["api_section_match"].sum())
    schedule_match_count = int(verification["api_schedule_match"].sum())
    summary = {
        "local_sections_matched_by_class_number": section_match_count,
        "local_section_match_rate": (
            section_match_count / len(enriched_sections) if len(enriched_sections) else math.nan
        ),
        "local_meeting_day_rows_exactly_matched": schedule_match_count,
        "local_meeting_schedule_match_rate": (
            schedule_match_count / len(verification) if len(verification) else math.nan
        ),
        "local_sections_with_api_enrollment": int(enriched_sections["enrolled"].notna().sum()),
        "schedule_verification_status_counts": {
            str(status): int(count)
            for status, count in verification["verification_status"].value_counts().items()
        },
    }
    return enriched_sections, enriched_meetings, verification, summary


def canonical_meetings_from_api(
    enriched_sections: pd.DataFrame, api_schedules: pd.DataFrame
) -> pd.DataFrame:
    """Build the analysis meeting table from the verified XML schedule fields."""
    metadata_columns = [
        "academic_year",
        "term",
        "subject_query",
        "course_number",
        "course_title",
        "class_number",
        "section_number",
        "grading",
        "component",
        "session",
        "modality",
        "enrolled",
        "capacity",
        "cancelled",
        "source_url",
        "waitlist",
        "waitlist_capacity",
        "enrollment_status",
        "instruction_mode",
        "api_source_url",
        "api_section_match",
    ]
    section_metadata = enriched_sections[metadata_columns].rename(
        columns={"source_url": "mobile_source_url"}
    )
    schedule_columns = [
        "term",
        "class_number",
        "api_schedule_index",
        "date_start",
        "date_end",
        "day",
        "start_time",
        "end_time",
        "start_minutes",
        "end_minutes",
        "room",
    ]
    meetings = api_schedules[schedule_columns].merge(
        section_metadata,
        on=["term", "class_number"],
        how="left",
        validate="many_to_one",
    )
    if meetings["course_number"].isna().any():
        missing = meetings.loc[meetings["course_number"].isna(), "class_number"].unique()
        raise ValueError(f"XML schedules missing section metadata: {missing[:10].tolist()}")
    meetings = meetings.rename(columns={"api_schedule_index": "meeting_index"})
    meetings["source_url"] = meetings["api_source_url"]
    ordered_columns = [
        "academic_year",
        "term",
        "subject_query",
        "course_number",
        "course_title",
        "class_number",
        "section_number",
        "grading",
        "component",
        "session",
        "modality",
        "enrolled",
        "capacity",
        "cancelled",
        "source_url",
        "mobile_source_url",
        "waitlist",
        "waitlist_capacity",
        "enrollment_status",
        "instruction_mode",
        "api_section_match",
        "meeting_index",
        "date_start",
        "date_end",
        "day",
        "start_time",
        "end_time",
        "start_minutes",
        "end_minutes",
        "room",
    ]
    return meetings[ordered_columns].sort_values(
        ["term", "day", "start_minutes", "course_number", "class_number"]
    )
