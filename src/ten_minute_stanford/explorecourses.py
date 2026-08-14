from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
from bs4 import BeautifulSoup, Tag

from .config import ACADEMIC_YEAR, EXPLORE_BASE, PROCESSED_DIR, RAW_DIR, TERMS, WEEKDAYS
from .fetch import CachedFetcher

MEETING_RE = re.compile(
    r"(?P<date_start>\d{2}/\d{2}/\d{4})\s*-\s*"
    r"(?P<date_end>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<days>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
    r"(?:,\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))*)\s+"
    r"(?P<start>\d{1,2}:\d{2}\s*[AP]M)\s*-\s*"
    r"(?P<end>\d{1,2}:\d{2}\s*[AP]M)"
    r"(?:\s+at\s+(?P<room>.*?))?"
    r"(?=\s+with\b|\s+Exam Date/Time:|\s+Instructors:|\s+Notes:|"
    r"\s+Additional Resources:|$)"
)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return cleaned or "unknown"


def parse_time_minutes(value: str) -> int:
    parsed = datetime.strptime(normalize_space(value).upper(), "%I:%M %p")
    return parsed.hour * 60 + parsed.minute


def discover_subjects(html: str) -> list[str]:
    return [record["subject_code"] for record in discover_subject_catalog(html)]


