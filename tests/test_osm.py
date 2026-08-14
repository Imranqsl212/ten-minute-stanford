import pandas as pd

from ten_minute_stanford.osm import (
    _best_match_label,
    _way_is_bikeable,
    _way_is_walkable,
    build_bike_graph,
    build_walk_graph,
    calculate_route_distances,
    connected_components,
    dijkstra_targets,
    osm_way_tag_coverage,
)


def sample_payload() -> dict:
    return {
        "elements": [
            {"type": "node", "id": 1, "lat": 37.42, "lon": -122.18},
            {"type": "node", "id": 2, "lat": 37.42, "lon": -122.17},
            {"type": "node", "id": 3, "lat": 37.42, "lon": -122.16},
            {
                "type": "way",
                "id": 10,
                "nodes": [1, 2, 3],
                "tags": {"highway": "footway"},
            },
        ]
    }


def test_dijkstra_on_walk_graph() -> None:
    graph, _, edges = build_walk_graph(sample_payload())
    distances = dijkstra_targets(graph, 1, {3})
    assert 1700 < distances[3] < 1900
    assert len(edges) == 2


def test_osm_way_tag_coverage_uses_highway_ways_as_denominator() -> None:
    payload = sample_payload()
    payload["elements"][-1]["tags"].update(
        {"wheelchair": "yes", "surface": "paved"}
    )
    payload["elements"].append(
        {
            "type": "way",
            "id": 11,
            "nodes": [1, 2],
            "tags": {"highway": "steps", "incline": "up"},
        }
    )
    payload["elements"].append(
        {"type": "way", "id": 12, "nodes": [1, 2], "tags": {"building": "yes"}}
    )

    coverage = osm_way_tag_coverage(payload)

    assert coverage["total_highway_ways"] == 2
    assert coverage["ways_with_wheelchair_tag"] == 1
    assert coverage["ways_with_incline_tag"] == 1
    assert coverage["share_with_wheelchair_tag"] == 0.5


def test_route_matrix_is_symmetric(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ten_minute_stanford.osm.PROCESSED_DIR", tmp_path)
    lookup = pd.DataFrame(
        [
            {
                "room": "A 1",
                "match_status": "exact",
                "facility_id": "A",
                "latitude": 37.42,
                "longitude": -122.18,
                "address": "A",
            },
            {
                "room": "B 1",
                "match_status": "exact",
                "facility_id": "B",
                "latitude": 37.42,
                "longitude": -122.16,
                "address": "B",
            },
        ]
    )
    routes, facilities, _, validation = calculate_route_distances(
        lookup, sample_payload(), max_snap_meters=20
    )
    ab = routes.query("origin_facility_id == 'A' and destination_facility_id == 'B'")
    ba = routes.query("origin_facility_id == 'B' and destination_facility_id == 'A'")
    assert abs(float(ab.iloc[0]["route_distance_meters"]) - float(ba.iloc[0]["route_distance_meters"])) < 1
    assert len(facilities) == 2
    assert set(facilities["official_label"]) == {"A", "B"}
    assert validation["connected_route_pairs"] == 4


def test_indoor_ways_are_not_walkable() -> None:
    assert _way_is_walkable({"highway": "footway"}) is True
    assert _way_is_walkable({"highway": "corridor", "indoor": "yes"}) is False
    assert _way_is_walkable({"highway": "service", "indoor": "yes"}) is False


def test_bicycle_filter_requires_permission_on_pedestrian_ways() -> None:
    assert _way_is_bikeable({"highway": "cycleway"}) is True
    assert _way_is_bikeable({"highway": "residential"}) is True
    assert _way_is_bikeable({"highway": "footway"}) is False
    assert _way_is_bikeable({"highway": "footway", "bicycle": "designated"}) is True
    assert _way_is_bikeable({"highway": "steps", "bicycle": "yes"}) is False
    assert _way_is_bikeable({"highway": "service", "bicycle": "dismount"}) is False


def test_bicycle_graph_honors_oneway() -> None:
    payload = sample_payload()
    payload["elements"][-1]["tags"] = {"highway": "cycleway", "oneway": "yes"}

    graph, _, edges = build_bike_graph(payload)

    assert 2 in graph[1]
    assert 1 not in graph.get(2, {})
    assert 3 in graph[2]
    assert 2 not in graph.get(3, {})
    assert edges["forward_allowed"].all()
    assert not edges["backward_allowed"].any()


def test_connected_components_separate_isolated_networks() -> None:
    graph = {1: {2: 1.0}, 2: {1: 1.0}, 3: {4: 1.0}, 4: {3: 1.0}}
    components = connected_components(graph)
    assert {frozenset(component) for component in components} == {
        frozenset({1, 2}),
        frozenset({3, 4}),
    }


def test_facility_label_prefers_building_over_room_name() -> None:
    labels = pd.Series(
        ["bishop auditorium", "lathrop library", "lathrop library"]
    )
    assert _best_match_label(labels) == "lathrop library"
