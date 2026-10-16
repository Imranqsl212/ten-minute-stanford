from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from .config import CAMPUS_BBOX, CAMPUS_MAP_BASE, PROCESSED_DIR, RAW_DIR
from .fetch import CachedFetcher, FetchError

CLICK_RE = re.compile(
    r"bldg_clicked\(\s*'(?P<facility>[^']+)'\s*,\s*"
    r"(?P<lat>-?\d+(?:\.\d+)?)\s*,\s*"
    r"(?P<lon>-?\d+(?:\.\d+)?)\s*,\s*"
    r"\d+\s*,\s*'(?P<address>[^']*)'\s*\)"
)

USABLE_MATCH_STATUSES = {"exact", "single_result", "fallback"}

ROOM_PREFIX_ALIASES = {
    "agassiz": "Agassiz Building Hopkins Marine Station",
    "anko": "Anko Building",
    "aoerc": "AOERC",
    "barnum": "Barnum Center",
    "braun": "Braun Music Center",
    "ccsr": "Center for Clinical Sciences Research",
    "coda": "Computing and Data Science",
    "dink": "Dinkelspiel Auditorium",
    "edwrds": "Edwards Building",
    "econ": "Landau Building",
    "e.d. stone edwards": "Edwards Building",
    "gates": "Gates Computer Science",
    "green earth sciences": "Green Earth Sciences",
    "gsb botha-chan": "Botha-Chan",
    "gsb class of 1968": "Class of 1968 Building",
    "gsb faculty east": "Faculty Office Building",
    "gsb gunn": "635 Knight Way",
    "gsb mcclelland": "McClelland Building",
    "gsb patterson": "Patterson Building",
    "gsb zambrano": "Zambrano Hall",
    "hewlett teaching center": "Hewlett Teaching Center",
    "huang engineering center": "Huang Engineering Center",
    "lathrop": "Lathrop Library",
    "law": "559 Nathan Abbott Way",
    "li ka shing center": "Li Ka Shing Center",
    "littlefield": "Littlefield Center",
    "mcmurtry art building": "McMurtry Building",
    "memaud": "Memorial Auditorium",
    "mitchell earth sciences": "Mitchell Earth Sciences",
    "packrd": "Packard Electrical Engineering",
    "raikes": "Raikes Building",
    "roble gymnasium": "Roble Gymnasium",
    "shriram": "Shriram Center",
    "skilling": "Skilling Building",
    "spilkerengappliedsci": "Spilker Engineering and Applied Sciences",
    "stlc": "Sapp Center for Science Teaching and Learning",
    "thornton": "Thornton Center",
    "y2e2": "Y2E2 Building",
}


def normalize_room(value: str) -> str:
    value = value.casefold().replace("&amp;", "&")
    return re.sub(r"[^a-z0-9]+", "", value)


def _decode_js_hex_escapes(value: str) -> str:
    """Decode hex escapes in Campus Map's onclick string arguments."""
    return re.sub(
        r"\\x([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), value
    )


def is_queryable_room(room: str) -> bool:
    normalized = normalize_room(room)
    return bool(normalized) and normalized not in {
        "tba",
        "tbd",
        "online",
        "remote",
        "internetmediated",
        "nolocation",
        "departmentalroom",
        "schoolofmedicineroom",
    }


def room_query_candidates(room: str) -> list[str]:
    """Return exact-to-broad Campus Map searches for an ExploreCourses room label."""
    room = re.sub(r"\s+", " ", room).strip()
    candidates = [room]
    lowered = room.casefold()

    for prefix, alias in ROOM_PREFIX_ALIASES.items():
        if lowered.startswith(prefix):
            candidates.append(alias)
            break

    numeric_building = re.match(r"^(\d{1,3})[-/]", room)
    if numeric_building:
        candidates.append(f"Building {numeric_building.group(1)}")
    else:
        without_room = re.sub(
            r",?\s+(?:rooms?|rms?|rm)\s*[A-Z]?\d[\w/-]*$", "", room, flags=re.IGNORECASE
        )
        without_suffix = re.sub(
            r"\s+[A-Z]?\d[\w/-]*$", "", without_room, flags=re.IGNORECASE
        )
        if without_suffix != room:
            candidates.append(without_suffix)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_room(candidate)
        if key and key not in seen:
            deduplicated.append(candidate)
            seen.add(key)
    return deduplicated


