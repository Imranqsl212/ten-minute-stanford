from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTING_DIR = PROJECT_ROOT / "reporting"
REPORT_DIR = PROJECT_ROOT / "reports" / "generated"
TABLE_DIR = REPORT_DIR / "tables"
FIGURE_DIR = REPORT_DIR / "figures"

EXPLORE_BASE = "https://explorecourses.stanford.edu"
CAMPUS_MAP_BASE = "https://campus-map.stanford.edu"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

ACADEMIC_YEAR = "20252026"
TERMS = ("Autumn", "Winter", "Spring")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
WALKING_SPEEDS_MPH = (2.0, 3.0, 4.0)
BICYCLE_SPEEDS_MPH = (6.0, 8.0, 10.0)

# Includes the main academic campus, medical center and nearby campus facilities while
# excluding Redwood City and SLAC. Coordinates are WGS84.
CAMPUS_BBOX = (37.395, -122.220, 37.475, -122.120)

USER_AGENT = (
    "TenMinuteStanford/0.1 educational data-journalism project; "
    "cached and rate-limited public-data collection"
)


@dataclass(frozen=True)
class Paths:
    raw: Path = RAW_DIR
    processed: Path = PROCESSED_DIR
    reports: Path = REPORT_DIR
    tables: Path = TABLE_DIR
    figures: Path = FIGURE_DIR

    def create(self) -> None:
        for path in (self.raw, self.processed, self.reports, self.tables, self.figures):
            path.mkdir(parents=True, exist_ok=True)
