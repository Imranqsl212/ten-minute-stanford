# Data documentation

## Provenance

The analysis combines three public sources:

- Stanford ExploreCourses XML for Winter 2026 meeting dates, weekdays, times,
  room labels, enrollment and capacity, using the request and field conventions
  from `jeremyephron/explore-courses-api`;
- Stanford Campus Map for facility IDs, labels, addresses and coordinates;
- OpenStreetMap, retrieved through Overpass, for highway-tagged geometry filtered
  into separate walking and directional bicycle networks.

Collection times, source URLs and hashes are described in `article/source_log.md`, `reports/generated/source_manifest.json` and `reports/generated/validation.json`.

## Repository policy

`data/raw/` is excluded from Git. The cached HTML, XML and OSM responses total roughly 350 MB. The rate-limited collector can repeat the requests, but a later collection cannot recover the historical Aug. 3 and Aug. 5 bodies if a source changes. Do not commit credentials, authenticated pages or student-level data.

`data/processed/` contains the public-data snapshot used by the checked-in analysis:

| File | Unit |
|---|---|
| `sections.csv` | Parsed ExploreCourses section listing |
| `meetings.csv` | One canonical XML meeting weekday per section listing |
| `subject_catalog.csv` | One ExploreCourses subject code and public label |
| `explorecourses_api_sections.csv` | One XML API section per class number |
| `explorecourses_api_schedules.csv` | Canonical XML API meeting-day rows |
| `explorecourses_api_schedule_verification.csv` | Mobile HTML-to-XML comparison |
| `room_lookup.csv` | One decision per unique source room label |
| `facilities.csv` | One resolved Campus Map facility |
| `route_distances.csv` | One ordered facility-to-facility route |
| `walk_edges.csv` | One retained OpenStreetMap network segment |
| `bike_route_distances.csv` | One directed facility-to-facility bicycle route |
| `bike_edges.csv` | One retained directional-capable bicycle segment |
| `bike_facilities.csv` | Facility snaps to the bicycle network |
| `invalid_meeting_dates_excluded.csv` | Mobile HTML date-parser discrepancy retained for XML comparison |
| `invalid_meeting_times_excluded.csv` | Mobile HTML time-parser discrepancies retained for XML comparison |

Generated analytical tables live in `reports/generated/tables/`.
`component_time_summary.csv` and `component_day_summary.csv` compare eligible
lecture and discussion meeting-day rows. `component_transition_summary.csv`
tests all four directional LEC/DIS pair types against the ten-minute route
model. `department_location_summary.csv` groups mapped listing-day rows by
published subject code and Campus Map facility.
`subject_transition_feasibility.csv` reports incoming and outgoing pair counts
and route feasibility for each subject area; cross-listed pairs can appear under
more than one subject code, so subject totals are not additive.
`high_enrollment_transitions.csv` contains unique possible
different-building combinations where both meetings report at least 100
enrolled; it is a size screen, not co-enrollment.

`reporting/student_survey_responses.csv` contains four author-supplied survey
responses without names or contact information. `student_survey_summary.csv`
reproduces the response counts used in the story. The survey is a convenience
sample and is not used to estimate campus-wide prevalence.

`course_transition_cases.csv` contains four deterministic course-level examples
selected near the overall median, near ten minutes, near twelve minutes and at
the longest modeled route time. They illustrate the range and are not a sample
of student trips.

`passing_period_scenarios.csv` applies 10-, 12- and 15-minute route budgets to
the same Winter 2026 potential meeting pairs at 2, 3 and 4 mph, both with and
without a two-minute building allowance. The 12-minute case is hypothetical;
the 15-minute case is a historical comparison, not a current schedule claim.

## Important distinctions

- A section listing is an administrative record.
- A physical meeting collapses cross-listed records sharing room and time.
- A potential adjacent pair is a schedule combination, not a student trip.
- Reported enrollment is a section count, not co-enrollment or route flow.
- A route is a shortest-network estimate, not a measured path.
- Ways tagged indoor or corridor are excluded, and facilities are snapped to the
  largest connected retained walking component. Missing tags can remain.
- Straight-line facility-to-network snap connectors are included in distances;
  they are not path-verified.
- Bicycle routes honor mapped one-way and bicycle-access tags but do not model
  bike availability, parking or dismounting.
- Neither graph was validated for wheelchair routing or accessible entrances;
  use Stanford's Campus Access Guide for building-specific accessibility information.

## Refresh

```bash
python -m ten_minute_stanford collect --terms Winter --refresh
python -m ten_minute_stanford analyze
python -m ten_minute_stanford visuals
python scripts/audit_publication.py --require-raw --write
```

Refreshing data can change every reported number. Review validation outputs and article language before publishing updated results.

Use `make year-analysis` on a separate branch to collect Autumn, Winter and
Spring. Multi-quarter collection overwrites the Winter-only processed and
generated outputs; it is not part of the currently reported result.
