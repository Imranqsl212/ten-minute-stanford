# Source log

## Evidence types

- **Official Stanford sources:** ExploreCourses responses, Campus Map results,
  Bulletin guidance, Transportation rules and the Campus Access Guide are hosted
  on Stanford-operated domains. Only sources in this category support claims
  about Stanford policy, guidance or official systems.
- **External open data:** OpenStreetMap supplies the saved route-network snapshot
  and its documentation explains the tags and license. It is not an official
  Stanford source.
- **Third-party reference:** the mentor-recommended Explore Courses Python API is
  not an official Stanford publication. It supplies the XML request pattern and
  field reference; this project downloads and parses Stanford responses directly.
  It does not support claims about Stanford policy or the project's results.
- **Editorial context:** Stanford Daily links and the historical Google Sheet
  supply attributed prior reporting and an AY 2021-22 schedule artifact. They
  are not current policy, analytical inputs or evidence of Winter 2026 student
  outcomes.
- **Author-conducted reporting:** 27 responses from people the authors identify
  as Stanford students supply illustrative experiences, consequences and route
  comments. This convenience sample is not an official Stanford source and
  does not support a campus-wide prevalence estimate.
- **Derived results:** 27,197 sections, 283,079 potential pairs, 25 slots,
  component-pair and subject-area comparisons, and the walking/bicycle
  percentages are project calculations, not Stanford statistics. Their evidence
  is in the generated CSV and JSON audit artifacts below.

The route and schedule analysis has three public-data inputs: Stanford
ExploreCourses responses, Stanford Campus Map responses and the saved
OpenStreetMap snapshot. The 27-response survey is separate author-conducted
reporting and is not an input to the route model. GitHub code and Stanford Daily
pages do not supply any numerical result.

## Primary data

