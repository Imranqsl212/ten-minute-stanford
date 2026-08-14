import json
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "submission" / "article_draft.md"


def _visible_markdown(text: str) -> str:
    text = re.sub(r"!\[[^]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(
        r"^(?:#{2,3}|CAPTION:|CALLOUT:|LABEL:)\s*",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = " ".join(text.split())
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def test_submission_has_required_article_fields_and_sources() -> None:
    text = DRAFT.read_text(encoding="utf-8")

    for field in ("TITLE:", "SLUG:", "AUTHORS:", "CONTENT"):
        assert field in text
    assert "Imran Zakirov and Alisher Sabitov" in text
    assert len(set(re.findall(r"https://[^)\s]+", text))) >= 3
    assert "[REPORTING NEEDED" not in text


def test_submission_numbers_match_audited_analysis() -> None:
    text = DRAFT.read_text(encoding="utf-8")
    summary = json.loads((ROOT / "reports" / "generated" / "analysis_summary.json").read_text())
    three_mph = next(
        row for row in summary["walking_speed_results"] if row["walking_speed_mph"] == 3.0
    )
    passing_periods = pd.read_csv(
        ROOT / "reports" / "generated" / "tables" / "passing_period_scenarios.csv"
    ).set_index(["passing_period_minutes", "walking_speed_mph", "building_overhead_minutes"])

    required = (
        f"{summary['api_unique_sections']:,}",
        f"{summary['mapped_physical_meeting_day_rows']:,}",
        f"{summary['unique_mapped_facilities']:,}",
        f"{summary['potential_adjacent_meeting_pairs']:,}",
        f"{three_mph['share_within_10_minutes']:.1%}",
        f"{three_mph['share_within_10_minutes_with_2min_overhead']:.1%}",
        f"{summary['three_mph_median_route_minutes']:.1f}",
        f"{summary['three_mph_p90_route_minutes']:.1f}",
        f"{summary['lecture_component_meeting_day_rows']:,}",
        f"{summary['discussion_component_meeting_day_rows']:,}",
        f"{summary['large_enrollment_unique_different_building_pairs']:,}",
        f"{summary['large_enrollment_pairs_over_10min_3mph']:,}",
        f"{passing_periods.loc[(15, 3.0, 0), 'share_feasible']:.1%}",
        f"{passing_periods.loc[(15, 3.0, 2), 'share_feasible']:.1%}",
    )
    for value in required:
        assert value in text


def test_submission_course_examples_match_audited_cases() -> None:
    text = DRAFT.read_text(encoding="utf-8")
    cases = pd.read_csv(ROOT / "reports" / "generated" / "tables" / "course_transition_cases.csv")

    for row in cases.itertuples(index=False):
        assert row.origin_course_number in text
        assert row.destination_course_number in text
        formatted_minutes = f"{row.walk_minutes_3_0mph:.1f}"
        natural_minutes = formatted_minutes.removesuffix(".0")
        assert formatted_minutes in text or natural_minutes in text


def test_submission_includes_student_survey_and_limitation() -> None:
    text = _visible_markdown(DRAFT.read_text(encoding="utf-8"))

    assert "What 27 Stanford students have added" in text
    assert "20 participants (74%)" in text
    assert "Eleven cited a specific consequence beyond arrival time" in text
    assert "Twenty-one people selected walking, 11 selected biking" in text
    assert "not a representative sample of Stanford students" in text
    assert "were not independently verified" in text


def test_submission_includes_the_editorial_takeaways() -> None:
    text = _visible_markdown(DRAFT.read_text(encoding="utf-8"))

    assert "What the numbers actually say" in text
    assert "Typical is not universal" in text
    assert "82.5% to 69.0%" in text
    assert "not observed trips or late arrivals" in text


def test_submission_preserves_canonical_article_copy_in_order() -> None:
    draft = _visible_markdown(DRAFT.read_text(encoding="utf-8"))
    canonical_lines = (ROOT / "article" / "article.md").read_text(encoding="utf-8").splitlines()

    cursor = 0
    for line in canonical_lines:
        visible_line = _visible_markdown(line)
        if not visible_line:
            continue
        position = draft.find(visible_line, cursor)
        assert position >= 0, f"Canonical website copy is missing or out of order: {line}"
        cursor = position + len(visible_line)


def test_submission_includes_every_website_figure_and_caption() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    draft_visible = _visible_markdown(draft)
    page = BeautifulSoup(
        (ROOT / "site" / "index.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    figures = [figure for figure in page.select("figure") if figure.find("img")]

    assert len(figures) == 8
    for figure in figures:
        image = figure.find("img")
        assert Path(str(image["src"])).name in draft
        assert str(image["alt"]) in draft
        caption = _visible_markdown(figure.find("figcaption").get_text(" ", strip=True))
        assert caption in draft_visible


def test_submission_includes_website_labels_cards_and_route_copy() -> None:
    draft_visible = _visible_markdown(DRAFT.read_text(encoding="utf-8"))
    page = BeautifulSoup(
        (ROOT / "site" / "index.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    selectors = (
        ".eyebrow",
        ".transition-case",
        ".history-card",
        ".route-lab-header h2",
        ".route-lab-header > p",
        ".policy-copy h3",
        ".policy-copy > p",
        ".route-lab-footer > p",
    )

    for selector in selectors:
        for element in page.select(selector):
            website_text = _visible_markdown(element.get_text(" ", strip=True))
            assert website_text in draft_visible

    assert "Try the interactive route checker." not in draft_visible
