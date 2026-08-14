from ten_minute_stanford.campus_map import parse_room_search, room_query_candidates


def test_parse_exact_room_match() -> None:
    html = """
    <a class="list-group-item"
       onclick="bldg_clicked('01-320', 37.42694141, -122.17188691, 17,
       '450 jane stanford way, bldg. 320 stanford')">
       <b>320-105</b>
    </a>
    """
    row = parse_room_search(html, "320-105")
    assert row["match_status"] == "exact"
    assert row["facility_id"] == "01-320"
    assert row["latitude"] == 37.42694141


def test_outside_campus_is_flagged() -> None:
    html = """
    <a class="list-group-item"
       onclick="bldg_clicked('99-999', 37.0, -121.0, 17, 'Elsewhere')">
       <b>Remote 1</b>
    </a>
    """
    row = parse_room_search(html, "Remote 1")
    assert row["match_status"] == "outside_campus_bbox"


def test_room_query_candidates_broaden_named_rooms() -> None:
    assert room_query_candidates("Hewlett Teaching Center 200") == [
        "Hewlett Teaching Center 200",
        "Hewlett Teaching Center",
    ]
    assert room_query_candidates("320-105") == ["320-105", "Building 320"]
    assert room_query_candidates("AOERC Studio 203") == [
        "AOERC Studio 203",
        "AOERC",
        "AOERC Studio",
    ]
    assert room_query_candidates("Li Ka Shing Center,rms101/102") == [
        "Li Ka Shing Center,rms101/102",
        "Li Ka Shing Center",
    ]