def discover_subject_catalog(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    subjects: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        query = parse_qs(urlparse(anchor["href"]).query)
        for value in query.get("q", []):
            subject = value.strip()
            if (
                subject
                and subject.upper() == subject
                and len(subject) <= 20
                and not any(char.isspace() for char in subject)
            ):
                label = normalize_space(anchor.get_text(" ", strip=True))
                suffix = f"({subject})"
                subject_name = label[: -len(suffix)].strip() if label.endswith(suffix) else subject
                subjects[subject] = subject_name or subject
    return [
        {"subject_code": subject, "subject_name": subjects[subject]}
        for subject in sorted(subjects)
    ]


def result_count(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    summary = soup.select_one(".resultsSummary")
    if summary is None:
        return 0
    text = normalize_space(summary.get_text(" ", strip=True))
    match = re.search(r"(?:of\s+)?([\d,]+)\s+results?\s+for", text, re.IGNORECASE)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def _field(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return normalize_space(match.group(1)) if match else default


def _parse_section(
    section: Tag,
    *,
    course_number: str,
    course_title: str,
    academic_year: str,
    term: str,
    subject_query: str,
    source_url: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    text = normalize_space(" ".join(section.stripped_strings))
    class_number_match = re.search(r"Class #\s*(\d+)", text, re.IGNORECASE)
    if not class_number_match:
        return None, []

    class_number = class_number_match.group(1)
    cancelled = bool(
        re.search(r"Class #\s*\d+\s*\(CANCELLED\)", text, re.IGNORECASE)
        or re.search(r"class section has been cancelled", text, re.IGNORECASE)
    )
    component_match = re.search(
        r"Grading:\s*(.*?)\s*\|\s*([A-Z][A-Z0-9-]{1,12})"
        r"(?=\s*(?:\||\d{2}/\d{2}/\d{4}|-\s+-|$))",
        text,
    )
    enrollment_match = re.search(
        r"Students enrolled:\s*([\d,]+)\s*/\s*([\d,]+)", text, re.IGNORECASE
    )

    meeting_matches = list(MEETING_RE.finditer(text))
    meeting_rooms = [normalize_space(match.group("room") or "") for match in meeting_matches]
    physical_room = any(
        room
        and normalize_space(room).casefold()
        not in {"online", "remote", "departmental room", "school of medicine room"}
        for room in meeting_rooms
    )

    if "In Person" in text or physical_room:
        modality = "In Person"
    elif "Online" in text:
        modality = "Online"
    elif "Hybrid" in text:
        modality = "Hybrid"
    else:
        modality = "Unspecified"

    section_record: dict[str, Any] = {
        "academic_year": academic_year,
        "term": term,
        "subject_query": subject_query,
        "course_number": course_number,
        "course_title": course_title,
        "class_number": class_number,
        "section_number": _field(r"Section\s+([^|]+?)\s*\|", text),
        "grading": normalize_space(component_match.group(1)) if component_match else "",
        "component": normalize_space(component_match.group(2)) if component_match else "",
        "session": _field(r"Session:\s*([^|]+?)(?:\s*\||$)", text),
        "modality": modality,
        "enrolled": (
            int(enrollment_match.group(1).replace(",", "")) if enrollment_match else None
        ),
        "capacity": (
            int(enrollment_match.group(2).replace(",", "")) if enrollment_match else None
        ),
        "cancelled": cancelled,
        "source_url": source_url,
    }

    meetings: list[dict[str, Any]] = []
    for meeting_index, match in enumerate(meeting_matches, start=1):
        data = match.groupdict()
        room = normalize_space(data.get("room") or "")
        days = [day.strip() for day in data["days"].split(",")]
        for day in days:
            if day not in WEEKDAYS and day not in {"Sat", "Sun"}:
                continue
            meetings.append(
                {
                    **section_record,
                    "meeting_index": meeting_index,
                    "date_start": datetime.strptime(data["date_start"], "%m/%d/%Y").date(),
                    "date_end": datetime.strptime(data["date_end"], "%m/%d/%Y").date(),
                    "day": day,
                    "start_time": normalize_space(data["start"]).upper(),
                    "end_time": normalize_space(data["end"]).upper(),
                    "start_minutes": parse_time_minutes(data["start"]),
                    "end_minutes": parse_time_minutes(data["end"]),
                    "room": room,
                }
            )
    return section_record, meetings


def parse_schedule_page(
    html: str,
    *,
    academic_year: str,
    term: str,
    subject_query: str,
    source_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    soup = BeautifulSoup(html, "lxml")
    sections: list[dict[str, Any]] = []
    meetings: list[dict[str, Any]] = []
    selector = "div.searchResult, div.searchResult-noBorder"
    for result in soup.select(selector):
        number_node = result.select_one(".courseNumber")
        title_node = result.select_one(".courseTitle")
        if number_node is None:
            continue
        course_number = normalize_space(number_node.get_text(" ", strip=True)).rstrip(":")
        course_prefix = course_number.split(maxsplit=1)[0] if course_number else ""
        if course_prefix != subject_query:
            continue
        course_title = (
            normalize_space(title_node.get_text(" ", strip=True)) if title_node else ""
        )
        containers = result.select(".sectionContainer")
        if containers:
            expected = f"{academic_year[:4]}-{academic_year[4:]} {term}".casefold()
            matching_containers = []
            for container in containers:
                heading = container.select_one(".sectionContainerTerm")
                heading_text = (
                    normalize_space(heading.get_text(" ", strip=True)).casefold()
                    if heading
                    else ""
                )
                if heading_text == expected:
                    matching_containers.append(container)
            section_nodes = [
                section
                for container in matching_containers
                for section in container.select(".sectionDetails")
            ]
        else:
            section_nodes = result.select(".sectionDetails")

        for section in section_nodes:
            section_record, meeting_records = _parse_section(
                section,
                course_number=course_number,
                course_title=course_title,
                academic_year=academic_year,
                term=term,
                subject_query=subject_query,
                source_url=source_url,
            )
            if section_record is not None:
                sections.append(section_record)
                meetings.extend(meeting_records)
    return sections, meetings


def _source_url(subject: str, term: str, academic_year: str, page: int) -> str:
    params = {
        "q": subject,
        f"filter-catalognumber-{subject}": "on",
        f"filter-term-{term}": "on",
        "academicYear": academic_year,
        "page": page,
    }
    return f"{EXPLORE_BASE}/m_search?{urlencode(params)}"


def split_invalid_meeting_rows(
    meetings: pd.DataFrame, academic_year: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Separate source rows with impossible term dates or meeting durations."""
    if meetings.empty:
        return meetings.copy(), pd.DataFrame(), pd.DataFrame()

    start_year = int(academic_year[:4])
    expected_years = {
        "Autumn": start_year,
        "Winter": start_year + 1,
        "Spring": start_year + 1,
        "Summer": start_year + 1,
    }
    expected = meetings["term"].map(expected_years)
    starts = pd.to_datetime(meetings["date_start"])
    ends = pd.to_datetime(meetings["date_end"])
    invalid_date_mask = expected.notna() & (
        starts.dt.year.ne(expected) | ends.dt.year.ne(expected) | starts.gt(ends)
    )
    invalid_dates = meetings[invalid_date_mask].copy()
    remaining = meetings[~invalid_date_mask].copy()

    invalid_time_mask = remaining["start_minutes"].ge(remaining["end_minutes"])
    invalid_times = remaining[invalid_time_mask].copy()
    valid = remaining[~invalid_time_mask].copy()
    return valid, invalid_dates, invalid_times


def collect_explorecourses(
    fetcher: CachedFetcher,
    *,
    academic_year: str = ACADEMIC_YEAR,
    terms: tuple[str, ...] = TERMS,
    refresh: bool = False,
    subject_limit: int | None = None,
    use_xml_api: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    index_path = RAW_DIR / "explorecourses" / "subject_index.html"
    index_html = fetcher.get_text(f"{EXPLORE_BASE}/m", index_path, refresh=refresh)
    subject_catalog = discover_subject_catalog(index_html)
    if subject_limit is not None:
        subject_catalog = subject_catalog[:subject_limit]
    subjects = [record["subject_code"] for record in subject_catalog]

    all_sections: list[dict[str, Any]] = []
    all_meetings: list[dict[str, Any]] = []
    pages_fetched = 0
    empty_queries = 0

    for term in terms:
        for subject_index, subject in enumerate(subjects, start=1):
            cache_dir = RAW_DIR / "explorecourses" / academic_year / term
            filename = f"{safe_filename(subject)}_mobile_page_000.html"
            params = {
                "q": subject,
                f"filter-catalognumber-{subject}": "on",
                f"filter-term-{term}": "on",
                "academicYear": academic_year,
                "page": 0,
            }
            first_html = fetcher.get_text(
                f"{EXPLORE_BASE}/m_search",
                cache_dir / filename,
                params=params,
                refresh=refresh,
            )
            pages_fetched += 1
            total = result_count(first_html)
            if total == 0:
                empty_queries += 1
                continue
            pages = max(1, math.ceil(total / 10))
            for page in range(pages):
                if page == 0:
                    html = first_html
                else:
                    params["page"] = page
                    html = fetcher.get_text(
                        f"{EXPLORE_BASE}/m_search",
                        cache_dir
                        / f"{safe_filename(subject)}_mobile_page_{page:03d}.html",
                        params=params,
                        refresh=refresh,
                    )
                    pages_fetched += 1
                source_url = _source_url(subject, term, academic_year, page)
                sections, meetings = parse_schedule_page(
                    html,
                    academic_year=academic_year,
                    term=term,
                    subject_query=subject,
                    source_url=source_url,
                )
                all_sections.extend(sections)
                all_meetings.extend(meetings)

            if subject_index % 25 == 0:
                print(
                    f"ExploreCourses: {term} {subject_index}/{len(subjects)} subjects, "
                    f"{len(all_sections):,} section rows"
                )

    section_df = pd.DataFrame(all_sections)
    meeting_df = pd.DataFrame(all_meetings)
    invalid_meeting_dates = pd.DataFrame()
    invalid_meeting_times = pd.DataFrame()
    parsed_meeting_day_rows = len(meeting_df)
    if not section_df.empty:
        section_df = section_df.drop_duplicates(
            subset=["term", "class_number"], keep="first"
        ).sort_values(["term", "course_number", "class_number"])
    if not meeting_df.empty:
        meeting_df = meeting_df.drop_duplicates(
            subset=[
                "term",
                "class_number",
                "meeting_index",
                "day",
                "start_minutes",
                "end_minutes",
                "room",
            ],
            keep="first",
        ).sort_values(["term", "day", "start_minutes", "course_number"])
        parsed_meeting_day_rows = len(meeting_df)
        meeting_df, invalid_meeting_dates, invalid_meeting_times = (
            split_invalid_meeting_rows(meeting_df, academic_year)
        )

    api_manifest: dict[str, Any] = {"enabled": use_xml_api}
    if use_xml_api and not section_df.empty:
        # Imported here to avoid a module cycle: the XML parser shares the text
        # normalization helpers defined above.
        from .explorecourses_api import (
            canonical_meetings_from_api,
            collect_explorecourses_api,
            enrich_with_api,
        )

        api_sections, api_schedules, collection_manifest = collect_explorecourses_api(
            fetcher,
            subjects=subjects,
            academic_year=academic_year,
            terms=terms,
            refresh=refresh,
        )
        section_df, _mobile_meetings, _verification, match_manifest = enrich_with_api(
            section_df, meeting_df, api_sections, api_schedules
        )
        meeting_df = canonical_meetings_from_api(section_df, api_schedules)
        api_manifest.update(collection_manifest)
        api_manifest.update(match_manifest)
        api_manifest["canonical_meeting_day_rows"] = len(meeting_df)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(subject_catalog).to_csv(
        PROCESSED_DIR / "subject_catalog.csv", index=False
    )
    section_df.to_csv(PROCESSED_DIR / "sections.csv", index=False)
    meeting_df.to_csv(PROCESSED_DIR / "meetings.csv", index=False)
    invalid_meeting_dates.to_csv(
        PROCESSED_DIR / "invalid_meeting_dates_excluded.csv", index=False
    )
    invalid_meeting_times.to_csv(
        PROCESSED_DIR / "invalid_meeting_times_excluded.csv", index=False
    )
    manifest = {
        "academic_year": academic_year,
        "terms": list(terms),
        "subjects_discovered": len(subjects),
        "pages_fetched_or_cached": pages_fetched,
        "empty_subject_term_queries": empty_queries,
        "unique_sections": len(section_df),
        "parsed_meeting_day_rows_before_validation": parsed_meeting_day_rows,
        "meeting_day_rows": len(meeting_df),
        "invalid_term_date_rows_excluded": len(invalid_meeting_dates),
        "invalid_time_rows_excluded": len(invalid_meeting_times),
        "xml_api": api_manifest,
    }
    return section_df, meeting_df, manifest