- [Stanford ExploreCourses](https://explorecourses.stanford.edu/): Winter 2026
  section dates, weekdays, times, class numbers, components, room labels,
  enrollment and capacity from the public XML view.
- [Explore Courses Python
  API](https://github.com/jeremyephron/explore-courses-api): mentor-recommended
  reference for the `xml-20200810` request structure and XML field mapping. The
  project parses current public responses directly.
- [CourseConnection request
  implementation](https://github.com/jeremyephron/explore-courses-api/blob/master/explorecourses/course_connection.py):
  third-party code reference for the XML view, active-course filter, department
  filter and academic-year request fields.
- [Explore Courses XML class
  mapping](https://github.com/jeremyephron/explore-courses-api/blob/master/explorecourses/classes.py):
  third-party XML field reference.
- [Example live Stanford XML
  response](https://explorecourses.stanford.edu/search?view=xml-20200810&filter-coursestatus-Active=on&q=AA&filter-departmentcode-AA=on&filter-term-Winter=on&academicYear=20252026):
  one of 253 official endpoint URLs recorded in the source manifest.
- [About ExploreCourses](https://explorecourses.stanford.edu/about): source
  description, schedule coverage and stated daily refresh cadence.
- [Stanford Academic Advising: Understanding the Course
  Catalog](https://advising.stanford.edu/current-students/advising-student-handbook/course-catalog):
  official definitions of `LEC`, `DIS` and other class component codes.
- [Stanford Student Services: Enrollment Components and Troubleshooting
  Tips](https://studentservices.stanford.edu/my-academics/enroll-classes/enrollment-troubleshooting):
  explains that cross-listed classes are typically combined at the same time
  and place and that total enrollment spans combined sections.
- [Stanford SIRIS: Common Terms in Student
  Analytics](https://siris.stanford.edu/sites/g/files/sbiybj16456/files/media/file/common-terms-in-siris-student-analytics.pdf):
  official definitions for class components, cross-listed classes and subject
  codes, including the warning that a subject can be a curricular category.
- [Stanford Campus Map](https://campus-map.stanford.edu/): official facility
  IDs, room/building search labels, addresses and coordinates.
- [Stanford Campus Map FAQ](https://campus-map.stanford.edu/faq/FAQ.html):
  confirms that the map is maintained by Stanford LBRE and supports searches
  by building, room, facility ID and address.
- [Project student-survey response
  sheet](https://docs.google.com/spreadsheets/d/1gF9X8H8e44hamMNEyIAbUJVcV6Bubre1K2IJJMwd5ZI/edit?gid=1824059912#gid=1824059912):
  author-conducted reporting, not an official Stanford dataset. The Aug. 12,
  2026 export contained 26 rows; the normalized reporting file also retains one
  earlier response absent from that export, for 27 unique responses in total.
- [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright):
  highway-tagged ways and nodes filtered into the modeled walking and bicycle networks,
  retrieved through the
  [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API). The response
  was retrieved at 10:24:58 UTC on Aug. 3, 2026 and reports an OSM database
  timestamp of `2026-08-03T10:23:14Z`.
- [OpenStreetMap wheelchair-tag
  documentation](https://wiki.openstreetmap.org/wiki/Key:wheelchair): documents
  explicit wheelchair values, notes that there is no default and identifies
  other physical-way tags relevant to wheelchair routing.
- [OpenStreetMap incline-tag
  documentation](https://wiki.openstreetmap.org/wiki/Key:incline): defines the
  way tag for grade, slope or incline.

## Context and framing

- [Stanford University Bulletin: Unit of
  Credit](https://bulletin.stanford.edu/pages/oCRJSOUvJspMtKMq0G4L): states
  that a class is assumed to end ten minutes early to allow movement to the
  next class.
- [Stanford Undergraduate Admission tips](https://admit.stanford.edu/advice):
  notes that classes often end ten minutes before the half-hour and warns
  visitors about class-change traffic.
- [Stanford University Bulletin: Standard Meeting
  Patterns](https://bulletin.stanford.edu/academic-polices/courses/standard-meeting-patterns):
  describes common meeting times and their role in reducing schedule conflicts.
  Its current grid is marked effective Autumn 2024. The policy also states that
  classroom assignment considers efficient use and room characteristics and
  sets a 75% enrollment-to-capacity threshold. The public page does not identify
  consecutive-student travel distance as an assignment objective.
- [Stanford bicycle laws](https://transportation.stanford.edu/getting-stanford/bike/education/comply-bike-laws):
  supports the 10 mph maximum in the central Pedestrian Zone and identifies
  places where riding is prohibited.
- [Stanford Bikeways
  Map](https://transportation.stanford.edu/sites/g/files/sbiybj27281/files/media/file/bikeways-map.pdf):
  official campus bicycle-route context; revised October 2024.
- [Stanford Campus Access Guide](https://maps.stanford.edu/ada/): official
  building-specific accessible entrance and disability access information.
- [Stanford Suggested Travel
  Routes](https://police.stanford.edu/suggested-travel-routes.html): official
  pedestrian and bicycle route guidance described as accessible, lighted and paved.
- [The Stanford Daily Data section](https://stanforddaily.com/category/data94305/):
  editorial-format comparison only; it does not support an analytical or Stanford
  factual claim.
- [The Daily's prior reporting on overlapping class
  times](https://stanforddaily.com/2021/09/14/overlapping-class-meeting-times-leave-students-stressed/):
  attributed historical reporting on the pre-pandemic 10-minute commuting
  break, the AY 2021-22 shift to 15-minute breaks and student experiences with
  partial schedule overlaps. It does not establish current policy or current
  student travel outcomes.
- [AY 2021-22 meeting-pattern
  spreadsheet](https://docs.google.com/spreadsheets/d/1Gxv03c2yyypmCF1Hot5VJ9f3Wi5LADMyjLsmiABhNsQ/edit?gid=1166637319#gid=1166637319):
  historical Google Sheet linked from the Daily story, which reported that the
  scheduling documents were provided by a University spokesperson. The visible
  `Opt 4` grid includes 60-minute starts at 8:30, 9:45 and 11:00 and 90-minute
  starts at 9:45 and 11:30, examples that display 15-minute intervals. It
  contains no current courses, rooms, co-enrollment or
  travel observations and is not treated as current official policy.
- [The Daily's submission page](https://stanforddaily.com/submitting-to-the-daily/):
  publication-process context only.

The original context set was checked on Aug. 4, 2026; API, bicycle, access and
historical schedule sources were checked on Aug. 5, 2026. Component, enrollment
and SIRIS terminology sources were checked on Aug. 7, 2026. The student survey
sheet was exported and checked on Aug. 12, 2026. Both Bulletin pages returned
HTTP 200 during the final direct check, and their exact supporting text was
present in the live HTML. Source URLs, supporting claims, check dates and
verification statuses are recorded in `reports/generated/claim_audit.json`.

## Local audit artifacts

- `data/raw/**.meta.json`: retrieval URLs, UTC timestamps and hashes.
- `data/processed/invalid_meeting_dates_excluded.csv`: one mobile HTML date-parser
  discrepancy retained for comparison with the XML API schedule.
- `data/processed/invalid_meeting_times_excluded.csv`: four zero-duration source
  HTML-parser records retained as a cross-source discrepancy audit; the XML API
  supplies valid canonical times.
- `data/processed/explorecourses_api_sections.csv`: one canonical API section row
  per Winter class number, including enrollment and capacity.
- `data/processed/explorecourses_api_schedules.csv`: canonical XML meeting-day rows.
- `data/processed/explorecourses_api_schedule_verification.csv`: exact HTML-to-XML
  schedule comparison.
- `data/processed/room_lookup.csv`: every room matching decision and fallback.
- `reports/generated/validation.json`: collection, geocoding and network counts.
- `reports/generated/analysis_summary.json`: final reported statistics.
- `reports/generated/tables/speed_summary.csv`: walking speed and building-time
  scenarios reported in the article.
- `reports/generated/tables/bicycle_speed_summary.csv`: bicycle speed and
  handling-time scenarios reported in the article.
- `reports/generated/tables/passing_period_scenarios.csv`: 10-, 12- and
  15-minute time-budget scenarios applied to the same potential Winter 2026
  pairs; the 15-minute case is a historical comparison, not current policy.
- `reports/generated/source_manifest.json`: URL, retrieval time and SHA-256 for
  each of the 1,278 active raw responses: 580 ExploreCourses HTML responses,
  253 ExploreCourses XML responses, 444 Campus Map responses and one OSM response.
- `reports/generated/publication_audit.json`: internal consistency checks
  against the processed data, generated tables and interactive payload.
- `reports/generated/claim_audit.json`: reported values, evidence paths,
  assumptions, external-context status and explicit unsupported inferences.
- `reports/generated/interactive/route_explorer.json`: simplified shortest-path
  walking and directional bicycle geometry plus passing-period scenarios.
- `reports/generated/tables/time_slot_summary.csv`: actual end-to-start slot analysis.
- `reports/generated/tables/weekday_time_slot_summary.csv`: weekday-specific slots.
- `reports/generated/tables/component_time_summary.csv`: LEC and DIS start-time
  distributions for eligible section-listing meeting-day rows.
- `reports/generated/tables/component_day_summary.csv`: LEC and DIS weekday
  distributions.
- `reports/generated/tables/component_transition_summary.csv`: route feasibility
  for all four directional LEC/DIS pair types.
- `reports/generated/tables/department_location_summary.csv`: mapped
  subject-area rows by Campus Map facility.
- `reports/generated/tables/subject_transition_feasibility.csv`: incoming and
  outgoing possible-pair route feasibility by published subject code.
- `reports/generated/tables/high_enrollment_transitions.csv`: the 187 unique
  different-building combinations in which both meetings report at least 100
  enrolled, including the 42 above ten modeled minutes at 3 mph.
- `reporting/student_survey_responses.csv`: 27 normalized responses recorded
  without names or contact information, including provenance and manual coding
  fields; the authors identify the respondents as Stanford students.
- `reports/generated/tables/student_survey_summary.csv`: reproducible counts
  for lateness, travel modes and coded impacts. The table describes the
  27-response convenience sample only.
- `reports/generated/tables/course_transition_examples.csv`: auditable examples
  with course numbers, class numbers, buildings and both route estimates.
- `reports/generated/tables/course_transition_cases.csv`: four independently
  audited course-level cases selected near the median, near 9.5 minutes, near
  12 minutes and at the longest modeled route time.

The OSM accessibility-coverage audit uses all 30,835 highway ways in the saved
bounding-box snapshot as its denominator. Only 51 ways have a `wheelchair` tag
and 128 have an `incline` tag. Missing tags do not mean inaccessible or flat;
they mean the snapshot is not sufficient for a defensible wheelchair-time model.
The exact counts and rates are published in `reports/generated/validation.json`.

## Attribution language

Prototype graphics should use: "Source: Stanford ExploreCourses and Stanford
Campus Map. Map data (ODbL): OpenStreetMap contributors." The Stanford Daily
name should be added to a credit only after editorial acceptance. Interactive
maps link contributor attribution to the OpenStreetMap copyright page.

Source check dates are recorded per URL in the claim ledger. This is an internal
publication-consistency audit, not an external replication.