def parse_room_search(html: str, query: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    candidates: list[dict[str, Any]] = []
    for anchor in soup.select("a.list-group-item"):
        match = CLICK_RE.search(anchor.get("onclick", ""))
        if not match:
            continue
        label_node = anchor.find("b")
        label = label_node.get_text(" ", strip=True) if label_node else ""
        candidate = {
            "label": label,
            "facility_id": _decode_js_hex_escapes(match.group("facility")),
            "latitude": float(match.group("lat")),
            "longitude": float(match.group("lon")),
            "address": _decode_js_hex_escapes(match.group("address")),
        }
        candidates.append(candidate)

    if not candidates:
        return {
            "room": query,
            "match_status": "no_result",
            "match_label": "",
            "facility_id": "",
            "latitude": None,
            "longitude": None,
            "address": "",
            "candidate_count": 0,
        }

    query_key = normalize_room(query)
    exact = [candidate for candidate in candidates if normalize_room(candidate["label"]) == query_key]
    if len(exact) == 1:
        selected = exact[0]
        status = "exact"
    elif len(candidates) == 1:
        selected = candidates[0]
        status = "single_result"
    else:
        selected = candidates[0]
        status = "ambiguous"

    south, west, north, east = CAMPUS_BBOX
    on_campus = (
        south <= selected["latitude"] <= north
        and west <= selected["longitude"] <= east
    )
    if not on_campus:
        status = "outside_campus_bbox"

    return {
        "room": query,
        "match_status": status,
        "match_label": selected["label"],
        "facility_id": selected["facility_id"],
        "latitude": selected["latitude"],
        "longitude": selected["longitude"],
        "address": selected["address"],
        "candidate_count": len(candidates),
    }


def collect_room_lookup(
    fetcher: CachedFetcher,
    meetings: pd.DataFrame,
    *,
    refresh: bool = False,
    room_limit: int | None = None,
) -> pd.DataFrame:
    rooms = sorted(
        room
        for room in meetings["room"].dropna().astype(str).unique()
        if is_queryable_room(room)
    )
    if room_limit is not None:
        rooms = rooms[:room_limit]

    rows: list[dict[str, Any]] = []
    for index, room in enumerate(rooms, start=1):
        row: dict[str, Any] | None = None
        errors: list[str] = []
        for query_index, query in enumerate(room_query_candidates(room)):
            digest = hashlib.sha1(query.encode("utf-8"), usedforsecurity=False).hexdigest()
            cache_path = RAW_DIR / "campus_map" / f"{digest}.html"
            params = {
                "criteria": query,
                "orig_srch": query,
                "matches": "1",
                "hidden": "",
            }
            try:
                html = fetcher.get_text(
                    f"{CAMPUS_MAP_BASE}/report-cm.cfm",
                    cache_path,
                    params=params,
                    refresh=refresh,
                )
                candidate = parse_room_search(html, query)
            except FetchError as exc:
                errors.append(str(exc))
                continue
            if candidate["match_status"] not in {"exact", "single_result"}:
                continue
            row = candidate
            row["room"] = room
            row["query_used"] = query
            if query_index > 0:
                row["match_status"] = "fallback"
            break

        if row is None:
            row = {
                "room": room,
                "match_status": "fetch_error" if errors else "no_result",
                "match_label": "",
                "facility_id": "",
                "latitude": None,
                "longitude": None,
                "address": "",
                "candidate_count": 0,
                "query_used": "",
            }
            if errors:
                row["error"] = " | ".join(errors)
        rows.append(row)
        if index % 50 == 0:
            matched = sum(
                item["match_status"] in USABLE_MATCH_STATUSES for item in rows
            )
            print(f"Campus Map: {index}/{len(rooms)} rooms, {matched} usable matches")

    lookup = pd.DataFrame(rows)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(PROCESSED_DIR / "room_lookup.csv", index=False)
    return lookup
