import pandas as pd

from ten_minute_stanford import campus_map
from ten_minute_stanford.campus_map import (
    collect_room_lookup,
    parse_room_search,
    room_query_candidates,
)
from ten_minute_stanford.fetch import CachedFetcher

CODA_SEARCH_HTML = """
<a class="list-group-item"
   onclick="bldg_clicked('07&#x5c;x2D430', 37.429924, -122.17178, 17,
   '389&#x5c;x20jane&#x5c;x20stanford&#x5c;x20way&#x5c;x20stanford')">
   <b>computing and data science</b>
</a>
"""


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


def test_parse_room_search_decodes_javascript_hex_escapes() -> None:
    row = parse_room_search(CODA_SEARCH_HTML, "Computing and Data Science")
    assert row["match_status"] == "exact"
    assert row["facility_id"] == "07-430"
    assert row["address"] == "389 jane stanford way stanford"
    assert row["latitude"] == 37.429924
    assert row["longitude"] == -122.17178


def test_coda_rooms_resolve_to_computing_and_data_science_not_cordura(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(campus_map, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(campus_map, "PROCESSED_DIR", tmp_path / "processed")
    responses = {
        "Computing and Data Science": CODA_SEARCH_HTML,
        "Cordura Hall": """
            <a class="list-group-item"
               onclick="bldg_clicked('14-070', 37.43048734, -122.17877394, 17,
               '210 panama st stanford')"><b>cordura hall</b></a>
        """,
    }

    def get_text(url, cache_path, *, params, refresh):
        return responses.get(params["criteria"], "<html></html>")

    fetcher = CachedFetcher()
    monkeypatch.setattr(fetcher, "get_text", get_text)
    coda_rooms = ["CODAB60", "CODAB80", "CODAB90", "CoDa B60"]
    meetings = pd.DataFrame({"room": [*coda_rooms, "Cordura Hall 100"]})
    lookup = collect_room_lookup(fetcher, meetings).set_index("room")

    for room in coda_rooms:
        assert lookup.loc[room, "facility_id"] == "07-430"
        assert lookup.loc[room, "match_status"] == "fallback"
        assert lookup.loc[room, "query_used"] == "Computing and Data Science"
    assert lookup.loc["Cordura Hall 100", "facility_id"] == "14-070"
    assert lookup.loc["Cordura Hall 100", "query_used"] == "Cordura Hall"


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
