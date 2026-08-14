from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from .campus_map import USABLE_MATCH_STATUSES
from .config import CAMPUS_BBOX, OVERPASS_URL, PROCESSED_DIR, RAW_DIR
from .fetch import CachedFetcher

ALLOWED_HIGHWAYS = {
    "bridleway",
    "cycleway",
    "footway",
    "living_street",
    "path",
    "pedestrian",
    "primary",
    "primary_link",
    "residential",
    "secondary",
    "secondary_link",
    "service",
    "steps",
    "tertiary",
    "tertiary_link",
    "track",
    "unclassified",
}

BIKE_ROAD_HIGHWAYS = {
    "cycleway",
    "living_street",
    "path",
    "primary",
    "primary_link",
    "residential",
    "secondary",
    "secondary_link",
    "service",
    "tertiary",
    "tertiary_link",
    "track",
    "unclassified",
}
BIKE_EXPLICIT_ACCESS = {"yes", "designated", "permissive"}

FACILITY_BUILDING_WORDS = (
    "building",
    "center",
    "hall",
    "library",
    "sciences",
)

ACCESSIBILITY_WAY_TAGS = (
    "wheelchair",
    "incline",
    "surface",
    "smoothness",
    "width",
    "kerb",
)


def _best_match_label(values: pd.Series) -> str:
    labels = [str(value).strip() for value in values if str(value).strip()]
    if not labels:
        return ""

    counts = pd.Series(labels).value_counts().to_dict()
    first_position = {label: labels.index(label) for label in counts}

    def score(label: str) -> tuple[int, int, int]:
        lowered = label.casefold()
        if any(word in lowered for word in FACILITY_BUILDING_WORDS):
            label_type = 3
        elif "auditorium" in lowered:
            label_type = 2
        elif not any(character.isdigit() for character in label):
            label_type = 1
        else:
            label_type = 0
        return label_type, int(counts[label]), -first_position[label]

    return max(counts, key=score)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def overpass_query() -> str:
    south, west, north, east = CAMPUS_BBOX
    return f"""
[out:json][timeout:180];
(
  way[\"highway\"]({south},{west},{north},{east});
);
out body;
>;
out skel qt;
""".strip()


def osm_way_tag_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    """Count route-relevant accessibility tags in the exact OSM snapshot."""
    ways = [
        element
        for element in payload.get("elements", [])
        if element.get("type") == "way"
        and element.get("tags", {}).get("highway")
    ]
    total = len(ways)
    coverage: dict[str, Any] = {
        "denominator_note": (
            "All highway ways in the collected OSM bounding-box snapshot before "
            "walking or bicycle routing filters."
        ),
        "total_highway_ways": total,
    }
    for tag in ACCESSIBILITY_WAY_TAGS:
        count = sum(1 for way in ways if tag in way.get("tags", {}))
        coverage[f"ways_with_{tag}_tag"] = count
        coverage[f"share_with_{tag}_tag"] = count / total if total else None
    return coverage


def collect_osm_snapshot(
    fetcher: CachedFetcher, *, refresh: bool = False
) -> dict[str, Any]:
    cache_path = RAW_DIR / "osm" / "walk_network.json"
    return fetcher.get_json(
        OVERPASS_URL,
        cache_path,
        data={"data": overpass_query()},
        refresh=refresh,
    )


def _way_is_walkable(tags: dict[str, str]) -> bool:
    highway = tags.get("highway", "")
    if highway not in ALLOWED_HIGHWAYS:
        return False
    if tags.get("indoor") not in {None, "", "no"}:
        return False
    if tags.get("foot") in {"no", "private"}:
        return False
    return not (
        tags.get("access") in {"no", "private"}
        and tags.get("foot") not in {"yes", "designated", "permissive"}
    )


def _way_is_bikeable(tags: dict[str, str]) -> bool:
    highway = tags.get("highway", "")
    bicycle = tags.get("bicycle", "")
    if tags.get("indoor") not in {None, "", "no"}:
        return False
    if highway in {"steps", "corridor"}:
        return False
    if bicycle in {"no", "private", "dismount"}:
        return False
    if tags.get("access") in {"no", "private"} and bicycle not in BIKE_EXPLICIT_ACCESS:
        return False
    if highway in {"footway", "pedestrian"}:
        return bicycle in BIKE_EXPLICIT_ACCESS
    return highway in BIKE_ROAD_HIGHWAYS


