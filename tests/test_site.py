import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from scripts.build_site import build_site

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def built_site(tmp_path: Path) -> Path:
    return build_site(tmp_path / "pages")


def test_pages_artifact_contains_publication_files(built_site: Path) -> None:
    expected = {
        "index.html",
        "methodology.html",
        "source-log.html",
        "404.html",
        "social-preview.png",
        "assets/figures/campus_transition_risk.png",
        "assets/figures/component_schedule_patterns.png",
        "assets/figures/component_schedule_patterns_mobile.png",
        "assets/figures/department_location_concentration.png",
        "assets/figures/department_location_concentration_mobile.png",
        "assets/figures/high_enrollment_transitions.png",
        "data/analysis_summary.json",
        "data/claim_audit.json",
        "data/publication_audit.json",
        "data/route_explorer.json",
        "data/bicycle_speed_summary.csv",
        "data/time_slot_summary.csv",
        "data/weekday_time_slot_summary.csv",
        "data/component_time_summary.csv",
        "data/component_day_summary.csv",
        "data/component_transition_summary.csv",
        "data/department_location_summary.csv",
        "data/subject_transition_feasibility.csv",
        "data/high_enrollment_transitions.csv",
        "data/student_survey_summary.csv",
        "data/course_transition_examples.csv",
        "data/course_transition_cases.csv",
        "data/passing_period_scenarios.csv",
        "data/source_manifest.json",
        "data/top_constrained_routes.csv",
    }
    present = {
        str(path.relative_to(built_site)) for path in built_site.rglob("*") if path.is_file()
    }
    assert expected <= present
    assert "data/external_sources.json" not in present
    assert not any(path.suffix == ".md" for path in built_site.rglob("*"))


def test_site_headline_numbers_match_analysis_summary(built_site: Path) -> None:
    summary = json.loads((ROOT / "reports/generated/analysis_summary.json").read_text())
    html = (built_site / "index.html").read_text()
    three_mph = next(
        result for result in summary["walking_speed_results"] if result["walking_speed_mph"] == 3.0
    )

    assert f"{three_mph['share_within_10_minutes'] * 100:.1f}%" in html
    assert f"{three_mph['share_within_10_minutes_with_2min_overhead'] * 100:.1f}%" in html
    assert f"{summary['potential_adjacent_meeting_pairs']:,}" in html
    assert f"{summary['mapped_physical_meeting_day_rows']:,}" in html
    assert f"{summary['lecture_component_meeting_day_rows']:,}" in html
    assert f"{summary['discussion_component_meeting_day_rows']:,}" in html
    assert f"{summary['lecture_discussion_transition_pairs']:,}" in html
    for result in summary["component_transition_results"]:
        assert f"{result['share_within_10min_3mph'] * 100:.1f}%" in html
    assert f"{summary['large_enrollment_unique_different_building_pairs']:,}" in html

    passing_periods = pd.read_csv(ROOT / "reports/generated/tables/passing_period_scenarios.csv")
    fifteen_minute = passing_periods[
        passing_periods["passing_period_minutes"].eq(15)
        & passing_periods["walking_speed_mph"].eq(3)
    ].set_index("building_overhead_minutes")
    assert f"{fifteen_minute.loc[0, 'share_feasible'] * 100:.1f}%" in html
    assert f"{fifteen_minute.loc[2, 'share_feasible'] * 100:.1f}%" in html
    normalized_text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ").split())
    assert "historical spreadsheet contains meeting patterns" in normalized_text


def test_site_surfaces_conclusions_before_the_detailed_analysis(built_site: Path) -> None:
    soup = BeautifulSoup((built_site / "index.html").read_text(), "html.parser")
    summary = json.loads((ROOT / "reports/generated/analysis_summary.json").read_text())
    takeaways = soup.select(".story-takeaways .takeaway-grid article")

    assert len(takeaways) == 3
    takeaway_text = " ".join(
        " ".join(card.get_text(" ", strip=True).split()) for card in takeaways
    )
    assert "Typical is not universal" in takeaway_text
    share = summary["three_mph_share_within_10_minutes"]
    overhead_share = summary["three_mph_share_within_10_minutes_with_2min_overhead"]
    assert f"{share:.1%} to {overhead_share:.1%}" in takeaway_text
    assert "not observed trips or late arrivals" in takeaway_text

    script = (built_site / "script.js").read_text()
    assert script.index('".story-summary"') < script.index('".story-takeaways"')
    assert script.index('".story-takeaways"') < script.index('".story-speed"')


