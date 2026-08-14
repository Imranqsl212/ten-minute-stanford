from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from .config import BICYCLE_SPEEDS_MPH, PROCESSED_DIR, REPORT_DIR, WALKING_SPEEDS_MPH

PASSING_PERIODS_MINUTES = (10, 12, 15)
BUILDING_OVERHEADS_MINUTES = (0, 2)
ROUTE_SIMPLIFICATION_METERS = 3.0


def _route_key(left: str, right: str, *, directed: bool) -> str:
    return f"{left}|{right}" if directed else "|".join(sorted((left, right)))


def _build_graph(
    edges: pd.DataFrame,
    *,
    directed: bool = False,
) -> tuple[dict[int, dict[int, float]], dict[int, tuple[float, float]]]:
    graph: dict[int, dict[int, float]] = defaultdict(dict)
    coordinates: dict[int, tuple[float, float]] = {}
    for row in edges.itertuples(index=False):
        left = int(row.from_node)
        right = int(row.to_node)
        distance = float(row.distance_meters)
        coordinates[left] = (float(row.from_longitude), float(row.from_latitude))
        coordinates[right] = (float(row.to_longitude), float(row.to_latitude))
        forward_allowed = not directed or bool(row.forward_allowed)
        backward_allowed = not directed or bool(row.backward_allowed)
        if forward_allowed:
            previous = graph[left].get(right)
            if previous is None or distance < previous:
                graph[left][right] = distance
        if backward_allowed:
            previous = graph[right].get(left)
            if previous is None or distance < previous:
                graph[right][left] = distance
    return dict(graph), coordinates


def _shortest_path_tree(
    graph: dict[int, dict[int, float]], source: int, targets: set[int]
) -> tuple[dict[int, float], dict[int, int]]:
    distances = {source: 0.0}
    previous: dict[int, int] = {}
    queue: list[tuple[float, int]] = [(0.0, source)]
    remaining = set(targets)
    while queue and remaining:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        remaining.discard(node)
        for neighbor, weight in graph.get(node, {}).items():
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))
    return distances, previous


def _reconstruct_path(previous: dict[int, int], source: int, target: int) -> list[int]:
    if source == target:
        return [source]
    if target not in previous:
        return []
    path = [target]
    while path[-1] != source:
        parent = previous.get(path[-1])
        if parent is None:
            return []
        path.append(parent)
    path.reverse()
    return path


def _project(point: tuple[float, float], reference_latitude: float) -> tuple[float, float]:
    longitude, latitude = point
    return (
        longitude * 111_320.0 * math.cos(math.radians(reference_latitude)),
        latitude * 111_320.0,
    )