def _bike_directions(tags: dict[str, str]) -> tuple[bool, bool]:
    bicycle_oneway = tags.get("oneway:bicycle", "")
    if bicycle_oneway == "no":
        return True, True
    oneway = bicycle_oneway or tags.get("oneway", "")
    if not oneway and tags.get("junction") == "roundabout":
        oneway = "yes"
    if oneway in {"yes", "1", "true"}:
        return True, False
    if oneway == "-1":
        return False, True
    return True, True


def connected_components(graph: dict[int, dict[int, float]]) -> list[set[int]]:
    components: list[set[int]] = []
    visited: set[int] = set()
    for start in graph:
        if start in visited:
            continue
        component = {start}
        stack = [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            for neighbor in graph.get(node, {}):
                if neighbor not in visited:
                    visited.add(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components


def weakly_connected_components(
    graph: dict[int, dict[int, float]],
) -> list[set[int]]:
    undirected: dict[int, set[int]] = defaultdict(set)
    for node, neighbors in graph.items():
        undirected.setdefault(node, set())
        for neighbor in neighbors:
            undirected[node].add(neighbor)
            undirected[neighbor].add(node)
    weighted = {
        node: dict.fromkeys(neighbors, 1.0)
        for node, neighbors in undirected.items()
    }
    return connected_components(weighted)


def build_walk_graph(
    payload: dict[str, Any],
) -> tuple[dict[int, dict[int, float]], dict[int, tuple[float, float]], pd.DataFrame]:
    nodes: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            nodes[int(element["id"])] = (float(element["lat"]), float(element["lon"]))
        elif element.get("type") == "way":
            ways.append(element)

    adjacency: dict[int, dict[int, float]] = defaultdict(dict)
    edge_rows: list[dict[str, Any]] = []
    for way in ways:
        tags = way.get("tags", {})
        if not _way_is_walkable(tags):
            continue
        node_ids = [int(node_id) for node_id in way.get("nodes", [])]
        for left, right in pairwise(node_ids):
            if left not in nodes or right not in nodes:
                continue
            left_lat, left_lon = nodes[left]
            right_lat, right_lon = nodes[right]
            distance = haversine_meters(left_lat, left_lon, right_lat, right_lon)
            if distance <= 0:
                continue
            old = adjacency[left].get(right)
            if old is None or distance < old:
                adjacency[left][right] = distance
                adjacency[right][left] = distance
            edge_rows.append(
                {
                    "way_id": int(way["id"]),
                    "from_node": left,
                    "to_node": right,
                    "from_latitude": left_lat,
                    "from_longitude": left_lon,
                    "to_latitude": right_lat,
                    "to_longitude": right_lon,
                    "distance_meters": distance,
                    "highway": tags.get("highway", ""),
                    "steps": tags.get("highway") == "steps",
                }
            )
    return dict(adjacency), nodes, pd.DataFrame(edge_rows)


def build_bike_graph(
    payload: dict[str, Any],
) -> tuple[dict[int, dict[int, float]], dict[int, tuple[float, float]], pd.DataFrame]:
    nodes: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            nodes[int(element["id"])] = (float(element["lat"]), float(element["lon"]))
        elif element.get("type") == "way":
            ways.append(element)

    adjacency: dict[int, dict[int, float]] = defaultdict(dict)
    edge_rows: list[dict[str, Any]] = []
    for way in ways:
        tags = way.get("tags", {})
        if not _way_is_bikeable(tags):
            continue
        forward_allowed, backward_allowed = _bike_directions(tags)
        node_ids = [int(node_id) for node_id in way.get("nodes", [])]
        for left, right in pairwise(node_ids):
            if left not in nodes or right not in nodes:
                continue
            left_lat, left_lon = nodes[left]
            right_lat, right_lon = nodes[right]
            distance = haversine_meters(left_lat, left_lon, right_lat, right_lon)
            if distance <= 0:
                continue
            if forward_allowed:
                previous = adjacency[left].get(right)
                if previous is None or distance < previous:
                    adjacency[left][right] = distance
            if backward_allowed:
                previous = adjacency[right].get(left)
                if previous is None or distance < previous:
                    adjacency[right][left] = distance
            edge_rows.append(
                {
                    "way_id": int(way["id"]),
                    "from_node": left,
                    "to_node": right,
                    "from_latitude": left_lat,
                    "from_longitude": left_lon,
                    "to_latitude": right_lat,
                    "to_longitude": right_lon,
                    "distance_meters": distance,
                    "highway": tags.get("highway", ""),
                    "bicycle": tags.get("bicycle", ""),
                    "surface": tags.get("surface", ""),
                    "forward_allowed": forward_allowed,
                    "backward_allowed": backward_allowed,
                }
            )
    return dict(adjacency), nodes, pd.DataFrame(edge_rows)


def nearest_nodes(
    facilities: pd.DataFrame, nodes: dict[int, tuple[float, float]]
) -> pd.DataFrame:
    node_ids = np.fromiter(nodes.keys(), dtype=np.int64)
    coordinates = np.array([nodes[int(node_id)] for node_id in node_ids], dtype=float)
    latitudes = coordinates[:, 0]
    longitudes = coordinates[:, 1]
    reference_latitude = math.radians(float(latitudes.mean()))

    rows: list[dict[str, Any]] = []
    for row in facilities.itertuples(index=False):
        lat_scale = 111_320.0
        lon_scale = 111_320.0 * math.cos(reference_latitude)
        dy = (latitudes - float(row.latitude)) * lat_scale
        dx = (longitudes - float(row.longitude)) * lon_scale
        index = int(np.argmin(dx * dx + dy * dy))
        node_id = int(node_ids[index])
        node_lat, node_lon = nodes[node_id]
        rows.append(
            {
                "facility_id": row.facility_id,
                "latitude": float(row.latitude),
                "longitude": float(row.longitude),
                "node_id": node_id,
                "node_latitude": node_lat,
                "node_longitude": node_lon,
                "snap_distance_meters": haversine_meters(
                    float(row.latitude), float(row.longitude), node_lat, node_lon
                ),
            }
        )
    return pd.DataFrame(rows)


def dijkstra_targets(
    graph: dict[int, dict[int, float]], source: int, targets: set[int]
) -> dict[int, float]:
    distances = {source: 0.0}
    queue: list[tuple[float, int]] = [(0.0, source)]
    remaining = set(targets)
    found: dict[int, float] = {}
    while queue and remaining:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node in remaining:
            found[node] = distance
            remaining.remove(node)
        for neighbor, weight in graph.get(node, {}).items():
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return found


def calculate_route_distances(
    lookup: pd.DataFrame,
    osm_payload: dict[str, Any],
    *,
    max_snap_meters: float = 250.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    usable = lookup[lookup["match_status"].isin(USABLE_MATCH_STATUSES)].copy()
    usable = usable.dropna(subset=["facility_id", "latitude", "longitude"])
    if "match_label" not in usable.columns:
        fallback_labels = usable["address"] if "address" in usable.columns else usable["room"]
        usable["match_label"] = fallback_labels.fillna(usable["room"])
    facilities = (
        usable.groupby("facility_id", as_index=False)
        .agg(
            latitude=("latitude", "median"),
            longitude=("longitude", "median"),
            address=("address", "first"),
            official_label=("match_label", _best_match_label),
            representative_room=("room", "first"),
            room_count=("room", "nunique"),
        )
        .sort_values("facility_id")
    )

    full_graph, nodes, all_edges = build_walk_graph(osm_payload)
    components = connected_components(full_graph)
    if not components:
        raise ValueError("OpenStreetMap snapshot produced no walkable network")
    routing_node_ids = max(components, key=len)
    graph = {
        node: {
            neighbor: weight
            for neighbor, weight in full_graph[node].items()
            if neighbor in routing_node_ids
        }
        for node in routing_node_ids
    }
    routing_nodes = {node: nodes[node] for node in routing_node_ids}
    edges = all_edges[
        all_edges["from_node"].isin(routing_node_ids)
        & all_edges["to_node"].isin(routing_node_ids)
    ].copy()
    snapped = nearest_nodes(facilities, routing_nodes)
    snapped["snap_usable"] = snapped["snap_distance_meters"] <= max_snap_meters
    valid = snapped[snapped["snap_usable"]].copy()
    target_nodes = set(valid["node_id"].astype(int))

    rows: list[dict[str, Any]] = []
    valid_by_facility = valid.set_index("facility_id")
    for index, origin in enumerate(valid.itertuples(index=False), start=1):
        network_distances = dijkstra_targets(graph, int(origin.node_id), target_nodes)
        for destination in valid.itertuples(index=False):
            if origin.facility_id == destination.facility_id:
                route_distance = 0.0
                connected = True
            else:
                network_distance = network_distances.get(int(destination.node_id))
                connected = network_distance is not None
                route_distance = (
                    float(origin.snap_distance_meters)
                    + float(network_distance)
                    + float(destination.snap_distance_meters)
                    if network_distance is not None
                    else math.nan
                )
            rows.append(
                {
                    "origin_facility_id": origin.facility_id,
                    "destination_facility_id": destination.facility_id,
                    "route_distance_meters": route_distance,
                    "connected": connected,
                    "origin_snap_meters": float(origin.snap_distance_meters),
                    "destination_snap_meters": float(destination.snap_distance_meters),
                }
            )
        if index % 25 == 0:
            print(f"Routing: {index}/{len(valid)} origin facilities")

    route_df = pd.DataFrame(rows)
    facilities = facilities.merge(snapped, on=["facility_id", "latitude", "longitude"], how="left")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    route_df.to_csv(PROCESSED_DIR / "route_distances.csv", index=False)
    facilities.to_csv(PROCESSED_DIR / "facilities.csv", index=False)
    edges.to_csv(PROCESSED_DIR / "walk_edges.csv", index=False)
    validation = {
        "osm_elements": len(osm_payload.get("elements", [])),
        "indoor_or_corridor_ways_excluded": sum(
            1
            for element in osm_payload.get("elements", [])
            if element.get("type") == "way"
            and (
                element.get("tags", {}).get("highway") == "corridor"
                or element.get("tags", {}).get("indoor") not in {None, "", "no"}
            )
        ),
        "walk_graph_components_before_filter": len(components),
        "walk_graph_nodes_before_component_filter": len(full_graph),
        "walk_graph_undirected_edges_before_component_filter": (
            sum(len(neighbors) for neighbors in full_graph.values()) // 2
        ),
        "walk_edge_segments_before_component_filter": len(all_edges),
        "walk_graph_nodes": len(graph),
        "walk_graph_directed_edges": sum(len(neighbors) for neighbors in graph.values()),
        "walk_graph_undirected_edges": (
            sum(len(neighbors) for neighbors in graph.values()) // 2
        ),
        "walk_edge_segments": len(edges),
        "facilities_from_room_lookup": len(facilities),
        "facilities_with_usable_snap": int(valid["facility_id"].nunique()),
        "snap_distance_limit_meters": max_snap_meters,
        "max_snap_distance_meters": (
            float(valid_by_facility["snap_distance_meters"].max()) if len(valid) else None
        ),
        "median_snap_meters": (
            float(valid_by_facility["snap_distance_meters"].median()) if len(valid) else None
        ),
        "connected_route_pairs": int(route_df["connected"].sum()),
        "total_route_pairs": len(route_df),
    }
    return route_df, facilities, edges, validation


def calculate_bike_route_distances(
    facilities: pd.DataFrame,
    osm_payload: dict[str, Any],
    *,
    max_snap_meters: float = 250.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build a directional OSM bicycle network and route every facility pair."""
    base_facilities = facilities[
        [
            "facility_id",
            "latitude",
            "longitude",
            "address",
            "official_label",
            "representative_room",
            "room_count",
        ]
    ].drop_duplicates("facility_id")
    full_graph, nodes, all_edges = build_bike_graph(osm_payload)
    components = weakly_connected_components(full_graph)
    if not components:
        raise ValueError("OpenStreetMap snapshot produced no bicycle network")
    routing_node_ids = max(components, key=len)
    graph = {
        node: {
            neighbor: weight
            for neighbor, weight in full_graph.get(node, {}).items()
            if neighbor in routing_node_ids
        }
        for node in routing_node_ids
    }
    routing_nodes = {node: nodes[node] for node in routing_node_ids}
    edges = all_edges[
        all_edges["from_node"].isin(routing_node_ids)
        & all_edges["to_node"].isin(routing_node_ids)
    ].copy()
    snapped = nearest_nodes(base_facilities, routing_nodes)
    snapped["snap_usable"] = snapped["snap_distance_meters"] <= max_snap_meters
    valid = snapped[snapped["snap_usable"]].copy()
    targets = set(valid["node_id"].astype(int))

    rows: list[dict[str, Any]] = []
    for index, origin in enumerate(valid.itertuples(index=False), start=1):
        network_distances = dijkstra_targets(graph, int(origin.node_id), targets)
        for destination in valid.itertuples(index=False):
            if origin.facility_id == destination.facility_id:
                route_distance = 0.0
                connected = True
            else:
                network_distance = network_distances.get(int(destination.node_id))
                connected = network_distance is not None
                route_distance = (
                    float(origin.snap_distance_meters)
                    + float(network_distance)
                    + float(destination.snap_distance_meters)
                    if network_distance is not None
                    else math.nan
                )
            rows.append(
                {
                    "origin_facility_id": origin.facility_id,
                    "destination_facility_id": destination.facility_id,
                    "route_distance_meters": route_distance,
                    "connected": connected,
                    "origin_snap_meters": float(origin.snap_distance_meters),
                    "destination_snap_meters": float(destination.snap_distance_meters),
                }
            )
        if index % 25 == 0:
            print(f"Bicycle routing: {index}/{len(valid)} origin facilities")

    routes = pd.DataFrame(rows)
    bike_facilities = base_facilities.merge(
        snapped, on=["facility_id", "latitude", "longitude"], how="left"
    )
    routes.to_csv(PROCESSED_DIR / "bike_route_distances.csv", index=False)
    bike_facilities.to_csv(PROCESSED_DIR / "bike_facilities.csv", index=False)
    edges.to_csv(PROCESSED_DIR / "bike_edges.csv", index=False)
    validation = {
        "bike_filter_note": (
            "Excludes steps, indoor ways, bicycle=no/private/dismount, restricted "
            "access without a bicycle override, and footway/pedestrian ways without "
            "explicit bicycle permission. Directional bicycle access follows oneway tags."
        ),
        "bike_graph_weak_components_before_filter": len(components),
        "bike_graph_nodes_before_component_filter": len(full_graph),
        "bike_edge_segments_before_component_filter": len(all_edges),
        "bike_graph_nodes": len(graph),
        "bike_graph_directed_edges": sum(len(neighbors) for neighbors in graph.values()),
        "bike_edge_segments": len(edges),
        "facilities_with_usable_bike_snap": int(valid["facility_id"].nunique()),
        "bike_snap_distance_limit_meters": max_snap_meters,
        "max_bike_snap_distance_meters": (
            float(valid["snap_distance_meters"].max()) if len(valid) else None
        ),
        "median_bike_snap_meters": (
            float(valid["snap_distance_meters"].median()) if len(valid) else None
        ),
        "connected_bike_route_pairs": int(routes["connected"].sum()),
        "total_bike_route_pairs": len(routes),
    }
    return routes, bike_facilities, edges, validation


def save_osm_payload_summary(payload: dict[str, Any]) -> None:
    summary = {
        "generator": payload.get("generator"),
        "osm3s": payload.get("osm3s", {}),
        "element_count": len(payload.get("elements", [])),
        "query": overpass_query(),
    }
    path = PROCESSED_DIR / "osm_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