def test_site_credits_both_authors(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()

    assert "Imran Zakirov and Alisher Sabitov" in html
    assert "ALisher Sabitov" not in html


def test_site_reports_student_survey_without_overclaiming(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
    survey = pd.read_csv(built_site / "data/student_survey_summary.csv").set_index("metric")

    assert survey.loc["reported_late", "count"] == 14
    assert survey.loc["close_call", "count"] == 6
    assert survey.loc["never_late", "count"] == 7
    assert survey.loc["late_or_close_call", "count"] == 20
    assert survey.loc["selected_walking", "count"] == 21
    assert survey.loc["selected_biking", "count"] == 11
    assert survey.loc["selected_e-scooter", "count"] == 5
    assert survey.loc["reported_concrete_consequence", "count"] == 11
    assert survey.loc["missed_class_content", "count"] == 6
    assert survey.loc["course_choice_effect", "count"] == 2
    assert survey.loc["skipped_adjacent_activity", "count"] == 3
    assert "What 27 Stanford students have added" in text
    assert "20 participants (74%)" in text
    assert "not a representative sample of Stanford students" in text
    assert "were not independently verified" in text
    assert 'href="data/student_survey_summary.csv"' in html

    script = (built_site / "script.js").read_text()
    assert script.index('".story-course-cases"') < script.index('".story-survey"')
    assert script.index('".story-survey"') < script.index('".story-planning"')


def test_route_widget_is_immediate_and_has_bicycle_mode(built_site: Path) -> None:
    html = (built_site / "index.html").read_text()
    script = (built_site / "script.js").read_text()

    assert 'data-mode="walk"' in html
    assert 'data-mode="bike"' in html
    assert "race-button" not in html
    assert "map-traveler" not in html
    assert "requestAnimationFrame" not in script
    assert "Run the 10-minute test" not in script


def test_course_transition_cards_match_audited_cases(built_site: Path) -> None:
    cases = pd.read_csv(ROOT / "reports/generated/tables/course_transition_cases.csv")
    html = (built_site / "index.html").read_text()
    soup = BeautifulSoup(html, "html.parser")

    assert len(soup.select(".transition-case")) == len(cases) == 4
    for row in cases.itertuples(index=False):
        assert row.origin_course_number in html
        assert row.destination_course_number in html
        assert row.origin_label in html
        assert row.destination_label in html
        assert f"{row.walk_minutes_3_0mph:.1f} min" in html
    normalized_text = " ".join(soup.get_text(" ", strip=True).split())
    assert "does not show whether any student actually took both" in normalized_text


def test_published_claim_audit_declares_its_boundaries(built_site: Path) -> None:
    claim_audit = json.loads((built_site / "data/claim_audit.json").read_text())
    assert claim_audit["status"] == "pass"
    assert "not an external replication" in claim_audit["audit_scope"]["independence"]
    assert (
        claim_audit["claims"]["enrollment_availability"]["meeting_rows_with_reported_enrollment"]
        == 6_876
    )
    assert (
        claim_audit["claims"]["enrollment_availability"]["section_rows_with_reported_enrollment"]
        == 27_197
    )
    assert claim_audit["claims"]["time_slot_analysis"]["distinct_ten_minute_slots"] == 25
    assert len(claim_audit["external_context_sources"]) == 25
    source_class_counts: dict[str, int] = {}
    for source in claim_audit["external_context_sources"]:
        source_class = source["source_class"]
        source_class_counts[source_class] = source_class_counts.get(source_class, 0) + 1
        if source["supports_stanford_claim"]:
            hostname = urlparse(source["url"]).hostname
            assert source_class == "official_stanford"
            assert hostname == "stanford.edu" or hostname.endswith(".stanford.edu")
    assert source_class_counts == {
        "editorial_context": 4,
        "external_open_data": 4,
        "official_stanford": 14,
        "third_party_code": 3,
    }
    assert claim_audit["claims"]["osm_accessibility_tag_coverage"]["ways_with_wheelchair_tag"] == 51
    assert claim_audit["claims"]["osm_accessibility_tag_coverage"]["ways_with_incline_tag"] == 128
    assert claim_audit["claims"]["component_schedule_analysis"]["lecture_rows"] == 2_035
    assert (
        claim_audit["claims"]["component_transition_analysis"]["lecture_discussion_pairs"] == 62_525
    )
    assert (
        claim_audit["claims"]["subject_area_transition_analysis"]["subject_areas_with_estimates"]
        == 161
    )
    assert (
        claim_audit["claims"]["large_enrollment_screen"]["unique_different_building_combinations"]
        == 187
    )
    survey_claim = claim_audit["claims"]["student_survey"]
    assert survey_claim["response_count"] == 27
    assert survey_claim["linked_google_sheet_responses"] == 26
    assert survey_claim["prior_retained_responses"] == 1
    assert survey_claim["reported_late"] == 14
    assert survey_claim["reported_close_call"] == 6
    assert survey_claim["reported_never_late"] == 7
    assert survey_claim["reported_late_or_close_call"] == 20
    assert survey_claim["selected_walking"] == 21
    assert survey_claim["selected_biking"] == 11
    assert survey_claim["selected_e_scooter"] == 5
    assert survey_claim["expanded_followup_responses"] == 23
    assert survey_claim["reported_concrete_consequence"] == 11
    assert survey_claim["reported_missed_class_content"] == 6
    assert survey_claim["reported_course_choice_effect"] == 2
    assert survey_claim["reported_skipped_adjacent_activity"] == 3
    assert survey_claim["identity_course_pairs_and_times_independently_verified"] is False
    assert survey_claim["is_representative_sample"] is False


def test_published_article_matches_canonical_copy(built_site: Path) -> None:
    source_lines = [
        " ".join(line.strip().removeprefix("- ").split())
        for line in (ROOT / "article" / "article.md").read_text().splitlines()
        if line.strip()
    ]
    soup = BeautifulSoup((built_site / "index.html").read_text(), "html.parser")
    published_lines = [
        " ".join(element.get_text(" ", strip=True).split())
        for element in soup.select("#edited-article [data-source-line]")
    ]

    assert published_lines == source_lines


def test_main_article_keeps_technical_material_compact(built_site: Path) -> None:
    soup = BeautifulSoup((built_site / "index.html").read_text(), "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())

    assert "What the model cannot answer" not in text
    assert not soup.select(".source-list, .method-stats, .verified-route-table")
    assert len(soup.select(".source-summary p")) == 3
    assert soup.select_one('a[href="methodology.html"]')
    assert soup.select_one('a[href="source-log.html"]')
    assert soup.select_one('a[href="data/claim_audit.json"]')
