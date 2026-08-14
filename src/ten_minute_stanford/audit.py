from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from .campus_map import (
    USABLE_MATCH_STATUSES,
    is_queryable_room,
    parse_room_search,
    room_query_candidates,
)
from .config import (
    BICYCLE_SPEEDS_MPH,
    PROCESSED_DIR,
    PROJECT_ROOT,
    RAW_DIR,
    REPORT_DIR,
    REPORTING_DIR,
    WALKING_SPEEDS_MPH,
)
from .explorecourses import (
    discover_subjects,
    parse_schedule_page,
    safe_filename,
    split_invalid_meeting_rows,
)
from .explorecourses_api import (
    canonical_meetings_from_api,
    enrich_with_api,
    parse_explorecourses_xml,
)
from .external_context import EXTERNAL_CONTEXT_SOURCES, VERIFICATION_SCOPE
from .osm import (
    build_bike_graph,
    build_walk_graph,
    connected_components,
    osm_way_tag_coverage,
    weakly_connected_components,
)

SOURCE_MANIFEST_PATH = REPORT_DIR / "source_manifest.json"
PUBLICATION_AUDIT_PATH = REPORT_DIR / "publication_audit.json"
CLAIM_AUDIT_PATH = REPORT_DIR / "claim_audit.json"


class AuditError(RuntimeError):
    """Raised when a publication claim cannot be reproduced."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _close(left: float, right: float, *, tolerance: float = 1e-10) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.casefold().isin({"true", "1", "yes"})


def _assert_frames_equal(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    sort_columns: list[str],
    date_columns: tuple[str, ...] = (),
    numeric_columns: tuple[str, ...] = (),
    bool_columns: tuple[str, ...] = (),
    message: str,
) -> None:
    _require(
        list(expected.columns) == list(actual.columns),
        f"{message}: columns differ",
    )
    expected = expected.copy()
    actual = actual.copy()
    for frame in (expected, actual):
        for column in date_columns:
            frame[column] = pd.to_datetime(frame[column])
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        for column in bool_columns:
            frame[column] = _as_bool(frame[column])
        typed = set(date_columns) | set(numeric_columns) | set(bool_columns)
        for column in set(frame.columns) - typed:
            frame[column] = frame[column].fillna("").astype(str)
    expected = expected.sort_values(sort_columns).reset_index(drop=True)
    actual = actual.sort_values(sort_columns).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            expected,
            actual,
            check_dtype=False,
            check_like=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError(message) from exc


def _load_external_context_sources() -> dict[str, object]:
    registry = {
        "verification_scope": VERIFICATION_SCOPE,
        "sources": [dict(source) for source in EXTERNAL_CONTEXT_SOURCES],
    }
    _require(
        registry.get("verification_scope")
        == "Manual live content and HTTP verification; automated audits validate source classification and registry consistency but do not refetch the web.",
        "External context verification scope is missing or ambiguous",
    )
    sources = registry.get("sources")
    _require(isinstance(sources, list) and sources, "External context source list is empty")

    required_fields = {
        "id",
        "url",
        "supports",
        "checked_on",
        "evidence_use",
        "source_class",
        "supports_stanford_claim",
        "verification_status",
    }
    allowed_statuses = {"verified_live", "verified_indexed_copy"}
    allowed_source_classes = {
        "editorial_context",
        "external_open_data",
        "official_stanford",
        "third_party_code",
    }
    allowed_evidence_uses = {
        "analysis_input",
        "analysis_input_attribution",
        "context_only",
        "editorial_context_only",
        "implementation_reference",
        "policy_or_guidance",
        "source_description",
        "technical_documentation",
    }
    source_ids: list[str] = []
    for source in sources:
        _require(isinstance(source, dict), "External source entry is not an object")
        missing = required_fields - set(source)
        _require(not missing, f"External source entry is missing {sorted(missing)}")
        source_id = str(source["id"])
        source_ids.append(source_id)
        parsed = urlparse(str(source["url"]))
        _require(
            parsed.scheme == "https" and bool(parsed.hostname),
            f"External source {source_id} does not use an HTTPS URL",
        )
        _require(
            source["verification_status"] in allowed_statuses,
            f"External source {source_id} is not verified",
        )
        _require(
            source["source_class"] in allowed_source_classes,
            f"External source {source_id} has an invalid source class",
        )
        _require(
            source["evidence_use"] in allowed_evidence_uses,
            f"External source {source_id} has an invalid evidence use",
        )
        _require(
            isinstance(source["supports_stanford_claim"], bool),
            f"External source {source_id} has a non-boolean Stanford claim flag",
        )
        is_stanford_host = parsed.hostname == "stanford.edu" or str(parsed.hostname).endswith(
            ".stanford.edu"
        )
        if source["source_class"] == "official_stanford":
            _require(
                is_stanford_host,
                f"Official Stanford source {source_id} is not on a stanford.edu host",
            )
        _require(
            not source["supports_stanford_claim"]
            or (source["source_class"] == "official_stanford" and is_stanford_host),
            f"Non-Stanford source {source_id} cannot support a Stanford factual claim",
        )
        if source["source_class"] == "third_party_code":
            _require(
                source["evidence_use"] == "implementation_reference"
                and not source["supports_stanford_claim"],
                f"Third-party code source {source_id} exceeds its allowed evidence role",
            )
        if source["source_class"] == "editorial_context":
            _require(
                source["evidence_use"] == "editorial_context_only"
                and not source["supports_stanford_claim"],
                f"Editorial source {source_id} exceeds its context-only role",
            )
        try:
            date.fromisoformat(str(source["checked_on"]))
        except ValueError as exc:
            raise AuditError(f"External source {source_id} has an invalid check date") from exc
        for field in required_fields - {"url", "checked_on"}:
            _require(str(source[field]).strip(), f"External source {source_id} has a blank {field}")

    _require(len(source_ids) == len(set(source_ids)), "Duplicate external source IDs")
    return registry


def _metadata_record(path: Path, expected_host: str, source: str) -> dict[str, object]:
    metadata_path = path.with_suffix(path.suffix + ".meta.json")
    _require(metadata_path.exists(), f"Missing metadata for {path.relative_to(PROJECT_ROOT)}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _require(digest == metadata.get("sha256"), f"SHA-256 mismatch for {path.name}")
    _require(metadata.get("status_code") == 200, f"Non-200 source response for {path.name}")
    host = urlparse(str(metadata.get("source_url", ""))).hostname
    _require(host == expected_host, f"Unexpected source host {host!r} for {path.name}")
    text = path.read_text(encoding="utf-8", errors="replace") if path.suffix == ".html" else ""
    _require("Stanford Login" not in text, f"Authentication page cached as data: {path.name}")
    return {
        "cache_path": str(path.relative_to(PROJECT_ROOT)),
        "source": source,
        "source_url": metadata["source_url"],
        "retrieved_at_utc": metadata["retrieved_at_utc"],
        "sha256": digest,
        "bytes": path.stat().st_size,
        "request_params": metadata.get("params", {}),
    }


def build_source_manifest() -> dict[str, object]:
    validation = json.loads((REPORT_DIR / "validation.json").read_text(encoding="utf-8"))
    room_lookup = pd.read_csv(PROCESSED_DIR / "room_lookup.csv").fillna("")
    records: dict[Path, dict[str, object]] = {}

    explore_html_paths = [
        RAW_DIR / "explorecourses" / "subject_index.html",
        *sorted((RAW_DIR / "explorecourses" / "20252026" / "Winter").glob("*_mobile_page_*.html")),
    ]
    expected_pages = int(validation["explorecourses"]["pages_fetched_or_cached"])
    _require(
        len(explore_html_paths) == expected_pages + 1,
        f"Expected {expected_pages} ExploreCourses pages, found {len(explore_html_paths) - 1}",
    )
    subjects = set(discover_subjects(explore_html_paths[0].read_text(encoding="utf-8")))
    _require(
        len(subjects) == validation["explorecourses"]["subjects_discovered"],
        "Subject-index count differs from validation.json",
    )
    queried_pages: dict[str, set[int]] = defaultdict(set)
    reparsed_sections: list[dict[str, object]] = []
    reparsed_meetings: list[dict[str, object]] = []
    for path in explore_html_paths:
        record = _metadata_record(
            path, "explorecourses.stanford.edu", "Stanford ExploreCourses HTML"
        )
        records[path] = record
        if path.name != "subject_index.html":
            text = path.read_text(encoding="utf-8")
            _require("resultsSummary" in text, f"Not an ExploreCourses result page: {path.name}")
            query = parse_qs(urlparse(str(record["source_url"])).query)
            subject = query.get("q", [""])[0]
            page = query.get("page", [""])[0]
            expected_page = str(int(path.stem.rsplit("_", maxsplit=1)[1]))
            _require(subject in subjects, f"Unknown subject query for {path.name}")
            _require(page == expected_page, f"Page query differs from cache name: {path.name}")
            queried_pages[subject].add(int(page))
            _require(
                query.get("academicYear") == ["20252026"]
                and query.get("filter-term-Winter") == ["on"],
                f"Wrong academic year or term in {path.name}",
            )
            sections, meetings = parse_schedule_page(
                text,
                academic_year="20252026",
                term="Winter",
                subject_query=subject,
                source_url=str(record["source_url"]),
            )
            reparsed_sections.extend(sections)
            reparsed_meetings.extend(meetings)

    _require(
        set(queried_pages) == subjects,
        "Cached ExploreCourses pages do not cover every discovered subject",
    )
    for subject, pages in queried_pages.items():
        _require(
            pages == set(range(max(pages) + 1)),
            f"Cached ExploreCourses pagination is incomplete for {subject}",
        )

    section_frame = pd.DataFrame(reparsed_sections).drop_duplicates(
        ["term", "class_number"], keep="first"
    )
    meeting_frame = pd.DataFrame(reparsed_meetings).drop_duplicates(
        [
            "term",
            "class_number",
            "meeting_index",
            "day",
            "start_minutes",
            "end_minutes",
            "room",
        ],
        keep="first",
    )
    valid_meetings, invalid_dates, invalid_times = split_invalid_meeting_rows(
        meeting_frame, "20252026"
    )
    _require(
        len(section_frame) == validation["explorecourses"]["unique_sections"],
        "Raw ExploreCourses pages do not reproduce the section count",
    )
    _require(
        len(invalid_dates) == validation["explorecourses"]["invalid_term_date_rows_excluded"]
        and len(invalid_times) == validation["explorecourses"]["invalid_time_rows_excluded"],
        "Raw ExploreCourses pages do not reproduce excluded source anomalies",
    )
    anomaly_columns = [
        "course_number",
        "class_number",
        "date_start",
        "date_end",
        "day",
        "start_minutes",
        "end_minutes",
        "room",
    ]

    def anomaly_signatures(frame: pd.DataFrame) -> list[tuple[str, ...]]:
        return sorted(
            tuple(str(value) for value in row)
            for row in frame[anomaly_columns].fillna("").itertuples(index=False, name=None)
        )

    checked_invalid_dates = pd.read_csv(PROCESSED_DIR / "invalid_meeting_dates_excluded.csv")
    checked_invalid_times = pd.read_csv(PROCESSED_DIR / "invalid_meeting_times_excluded.csv")
    _require(
        anomaly_signatures(invalid_dates) == anomaly_signatures(checked_invalid_dates)
        and anomaly_signatures(invalid_times) == anomaly_signatures(checked_invalid_times),
        "Excluded source-anomaly files do not match the active raw schedule pages",
    )
    xml_validation = validation["explorecourses"]["xml_api"]
    xml_paths = sorted((RAW_DIR / "explorecourses_xml" / "20252026" / "Winter").glob("*.xml"))
    _require(
        len(xml_paths) == int(xml_validation["xml_queries_fetched_or_cached"]),
        "ExploreCourses XML cache does not contain one response per subject",
    )
    api_section_rows: list[dict[str, object]] = []
    api_schedule_rows: list[dict[str, object]] = []
    xml_subjects: set[str] = set()
    for path in xml_paths:
        record = _metadata_record(
            path,
            "explorecourses.stanford.edu",
            "Stanford ExploreCourses XML API",
        )
        records[path] = record
        params = record["request_params"]
        _require(isinstance(params, dict), f"Missing XML request parameters for {path.name}")
        subject = str(params.get("q", ""))
        _require(
            subject in subjects
            and path.name == f"{safe_filename(subject)}.xml"
            and params.get("academicYear") == "20252026"
            and params.get("filter-term-Winter") == "on"
            and params.get("filter-coursestatus-Active") == "on"
            and params.get(f"filter-departmentcode-{subject}") == "on"
            and params.get("view") == "xml-20200810",
            f"XML request metadata differs from the canonical query for {path.name}",
        )
        xml_subjects.add(subject)
        sections, schedules = parse_explorecourses_xml(
            path.read_text(encoding="utf-8"),
            academic_year="20252026",
            term="Winter",
            subject_query=subject,
            source_url=str(record["source_url"]),
        )
        api_section_rows.extend(sections)
        api_schedule_rows.extend(schedules)
    _require(xml_subjects == subjects, "ExploreCourses XML queries do not cover every subject")

    raw_api_sections = pd.DataFrame(api_section_rows)
    api_sections = (
        raw_api_sections.sort_values(
            ["term", "class_number", "api_subject_query", "api_course_number"]
        )
        .drop_duplicates(["term", "class_number"], keep="first")
        .reset_index(drop=True)
    )
    api_schedules = (
        pd.DataFrame(api_schedule_rows)
        .sort_values(["term", "class_number", "day", "start_minutes", "api_subject_query"])
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
    _require(
        len(raw_api_sections)
        == int(xml_validation["api_section_rows_before_crosslist_deduplication"])
        and len(api_sections) == int(xml_validation["api_unique_sections"])
        and len(api_schedules) == int(xml_validation["api_schedule_day_rows"]),
        "Raw XML responses do not reproduce the API row counts",
    )

    checked_api_sections = pd.read_csv(
        PROCESSED_DIR / "explorecourses_api_sections.csv",
        dtype={"class_number": str, "api_section_number": str},
    )
    _assert_frames_equal(
        api_sections,
        checked_api_sections,
        sort_columns=["term", "class_number"],
        numeric_columns=(
            "enrolled",
            "capacity",
            "waitlist",
            "waitlist_capacity",
        ),
        message="explorecourses_api_sections.csv does not match the raw XML responses",
    )
    checked_api_schedules = pd.read_csv(
        PROCESSED_DIR / "explorecourses_api_schedules.csv",
        dtype={"class_number": str, "api_section_number": str},
    )
    _assert_frames_equal(
        api_schedules,
        checked_api_schedules,
        sort_columns=[
            "term",
            "class_number",
            "day",
            "start_minutes",
            "api_schedule_index",
        ],
        date_columns=("date_start", "date_end"),
        numeric_columns=(
            "enrolled",
            "capacity",
            "waitlist",
            "waitlist_capacity",
            "api_schedule_index",
            "start_minutes",
            "end_minutes",
        ),
        message="explorecourses_api_schedules.csv does not match the raw XML responses",
    )

    expected_sections, _mobile_meetings, expected_verification, _api_summary = enrich_with_api(
        section_frame,
        valid_meetings,
        api_sections,
        api_schedules,
        write_outputs=False,
    )
    expected_meetings = canonical_meetings_from_api(expected_sections, api_schedules)
    checked_in_sections = pd.read_csv(
        PROCESSED_DIR / "sections.csv",
        dtype={
            "academic_year": str,
            "class_number": str,
            "section_number": str,
        },
    )
    _assert_frames_equal(
        expected_sections,
        checked_in_sections,
        sort_columns=["term", "class_number"],
        numeric_columns=(
            "enrolled",
            "capacity",
            "waitlist",
            "waitlist_capacity",
        ),
        bool_columns=("cancelled", "api_section_match"),
        message="sections.csv does not reproduce from HTML metadata and XML API fields",
    )
    checked_in_meetings = pd.read_csv(
        PROCESSED_DIR / "meetings.csv",
        dtype={
            "academic_year": str,
            "class_number": str,
            "section_number": str,
        },
    )
    _assert_frames_equal(
        expected_meetings,
        checked_in_meetings,
        sort_columns=[
            "term",
            "day",
            "start_minutes",
            "course_number",
            "class_number",
            "meeting_index",
        ],
        date_columns=("date_start", "date_end"),
        numeric_columns=(
            "enrolled",
            "capacity",
            "waitlist",
            "waitlist_capacity",
            "meeting_index",
            "start_minutes",
            "end_minutes",
        ),
        bool_columns=("cancelled", "api_section_match"),
        message="meetings.csv does not reproduce from the XML API schedules",
    )
    checked_verification = pd.read_csv(
        PROCESSED_DIR / "explorecourses_api_schedule_verification.csv",
        dtype={"class_number": str},
    )
    _assert_frames_equal(
        expected_verification,
        checked_verification,
        sort_columns=["term", "class_number", "day", "start_minutes"],
        date_columns=("date_start", "date_end"),
        numeric_columns=("start_minutes", "end_minutes"),
        bool_columns=("api_schedule_match", "api_section_match"),
        message="HTML-to-XML schedule verification table is stale",
    )

    for row in room_lookup.itertuples(index=False):
        accepted: tuple[str, dict[str, object]] | None = None
        for query in room_query_candidates(str(row.room)):
            digest = hashlib.sha1(query.encode("utf-8"), usedforsecurity=False).hexdigest()
            path = RAW_DIR / "campus_map" / f"{digest}.html"
            _require(path.exists(), f"Missing Campus Map response for query {query!r}")
            record = _metadata_record(path, "campus-map.stanford.edu", "Stanford Campus Map")
            records[path] = record
            request_params = record["request_params"]
            _require(
                isinstance(request_params, dict)
                and request_params.get("criteria") == query
                and request_params.get("orig_srch") == query,
                f"Campus Map request metadata differs for query {query!r}",
            )
            parsed = parse_room_search(path.read_text(encoding="utf-8"), query)
            if parsed["match_status"] in {"exact", "single_result"}:
                accepted = query, parsed
                break

        if str(row.match_status) in USABLE_MATCH_STATUSES:
            _require(accepted is not None, f"No reproducible Campus Map match for {row.room}")
            query, parsed = accepted
            _require(query == str(row.query_used), f"Fallback query changed for {row.room}")
            _require(
                str(parsed["facility_id"]) == str(row.facility_id),
                f"Facility decision changed for {row.room}",
            )
            _require(
                _close(float(parsed["latitude"]), float(row.latitude))
                and _close(float(parsed["longitude"]), float(row.longitude)),
                f"Campus Map coordinates changed for {row.room}",
            )
        else:
            _require(accepted is None, f"Unresolved room now has a cached match: {row.room}")

    expected_rooms = {
        room
        for room in checked_in_meetings["room"].dropna().astype(str).unique()
        if is_queryable_room(room)
    }
    _require(
        not room_lookup["room"].duplicated().any()
        and set(room_lookup["room"].astype(str)) == expected_rooms,
        "room_lookup.csv does not cover exactly the queryable schedule rooms",
    )

    osm_path = RAW_DIR / "osm" / "walk_network.json"
    records[osm_path] = _metadata_record(osm_path, "overpass-api.de", "OpenStreetMap via Overpass")
    osm_payload = json.loads(osm_path.read_text(encoding="utf-8"))
    osm_base_timestamp = str(osm_payload.get("osm3s", {}).get("timestamp_osm_base", ""))
    _require(
        osm_base_timestamp.endswith("Z"),
        "Raw OSM snapshot does not report a UTC database timestamp",
    )
    records[osm_path]["source_data_timestamp_utc"] = osm_base_timestamp
    _require(
        len(osm_payload.get("elements", [])) == validation["routing"]["osm_elements"],
        "OSM element count differs from validation.json",
    )
    _require(
        osm_way_tag_coverage(osm_payload) == validation["osm_way_tag_coverage"],
        "OSM way-tag coverage differs from validation.json",
    )
    full_graph, _nodes, all_edges = build_walk_graph(osm_payload)
    components = connected_components(full_graph)
    _require(components, "Raw OSM snapshot contains no retained walking component")
    main_component = max(components, key=len)
    raw_graph_counts = {
        "walk_graph_components_before_filter": len(components),
        "walk_graph_nodes_before_component_filter": len(full_graph),
        "walk_graph_undirected_edges_before_component_filter": (
            sum(len(neighbors) for neighbors in full_graph.values()) // 2
        ),
        "walk_edge_segments_before_component_filter": len(all_edges),
        "walk_graph_nodes": len(main_component),
    }
    for field, value in raw_graph_counts.items():
        _require(
            value == validation["routing"][field],
            f"Raw OSM graph count differs from validation.json for {field}",
        )
    raw_main_edges = all_edges[
        all_edges["from_node"].isin(main_component) & all_edges["to_node"].isin(main_component)
    ].reset_index(drop=True)
    checked_in_edges = pd.read_csv(PROCESSED_DIR / "walk_edges.csv")
    try:
        pd.testing.assert_frame_equal(
            raw_main_edges,
            checked_in_edges,
            check_dtype=False,
            check_like=False,
        )
    except AssertionError as exc:
        raise AuditError("walk_edges.csv does not match the active raw OSM snapshot") from exc

    full_bike_graph, _bike_nodes, all_bike_edges = build_bike_graph(osm_payload)
    bike_components = weakly_connected_components(full_bike_graph)
    _require(bike_components, "Raw OSM snapshot contains no retained bicycle component")
    main_bike_component = max(bike_components, key=len)
    raw_bike_counts = {
        "bike_graph_weak_components_before_filter": len(bike_components),
        "bike_graph_nodes_before_component_filter": len(full_bike_graph),
        "bike_edge_segments_before_component_filter": len(all_bike_edges),
        "bike_graph_nodes": len(main_bike_component),
        "bike_graph_directed_edges": sum(
            1
            for node in main_bike_component
            for neighbor in full_bike_graph.get(node, {})
            if neighbor in main_bike_component
        ),
    }
    for field, value in raw_bike_counts.items():
        _require(
            value == validation["bicycle_routing"][field],
            f"Raw OSM bicycle graph count differs from validation.json for {field}",
        )
    raw_main_bike_edges = all_bike_edges[
        all_bike_edges["from_node"].isin(main_bike_component)
        & all_bike_edges["to_node"].isin(main_bike_component)
    ].reset_index(drop=True)
    checked_in_bike_edges = pd.read_csv(PROCESSED_DIR / "bike_edges.csv")
    _assert_frames_equal(
        raw_main_bike_edges,
        checked_in_bike_edges,
        sort_columns=["way_id", "from_node", "to_node"],
        numeric_columns=(
            "way_id",
            "from_node",
            "to_node",
            "from_latitude",
            "from_longitude",
            "to_latitude",
            "to_longitude",
            "distance_meters",
        ),
        bool_columns=("forward_allowed", "backward_allowed"),
        message="bike_edges.csv does not match the active raw OSM snapshot",
    )

    ordered = [records[path] for path in sorted(records, key=lambda item: str(item))]
    source_counts = Counter(str(record["source"]) for record in ordered)
    retrievals = [str(record["retrieved_at_utc"]) for record in ordered]
    return {
        "schema_version": 3,
        "scope": "Active raw responses used for the checked-in Winter 2026 analysis",
        "raw_source_verification": "complete",
        "file_count": len(ordered),
        "source_file_counts": dict(sorted(source_counts.items())),
        "earliest_retrieval_utc": min(retrievals),
        "latest_retrieval_utc": max(retrievals),
        "source_data_timestamps": {
            "openstreetmap_base_utc": osm_base_timestamp,
        },
        "validated_section_rows_reparsed": len(api_sections),
        "validated_schedule_rows_reparsed": len(api_schedules),
        "mobile_section_rows_reparsed": len(section_frame),
        "mobile_schedule_rows_reparsed": len(valid_meetings),
        "walking_segments_reparsed": len(raw_main_edges),
        "bicycle_segments_reparsed": len(raw_main_bike_edges),
        "files": ordered,
    }


def _verify_route_distances(
    facilities: pd.DataFrame,
    edges: pd.DataFrame,
    routes: pd.DataFrame,
    *,
    directed: bool = False,
) -> int:
    graph: dict[int, dict[int, float]] = defaultdict(dict)
    for row in edges.itertuples(index=False):
        left = int(row.from_node)
        right = int(row.to_node)
        weight = float(row.distance_meters)
        forward_allowed = not directed or bool(row.forward_allowed)
        backward_allowed = not directed or bool(row.backward_allowed)
        if forward_allowed and weight < graph[left].get(right, math.inf):
            graph[left][right] = weight
        if backward_allowed and weight < graph[right].get(left, math.inf):
            graph[right][left] = weight

    target_nodes = set(facilities["node_id"].astype(int))
    route_lookup = routes.set_index(["origin_facility_id", "destination_facility_id"])
    verified = 0
    for origin in facilities.itertuples(index=False):
        source = int(origin.node_id)
        distances = {source: 0.0}
        queue = [(0.0, source)]
        remaining = set(target_nodes)
        while queue and remaining:
            distance, node = heapq.heappop(queue)
            if distance != distances.get(node):
                continue
            remaining.discard(node)
            for neighbor, weight in graph[node].items():
                candidate = distance + weight
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))

        for destination in facilities.itertuples(index=False):
            published = route_lookup.loc[
                (origin.facility_id, destination.facility_id),
                "route_distance_meters",
            ]
            if origin.facility_id == destination.facility_id:
                expected = 0.0
            else:
                expected = (
                    float(origin.snap_distance_meters)
                    + distances[int(destination.node_id)]
                    + float(destination.snap_distance_meters)
                )
            _require(
                _close(float(published), expected, tolerance=1e-8),
                "Published route distance differs from separate Dijkstra check: "
                f"{origin.facility_id} -> {destination.facility_id}",
            )
            verified += 1
    return verified


def _recompute_student_survey() -> tuple[pd.DataFrame, dict[str, int]]:
    responses = pd.read_csv(REPORTING_DIR / "student_survey_responses.csv").fillna("")
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
    _require(required <= set(responses.columns), "Student survey columns are incomplete")
    _require(not responses.empty, "Student survey contains no responses")
    _require(
        not responses["respondent_id"].duplicated().any(),
        "Student survey respondent IDs are not unique",
    )
    allowed_batches = {
        "prior_project_response",
        "google_sheet_legacy_questionnaire",
        "google_sheet_expanded_questionnaire",
    }
    _require(
        set(responses["source_batch"]) <= allowed_batches,
        "Student survey has unknown source batches",
    )

    modes = responses["travel_modes"].map(
        lambda value: {mode.strip() for mode in str(value).split(",") if mode.strip()}
    )
    followup = responses[_as_bool(responses["expanded_followup"])].copy()
    _require(not followup.empty, "Student survey contains no expanded follow-up responses")
    impact_categories = {
        "none_reported",
        "missed_class_content",
        "course_choice",
        "skipped_adjacent_activity",
    }
    _require(
        set(followup["impact_category"]) <= impact_categories,
        "Student survey has unknown impact categories",
    )
    counts = {
        "student_survey_responses": len(responses),
        "student_survey_linked_sheet_responses": int(
            responses["source_batch"].str.startswith("google_sheet_").sum()
        ),
        "student_survey_prior_retained_responses": int(
            responses["source_batch"].eq("prior_project_response").sum()
        ),
        "student_survey_reported_late": int(
            responses["late_response"].isin(("Yes, once or twice.", "Yes, multiple times.")).sum()
        ),
        "student_survey_close_call": int(
            responses["late_response"].eq("No, but it's been close.").sum()
        ),
        "student_survey_never_late": int(responses["late_response"].eq("No, never.").sum()),
        "student_survey_late_or_close_call": int(
            responses["late_response"]
            .isin(
                (
                    "Yes, once or twice.",
                    "Yes, multiple times.",
                    "No, but it's been close.",
                )
            )
            .sum()
        ),
        "student_survey_selected_walking": int(modes.map(lambda values: "Walking" in values).sum()),
        "student_survey_selected_biking": int(modes.map(lambda values: "Biking" in values).sum()),
        "student_survey_selected_e_scooter": int(
            modes.map(lambda values: "E-scooter" in values).sum()
        ),
        "student_survey_expanded_followup_responses": len(followup),
        "student_survey_transition_may_exceed_10min": int(
            _as_bool(followup["transition_may_exceed_10min"]).sum()
        ),
        "student_survey_reported_exact_ten_minute_gap": int(
            _as_bool(followup["reported_exact_ten_minute_gap"]).sum()
        ),
        "student_survey_reported_concrete_consequence": int(
            followup["impact_category"].ne("none_reported").sum()
        ),
        "student_survey_missed_class_content": int(
            followup["impact_category"].eq("missed_class_content").sum()
        ),
        "student_survey_course_choice_effect": int(
            followup["impact_category"].eq("course_choice").sum()
        ),
        "student_survey_skipped_adjacent_activity": int(
            followup["impact_category"].eq("skipped_adjacent_activity").sum()
        ),
    }
    denominator = counts["student_survey_responses"]
    table_rows = (
        (
            "reported_late",
            "Said distance had made them late",
            counts["student_survey_reported_late"],
            denominator,
            "Mutually exclusive response category",
        ),
        (
            "close_call",
            "Said it had been close",
            counts["student_survey_close_call"],
            denominator,
            "Mutually exclusive response category",
        ),
        (
            "never_late",
            "Said distance had never made them late",
            counts["student_survey_never_late"],
            denominator,
            "Mutually exclusive response category",
        ),
        (
            "late_or_close_call",
            "Reported lateness or a close call",
            counts["student_survey_late_or_close_call"],
            denominator,
            "Combines the two yes responses and the close-call response",
        ),
        (
            "selected_walking",
            "Selected walking",
            counts["student_survey_selected_walking"],
            denominator,
            "Respondents could select more than one mode",
        ),
        (
            "selected_biking",
            "Selected biking",
            counts["student_survey_selected_biking"],
            denominator,
            "Respondents could select more than one mode",
        ),
        (
            "selected_e-scooter",
            "Selected e-scooter",
            counts["student_survey_selected_e_scooter"],
            denominator,
            "Respondents could select more than one mode",
        ),
        (
            "transition_may_exceed_10min",
            "Reported a usual transition time or range extending beyond ten minutes",
            counts["student_survey_transition_may_exceed_10min"],
            len(followup),
            "Self-reported estimate; does not imply the respondent had a ten-minute gap",
        ),
        (
            "reported_exact_ten_minute_gap",
            "Explicitly reported a current ten-minute class gap",
            counts["student_survey_reported_exact_ten_minute_gap"],
            len(followup),
            "Based on the respondent's free-text course-pair answer",
        ),
        (
            "reported_concrete_consequence",
            "Described a concrete consequence beyond arrival time",
            counts["student_survey_reported_concrete_consequence"],
            len(followup),
            "Manually coded from the expanded impact question",
        ),
        (
            "missed_class_content",
            "Reported missing class content or an announcement",
            counts["student_survey_missed_class_content"],
            len(followup),
            "Mutually exclusive manually coded impact category",
        ),
        (
            "course_choice_effect",
            "Reported that distance affected a course choice",
            counts["student_survey_course_choice_effect"],
            len(followup),
            "Mutually exclusive manually coded impact category",
        ),
        (
            "skipped_adjacent_activity",
            "Reported skipping office hours, a study group or lunch",
            counts["student_survey_skipped_adjacent_activity"],
            len(followup),
            "Mutually exclusive manually coded impact category",
        ),
    )
    expected = pd.DataFrame(
        [
            {
                "metric": metric,
                "label": label,
                "count": count,
                "denominator": row_denominator,
                "share": count / row_denominator,
                "notes": notes,
            }
            for metric, label, count, row_denominator, notes in table_rows
        ]
    )
    return expected, counts


def _recompute_analysis() -> tuple[dict[str, object], pd.DataFrame]:
    meetings = pd.read_csv(PROCESSED_DIR / "meetings.csv", parse_dates=["date_start", "date_end"])
    room_lookup = pd.read_csv(PROCESSED_DIR / "room_lookup.csv")
    routes = pd.read_csv(PROCESSED_DIR / "route_distances.csv")
    bike_routes = pd.read_csv(PROCESSED_DIR / "bike_route_distances.csv")
    subject_catalog = pd.read_csv(PROCESSED_DIR / "subject_catalog.csv")

    meetings["cancelled"] = _as_bool(meetings["cancelled"])
    meetings["enrolled"] = pd.to_numeric(meetings["enrolled"], errors="coerce")
    queryable = meetings["room"].fillna("").astype(str).map(is_queryable_room)
    merged = meetings.merge(
        room_lookup[["room", "match_status", "facility_id"]], on="room", how="left"
    )
    eligible = merged[
        (~merged["cancelled"])
        & merged["modality"].eq("In Person")
        & merged["day"].isin(["Mon", "Tue", "Wed", "Thu", "Fri"])
        & queryable
    ].copy()
    mapped_listings = eligible[
        eligible["match_status"].isin(USABLE_MATCH_STATUSES) & eligible["facility_id"].notna()
    ].copy()
    physical_key = [
        "term",
        "day",
        "date_start",
        "date_end",
        "start_minutes",
        "end_minutes",
        "room",
        "facility_id",
    ]
    mapped_listings["reported_enrollment_at_meeting"] = mapped_listings.groupby(physical_key)[
        "enrolled"
    ].transform(lambda values: values.sum(min_count=1))
    mapped_listings["course_listings"] = mapped_listings.groupby(physical_key)[
        "course_number"
    ].transform(lambda values: " / ".join(dict.fromkeys(values.astype(str))))
    mapped_listings["subject_codes"] = mapped_listings.groupby(physical_key)[
        "subject_query"
    ].transform(lambda values: " / ".join(dict.fromkeys(values.astype(str))))
    mapped = mapped_listings.sort_values([*physical_key, "course_number"]).drop_duplicates(
        physical_key
    )
    mapped["enrolled"] = mapped["reported_enrollment_at_meeting"]
    mapped["course_number"] = mapped["course_listings"]

    origin = mapped[
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
    destination = mapped[
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
    ].rename(
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
    pairs = origin.merge(destination, on=["term", "day", "next_start_minutes"])
    overlap_start = pairs[["origin_date_start", "destination_date_start"]].max(axis=1)
    overlap_end = pairs[["origin_date_end", "destination_date_end"]].min(axis=1)
    weekday_number = pairs["day"].map({"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4})
    days_to_shared_meeting = (weekday_number - overlap_start.dt.weekday) % 7
    first_shared_meeting = overlap_start + pd.to_timedelta(days_to_shared_meeting, unit="D")
    has_shared_meeting = first_shared_meeting <= overlap_end
    same_class_number = pairs["origin_class_number"] == pairs["destination_class_number"]
    pair_date_rows_before_same_class_exclusion = int(has_shared_meeting.sum())
    same_class_number_rows_excluded = int((has_shared_meeting & same_class_number).sum())
    pairs = pairs[has_shared_meeting & ~same_class_number].copy()
    before_recurrence_deduplication = len(pairs)
    pair_key = [
        "term",
        "day",
        "origin_class_number",
        "destination_class_number",
        "origin_facility_id",
        "destination_facility_id",
        "origin_end_minutes",
        "next_start_minutes",
    ]
    pairs = pairs.drop_duplicates(pair_key)
    candidate_count = len(pairs)
    pairs = pairs.merge(
        routes,
        on=["origin_facility_id", "destination_facility_id"],
        how="left",
        validate="many_to_one",
    )
    pairs["walk_minutes_3_0mph"] = pairs["route_distance_meters"] / (3 * 1609.344 / 60)

    pairs = pairs[_as_bool(pairs["connected"])].dropna(subset=["route_distance_meters"])
    pairs["within_10min_3_0mph"] = pairs["walk_minutes_3_0mph"] <= 10
    pairs = pairs.merge(
        bike_routes[
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
        ),
        on=["origin_facility_id", "destination_facility_id"],
        how="left",
        validate="many_to_one",
    )

    large_candidates = pairs[
        pairs["origin_facility_id"].ne(pairs["destination_facility_id"])
        & pairs["origin_enrolled"].ge(100)
        & pairs["destination_enrolled"].ge(100)
    ].copy()
    large_pair_key = [
        "term",
        "origin_course_number",
        "origin_component",
        "origin_facility_id",
        "origin_end_minutes",
        "origin_enrolled",
        "destination_course_number",
        "destination_component",
        "destination_facility_id",
        "next_start_minutes",
        "destination_enrolled",
        "route_distance_meters",
        "walk_minutes_3_0mph",
    ]
    large_pairs = large_candidates.drop_duplicates(large_pair_key)

    component_pairs = pairs[
        pairs["origin_component"].isin(("LEC", "DIS"))
        & pairs["destination_component"].isin(("LEC", "DIS"))
    ].copy()
    component_pairs["over_10min_3mph"] = ~component_pairs["within_10min_3_0mph"]
    component_transition_results = component_pairs.groupby(
        ["origin_component", "destination_component"], as_index=False
    ).agg(
        potential_meeting_pairs=("origin_class_number", "size"),
        pairs_over_10min_3mph=("over_10min_3mph", "sum"),
        median_route_minutes_3mph=("walk_minutes_3_0mph", "median"),
        p90_route_minutes_3mph=(
            "walk_minutes_3_0mph",
            lambda values: values.quantile(0.9),
        ),
    )
    component_transition_results["share_over_10min_3mph"] = (
        component_transition_results["pairs_over_10min_3mph"]
        / component_transition_results["potential_meeting_pairs"]
    )
    component_transition_results["share_within_10min_3mph"] = (
        1 - component_transition_results["share_over_10min_3mph"]
    )
    represented_subject_codes = set()
    for column in ("origin_subject_codes", "destination_subject_codes"):
        for codes in pairs[column].dropna().astype(str):
            represented_subject_codes.update(
                code.strip() for code in codes.split(" / ") if code.strip()
            )

    speed_results = []
    for speed in WALKING_SPEEDS_MPH:
        minutes = pairs["route_distance_meters"] / (speed * 1609.344 / 60)
        speed_results.append(
            {
                "walking_speed_mph": speed,
                "share_within_10_minutes": float((minutes <= 10).mean()),
                "share_within_10_minutes_with_2min_overhead": float((minutes <= 8).mean()),
                "median_route_minutes": float(minutes.median()),
                "p90_route_minutes": float(minutes.quantile(0.9)),
            }
        )

    bicycle_speed_results = []
    for speed in BICYCLE_SPEEDS_MPH:
        minutes = pairs["bike_route_distance_meters"] / (speed * 1609.344 / 60)
        connected = _as_bool(pairs["bike_connected"]) & minutes.notna()
        bicycle_speed_results.append(
            {
                "bicycle_speed_mph": speed,
                "share_within_10_minutes": float((connected & (minutes <= 10)).mean()),
                "share_within_10_minutes_with_2min_handling": float(
                    (connected & (minutes <= 8)).mean()
                ),
                "median_route_minutes": float(minutes[connected].median()),
                "p90_route_minutes": float(minutes[connected].quantile(0.9)),
            }
        )

    _, survey_counts = _recompute_student_survey()
    result = {
        "source_meeting_day_rows": len(meetings),
        "eligible_physical_meeting_day_rows": len(eligible),
        "mapped_section_listing_day_rows": len(mapped_listings),
        "mapped_physical_meeting_day_rows": len(mapped),
        "cross_listing_rows_collapsed": len(mapped_listings) - len(mapped),
        "meeting_mapping_rate": len(mapped_listings) / len(eligible),
        "pair_date_rows_before_same_class_exclusion": (pair_date_rows_before_same_class_exclusion),
        "candidate_adjacent_meeting_pairs_before_routing": candidate_count,
        "same_class_number_pair_rows_excluded": same_class_number_rows_excluded,
        "recurring_pair_rows_collapsed": before_recurrence_deduplication - candidate_count,
        "potential_adjacent_meeting_pairs": len(pairs),
        "pair_routing_coverage": len(pairs) / candidate_count,
        "speed_results": speed_results,
        "bicycle_speed_results": bicycle_speed_results,
        "eligible_rows_with_reported_enrollment": int(eligible["enrolled"].notna().sum()),
        "enrollment_reporting_rate": float(eligible["enrolled"].notna().mean()),
        "distinct_passing_period_time_slots": int(
            pairs[["origin_end_minutes", "next_start_minutes"]].drop_duplicates().shape[0]
        ),
        "distinct_weekday_time_slots": int(
            pairs[["day", "origin_end_minutes", "next_start_minutes"]].drop_duplicates().shape[0]
        ),
        "lecture_component_meeting_day_rows": int(eligible["component"].eq("LEC").sum()),
        "discussion_component_meeting_day_rows": int(eligible["component"].eq("DIS").sum()),
        "lecture_median_start_minutes": float(
            eligible.loc[eligible["component"].eq("LEC"), "start_minutes"].median()
        ),
        "discussion_median_start_minutes": float(
            eligible.loc[eligible["component"].eq("DIS"), "start_minutes"].median()
        ),
        "lecture_share_starting_at_or_after_230pm": float(
            eligible.loc[eligible["component"].eq("LEC"), "start_minutes"].ge(870).mean()
        ),
        "discussion_share_starting_at_or_after_230pm": float(
            eligible.loc[eligible["component"].eq("DIS"), "start_minutes"].ge(870).mean()
        ),
        "lecture_share_on_thursday_or_friday": float(
            eligible.loc[eligible["component"].eq("LEC"), "day"].isin(["Thu", "Fri"]).mean()
        ),
        "discussion_share_on_thursday_or_friday": float(
            eligible.loc[eligible["component"].eq("DIS"), "day"].isin(["Thu", "Fri"]).mean()
        ),
        "lecture_discussion_transition_pairs": len(component_pairs),
        "component_transition_results": component_transition_results.to_dict(orient="records"),
        "subject_catalog_entries": len(subject_catalog),
        "subject_areas_with_transition_estimates": len(represented_subject_codes),
        "large_enrollment_screen_threshold": 100,
        "large_enrollment_unique_different_building_pairs": len(large_pairs),
        "large_enrollment_pairs_over_10min_3mph": int(
            large_pairs["walk_minutes_3_0mph"].gt(10).sum()
        ),
        "large_enrollment_share_over_10min_3mph": float(
            large_pairs["walk_minutes_3_0mph"].gt(10).mean()
        ),
        **survey_counts,
    }
    return result, pairs


def _check_publication_files(
    summary: dict[str, object],
    validation: dict[str, object],
    source_manifest: dict[str, object],
    external_context: dict[str, object],
) -> int:
    pairs = f"{int(summary['potential_adjacent_meeting_pairs']):,}"
    eligible = f"{int(summary['eligible_physical_meeting_day_rows']):,}"
    mapped = f"{int(summary['mapped_section_listing_day_rows']):,}"
    physical = f"{int(summary['mapped_physical_meeting_day_rows']):,}"
    share = f"{float(summary['three_mph_share_within_10_minutes']):.1%}"
    overhead = f"{float(summary['three_mph_share_within_10_minutes_with_2min_overhead']):.1%}"
    median = f"{float(summary['three_mph_median_route_minutes']):.1f}"
    p90 = f"{float(summary['three_mph_p90_route_minutes']):.1f}"
    mapping_rate = f"{float(summary['meeting_mapping_rate']):.2%}"
    source_count = f"{int(source_manifest['file_count']):,}"
    campus_map_count = f"{int(source_manifest['source_file_counts']['Stanford Campus Map']):,}"
    pair_date_rows = f"{int(summary['potential_adjacent_meeting_pairs']) + int(summary['recurring_pair_rows_collapsed']):,}"
    pre_exclusion_pair_date_rows = f"{int(summary['pair_date_rows_before_same_class_exclusion']):,}"
    cross_listings = f"{int(summary['cross_listing_rows_collapsed']):,}"
    same_class_exclusions = (
        f"{int(summary['same_class_number_pair_rows_excluded']):,} same-class-number pair-date row"
    )
    speed_results = {
        float(row["walking_speed_mph"]): row for row in summary["walking_speed_results"]
    }
    two_mph_share = f"{float(speed_results[2.0]['share_within_10_minutes']):.1%}"
    four_mph_share = f"{float(speed_results[4.0]['share_within_10_minutes']):.1%}"
    over_ten_share = f"{1 - float(summary['three_mph_share_within_10_minutes']):.1%}"
    mapping_rate_one_decimal = f"{float(summary['meeting_mapping_rate']):.1%}"
    unmapped = f"{int(summary['eligible_physical_meeting_day_rows']) - int(summary['mapped_section_listing_day_rows']):,}"
    unresolved_labels = f"{int(summary['room_match_status_counts']['no_result']):,}"
    facility_count = f"{int(summary['unique_mapped_facilities']):,}"
    api_sections = f"{int(summary['api_unique_sections']):,}"
    time_slots = f"{int(summary['distinct_passing_period_time_slots']):,}"
    weekday_time_slots = f"{int(summary['distinct_weekday_time_slots']):,}"
    bicycle_share = f"{float(summary['eight_mph_bicycle_share_within_10_minutes']):.1%}"
    bicycle_overhead = (
        f"{float(summary['eight_mph_bicycle_share_within_10_minutes_with_2min_handling']):.1%}"
    )
    bicycle_p90 = f"{float(summary['eight_mph_bicycle_p90_route_minutes']):.1f}"
    lecture_rows = f"{int(summary['lecture_component_meeting_day_rows']):,}"
    discussion_rows = f"{int(summary['discussion_component_meeting_day_rows']):,}"
    lecture_late_share = f"{float(summary['lecture_share_starting_at_or_after_230pm']):.1%}"
    discussion_late_share = f"{float(summary['discussion_share_starting_at_or_after_230pm']):.1%}"
    lecture_thu_fri_share = f"{float(summary['lecture_share_on_thursday_or_friday']):.1%}"
    discussion_thu_fri_share = f"{float(summary['discussion_share_on_thursday_or_friday']):.1%}"
    subject_catalog_entries = f"{int(summary['subject_catalog_entries']):,}"
    component_transition_pairs = f"{int(summary['lecture_discussion_transition_pairs']):,}"
    component_transition_results = {
        (row["origin_component"], row["destination_component"]): row
        for row in summary["component_transition_results"]
    }
    component_transition_shares = tuple(
        f"{float(component_transition_results[key]['share_within_10min_3mph']):.1%}"
        for key in (("LEC", "LEC"), ("LEC", "DIS"), ("DIS", "LEC"), ("DIS", "DIS"))
    )
    subject_transition_count = f"{int(summary['subject_areas_with_transition_estimates']):,}"
    subject_transition_table = pd.read_csv(
        REPORT_DIR / "tables" / "subject_transition_feasibility.csv"
    ).set_index("subject_code")
    subject_transition_shares = tuple(
        f"{float(subject_transition_table.loc[code, 'outgoing_share_over_10min_3mph']):.1%}"
        for code in ("HISTORY", "CS", "MUSIC")
    )
    large_enrollment_threshold = str(int(summary["large_enrollment_screen_threshold"]))
    large_enrollment_pairs = f"{int(summary['large_enrollment_unique_different_building_pairs']):,}"
    large_enrollment_over_ten = f"{int(summary['large_enrollment_pairs_over_10min_3mph']):,}"
    large_enrollment_over_ten_share = (
        f"{float(summary['large_enrollment_share_over_10min_3mph']):.1%}"
    )
    slot_table = pd.read_csv(REPORT_DIR / "tables" / "time_slot_summary.csv")
    busiest_slot = slot_table.loc[slot_table["potential_meeting_pairs"].idxmax()]
    morning_slot = slot_table[slot_table["passing_period"].eq("10:20 a.m. to 10:30 a.m.")]
    _require(len(morning_slot) == 1, "Expected 10:20 a.m. passing period is missing")
    morning_slot_row = morning_slot.iloc[0]
    busiest_slot_pairs = f"{int(busiest_slot['potential_meeting_pairs']):,}"
    busiest_slot_share = f"{float(busiest_slot['walk_share_within_10min_3mph']):.1%}"
    morning_slot_pairs = f"{int(morning_slot_row['potential_meeting_pairs']):,}"
    morning_slot_share = f"{float(morning_slot_row['walk_share_within_10min_3mph']):.1%}"
    route_example_snippets = (
        "Lathrop Library",
        "Thornton Center",
        "12.9",
        "Building 200",
        "Cordura Hall",
        "14.1",
        "Building 260",
        "McMurtry Building",
    )
    course_cases = pd.read_csv(REPORT_DIR / "tables" / "course_transition_cases.csv")
    course_case_snippets = tuple(
        str(value)
        for row in course_cases.itertuples(index=False)
        for value in (
            row.origin_course_number,
            row.origin_label,
            row.destination_course_number,
            row.destination_label,
        )
    )
    passing_period_scenarios = pd.read_csv(REPORT_DIR / "tables" / "passing_period_scenarios.csv")
    three_mph_passing_periods = passing_period_scenarios[
        passing_period_scenarios["walking_speed_mph"].eq(3)
    ].set_index(["passing_period_minutes", "building_overhead_minutes"])
    fifteen_minute_share = f"{float(three_mph_passing_periods.loc[(15, 0), 'share_feasible']):.1%}"
    fifteen_minute_overhead_share = (
        f"{float(three_mph_passing_periods.loc[(15, 2), 'share_feasible']):.1%}"
    )
    survey_article_snippets = (
        "What 27 Stanford students have added",
        "Fourteen of 27 respondents said distance had made them late at least once",
        "20 participants (74%)",
        "Eleven cited a specific consequence beyond arrival time",
        "Twenty-one people selected walking",
        "convenience sample",
    )

    required_by_file = {
        PROJECT_ROOT / "README.md": (
            pairs,
            share,
            overhead,
            p90,
            source_count,
            time_slots,
            component_transition_pairs,
            subject_transition_count,
            "27-response convenience survey",
        ),
        PROJECT_ROOT / "article" / "article.md": (
            pairs,
            share,
            overhead,
            median,
            p90,
            cross_listings,
            two_mph_share,
            four_mph_share,
            over_ten_share,
            eligible,
            mapped,
            physical,
            unmapped,
            facility_count,
            api_sections,
            time_slots,
            weekday_time_slots,
            bicycle_share,
            bicycle_overhead,
            bicycle_p90,
            busiest_slot_pairs,
            busiest_slot_share,
            morning_slot_pairs,
            morning_slot_share,
            lecture_rows,
            discussion_rows,
            lecture_late_share,
            discussion_late_share,
            lecture_thu_fri_share,
            discussion_thu_fri_share,
            subject_catalog_entries,
            component_transition_pairs,
            *component_transition_shares,
            *subject_transition_shares,
            large_enrollment_threshold,
            large_enrollment_pairs,
            large_enrollment_over_ten,
            large_enrollment_over_ten_share,
            "Lathrop Library",
            "Thornton Center",
            "12.9",
            "Cordura Hall",
            "14.1",
            "McMurtry Building",
            *survey_article_snippets,
        ),
        PROJECT_ROOT / "article" / "methodology.md": (
            pairs,
            eligible,
            mapped,
            physical,
            mapping_rate,
            pre_exclusion_pair_date_rows,
            pair_date_rows,
            cross_listings,
            same_class_exclusions,
            api_sections,
            time_slots,
            weekday_time_slots,
            lecture_rows,
            discussion_rows,
            component_transition_pairs,
            subject_transition_count,
            large_enrollment_pairs,
            large_enrollment_over_ten,
            "student_survey_summary.csv",
            "convenience sample",
        ),
        PROJECT_ROOT / "article" / "source_log.md": (
            source_count,
            "student_survey_summary.csv",
            "Author-conducted reporting",
        ),
        REPORT_DIR / "FINDINGS.md": (
            pairs,
            mapped,
            physical,
            share,
            overhead,
            "27-response convenience survey",
        ),
        PROJECT_ROOT / "site" / "index.html": (
            pairs,
            share,
            overhead,
            median,
            p90,
            two_mph_share,
            four_mph_share,
            over_ten_share,
            eligible,
            mapped,
            physical,
            mapping_rate_one_decimal,
            unmapped,
            unresolved_labels,
            facility_count,
            api_sections,
            time_slots,
            weekday_time_slots,
            bicycle_share,
            bicycle_overhead,
            bicycle_p90,
            busiest_slot_pairs,
            busiest_slot_share,
            morning_slot_pairs,
            morning_slot_share,
            lecture_rows,
            discussion_rows,
            lecture_late_share,
            discussion_late_share,
            lecture_thu_fri_share,
            discussion_thu_fri_share,
            subject_catalog_entries,
            component_transition_pairs,
            *component_transition_shares,
            *subject_transition_shares,
            large_enrollment_threshold,
            large_enrollment_pairs,
            large_enrollment_over_ten,
            large_enrollment_over_ten_share,
            fifteen_minute_share,
            fifteen_minute_overhead_share,
            *route_example_snippets,
            *course_case_snippets,
            *survey_article_snippets,
            "student_survey_summary.csv",
        ),
        PROJECT_ROOT / "site" / "script.js": (),
        PROJECT_ROOT / "site" / "methodology.html": (
            pairs,
            eligible,
            mapped,
            physical,
            mapping_rate,
            pre_exclusion_pair_date_rows,
            pair_date_rows,
            cross_listings,
            same_class_exclusions,
            api_sections,
            time_slots,
            weekday_time_slots,
            lecture_rows,
            discussion_rows,
            component_transition_pairs,
            subject_transition_count,
            large_enrollment_pairs,
            large_enrollment_over_ten,
            "student_survey_summary.csv",
            "convenience sample",
        ),
        PROJECT_ROOT / "site" / "source-log.html": (
            source_count,
            f"{campus_map_count} Campus Map responses",
            "student_survey_summary.csv",
            "Author-conducted reporting",
        ),
    }
    stale_claims = (
        "267,998",
        "277,485",
        "86.2%",
        "72.4%",
        "59.2%",
        "13.8%",
        "11.1 min",
        "5.8 min",
        "6,041",
        "5,797",
        "4,411",
        "95.96%",
        "96.58%",
        "Bishop Auditorium to Thornton Center",
        "277,182",
        "277,764",
        "84.0%",
        "70.3%",
        "57.3%",
        "42.8%",
        "94.7%",
        "86.9%",
        "16.0%",
        "11.8 min",
        "6.0 min",
        "5,793",
        "4,407",
        "1,386",
        "96.21%",
        "449 Campus Map responses",
        "1,030-source manifest",
        "283,288",
        "6,021",
        "5,843",
        "4,456",
        "1,387",
        "56.3%",
        "69.1%",
        "1,025-source manifest",
    )
    unsupported_or_overstated_phrases = (
        "the collector can recreate them",
        "publication audit independently rebuilds",
        "Independent recomputation",
        "Shortest outdoor routes were calculated",
        "Nonphysical and weekend meetings were excluded",
        "A 12-person seminar",
        "Estimated shortest outdoor",
        "ten outdoor minutes",
        "an outdoor route of",
        "so an outdoor route",
        "HTTP 403",
        "indexed copies",
    )
    publication_texts: dict[Path, str] = {}
    for path, required in required_by_file.items():
        _require(path.exists(), f"Publication file is missing: {path.relative_to(PROJECT_ROOT)}")
        text = path.read_text(encoding="utf-8")
        publication_texts[path] = text
        normalized_text = " ".join(text.split())
        for snippet in required:
            _require(
                " ".join(snippet.split()) in normalized_text,
                f"Current claim {snippet!r} missing from {path.relative_to(PROJECT_ROOT)}",
            )
        for snippet in stale_claims:
            _require(
                snippet not in text,
                f"Stale claim {snippet!r} remains in {path.relative_to(PROJECT_ROOT)}",
            )
        lowered = text.casefold()
        for phrase in unsupported_or_overstated_phrases:
            _require(
                phrase.casefold() not in lowered,
                f"Unsupported or overstated wording {phrase!r} remains in "
                f"{path.relative_to(PROJECT_ROOT)}",
            )

    attribution_files = (
        PROJECT_ROOT / "article" / "source_log.md",
        PROJECT_ROOT / "site" / "index.html",
        PROJECT_ROOT / "site" / "source-log.html",
    )
    for path in attribution_files:
        text = path.read_text(encoding="utf-8")
        _require(
            "https://www.openstreetmap.org/copyright" in text,
            f"OSM license link missing from {path.relative_to(PROJECT_ROOT)}",
        )
        _require(
            "OpenStreetMap contributors" in text,
            f"OSM contributor credit missing from {path.relative_to(PROJECT_ROOT)}",
        )

    all_publication_text = "\n".join(publication_texts.values())
    for source in external_context["sources"]:
        url = str(source["url"])
        _require(
            url in all_publication_text,
            f"Verified external source {source['id']} is not cited in an audited publication file",
        )
    return len(set(required_by_file) | set(attribution_files))


def _build_claim_audit(
    summary: dict[str, object],
    validation: dict[str, object],
    source_manifest: dict[str, object],
    external_context: dict[str, object],
    pair_table: pd.DataFrame,
) -> dict[str, object]:
    route_examples = []
    for origin_id, destination_id in (
        ("08-350", "04-720"),
        ("01-200", "14-070"),
        ("01-260", "07-090"),
    ):
        match = pair_table[
            pair_table["origin_facility_id"].astype(str).eq(origin_id)
            & pair_table["destination_facility_id"].astype(str).eq(destination_id)
        ]
        _require(
            len(match) == 1,
            f"Expected route example {origin_id} -> {destination_id} is missing",
        )
        row = match.iloc[0]
        route_examples.append(
            {
                "origin_facility_id": origin_id,
                "origin_label": str(row["origin_label"]),
                "destination_facility_id": destination_id,
                "destination_label": str(row["destination_label"]),
                "route_distance_meters": float(row["route_distance_meters"]),
                "route_minutes_3mph": float(row["walk_minutes_3_0mph"]),
                "potential_meeting_pairs": int(row["potential_meeting_pairs"]),
                "evidence": "reports/generated/tables/building_pair_summary.csv",
            }
        )

    source_counts = source_manifest["source_file_counts"]
    pair_date_rows = int(summary["potential_adjacent_meeting_pairs"]) + int(
        summary["recurring_pair_rows_collapsed"]
    )
    passing_period_scenarios = pd.read_csv(REPORT_DIR / "tables" / "passing_period_scenarios.csv")
    three_mph_period_rows = passing_period_scenarios[
        passing_period_scenarios["walking_speed_mph"].eq(3)
    ].sort_values(["passing_period_minutes", "building_overhead_minutes"])
    subject_transition_rows = pd.read_csv(
        REPORT_DIR / "tables" / "subject_transition_feasibility.csv"
    )
    largest_subject_transition_rows = subject_transition_rows.nlargest(
        15, "total_mapped_meeting_day_rows"
    )
    claims = {
        "schedule_collection": {
            "subject_codes_discovered": int(validation["explorecourses"]["subjects_discovered"]),
            "schedule_responses": int(validation["explorecourses"]["pages_fetched_or_cached"]),
            "parsed_meeting_day_rows_before_validation": int(
                summary["parsed_meeting_day_rows_before_validation"]
            ),
            "mobile_html_invalid_term_date_rows": int(
                validation["explorecourses"]["invalid_term_date_rows_excluded"]
            ),
            "mobile_html_invalid_time_rows": int(
                validation["explorecourses"]["invalid_time_rows_excluded"]
            ),
            "xml_queries": int(
                validation["explorecourses"]["xml_api"]["xml_queries_fetched_or_cached"]
            ),
            "xml_sections": int(summary["api_unique_sections"]),
            "canonical_meeting_day_rows": int(summary["source_meeting_day_rows"]),
            "canonical_invalid_date_rows": int(summary["invalid_term_date_rows_excluded"]),
            "canonical_invalid_time_rows": int(summary["invalid_time_rows_excluded"]),
            "mobile_rows_exactly_matching_xml": int(
                summary["mobile_html_meeting_rows_exactly_matching_api"]
            ),
            "mobile_to_xml_schedule_match_rate": float(
                summary["mobile_html_meeting_schedule_match_rate"]
            ),
            "unique_sections": int(validation["explorecourses"]["unique_sections"]),
            "evidence": [
                "data/processed/meetings.csv",
                "data/processed/invalid_meeting_dates_excluded.csv",
                "data/processed/invalid_meeting_times_excluded.csv",
                "reports/generated/validation.json",
            ],
        },
        "source_provenance": {
            "active_raw_responses": int(source_manifest["file_count"]),
            "explorecourses_html_responses": int(source_counts["Stanford ExploreCourses HTML"]),
            "explorecourses_xml_responses": int(source_counts["Stanford ExploreCourses XML API"]),
            "campus_map_responses": int(source_counts["Stanford Campus Map"]),
            "openstreetmap_responses": int(source_counts["OpenStreetMap via Overpass"]),
            "section_rows_reparsed": int(source_manifest["validated_section_rows_reparsed"]),
            "meeting_day_rows_reparsed": int(source_manifest["validated_schedule_rows_reparsed"]),
            "openstreetmap_base_utc": source_manifest["source_data_timestamps"][
                "openstreetmap_base_utc"
            ],
            "raw_source_verification": source_manifest["raw_source_verification"],
            "evidence": "reports/generated/source_manifest.json",
        },
        "room_matching": {
            "queryable_room_labels": int(validation["room_lookup"]["rooms_queried"]),
            "exact_matches": int(summary["room_match_status_counts"]["exact"]),
            "fallback_matches": int(summary["room_match_status_counts"]["fallback"]),
            "unresolved_labels": int(summary["room_match_status_counts"]["no_result"]),
            "eligible_listing_day_rows": int(summary["eligible_physical_meeting_day_rows"]),
            "mapped_listing_day_rows": int(summary["mapped_section_listing_day_rows"]),
            "unmapped_eligible_listing_day_rows": int(summary["eligible_physical_meeting_day_rows"])
            - int(summary["mapped_section_listing_day_rows"]),
            "mapping_rate": float(summary["meeting_mapping_rate"]),
            "mapped_facilities": int(summary["unique_mapped_facilities"]),
            "evidence": [
                "data/processed/room_lookup.csv",
                "reports/generated/analysis_summary.json",
            ],
        },
        "pair_denominator": {
            "mapped_physical_meeting_day_rows": int(summary["mapped_physical_meeting_day_rows"]),
            "cross_listing_rows_collapsed": int(summary["cross_listing_rows_collapsed"]),
            "pair_date_rows_before_same_class_exclusion": int(
                summary["pair_date_rows_before_same_class_exclusion"]
            ),
            "pair_date_rows_before_recurrence_deduplication": pair_date_rows,
            "same_class_number_pair_rows_excluded": int(
                summary["same_class_number_pair_rows_excluded"]
            ),
            "recurring_pair_rows_collapsed": int(summary["recurring_pair_rows_collapsed"]),
            "potential_ordered_meeting_pairs": int(summary["potential_adjacent_meeting_pairs"]),
            "pair_routing_coverage": float(summary["pair_routing_coverage"]),
            "evidence": [
                "data/processed/meetings.csv",
                "reports/generated/tables/building_pair_summary.csv",
            ],
        },
        "walking_scenarios": {
            "results": summary["walking_speed_results"],
            "speeds_are_sensitivity_tests": True,
            "building_allowance_minutes": 2,
            "building_allowance_is_empirical": False,
            "evidence": [
                "reports/generated/tables/speed_summary.csv",
                "reports/generated/analysis_summary.json",
            ],
        },
        "passing_period_scenarios": {
            "walking_speed_mph": 3,
            "same_winter_2026_pair_denominator": True,
            "results": [
                {
                    "passing_period_minutes": int(row.passing_period_minutes),
                    "building_overhead_minutes": int(row.building_overhead_minutes),
                    "available_route_minutes": int(row.available_route_minutes),
                    "feasible_pairs": int(row.feasible_pairs),
                    "total_pairs": int(row.total_pairs),
                    "share_feasible": float(row.share_feasible),
                }
                for row in three_mph_period_rows.itertuples(index=False)
            ],
            "twelve_minute_case_is_hypothetical": True,
            "fifteen_minute_case_is_historical_comparison": True,
            "fifteen_minute_case_is_current_policy": False,
            "evidence": [
                "reports/generated/tables/passing_period_scenarios.csv",
                "reports/generated/interactive/route_explorer.json",
            ],
        },
        "bicycle_scenarios": {
            "results": summary["bicycle_speed_results"],
            "speeds_are_sensitivity_tests": True,
            "bike_handling_allowance_minutes": 2,
            "bike_handling_allowance_is_empirical": False,
            "evidence": [
                "reports/generated/tables/bicycle_speed_summary.csv",
                "reports/generated/analysis_summary.json",
            ],
        },
        "time_slot_analysis": {
            "distinct_ten_minute_slots": int(summary["distinct_passing_period_time_slots"]),
            "distinct_weekday_slots": int(summary["distinct_weekday_time_slots"]),
            "evidence": [
                "reports/generated/tables/time_slot_summary.csv",
                "reports/generated/tables/weekday_time_slot_summary.csv",
                "reports/generated/tables/course_transition_examples.csv",
                "reports/generated/tables/course_transition_cases.csv",
            ],
        },
        "component_schedule_analysis": {
            "unit": "eligible section-listing meeting-day row",
            "lecture_rows": int(summary["lecture_component_meeting_day_rows"]),
            "discussion_rows": int(summary["discussion_component_meeting_day_rows"]),
            "lecture_median_start_minutes": float(summary["lecture_median_start_minutes"]),
            "discussion_median_start_minutes": float(summary["discussion_median_start_minutes"]),
            "lecture_share_starting_at_or_after_230pm": float(
                summary["lecture_share_starting_at_or_after_230pm"]
            ),
            "discussion_share_starting_at_or_after_230pm": float(
                summary["discussion_share_starting_at_or_after_230pm"]
            ),
            "lecture_share_on_thursday_or_friday": float(
                summary["lecture_share_on_thursday_or_friday"]
            ),
            "discussion_share_on_thursday_or_friday": float(
                summary["discussion_share_on_thursday_or_friday"]
            ),
            "evidence": [
                "reports/generated/tables/component_time_summary.csv",
                "reports/generated/tables/component_day_summary.csv",
                "data/processed/meetings.csv",
            ],
        },
        "component_transition_analysis": {
            "unit": "possible ordered physical-meeting pair",
            "lecture_discussion_pairs": int(summary["lecture_discussion_transition_pairs"]),
            "results": summary["component_transition_results"],
            "is_student_schedule_measure": False,
            "evidence": ("reports/generated/tables/component_transition_summary.csv"),
        },
        "subject_area_location_analysis": {
            "subject_catalog_entries": int(summary["subject_catalog_entries"]),
            "unit": "mapped section-listing meeting-day row",
            "subject_is_not_always_a_formal_department": True,
            "cross_listed_records_remain_under_each_published_subject_code": True,
            "evidence": [
                "data/processed/subject_catalog.csv",
                "reports/generated/tables/department_location_summary.csv",
            ],
        },
        "subject_area_transition_analysis": {
            "unit": "possible ordered physical-meeting pair attributed by subject code",
            "subject_areas_with_estimates": int(summary["subject_areas_with_transition_estimates"]),
            "cross_listed_subject_totals_are_additive": False,
            "largest_15_subject_results": largest_subject_transition_rows[
                [
                    "subject_code",
                    "potential_outgoing_pairs",
                    "outgoing_pairs_over_10min_3mph",
                    "outgoing_share_over_10min_3mph",
                    "potential_incoming_pairs",
                    "incoming_pairs_over_10min_3mph",
                    "incoming_share_over_10min_3mph",
                ]
            ].to_dict(orient="records"),
            "evidence": ("reports/generated/tables/subject_transition_feasibility.csv"),
        },
        "large_enrollment_screen": {
            "minimum_reported_enrollment_in_each_meeting": int(
                summary["large_enrollment_screen_threshold"]
            ),
            "unique_different_building_combinations": int(
                summary["large_enrollment_unique_different_building_pairs"]
            ),
            "combinations_over_10min_at_3mph": int(
                summary["large_enrollment_pairs_over_10min_3mph"]
            ),
            "share_over_10min_at_3mph": float(summary["large_enrollment_share_over_10min_3mph"]),
            "is_co_enrollment_measure": False,
            "weekday_recurrences_are_collapsed": True,
            "evidence": [
                "reports/generated/tables/high_enrollment_transitions.csv",
                "data/processed/meetings.csv",
            ],
        },
        "student_survey": {
            "unit": "one response",
            "respondent_population_as_reported_by_authors": "Stanford students",
            "response_sheet": (
                "https://docs.google.com/spreadsheets/d/"
                "1gF9X8H8e44hamMNEyIAbUJVcV6Bubre1K2IJJMwd5ZI/"
                "edit?gid=1824059912#gid=1824059912"
            ),
            "response_count": int(summary["student_survey_responses"]),
            "linked_google_sheet_responses": int(
                summary["student_survey_linked_sheet_responses"]
            ),
            "prior_retained_responses": int(
                summary["student_survey_prior_retained_responses"]
            ),
            "reported_late": int(summary["student_survey_reported_late"]),
            "reported_close_call": int(summary["student_survey_close_call"]),
            "reported_never_late": int(summary["student_survey_never_late"]),
            "reported_late_or_close_call": int(
                summary["student_survey_late_or_close_call"]
            ),
            "selected_walking": int(summary["student_survey_selected_walking"]),
            "selected_biking": int(summary["student_survey_selected_biking"]),
            "selected_e_scooter": int(summary["student_survey_selected_e_scooter"]),
            "expanded_followup_responses": int(
                summary["student_survey_expanded_followup_responses"]
            ),
            "reported_transition_may_exceed_10min": int(
                summary["student_survey_transition_may_exceed_10min"]
            ),
            "reported_exact_ten_minute_gap": int(
                summary["student_survey_reported_exact_ten_minute_gap"]
            ),
            "reported_concrete_consequence": int(
                summary["student_survey_reported_concrete_consequence"]
            ),
            "reported_missed_class_content": int(
                summary["student_survey_missed_class_content"]
            ),
            "reported_course_choice_effect": int(
                summary["student_survey_course_choice_effect"]
            ),
            "reported_skipped_adjacent_activity": int(
                summary["student_survey_skipped_adjacent_activity"]
            ),
            "multiple_travel_modes_allowed": True,
            "response_versions": {
                "legacy_questionnaire": 4,
                "expanded_questionnaire": int(
                    summary["student_survey_expanded_followup_responses"]
                ),
            },
            "free_text_coding_is_manual": True,
            "identity_course_pairs_and_times_independently_verified": False,
            "is_representative_sample": False,
            "supports_prevalence_estimate": False,
            "evidence": [
                "reporting/student_survey_responses.csv",
                "reports/generated/tables/student_survey_summary.csv",
            ],
        },
        "routing_model": {
            "openstreetmap_elements": int(validation["routing"]["osm_elements"]),
            "components_before_largest_component_filter": int(
                validation["routing"]["walk_graph_components_before_filter"]
            ),
            "nodes_before_largest_component_filter": int(
                validation["routing"]["walk_graph_nodes_before_component_filter"]
            ),
            "undirected_edges_before_largest_component_filter": int(
                validation["routing"]["walk_graph_undirected_edges_before_component_filter"]
            ),
            "retained_largest_component_nodes": int(validation["routing"]["walk_graph_nodes"]),
            "retained_largest_component_undirected_edges": int(
                validation["routing"]["walk_graph_undirected_edges"]
            ),
            "retained_way_segments": int(validation["routing"]["walk_edge_segments"]),
            "facilities_snapped": int(validation["routing"]["facilities_with_usable_snap"]),
            "median_snap_meters": float(validation["routing"]["median_snap_meters"]),
            "maximum_snap_meters": float(validation["routing"]["max_snap_distance_meters"]),
            "ordered_route_matrix_rows": int(validation["routing"]["total_route_pairs"]),
            "evidence": [
                "data/processed/walk_edges.csv",
                "data/processed/facilities.csv",
                "data/processed/route_distances.csv",
                "reports/generated/validation.json",
            ],
        },
        "bicycle_routing_model": {
            "components_before_largest_component_filter": int(
                validation["bicycle_routing"]["bike_graph_weak_components_before_filter"]
            ),
            "retained_largest_component_nodes": int(
                validation["bicycle_routing"]["bike_graph_nodes"]
            ),
            "retained_directed_edges": int(
                validation["bicycle_routing"]["bike_graph_directed_edges"]
            ),
            "retained_way_segments": int(validation["bicycle_routing"]["bike_edge_segments"]),
            "facilities_snapped": int(
                validation["bicycle_routing"]["facilities_with_usable_bike_snap"]
            ),
            "ordered_route_matrix_rows": int(
                validation["bicycle_routing"]["total_bike_route_pairs"]
            ),
            "evidence": [
                "data/processed/bike_edges.csv",
                "data/processed/bike_facilities.csv",
                "data/processed/bike_route_distances.csv",
                "reports/generated/validation.json",
            ],
        },
        "osm_accessibility_tag_coverage": {
            **validation["osm_way_tag_coverage"],
            "evidence": [
                "data/raw/osm/walk_network.json",
                "reports/generated/validation.json",
            ],
            "interpretation": (
                "Sparse tags do not prove a way is inaccessible; they mean this "
                "snapshot cannot support a defensible campus-wide wheelchair model."
            ),
        },
        "reported_route_examples": route_examples,
        "enrollment_availability": {
            "meeting_rows_with_reported_enrollment": int(summary["source_meeting_day_rows"]),
            "eligible_rows_with_reported_enrollment": int(
                summary["eligible_rows_with_reported_enrollment"]
            ),
            "section_rows_with_reported_enrollment": int(
                summary["api_sections_with_reported_enrollment"]
            ),
            "pair_weighting": (
                "Each possible pair receives equal weight because section enrollment "
                "does not reveal co-enrollment between the two sections."
            ),
            "evidence": [
                "data/processed/meetings.csv",
                "data/processed/sections.csv",
            ],
        },
    }
    external_sources = [
        {
            key: source[key]
            for key in (
                "id",
                "url",
                "supports",
                "checked_on",
                "verification_status",
                "source_class",
                "evidence_use",
                "supports_stanford_claim",
            )
        }
        for source in external_context["sources"]
    ]
    return {
        "schema_version": 1,
        "status": "pass",
        "audit_scope": {
            "computed_claims": ("Recomputed from checked-in processed rows and generated tables."),
            "raw_provenance": (
                "The checked-in source manifest was generated by reparsing every active "
                "cached response and validating its URL, retrieval metadata and SHA-256."
            ),
            "route_check": (
                "All 5,625 walking and 5,625 directed bicycle distances were checked "
                "with a separate Dijkstra implementation over their retained edge tables."
            ),
            "external_context": external_context["verification_scope"],
            "independence": (
                "This is an internal publication-consistency audit, not an external replication."
            ),
        },
        "claims": claims,
        "external_context_sources": external_sources,
        "model_boundaries": [
            "Potential meeting pairs are not observed student schedules or trips.",
            "Course-level cases are possible pairings, not evidence that any student enrolled in both sections.",
            "The large-enrollment screen identifies possible combinations of two large meetings, not co-enrollment or student traffic between them.",
            "Component timing uses section-listing meeting-day rows; it does not count unique students or attendance.",
            "Component transition shares use possible LEC/DIS meeting pairs; they do not measure student movement between lectures and sections.",
            "ExploreCourses subject codes are reported as subject areas because a subject does not always represent a formal department.",
            "Cross-listed meeting pairs are attributed to every published subject code, so subject-area pair totals are not additive.",
            "Public scheduling policy does not establish that rooms were assigned to minimize consecutive-class travel distance.",
            "Rows pairing a class number with itself are excluded; one same-room CHEMENG 20 row was affected.",
            "The model cannot estimate the number or share of students who are late.",
            "The 27 survey responses are an illustrative convenience sample and cannot estimate how common lateness is among Stanford students.",
            "Survey identities, course pairs and reported travel times were not independently verified.",
            "The 2, 3 and 4 mph speeds are scenarios, not measured population groups.",
            "The two-minute building allowance is illustrative, not empirical.",
            "The 12- and 15-minute budgets are applied to the same potential Winter 2026 pairs identified around ten-minute schedule gaps; they are not analyses of schedules with different pair sets.",
            "The 15-minute case is a historical comparison with the AY 2021-22 meeting pattern, not a statement of current Stanford policy or an analysis of 2021 course locations.",
            "Facility points are not verified entrances.",
            "Straight-line facility-to-network snap connectors are not path-verified and may cross barriers.",
            "Ways tagged indoor or corridor are excluded, but missing or incorrect OSM tags can remain.",
            "Neither graph is validated for wheelchair routing or accessible building entrances.",
            "A wheelchair time is not reported because accessibility and incline tags are too sparse for a defensible campus-wide route model.",
            "One Campus Map facility can aggregate multiple named rooms; Bishop Auditorium and Lathrop rooms share facility 08-350.",
            "The 25 unresolved room labels are excluded rather than manually assigned guessed coordinates.",
        ],
    }


def audit_publication(*, check_raw: bool = False, write: bool = False) -> dict[str, object]:
    summary = json.loads((REPORT_DIR / "analysis_summary.json").read_text(encoding="utf-8"))
    validation = json.loads((REPORT_DIR / "validation.json").read_text(encoding="utf-8"))
    external_context = _load_external_context_sources()
    recomputed, pairs = _recompute_analysis()

    integer_fields = (
        "source_meeting_day_rows",
        "eligible_physical_meeting_day_rows",
        "mapped_section_listing_day_rows",
        "mapped_physical_meeting_day_rows",
        "cross_listing_rows_collapsed",
        "pair_date_rows_before_same_class_exclusion",
        "candidate_adjacent_meeting_pairs_before_routing",
        "same_class_number_pair_rows_excluded",
        "recurring_pair_rows_collapsed",
        "potential_adjacent_meeting_pairs",
        "eligible_rows_with_reported_enrollment",
        "distinct_passing_period_time_slots",
        "distinct_weekday_time_slots",
        "lecture_component_meeting_day_rows",
        "discussion_component_meeting_day_rows",
        "lecture_discussion_transition_pairs",
        "subject_catalog_entries",
        "subject_areas_with_transition_estimates",
        "large_enrollment_screen_threshold",
        "large_enrollment_unique_different_building_pairs",
        "large_enrollment_pairs_over_10min_3mph",
        "student_survey_responses",
        "student_survey_linked_sheet_responses",
        "student_survey_prior_retained_responses",
        "student_survey_reported_late",
        "student_survey_close_call",
        "student_survey_never_late",
        "student_survey_late_or_close_call",
        "student_survey_selected_walking",
        "student_survey_selected_biking",
        "student_survey_selected_e_scooter",
        "student_survey_expanded_followup_responses",
        "student_survey_transition_may_exceed_10min",
        "student_survey_reported_exact_ten_minute_gap",
        "student_survey_reported_concrete_consequence",
        "student_survey_missed_class_content",
        "student_survey_course_choice_effect",
        "student_survey_skipped_adjacent_activity",
    )
    for field in integer_fields:
        _require(summary[field] == recomputed[field], f"Summary mismatch for {field}")
    for field in (
        "meeting_mapping_rate",
        "pair_routing_coverage",
        "enrollment_reporting_rate",
        "lecture_median_start_minutes",
        "discussion_median_start_minutes",
        "lecture_share_starting_at_or_after_230pm",
        "discussion_share_starting_at_or_after_230pm",
        "lecture_share_on_thursday_or_friday",
        "discussion_share_on_thursday_or_friday",
        "large_enrollment_share_over_10min_3mph",
    ):
        _require(_close(summary[field], recomputed[field]), f"Summary mismatch for {field}")

    expected_survey, _ = _recompute_student_survey()
    published_survey = pd.read_csv(REPORT_DIR / "tables" / "student_survey_summary.csv")
    _assert_frames_equal(
        expected_survey,
        published_survey,
        sort_columns=["metric"],
        numeric_columns=("count", "denominator", "share"),
        message="student_survey_summary.csv does not match the reporting responses",
    )

    published_component_results = {
        (row["origin_component"], row["destination_component"]): row
        for row in summary["component_transition_results"]
    }
    recomputed_component_results = {
        (row["origin_component"], row["destination_component"]): row
        for row in recomputed["component_transition_results"]
    }
    _require(
        published_component_results.keys() == recomputed_component_results.keys(),
        "Component transition categories do not match recomputation",
    )
    for transition, expected in recomputed_component_results.items():
        published = published_component_results[transition]
        for field in ("potential_meeting_pairs", "pairs_over_10min_3mph"):
            _require(
                int(published[field]) == int(expected[field]),
                f"Component transition mismatch for {transition} {field}",
            )
        for field in (
            "share_within_10min_3mph",
            "share_over_10min_3mph",
            "median_route_minutes_3mph",
            "p90_route_minutes_3mph",
        ):
            _require(
                _close(published[field], expected[field]),
                f"Component transition mismatch for {transition} {field}",
            )

    for expected in recomputed["speed_results"]:
        published = next(
            row
            for row in summary["walking_speed_results"]
            if float(row["walking_speed_mph"]) == float(expected["walking_speed_mph"])
        )
        for field in (
            "share_within_10_minutes",
            "share_within_10_minutes_with_2min_overhead",
            "median_route_minutes",
            "p90_route_minutes",
        ):
            _require(
                _close(published[field], expected[field]),
                f"Speed result mismatch for {expected['walking_speed_mph']} mph {field}",
            )

    for expected in recomputed["bicycle_speed_results"]:
        published = next(
            row
            for row in summary["bicycle_speed_results"]
            if float(row["bicycle_speed_mph"]) == float(expected["bicycle_speed_mph"])
        )
        for field in (
            "share_within_10_minutes",
            "share_within_10_minutes_with_2min_handling",
            "median_route_minutes",
            "p90_route_minutes",
        ):
            _require(
                _close(published[field], expected[field]),
                f"Bicycle result mismatch for {expected['bicycle_speed_mph']} mph {field}",
            )

    meetings = pd.read_csv(PROCESSED_DIR / "meetings.csv", parse_dates=["date_start", "date_end"])
    sections = pd.read_csv(PROCESSED_DIR / "sections.csv")
    for frame_name, frame in (("meetings.csv", meetings), ("sections.csv", sections)):
        for field in ("enrolled", "capacity"):
            _require(
                pd.to_numeric(frame[field], errors="coerce").notna().sum() == len(frame),
                f"{frame_name} does not contain API {field} for every row",
            )
        _require(
            _as_bool(frame["api_section_match"]).all(),
            f"{frame_name} contains a row without an XML API class-number match",
        )
    _require(
        summary["eligible_rows_with_reported_enrollment"]
        == summary["eligible_physical_meeting_day_rows"]
        and _close(summary["enrollment_reporting_rate"], 1.0),
        "Enrollment availability in the summary is stale",
    )
    _require((meetings["date_start"] <= meetings["date_end"]).all(), "Invalid date range")
    _require((meetings["start_minutes"] < meetings["end_minutes"]).all(), "Invalid time range")
    weekday_number = meetings["day"].map(
        {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    )
    first_listed_weekday = meetings["date_start"] + pd.to_timedelta(
        (weekday_number - meetings["date_start"].dt.weekday) % 7, unit="D"
    )
    _require(
        first_listed_weekday.le(meetings["date_end"]).all(),
        "Meeting date range does not contain its listed weekday",
    )
    invalid_dates = pd.read_csv(PROCESSED_DIR / "invalid_meeting_dates_excluded.csv")
    invalid_times = pd.read_csv(PROCESSED_DIR / "invalid_meeting_times_excluded.csv")
    _require(
        len(invalid_dates) == validation["explorecourses"]["invalid_term_date_rows_excluded"],
        "Mobile HTML date-discrepancy audit mismatch",
    )
    _require(
        len(invalid_times) == validation["explorecourses"]["invalid_time_rows_excluded"],
        "Mobile HTML time-discrepancy audit mismatch",
    )

    facilities = pd.read_csv(PROCESSED_DIR / "facilities.csv")
    routes = pd.read_csv(PROCESSED_DIR / "route_distances.csv")
    edges = pd.read_csv(PROCESSED_DIR / "walk_edges.csv")
    facility_count = len(facilities)
    _require(facility_count == summary["unique_mapped_facilities"], "Facility count mismatch")
    room_lookup = pd.read_csv(PROCESSED_DIR / "room_lookup.csv")
    facility_08350_rooms = set(
        room_lookup.loc[room_lookup["facility_id"].astype(str).eq("08-350"), "room"].astype(str)
    )
    _require(
        any(room.startswith("Lathrop") for room in facility_08350_rooms)
        and "Bishop Auditorium" in facility_08350_rooms,
        "Facility-level aggregation disclosure for Lathrop/Bishop is stale",
    )
    expected_facility_coordinates = (
        room_lookup[room_lookup["match_status"].isin(USABLE_MATCH_STATUSES)]
        .dropna(subset=["facility_id", "latitude", "longitude"])
        .groupby("facility_id", as_index=False)
        .agg(latitude=("latitude", "median"), longitude=("longitude", "median"))
    )
    coordinate_check = facilities.merge(
        expected_facility_coordinates,
        on="facility_id",
        how="outer",
        suffixes=("_published", "_lookup"),
        validate="one_to_one",
    )
    _require(
        len(coordinate_check) == facility_count
        and np.allclose(coordinate_check["latitude_published"], coordinate_check["latitude_lookup"])
        and np.allclose(
            coordinate_check["longitude_published"], coordinate_check["longitude_lookup"]
        ),
        "Facility coordinates do not reproduce from room_lookup.csv",
    )
    _require(len(routes) == facility_count**2, "Route matrix is incomplete")
    _require(
        not routes.duplicated(["origin_facility_id", "destination_facility_id"]).any(),
        "Duplicate routes",
    )
    _require(_as_bool(routes["connected"]).all(), "Disconnected published route")
    diagonal = routes[routes["origin_facility_id"] == routes["destination_facility_id"]]
    _require((diagonal["route_distance_meters"].abs() < 1e-9).all(), "Nonzero diagonal route")
    matrix = routes.pivot(
        index="origin_facility_id",
        columns="destination_facility_id",
        values="route_distance_meters",
    )
    _require(np.allclose(matrix.to_numpy(), matrix.to_numpy().T), "Route matrix is asymmetric")
    _require(facilities["snap_usable"].astype(bool).all(), "Unusable facility snap published")
    _require(
        _close(
            facilities["snap_distance_meters"].max(),
            validation["routing"]["max_snap_distance_meters"],
        ),
        "Maximum facility snap distance differs from validation.json",
    )
    _require(
        _close(
            facilities["snap_distance_meters"].median(),
            validation["routing"]["median_snap_meters"],
        ),
        "Median facility snap distance differs from validation.json",
    )
    _require(
        (
            facilities["snap_distance_meters"]
            <= float(validation["routing"]["snap_distance_limit_meters"])
        ).all(),
        "Published facility exceeds the configured snap-distance limit",
    )
    _require("corridor" not in set(edges["highway"]), "Indoor corridor retained in route graph")
    graph_nodes = set(edges["from_node"].astype(int)) | set(edges["to_node"].astype(int))
    _require(
        set(facilities["node_id"].astype(int)) <= graph_nodes,
        "Facility snapped outside route graph",
    )
    _require(
        len(edges) == validation["routing"]["walk_edge_segments"],
        "Published edge count differs from validation.json",
    )
    undirected_edges = edges.assign(
        low_node=edges[["from_node", "to_node"]].min(axis=1),
        high_node=edges[["from_node", "to_node"]].max(axis=1),
    )[["low_node", "high_node"]].drop_duplicates()
    _require(
        len(undirected_edges) == validation["routing"]["walk_graph_undirected_edges"],
        "Unique walking-graph edge count differs from validation.json",
    )
    separately_verified_routes = _verify_route_distances(facilities, edges, routes)

    bike_routes = pd.read_csv(PROCESSED_DIR / "bike_route_distances.csv")
    bike_facilities = pd.read_csv(PROCESSED_DIR / "bike_facilities.csv")
    bike_edges = pd.read_csv(PROCESSED_DIR / "bike_edges.csv")
    _require(len(bike_routes) == facility_count**2, "Bicycle route matrix is incomplete")
    _require(
        not bike_routes.duplicated(["origin_facility_id", "destination_facility_id"]).any(),
        "Duplicate bicycle routes",
    )
    _require(_as_bool(bike_routes["connected"]).all(), "Disconnected bicycle route")
    bike_diagonal = bike_routes[
        bike_routes["origin_facility_id"] == bike_routes["destination_facility_id"]
    ]
    _require(
        (bike_diagonal["route_distance_meters"].abs() < 1e-9).all(),
        "Nonzero bicycle-route diagonal",
    )
    _require(
        len(bike_facilities) == facility_count and _as_bool(bike_facilities["snap_usable"]).all(),
        "Bicycle facility snaps are incomplete",
    )
    _require(
        _close(
            bike_facilities["snap_distance_meters"].max(),
            validation["bicycle_routing"]["max_bike_snap_distance_meters"],
        )
        and _close(
            bike_facilities["snap_distance_meters"].median(),
            validation["bicycle_routing"]["median_bike_snap_meters"],
        ),
        "Bicycle facility snap distances differ from validation.json",
    )
    _require(
        len(bike_edges) == validation["bicycle_routing"]["bike_edge_segments"],
        "Bicycle edge count differs from validation.json",
    )
    _require(
        not bike_edges["highway"].isin(["steps", "corridor"]).any(),
        "Steps or corridors remain in the bicycle graph",
    )
    separately_verified_bike_routes = _verify_route_distances(
        bike_facilities,
        bike_edges,
        bike_routes,
        directed=True,
    )

    pair_table = pd.read_csv(REPORT_DIR / "tables" / "building_pair_summary.csv")
    _require(
        int(pair_table["potential_meeting_pairs"].sum()) == len(pairs),
        "Building-pair weights do not sum to the analysis denominator",
    )
    expected_pair_values = (
        pairs.groupby(["origin_facility_id", "destination_facility_id"], as_index=False)
        .agg(
            potential_meeting_pairs=("origin_class_number", "count"),
            route_distance_meters=("route_distance_meters", "first"),
            bike_route_distance_meters=("bike_route_distance_meters", "first"),
            distinct_origin_meetings=("origin_class_number", "nunique"),
            distinct_destination_meetings=("destination_class_number", "nunique"),
        )
        .sort_values(["origin_facility_id", "destination_facility_id"])
        .reset_index(drop=True)
    )
    comparison_columns = list(expected_pair_values.columns)
    published_pair_values = (
        pair_table[comparison_columns]
        .sort_values(["origin_facility_id", "destination_facility_id"])
        .reset_index(drop=True)
    )
    try:
        pd.testing.assert_frame_equal(
            expected_pair_values,
            published_pair_values,
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError(
            "building_pair_summary.csv does not match separately rebuilt pairs"
        ) from exc

    for speed in WALKING_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        expected_minutes = pair_table["route_distance_meters"] / (speed * 1609.344 / 60)
        _require(
            np.allclose(pair_table[f"walk_minutes_{suffix}mph"], expected_minutes)
            and (
                _as_bool(pair_table[f"within_10min_{suffix}mph"]) == (expected_minutes <= 10)
            ).all()
            and (
                _as_bool(pair_table[f"within_10min_{suffix}mph_with_2min_overhead"])
                == (expected_minutes <= 8)
            ).all(),
            f"Building-pair scenario columns are stale at {speed} mph",
        )

    for speed in BICYCLE_SPEEDS_MPH:
        suffix = str(speed).replace(".", "_")
        expected_minutes = pair_table["bike_route_distance_meters"] / (speed * 1609.344 / 60)
        _require(
            np.allclose(pair_table[f"bike_minutes_{suffix}mph"], expected_minutes)
            and (
                _as_bool(pair_table[f"bike_within_10min_{suffix}mph"]) == (expected_minutes <= 10)
            ).all()
            and (
                _as_bool(pair_table[f"bike_within_10min_{suffix}mph_with_2min_overhead"])
                == (expected_minutes <= 8)
            ).all(),
            f"Building-pair bicycle scenario columns are stale at {speed} mph",
        )

    case_table = pd.read_csv(REPORT_DIR / "tables" / "course_transition_cases.csv")
    expected_case_types = (
        "Near the median",
        "Near the limit",
        "Above the limit",
        "Longest modeled example",
    )
    _require(
        tuple(case_table["case_type"]) == expected_case_types,
        "Course-transition case categories are incomplete or out of order",
    )
    case_candidates = pairs[pairs["origin_facility_id"] != pairs["destination_facility_id"]].copy()
    case_candidates["walk_minutes_3_0mph"] = case_candidates["route_distance_meters"] / (
        3 * 1609.344 / 60
    )

    def nearest_case(pool: pd.DataFrame, target: float) -> pd.Series:
        return (
            pool.assign(target_delta=(pool["walk_minutes_3_0mph"] - target).abs())
            .sort_values(
                [
                    "target_delta",
                    "day",
                    "origin_end_minutes",
                    "origin_class_number",
                    "destination_class_number",
                ]
            )
            .iloc[0]
        )

    median_case_minutes = float(pairs["route_distance_meters"].median()) / (3 * 1609.344 / 60)
    expected_cases = pd.DataFrame(
        [
            nearest_case(
                case_candidates[case_candidates["walk_minutes_3_0mph"] <= 8],
                median_case_minutes,
            ),
            nearest_case(
                case_candidates[case_candidates["walk_minutes_3_0mph"].between(9, 10)],
                9.5,
            ),
            nearest_case(
                case_candidates[case_candidates["walk_minutes_3_0mph"].between(11.5, 12.5)],
                12,
            ),
            nearest_case(
                case_candidates,
                float(case_candidates["walk_minutes_3_0mph"].max()),
            ),
        ]
    )
    case_keys = [
        "term",
        "day",
        "origin_end_minutes",
        "next_start_minutes",
        "origin_class_number",
        "origin_facility_id",
        "destination_class_number",
        "destination_facility_id",
    ]
    try:
        pd.testing.assert_frame_equal(
            expected_cases[case_keys].reset_index(drop=True),
            case_table[case_keys].reset_index(drop=True),
            check_dtype=False,
        )
    except AssertionError as exc:
        raise AuditError(
            "course_transition_cases.csv does not match independently selected pairs"
        ) from exc
    expected_walk_minutes = case_table["route_distance_meters"] / (3 * 1609.344 / 60)
    expected_bike_minutes = case_table["bike_route_distance_meters"] / (8 * 1609.344 / 60)
    _require(
        (case_table["next_start_minutes"] - case_table["origin_end_minutes"]).eq(10).all()
        and np.allclose(case_table["walk_minutes_3_0mph"], expected_walk_minutes)
        and np.allclose(case_table["bike_minutes_8_0mph"], expected_bike_minutes)
        and (_as_bool(case_table["within_10min_3mph"]) == (expected_walk_minutes <= 10)).all()
        and np.allclose(case_table["margin_minutes_3mph"], 10 - expected_walk_minutes),
        "Course-transition case calculations are stale",
    )
    label_pairs = pair_table[
        [
            "origin_facility_id",
            "origin_label",
            "destination_facility_id",
            "destination_label",
        ]
    ].drop_duplicates()
    case_labels = case_table.merge(
        label_pairs,
        on=["origin_facility_id", "destination_facility_id"],
        how="left",
        suffixes=("_published", "_expected"),
        validate="many_to_one",
    )
    _require(
        case_labels["origin_label_published"].eq(case_labels["origin_label_expected"]).all()
        and case_labels["destination_label_published"]
        .eq(case_labels["destination_label_expected"])
        .all(),
        "Course-transition case facility labels are stale",
    )

    speed_table = pd.read_csv(REPORT_DIR / "tables" / "speed_summary.csv")
    expected_speed_table = pd.DataFrame(recomputed["speed_results"])
    try:
        pd.testing.assert_frame_equal(
            expected_speed_table,
            speed_table,
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError("speed_summary.csv does not match recomputed scenarios") from exc
    bicycle_speed_table = pd.read_csv(REPORT_DIR / "tables" / "bicycle_speed_summary.csv")
    expected_bicycle_speed_table = pd.DataFrame(recomputed["bicycle_speed_results"])
    try:
        pd.testing.assert_frame_equal(
            expected_bicycle_speed_table,
            bicycle_speed_table,
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError("bicycle_speed_summary.csv does not match recomputed scenarios") from exc

    pair_slot_values = pairs.copy()
    pair_slot_values["walk_minutes_3mph"] = pair_slot_values["route_distance_meters"] / (
        3 * 1609.344 / 60
    )
    pair_slot_values["bike_minutes_8mph"] = pair_slot_values["bike_route_distance_meters"] / (
        8 * 1609.344 / 60
    )
    pair_slot_values["walk_within_10"] = pair_slot_values["walk_minutes_3mph"] <= 10
    pair_slot_values["bike_within_10"] = _as_bool(pair_slot_values["bike_connected"]) & (
        pair_slot_values["bike_minutes_8mph"] <= 10
    )

    def recompute_slots(group_columns: list[str]) -> pd.DataFrame:
        return (
            pair_slot_values.groupby(group_columns, as_index=False)
            .agg(
                potential_meeting_pairs=("origin_class_number", "count"),
                walk_share_within_10min_3mph=("walk_within_10", "mean"),
                walk_median_minutes_3mph=("walk_minutes_3mph", "median"),
                walk_p90_minutes_3mph=(
                    "walk_minutes_3mph",
                    lambda values: values.quantile(0.9),
                ),
                bike_share_within_10min_8mph=("bike_within_10", "mean"),
                bike_median_minutes_8mph=("bike_minutes_8mph", "median"),
            )
            .sort_values(group_columns)
            .reset_index(drop=True)
        )

    slot_columns = [
        "origin_end_minutes",
        "next_start_minutes",
        "potential_meeting_pairs",
        "walk_share_within_10min_3mph",
        "walk_median_minutes_3mph",
        "walk_p90_minutes_3mph",
        "bike_share_within_10min_8mph",
        "bike_median_minutes_8mph",
    ]
    expected_slots = recompute_slots(slot_columns[:2])
    published_slots = pd.read_csv(REPORT_DIR / "tables" / "time_slot_summary.csv")
    _require(
        len(published_slots) == summary["distinct_passing_period_time_slots"]
        and int(published_slots["potential_meeting_pairs"].sum()) == len(pairs)
        and (published_slots["next_start_minutes"] - published_slots["origin_end_minutes"])
        .eq(10)
        .all(),
        "Published passing-period slots are incomplete",
    )
    try:
        pd.testing.assert_frame_equal(
            expected_slots[slot_columns],
            published_slots[slot_columns].sort_values(slot_columns[:2]).reset_index(drop=True),
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError("time_slot_summary.csv does not match recomputed pairs") from exc

    weekday_slot_columns = ["day", *slot_columns]
    expected_weekday_slots = recompute_slots(weekday_slot_columns[:3])
    published_weekday_slots = pd.read_csv(REPORT_DIR / "tables" / "weekday_time_slot_summary.csv")
    _require(
        len(published_weekday_slots) == summary["distinct_weekday_time_slots"]
        and int(published_weekday_slots["potential_meeting_pairs"].sum()) == len(pairs),
        "Published weekday passing-period slots are incomplete",
    )
    try:
        pd.testing.assert_frame_equal(
            expected_weekday_slots[weekday_slot_columns],
            published_weekday_slots[weekday_slot_columns]
            .sort_values(weekday_slot_columns[:3])
            .reset_index(drop=True),
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError("weekday_time_slot_summary.csv does not match recomputed pairs") from exc

    schedule_rows = meetings.merge(
        room_lookup[["room", "match_status", "facility_id", "latitude", "longitude"]],
        on="room",
        how="left",
    )
    schedule_rows = schedule_rows[
        (~_as_bool(schedule_rows["cancelled"]))
        & schedule_rows["modality"].eq("In Person")
        & schedule_rows["day"].isin(["Mon", "Tue", "Wed", "Thu", "Fri"])
        & schedule_rows["room"].fillna("").astype(str).map(is_queryable_room)
    ].copy()
    schedule_rows["enrolled"] = pd.to_numeric(schedule_rows["enrolled"], errors="coerce")

    component_rows = schedule_rows[schedule_rows["component"].isin(["LEC", "DIS"])].copy()
    component_rows["time_bin"] = pd.cut(
        component_rows["start_minutes"],
        bins=[-math.inf, 630, 720, 870, 990, math.inf],
        labels=[
            "Before 10:30 a.m.",
            "10:30-11:59 a.m.",
            "Noon-2:29 p.m.",
            "2:30-4:29 p.m.",
            "4:30 p.m. or later",
        ],
        right=False,
    )
    component_rows["day"] = pd.Categorical(
        component_rows["day"],
        categories=["Mon", "Tue", "Wed", "Thu", "Fri"],
        ordered=True,
    )

    def recompute_component_table(group_column: str) -> pd.DataFrame:
        frame = (
            component_rows.groupby(["component", group_column], observed=False)
            .agg(
                section_listing_meeting_day_rows=("class_number", "size"),
                distinct_class_sections=("class_number", "nunique"),
                reported_enrollment_seat_instances=(
                    "enrolled",
                    lambda values: values.sum(min_count=1),
                ),
            )
            .reset_index()
        )
        totals = frame.groupby("component")["section_listing_meeting_day_rows"].transform("sum")
        frame["share_of_component_rows"] = frame["section_listing_meeting_day_rows"] / totals
        frame[group_column] = frame[group_column].astype(str)
        return frame

    component_value_columns = [
        "component",
        "section_listing_meeting_day_rows",
        "distinct_class_sections",
        "reported_enrollment_seat_instances",
        "share_of_component_rows",
    ]
    expected_component_times = recompute_component_table("time_bin")
    published_component_times = pd.read_csv(REPORT_DIR / "tables" / "component_time_summary.csv")
    _assert_frames_equal(
        expected_component_times[["time_bin", *component_value_columns]],
        published_component_times[["time_bin", *component_value_columns]],
        sort_columns=["component", "time_bin"],
        numeric_columns=(
            "section_listing_meeting_day_rows",
            "distinct_class_sections",
            "reported_enrollment_seat_instances",
            "share_of_component_rows",
        ),
        message="component_time_summary.csv does not match eligible schedule rows",
    )
    expected_component_days = recompute_component_table("day")
    published_component_days = pd.read_csv(REPORT_DIR / "tables" / "component_day_summary.csv")
    _assert_frames_equal(
        expected_component_days[["day", *component_value_columns]],
        published_component_days[["day", *component_value_columns]],
        sort_columns=["component", "day"],
        numeric_columns=(
            "section_listing_meeting_day_rows",
            "distinct_class_sections",
            "reported_enrollment_seat_instances",
            "share_of_component_rows",
        ),
        message="component_day_summary.csv does not match eligible schedule rows",
    )

    component_pair_rows = pairs[
        pairs["origin_component"].isin(["LEC", "DIS"])
        & pairs["destination_component"].isin(["LEC", "DIS"])
    ].copy()
    component_pair_rows["over_10min_3mph"] = component_pair_rows["walk_minutes_3_0mph"].gt(10)
    component_pair_rows["within_10min_3mph"] = ~component_pair_rows["over_10min_3mph"]
    component_pair_rows["building_pair"] = (
        component_pair_rows["origin_facility_id"].astype(str)
        + " -> "
        + component_pair_rows["destination_facility_id"].astype(str)
    )
    expected_component_transitions = component_pair_rows.groupby(
        ["origin_component", "destination_component"], as_index=False
    ).agg(
        potential_meeting_pairs=("origin_class_number", "size"),
        pairs_within_10min_3mph=("within_10min_3mph", "sum"),
        pairs_over_10min_3mph=("over_10min_3mph", "sum"),
        distinct_building_pairs=("building_pair", "nunique"),
        median_route_minutes_3mph=("walk_minutes_3_0mph", "median"),
        p90_route_minutes_3mph=(
            "walk_minutes_3_0mph",
            lambda values: values.quantile(0.9),
        ),
    )
    expected_component_transitions["share_within_10min_3mph"] = (
        expected_component_transitions["pairs_within_10min_3mph"]
        / expected_component_transitions["potential_meeting_pairs"]
    )
    expected_component_transitions["share_over_10min_3mph"] = (
        expected_component_transitions["pairs_over_10min_3mph"]
        / expected_component_transitions["potential_meeting_pairs"]
    )
    component_transition_columns = [
        "origin_component",
        "destination_component",
        "potential_meeting_pairs",
        "pairs_within_10min_3mph",
        "pairs_over_10min_3mph",
        "distinct_building_pairs",
        "median_route_minutes_3mph",
        "p90_route_minutes_3mph",
        "share_within_10min_3mph",
        "share_over_10min_3mph",
    ]
    published_component_transitions = pd.read_csv(
        REPORT_DIR / "tables" / "component_transition_summary.csv"
    )
    _assert_frames_equal(
        expected_component_transitions[component_transition_columns],
        published_component_transitions[component_transition_columns],
        sort_columns=["origin_component", "destination_component"],
        numeric_columns=tuple(component_transition_columns[2:]),
        message=("component_transition_summary.csv does not match recomputed pairs"),
    )

    mapped_schedule_rows = schedule_rows[
        schedule_rows["match_status"].isin(USABLE_MATCH_STATUSES)
        & schedule_rows["facility_id"].notna()
    ].copy()
    subject_catalog = pd.read_csv(PROCESSED_DIR / "subject_catalog.csv")
    expected_department_locations = (
        mapped_schedule_rows.groupby(["subject_query", "facility_id"], as_index=False)
        .agg(
            section_listing_meeting_day_rows=("class_number", "size"),
            distinct_class_sections_at_facility=("class_number", "nunique"),
            reported_enrollment_seat_instances=(
                "enrolled",
                lambda values: values.sum(min_count=1),
            ),
        )
        .rename(columns={"subject_query": "subject_code"})
        .merge(subject_catalog, on="subject_code", how="left", validate="many_to_one")
    )
    department_totals = (
        mapped_schedule_rows.groupby("subject_query", as_index=False)
        .agg(
            total_mapped_meeting_day_rows=("class_number", "size"),
            total_distinct_class_sections=("class_number", "nunique"),
            total_reported_enrollment_seat_instances=(
                "enrolled",
                lambda values: values.sum(min_count=1),
            ),
        )
        .rename(columns={"subject_query": "subject_code"})
    )
    expected_department_locations = expected_department_locations.merge(
        department_totals, on="subject_code", how="left", validate="many_to_one"
    )
    expected_department_locations["share_of_subject_mapped_rows"] = (
        expected_department_locations["section_listing_meeting_day_rows"]
        / expected_department_locations["total_mapped_meeting_day_rows"]
    )
    published_department_locations = pd.read_csv(
        REPORT_DIR / "tables" / "department_location_summary.csv"
    )
    department_columns = [
        "subject_code",
        "subject_name",
        "facility_id",
        "section_listing_meeting_day_rows",
        "distinct_class_sections_at_facility",
        "reported_enrollment_seat_instances",
        "total_mapped_meeting_day_rows",
        "total_distinct_class_sections",
        "total_reported_enrollment_seat_instances",
        "share_of_subject_mapped_rows",
    ]
    _assert_frames_equal(
        expected_department_locations[department_columns],
        published_department_locations[department_columns],
        sort_columns=["subject_code", "facility_id"],
        numeric_columns=tuple(department_columns[3:]),
        message=("department_location_summary.csv does not match mapped subject rows"),
    )
    _require(
        int(published_department_locations["section_listing_meeting_day_rows"].sum())
        == len(mapped_schedule_rows),
        "Department-location rows do not sum to the mapped listing denominator",
    )
    top_location_counts = published_department_locations.groupby("subject_code")[
        "section_listing_meeting_day_rows"
    ].transform("max")
    _require(
        published_department_locations.loc[
            published_department_locations["facility_rank_within_subject"].eq(1),
            "section_listing_meeting_day_rows",
        ]
        .eq(
            top_location_counts[
                published_department_locations["facility_rank_within_subject"].eq(1)
            ]
        )
        .all(),
        "A subject-area top facility is not actually its most-used facility",
    )

    def recompute_subject_direction(direction: str) -> pd.DataFrame:
        prefix = "outgoing" if direction == "origin" else "incoming"
        subject_column = f"{direction}_subject_codes"
        rows = pairs[[subject_column, "walk_minutes_3_0mph"]].copy()
        rows["subject_code"] = rows[subject_column].fillna("").astype(str).str.split(" / ")
        rows = rows.explode("subject_code")
        rows["subject_code"] = rows["subject_code"].str.strip()
        rows = rows[rows["subject_code"].ne("")].copy()
        rows["within_10min_3mph"] = rows["walk_minutes_3_0mph"].le(10)
        rows["over_10min_3mph"] = ~rows["within_10min_3mph"]
        result = rows.groupby("subject_code", as_index=False).agg(
            **{
                f"potential_{prefix}_pairs": ("subject_code", "size"),
                f"{prefix}_pairs_within_10min_3mph": (
                    "within_10min_3mph",
                    "sum",
                ),
                f"{prefix}_pairs_over_10min_3mph": (
                    "over_10min_3mph",
                    "sum",
                ),
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
        result[f"{prefix}_share_within_10min_3mph"] = (
            result[f"{prefix}_pairs_within_10min_3mph"] / result[f"potential_{prefix}_pairs"]
        )
        result[f"{prefix}_share_over_10min_3mph"] = (
            result[f"{prefix}_pairs_over_10min_3mph"] / result[f"potential_{prefix}_pairs"]
        )
        return result

    expected_subject_feasibility = recompute_subject_direction("origin").merge(
        recompute_subject_direction("destination"),
        on="subject_code",
        how="outer",
    )
    top_subject_facilities = published_department_locations[
        published_department_locations["facility_rank_within_subject"].eq(1)
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
    expected_subject_feasibility = expected_subject_feasibility.merge(
        top_subject_facilities,
        on="subject_code",
        how="left",
        validate="one_to_one",
    ).merge(
        subject_catalog[["subject_code", "subject_name"]],
        on="subject_code",
        how="left",
        validate="one_to_one",
    )
    expected_subject_feasibility["subject_name"] = expected_subject_feasibility[
        "subject_name"
    ].fillna(expected_subject_feasibility["subject_code"])
    subject_count_columns = [
        column
        for column in expected_subject_feasibility.columns
        if column.startswith("potential_") or "pairs_within" in column or "pairs_over" in column
    ]
    expected_subject_feasibility[subject_count_columns] = (
        expected_subject_feasibility[subject_count_columns].fillna(0).astype(int)
    )
    published_subject_feasibility = pd.read_csv(
        REPORT_DIR / "tables" / "subject_transition_feasibility.csv"
    )
    subject_feasibility_columns = list(expected_subject_feasibility.columns)
    subject_numeric_columns = tuple(
        column
        for column in subject_feasibility_columns
        if column not in {"subject_code", "subject_name", "top_facility_label"}
    )
    _assert_frames_equal(
        expected_subject_feasibility[subject_feasibility_columns],
        published_subject_feasibility[subject_feasibility_columns],
        sort_columns=["subject_code"],
        numeric_columns=subject_numeric_columns,
        message=("subject_transition_feasibility.csv does not match recomputed pairs"),
    )
    _require(
        len(published_subject_feasibility) == summary["subject_areas_with_transition_estimates"],
        "Subject-area transition count does not match the summary",
    )

    large_threshold = int(summary["large_enrollment_screen_threshold"])
    large_candidates = pairs[
        pairs["origin_facility_id"].ne(pairs["destination_facility_id"])
        & pairs["origin_enrolled"].ge(large_threshold)
        & pairs["destination_enrolled"].ge(large_threshold)
    ].copy()
    large_key = [
        "term",
        "origin_course_number",
        "origin_component",
        "origin_facility_id",
        "origin_end_minutes",
        "origin_enrolled",
        "destination_course_number",
        "destination_component",
        "destination_facility_id",
        "next_start_minutes",
        "destination_enrolled",
        "route_distance_meters",
        "walk_minutes_3_0mph",
    ]
    weekday_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    expected_large_pairs = large_candidates.groupby(large_key, as_index=False, dropna=False).agg(
        days=(
            "day",
            lambda values: " / ".join(sorted(set(values.astype(str)), key=weekday_order.get)),
        ),
        weekday_count=("day", "nunique"),
    )
    expected_large_pairs["smaller_reported_enrollment"] = expected_large_pairs[
        ["origin_enrolled", "destination_enrolled"]
    ].min(axis=1)
    expected_large_pairs["within_10min_3mph"] = expected_large_pairs["walk_minutes_3_0mph"].le(10)
    expected_large_pairs = expected_large_pairs.sort_values(
        [
            "smaller_reported_enrollment",
            "walk_minutes_3_0mph",
            "origin_course_number",
            "destination_course_number",
        ],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)
    expected_large_pairs["enrollment_rank"] = expected_large_pairs.index + 1
    published_large_pairs = pd.read_csv(REPORT_DIR / "tables" / "high_enrollment_transitions.csv")
    large_columns = [
        *large_key,
        "days",
        "weekday_count",
        "smaller_reported_enrollment",
        "within_10min_3mph",
        "enrollment_rank",
    ]
    _assert_frames_equal(
        expected_large_pairs[large_columns],
        published_large_pairs[large_columns],
        sort_columns=["enrollment_rank"],
        numeric_columns=(
            "origin_end_minutes",
            "origin_enrolled",
            "next_start_minutes",
            "destination_enrolled",
            "route_distance_meters",
            "walk_minutes_3_0mph",
            "weekday_count",
            "smaller_reported_enrollment",
            "enrollment_rank",
        ),
        bool_columns=("within_10min_3mph",),
        message=("high_enrollment_transitions.csv does not match recomputed large pairs"),
    )
    _require(
        len(published_large_pairs) == summary["large_enrollment_unique_different_building_pairs"]
        and int((~_as_bool(published_large_pairs["within_10min_3mph"])).sum())
        == summary["large_enrollment_pairs_over_10min_3mph"],
        "Large-enrollment headline values do not match the published table",
    )

    distribution = pd.read_csv(REPORT_DIR / "tables" / "route_time_distribution.csv")
    _require(_close(distribution.iloc[-1]["cumulative_share"], 1.0), "CDF does not end at one")
    share_at_ten = distribution.loc[
        distribution["route_minutes_3mph"] <= 10, "cumulative_share"
    ].max()
    _require(
        _close(share_at_ten, summary["three_mph_share_within_10_minutes"]),
        "CDF and headline share disagree",
    )

    payload = json.loads(
        (REPORT_DIR / "interactive" / "route_explorer.json").read_text(encoding="utf-8")
    )
    _require(
        payload["metadata"]["facility_count"] == facility_count, "Interactive facility mismatch"
    )
    _require(
        payload["metadata"]["potential_adjacent_meeting_pairs"] == len(pairs),
        "Interactive denominator mismatch",
    )
    _require(
        payload["metadata"]["route_count"]["walking_undirected"]
        == facility_count * (facility_count + 1) // 2
        and payload["metadata"]["route_count"]["bicycle_directed"] == facility_count**2,
        "Interactive walking or bicycle route set is incomplete",
    )
    facility_coordinates = {
        str(row.facility_id): (round(float(row.longitude), 6), round(float(row.latitude), 6))
        for row in facilities.itertuples(index=False)
    }
    route_matrix = routes.set_index(["origin_facility_id", "destination_facility_id"])
    bike_route_matrix = bike_routes.set_index(["origin_facility_id", "destination_facility_id"])
    for mode, matrix_name in (("walk", route_matrix), ("bike", bike_route_matrix)):
        for key, route in payload["routes"][mode].items():
            left, right = key.split("|")
            expected_distance = float(matrix_name.loc[(left, right), "route_distance_meters"])
            _require(
                _close(route["distance_meters"], round(expected_distance, 1)),
                f"Interactive {mode} distance mismatch for {key}",
            )
            _require(
                tuple(route["path"][0]) == facility_coordinates[left]
                and tuple(route["path"][-1]) == facility_coordinates[right],
                f"Interactive {mode} path endpoints mismatch for {key}",
            )

    published_scenarios = pd.read_csv(REPORT_DIR / "tables" / "passing_period_scenarios.csv")
    payload_scenarios = pd.DataFrame(payload["scenarios"])
    scenario_columns = [
        "passing_period_minutes",
        "walking_speed_mph",
        "building_overhead_minutes",
        "available_route_minutes",
        "feasible_pairs",
        "total_pairs",
        "share_feasible",
    ]
    try:
        pd.testing.assert_frame_equal(
            published_scenarios[scenario_columns]
            .sort_values(scenario_columns[:3])
            .reset_index(drop=True),
            payload_scenarios[scenario_columns]
            .sort_values(scenario_columns[:3])
            .reset_index(drop=True),
            check_dtype=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as exc:
        raise AuditError(
            "passing_period_scenarios.csv does not match the interactive payload"
        ) from exc

    for scenario in payload["scenarios"]:
        speed = float(scenario["walking_speed_mph"])
        available = float(scenario["available_route_minutes"])
        minutes = pair_table["route_distance_meters"] / (speed * 1609.344 / 60)
        expected_feasible = int(
            pair_table.loc[minutes <= available, "potential_meeting_pairs"].sum()
        )
        _require(
            int(scenario["total_pairs"]) == len(pairs)
            and int(scenario["feasible_pairs"]) == expected_feasible
            and _close(scenario["share_feasible"], expected_feasible / len(pairs)),
            "Interactive policy scenario differs from published pair weights",
        )

    source_manifest: dict[str, object]
    if check_raw:
        source_manifest = build_source_manifest()
        if write:
            SOURCE_MANIFEST_PATH.write_text(
                json.dumps(source_manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
    else:
        _require(SOURCE_MANIFEST_PATH.exists(), "Checked-in source manifest is missing")
        source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    _require(
        source_manifest["source_file_counts"]["Stanford ExploreCourses HTML"] == 580,
        "ExploreCourses HTML manifest count mismatch",
    )
    _require(
        source_manifest["source_file_counts"]["Stanford ExploreCourses XML API"] == 253,
        "ExploreCourses XML manifest count mismatch",
    )
    _require(
        source_manifest["source_file_counts"]["OpenStreetMap via Overpass"] == 1,
        "OSM manifest count mismatch",
    )
    _require(source_manifest.get("schema_version") == 3, "Source manifest schema is stale")
    _require(
        source_manifest.get("raw_source_verification") == "complete",
        "Source manifest does not document a complete raw-source audit",
    )
    _require(
        str(
            source_manifest.get("source_data_timestamps", {}).get("openstreetmap_base_utc", "")
        ).endswith("Z"),
        "Source manifest is missing the OSM database timestamp",
    )
    _require(
        source_manifest["file_count"]
        == sum(int(value) for value in source_manifest["source_file_counts"].values()),
        "Source manifest total does not match its source counts",
    )

    publication_files_checked = _check_publication_files(
        summary, validation, source_manifest, external_context
    )
    claim_audit = _build_claim_audit(
        summary,
        validation,
        source_manifest,
        external_context,
        pair_table,
    )
    if write:
        CLAIM_AUDIT_PATH.write_text(
            json.dumps(claim_audit, indent=2, sort_keys=True), encoding="utf-8"
        )
    else:
        _require(CLAIM_AUDIT_PATH.exists(), "Checked-in claim audit is missing")
        checked_in_claims = json.loads(CLAIM_AUDIT_PATH.read_text(encoding="utf-8"))
        _require(checked_in_claims == claim_audit, "Checked-in claim audit is stale")

    key_results = {
        "eligible_physical_meeting_day_rows": summary["eligible_physical_meeting_day_rows"],
        "mapped_section_listing_day_rows": summary["mapped_section_listing_day_rows"],
        "mapped_physical_meeting_day_rows": summary["mapped_physical_meeting_day_rows"],
        "potential_adjacent_meeting_pairs": summary["potential_adjacent_meeting_pairs"],
        "three_mph_share_within_10_minutes": summary["three_mph_share_within_10_minutes"],
        "three_mph_median_route_minutes": summary["three_mph_median_route_minutes"],
        "three_mph_p90_route_minutes": summary["three_mph_p90_route_minutes"],
    }
    external_source_class_counts = dict(
        sorted(
            Counter(str(source["source_class"]) for source in external_context["sources"]).items()
        )
    )
    report = {
        "schema_version": 2,
        "status": "pass",
        "raw_sources_verified": check_raw,
        "audit_scope": ("Internal publication-consistency audit; not an external replication."),
        "checks": {
            "active_source_files": source_manifest["file_count"],
            "explorecourses_subject_codes": validation["explorecourses"]["subjects_discovered"],
            "explorecourses_schedule_responses": validation["explorecourses"][
                "pages_fetched_or_cached"
            ],
            "raw_schedule_rows_reparsed": source_manifest["validated_schedule_rows_reparsed"],
            "raw_section_rows_reparsed": source_manifest["validated_section_rows_reparsed"],
            "raw_walking_segments_reparsed": source_manifest["walking_segments_reparsed"],
            "raw_bicycle_segments_reparsed": source_manifest["bicycle_segments_reparsed"],
            "validated_meeting_rows": len(meetings),
            "route_matrix_rows": len(routes),
            "route_distances_separately_verified": separately_verified_routes,
            "bicycle_route_distances_separately_verified": (separately_verified_bike_routes),
            "walking_network_graph_edges": validation["routing"]["walk_graph_undirected_edges"],
            "walking_network_graph_nodes": validation["routing"]["walk_graph_nodes"],
            "walking_network_components_before_filter": validation["routing"][
                "walk_graph_components_before_filter"
            ],
            "retained_osm_way_segments": len(edges),
            "mapped_facilities": facility_count,
            "room_labels_queried": validation["room_lookup"]["rooms_queried"],
            "unresolved_room_labels": validation["room_lookup"]["status_counts"]["no_result"],
            "pair_date_rows_before_same_class_exclusion": summary[
                "pair_date_rows_before_same_class_exclusion"
            ],
            "same_class_number_pair_rows_excluded": summary["same_class_number_pair_rows_excluded"],
            "potential_pair_rows_recomputed": len(pairs),
            "publication_files_checked": publication_files_checked,
            "external_context_sources_checked": len(external_context["sources"]),
            "external_source_class_counts": external_source_class_counts,
            "meeting_rows_with_enrollment_values": int(
                pd.to_numeric(meetings["enrolled"], errors="coerce").notna().sum()
            ),
            "section_rows_with_enrollment_values": int(
                pd.to_numeric(sections["enrolled"], errors="coerce").notna().sum()
            ),
            "actual_passing_period_time_slots": summary["distinct_passing_period_time_slots"],
            "weekday_passing_period_time_slots": summary["distinct_weekday_time_slots"],
            "component_schedule_rows_checked": (
                summary["lecture_component_meeting_day_rows"]
                + summary["discussion_component_meeting_day_rows"]
            ),
            "component_transition_pairs_checked": len(component_pair_rows),
            "subject_area_location_rows_checked": len(published_department_locations),
            "subject_area_transition_rows_checked": len(published_subject_feasibility),
            "large_enrollment_combinations_checked": len(published_large_pairs),
            "student_survey_responses_checked": int(summary["student_survey_responses"]),
            "course_transition_cases_checked": len(case_table),
            "passing_period_scenarios_checked": len(payload["scenarios"]),
        },
        "key_results": key_results,
    }
    if write:
        PUBLICATION_AUDIT_PATH.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    elif PUBLICATION_AUDIT_PATH.exists():
        checked_in = json.loads(PUBLICATION_AUDIT_PATH.read_text(encoding="utf-8"))
        _require(checked_in.get("status") == "pass", "Checked-in publication audit failed")
        _require(checked_in.get("key_results") == key_results, "Publication audit is stale")
    return report
