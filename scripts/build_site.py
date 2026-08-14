from __future__ import annotations

import argparse
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE_SOURCE = ROOT / "site"
FIGURE_SOURCE = ROOT / "reports" / "generated" / "figures"
REPORT_SOURCE = ROOT / "reports" / "generated"

PUBLISHED_DATA = (
    "analysis_summary.json",
    "claim_audit.json",
    "publication_audit.json",
    "source_manifest.json",
    "validation.json",
    "tables/speed_summary.csv",
    "tables/bicycle_speed_summary.csv",
    "tables/time_slot_summary.csv",
    "tables/weekday_time_slot_summary.csv",
    "tables/component_time_summary.csv",
    "tables/component_day_summary.csv",
    "tables/component_transition_summary.csv",
    "tables/department_location_summary.csv",
    "tables/subject_transition_feasibility.csv",
    "tables/high_enrollment_transitions.csv",
    "tables/student_survey_summary.csv",
    "tables/course_transition_examples.csv",
    "tables/course_transition_cases.csv",
    "tables/passing_period_scenarios.csv",
    "tables/top_constrained_routes.csv",
    "interactive/route_explorer.json",
)


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        reference = attributes.get("src") or attributes.get("href")
        if reference:
            self.references.append(reference)
        if srcset := attributes.get("srcset"):
            self.references.extend(
                candidate.strip().split()[0] for candidate in srcset.split(",") if candidate.strip()
            )
        if (
            tag == "meta"
            and attributes.get("property") in {"og:image", "twitter:image"}
            and (content := attributes.get("content"))
        ):
            self.references.append(content)


def validate_site(output_dir: Path) -> None:
    missing: list[str] = []
    for html_path in sorted(output_dir.rglob("*.html")):
        parser = ReferenceParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        for reference in parser.references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith("#"):
                continue
            relative_path = unquote(parsed.path)
            target = (
                output_dir / relative_path.lstrip("/")
                if relative_path.startswith("/")
                else html_path.parent / relative_path
            ).resolve()
            if not target.exists():
                missing.append(f"{html_path.relative_to(output_dir)} -> {reference}")
    if missing:
        details = "\n".join(f"- {reference}" for reference in missing)
        raise RuntimeError(f"Broken local references in Pages artifact:\n{details}")


def build_site(output_dir: Path) -> Path:
    output_dir = output_dir.resolve()
    if output_dir in {ROOT, SITE_SOURCE}:
        raise ValueError("Output directory must not replace repository or site sources")
    if output_dir.exists():
        shutil.rmtree(output_dir)

    shutil.copytree(SITE_SOURCE, output_dir)
    shutil.copytree(FIGURE_SOURCE, output_dir / "assets" / "figures")

    data_dir = output_dir / "data"
    for relative_path in PUBLISHED_DATA:
        source = REPORT_SOURCE / relative_path
        destination = data_dir / Path(relative_path).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (output_dir / ".nojekyll").touch()
    validate_site(output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages artifact.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "_site",
        help="Destination directory (default: ./_site)",
    )
    args = parser.parse_args()
    output = build_site(args.output)
    print(f"Pages artifact written to {output}")


if __name__ == "__main__":
    main()
