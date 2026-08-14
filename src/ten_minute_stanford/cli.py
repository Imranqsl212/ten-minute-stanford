from __future__ import annotations

import argparse
import json
from typing import Any

from .analysis import analyze
from .campus_map import collect_room_lookup
from .config import ACADEMIC_YEAR, REPORT_DIR, TERMS, Paths
from .explorecourses import collect_explorecourses
from .fetch import CachedFetcher
from .osm import (
    calculate_bike_route_distances,
    calculate_route_distances,
    collect_osm_snapshot,
    osm_way_tag_coverage,
    save_osm_payload_summary,
)
from .visuals import create_all_visuals


def collect(args: argparse.Namespace) -> dict[str, Any]:
    Paths().create()
    fetcher = CachedFetcher(min_delay_seconds=args.delay)
    _sections, meetings, explore_manifest = collect_explorecourses(
        fetcher,
        academic_year=args.academic_year,
        terms=tuple(args.terms),
        refresh=args.refresh,
        subject_limit=args.subject_limit,
    )
    lookup = collect_room_lookup(
        fetcher,
        meetings,
        refresh=args.refresh,
        room_limit=args.room_limit,
    )
    osm_payload = collect_osm_snapshot(fetcher, refresh=args.refresh)
    save_osm_payload_summary(osm_payload)
    _, facilities, _, route_validation = calculate_route_distances(lookup, osm_payload)
    _, _, _, bike_route_validation = calculate_bike_route_distances(
        facilities, osm_payload
    )

    validation = {
        "explorecourses": explore_manifest,
        "room_lookup": {
            "rooms_queried": len(lookup),
            "status_counts": {
                str(key): int(value)
                for key, value in lookup["match_status"].value_counts(dropna=False).items()
            },
            "usable_facilities": int(facilities["facility_id"].nunique()),
        },
        "routing": route_validation,
        "bicycle_routing": bike_route_validation,
        "osm_way_tag_coverage": osm_way_tag_coverage(osm_payload),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "validation.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(validation, indent=2, sort_keys=True))
    return validation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ten-minute-stanford",
        description="Collect and analyze Stanford classroom walking transitions.",
    )
    parser.add_argument(
        "command",
        choices=("collect", "analyze", "visuals", "all"),
        nargs="?",
        default="all",
    )
    parser.add_argument("--academic-year", default=ACADEMIC_YEAR)
    parser.add_argument("--terms", nargs="+", default=list(TERMS))
    parser.add_argument("--subject-limit", type=int)
    parser.add_argument("--room-limit", type=int)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--refresh", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    Paths().create()
    if args.command in {"collect", "all"}:
        collect(args)
    if args.command in {"analyze", "all"}:
        summary = analyze()
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.command in {"visuals", "all"}:
        create_all_visuals()
        print("Visuals written to reports/generated/figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