def _point_to_segment_distance(
    point: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    dx = right[0] - left[0]
    dy = right[1] - left[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - left[0], point[1] - left[1])
    fraction = ((point[0] - left[0]) * dx + (point[1] - left[1]) * dy) / (
        dx * dx + dy * dy
    )
    fraction = min(1.0, max(0.0, fraction))
    nearest = (left[0] + fraction * dx, left[1] + fraction * dy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _simplify_path(
    points: list[tuple[float, float]], epsilon_meters: float
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    reference_latitude = sum(point[1] for point in points) / len(points)
    projected = [_project(point, reference_latitude) for point in points]

    def simplify(start: int, end: int) -> list[int]:
        greatest_distance = 0.0
        greatest_index = -1
        for index in range(start + 1, end):
            distance = _point_to_segment_distance(
                projected[index], projected[start], projected[end]
            )
            if distance > greatest_distance:
                greatest_distance = distance
                greatest_index = index
        if greatest_distance > epsilon_meters and greatest_index >= 0:
            left = simplify(start, greatest_index)
            right = simplify(greatest_index, end)
            return [*left[:-1], *right]
        return [start, end]

    return [points[index] for index in simplify(0, len(points) - 1)]


def _deduplicate_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    deduplicated: list[tuple[float, float]] = []
    for point in points:
        if not deduplicated or point != deduplicated[-1]:
            deduplicated.append(point)
    return deduplicated


def _scenario_rows(pair_summary: pd.DataFrame) -> list[dict[str, Any]]:
    weights = pair_summary["potential_meeting_pairs"].astype(int)
    total = int(weights.sum())
    rows: list[dict[str, Any]] = []
    for passing_period in PASSING_PERIODS_MINUTES:
        for speed in WALKING_SPEEDS_MPH:
            meters_per_minute = speed * 1609.344 / 60
            walk_minutes = pair_summary["route_distance_meters"] / meters_per_minute
            for overhead in BUILDING_OVERHEADS_MINUTES:
                available = max(0, passing_period - overhead)
                feasible = int(weights[walk_minutes <= available].sum())
                rows.append(
                    {
                        "passing_period_minutes": passing_period,
                        "walking_speed_mph": speed,
                        "building_overhead_minutes": overhead,
                        "available_route_minutes": available,
                        "feasible_pairs": feasible,
                        "total_pairs": total,
                        "share_feasible": feasible / total if total else None,
                    }
                )
    return rows


def _create_mode_routes(
    facilities: pd.DataFrame,
    routes: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    directed: bool,
) -> tuple[dict[str, dict[str, Any]], int]:
    graph, node_coordinates = _build_graph(edges, directed=directed)
    usable = facilities[facilities["snap_usable"].astype(bool)].copy()
    usable = usable.dropna(subset=["node_id", "latitude", "longitude", "facility_label"])
    usable["node_id"] = usable["node_id"].astype(int)
    route_lookup = routes.set_index(["origin_facility_id", "destination_facility_id"])
    target_nodes = set(usable["node_id"].tolist())
    route_payload: dict[str, dict[str, Any]] = {}
    path_point_count = 0

    by_id = usable.sort_values("facility_id").reset_index(drop=True)
    for origin_index, origin in by_id.iterrows():
        source_node = int(origin["node_id"])
        distances, previous = _shortest_path_tree(graph, source_node, target_nodes)
        destination_indexes = (
            range(len(by_id)) if directed else range(origin_index, len(by_id))
        )
        for destination_index in destination_indexes:
            destination = by_id.iloc[destination_index]
            target_node = int(destination["node_id"])
            if target_node not in distances:
                continue
            facility_pair = (origin["facility_id"], destination["facility_id"])
            try:
                route_row = route_lookup.loc[facility_pair]
            except KeyError:
                continue
            if not bool(route_row["connected"]):
                continue
            node_path = _reconstruct_path(previous, source_node, target_node)
            if not node_path:
                continue
            coordinates = [
                (float(origin["longitude"]), float(origin["latitude"])),
                *(node_coordinates[node] for node in node_path),
                (float(destination["longitude"]), float(destination["latitude"])),
            ]
            coordinates = _simplify_path(
                _deduplicate_points(coordinates), ROUTE_SIMPLIFICATION_METERS
            )
            path_point_count += len(coordinates)
            route_payload[_route_key(*facility_pair, directed=directed)] = {
                "distance_meters": round(float(route_row["route_distance_meters"]), 1),
                "path": [
                    [round(longitude, 6), round(latitude, 6)]
                    for longitude, latitude in coordinates
                ],
            }
    return route_payload, path_point_count


def create_interactive_payload(
    facilities: pd.DataFrame,
    routes: pd.DataFrame,
    bike_routes: pd.DataFrame,
    pair_summary: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    walk_edges = pd.read_csv(PROCESSED_DIR / "walk_edges.csv")
    bike_edges = pd.read_csv(PROCESSED_DIR / "bike_edges.csv")
    bike_facilities = pd.read_csv(PROCESSED_DIR / "bike_facilities.csv")
    bike_facilities = bike_facilities.merge(
        facilities[["facility_id", "facility_label"]], on="facility_id", how="left"
    )
    walk_payload, walk_point_count = _create_mode_routes(
        facilities, routes, walk_edges, directed=False
    )
    bike_payload, bike_point_count = _create_mode_routes(
        bike_facilities, bike_routes, bike_edges, directed=True
    )

    usable = facilities[facilities["snap_usable"].astype(bool)].copy()
    usable = usable.dropna(subset=["node_id", "latitude", "longitude", "facility_label"])
    usable = usable.sort_values("facility_label").reset_index(drop=True)

    facility_payload = [
        {
            "id": str(row.facility_id),
            "label": str(row.facility_label),
            "latitude": round(float(row.latitude), 6),
            "longitude": round(float(row.longitude), 6),
        }
        for row in usable.itertuples(index=False)
    ]
    latitudes = usable["latitude"].astype(float)
    longitudes = usable["longitude"].astype(float)
    latitude_padding = max(0.001, float(latitudes.max() - latitudes.min()) * 0.06)
    longitude_padding = max(0.001, float(longitudes.max() - longitudes.min()) * 0.06)

    scenarios = _scenario_rows(pair_summary)
    scenario_output_dir = REPORT_DIR / "tables"
    scenario_output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(scenarios).to_csv(
        scenario_output_dir / "passing_period_scenarios.csv", index=False
    )

    payload = {
        "metadata": {
            "academic_year": summary["academic_year"],
            "terms": summary["terms"],
            "facility_count": len(facility_payload),
            "route_count": {
                "walking_undirected": len(walk_payload),
                "bicycle_directed": len(bike_payload),
            },
            "path_point_count": {
                "walking": walk_point_count,
                "bicycle": bike_point_count,
            },
            "potential_adjacent_meeting_pairs": summary[
                "potential_adjacent_meeting_pairs"
            ],
            "scenario_note": (
                "The 12-minute scenario is hypothetical. The 15-minute scenario is a "
                "historical comparison with the AY 2021-22 meeting pattern, applied to "
                "the same potential Winter 2026 pairs identified around current ten-minute "
                "schedule gaps. Neither describes current Stanford policy."
            ),
        },
        "bounds": {
            "south": round(float(latitudes.min()) - latitude_padding, 6),
            "west": round(float(longitudes.min()) - longitude_padding, 6),
            "north": round(float(latitudes.max()) + latitude_padding, 6),
            "east": round(float(longitudes.max()) + longitude_padding, 6),
        },
        "featured_route": {
            "origin_id": "08-350",
            "destination_id": "04-720",
            "passing_period_minutes": 10,
            "travel_mode": "walk",
            "speed_mph": 3,
            "building_overhead_minutes": 0,
        },
        "modes": {
            "walk": {
                "label": "Walking",
                "speeds_mph": list(WALKING_SPEEDS_MPH),
                "default_speed_mph": 3,
                "directional_routes": False,
            },
            "bike": {
                "label": "Bicycle",
                "speeds_mph": list(BICYCLE_SPEEDS_MPH),
                "default_speed_mph": 8,
                "directional_routes": True,
            },
        },
        "facilities": facility_payload,
        "routes": {"walk": walk_payload, "bike": bike_payload},
        "scenarios": scenarios,
    }

    output_dir = REPORT_DIR / "interactive"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "route_explorer.json").write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )
    return payload


def weighted_scenario_share(
    pair_summary: pd.DataFrame,
    *,
    passing_period_minutes: int,
    walking_speed_mph: float,
    building_overhead_minutes: int,
) -> float:
    meters_per_minute = walking_speed_mph * 1609.344 / 60
    walk_minutes = pair_summary["route_distance_meters"] / meters_per_minute
    feasible = walk_minutes <= passing_period_minutes - building_overhead_minutes
    return float(
        np.average(feasible.astype(float), weights=pair_summary["potential_meeting_pairs"])
    )
