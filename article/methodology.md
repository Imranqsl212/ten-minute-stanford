# Methodology: The Ten-Minute Stanford

## Research question

For pairs of physical class meetings in Stanford's published Winter 2026
schedule that are ten minutes apart, what share of shortest walking- and
bicycle-network routes fit inside that interval under stated speed assumptions?

The project does not estimate actual student trips, co-enrollment or lateness.

## Snapshot and sources

- ExploreCourses mobile schedule pages were collected on Aug. 3, 2026, from
  10:38 to 10:43 UTC. Public ExploreCourses XML responses were collected on
  Aug. 5, 2026, from 05:02 to 05:05 UTC and are the canonical schedule source.
  ExploreCourses says its course and class data are refreshed daily and no more
  than 24 hours old, although Axess is the latest source for students.
- Stanford Campus Map room searches were collected on Aug. 3, 2026, from 10:24
  to 10:48 UTC. The Computing and Data Science building lookup used to correct
  CoDa classroom locations was retrieved on Oct. 16, 2026, at 14:41:38 UTC.
- The OpenStreetMap walking-network snapshot was collected through Overpass on
  Aug. 3, 2026, at 10:24 UTC. The response identifies the underlying OSM
  database state as `2026-08-03T10:23:14Z`.
- The academic-year parameter was `20252026`; this release analyzes the Winter
  term only.

Every active raw response in the local audit snapshot is cached with its source
URL, retrieval time and SHA-256 digest. The raw bodies are not committed to Git;
repeating the requests later may return changed content and cannot reconstruct
the historical bodies.

## Schedule collection and API verification

The collector discovered 253 subject codes from the public ExploreCourses
mobile index. It requested 579 paginated mobile result pages and 253 XML
department queries. The XML request structure and field mapping follow
[`jeremyephron/explore-courses-api`](https://github.com/jeremyephron/explore-courses-api),
which uses ExploreCourses' public `xml-20200810` view. This project parses the
current XML directly rather than depending on the older package at runtime.
The package is a third-party code reference, not an official Stanford
publication. Its [request
implementation](https://github.com/jeremyephron/explore-courses-api/blob/master/explorecourses/course_connection.py)
and [XML class
mapping](https://github.com/jeremyephron/explore-courses-api/blob/master/explorecourses/classes.py)
document the request pattern and field names. All 253 exact Stanford request
URLs and response hashes are recorded in
`reports/generated/source_manifest.json`.

The API returned 27,197 Winter section records. Every local section class number
matched an XML section, and every XML section had `currentClassSize` and
`maxClassSize`. Sections without a complete date, time and weekday were not
treated as meetings. Multi-day schedules were expanded to one meeting-day row
per weekday, producing 6,876 canonical rows.

The mobile HTML snapshot remains an independent parser check. Of its 6,871
previously accepted meeting-day rows, 6,868 matched XML exactly on class number,
dates, weekday, times and room. The other three exposed HTML parsing errors in
INTNLREL 183 and ESS 71. XML also supplied valid values for five rows that the
HTML parser had previously isolated as anomalies in EDUC 228G and CS/LINGUIST
180. The old discrepancies remain in audit files; they are not exclusions from
the API-canonical meeting table.

## Eligibility and cross-listings

Eligible rows were non-cancelled, in-person meetings on Monday through Friday
with a queryable room label, start time, end time and date range. Remote listings,
weekend meetings and listings without a queryable room label, including
departmental-room placeholders, were not used.

The eligible set contained 6,026 section-listing meeting-day rows. Campus Map
matching resolved 5,848, a 97.05% row-level mapping rate.

Cross-listed courses can produce several section records for one physical
class. Records with the same room, facility, weekday, start and end time, start
date and end date were counted as one physical meeting. This removed 1,394
duplicate listings and produced 4,454 mapped physical meeting-day rows. The
original course labels and listing counts remain in the processed data.

## Room matching

The collector queried 384 unique ExploreCourses room labels against Stanford
Campus Map. It found 138 exact matches and 221 reproducible fallback matches; 25
labels remained unresolved. Fallbacks broadened room labels to verified
building names, for example `Lathrop 294` to `Lathrop Library` and `LAW 280A` to
the Law School address at 559 Nathan Abbott Way. The lookup table preserves the
original room, query used, match label, status, facility ID and coordinates.

On Oct. 16, 2026, we corrected an erroneous fallback that had assigned the
room labels `CODAB60`, `CODAB80` and `CODAB90` to Cordura Hall. Stanford's
[Campus Map result for Computing and Data Science](https://campus-map.stanford.edu/report-cm.cfm?criteria=Computing+and+Data+Science&orig_srch=Computing+and+Data+Science&matches=1&hidden=)
identifies CoDa as facility `07-430` at 389 Jane Stanford Way, with coordinates
37.429924, -122.171780. We rebuilt both route matrices and every dependent
statistic using that location. The Winter 2026 schedule, saved OSM network,
meeting counts and pair denominator remained unchanged. The previously
misidentified Building 200-to-CoDa route now takes 7.2 modeled minutes at
3 mph, rather than the 14.1 minutes calculated using Cordura Hall's location.
The original inputs and correction provenance are retained in
`reports/corrections/coda-2026-10-16/`.

The 25 unresolved labels account for 178 rows, or 3.0% of otherwise eligible
section-listing meeting-day rows. Some labels may be inferable from other
Stanford pages, but the active Campus Map query snapshot did not return an
unambiguous reproducible match. They were therefore excluded rather than
assigned guessed coordinates.

Analysis labels are aggregated at the Campus Map facility level. A facility can
contain several named rooms: Bishop Auditorium and multiple Lathrop room labels,
for example, resolve to facility 08-350 and are reported under its official
building label, Lathrop Library.

## Walking network and routes

An Overpass query downloaded highway-tagged OpenStreetMap ways in a bounding
box containing Stanford's main campus, the medical center and nearby campus
facilities. The graph retained ways whose OSM access tags permit walking. Ways
tagged as indoor or as corridors were excluded.
`foot=no` and `foot=private` were excluded; `access=no` and `access=private` were
excluded unless `foot` explicitly allowed walking. The graph treats retained
segments as undirected.

The retained data initially formed 222 components with 116,885 nodes and
133,653 unique undirected graph edges. Routing used the largest connected
component: 114,337 nodes and 131,249 unique edges. All 75 facility points snapped to this
component within 61.0 meters; the median snap distance was 19.0 meters. For each
ordered facility pair, Dijkstra's algorithm found the shortest network
distance. Straight-line distances from each facility point to its nearest graph
node were added at both ends. These connectors are not path-verified and may
cross a building edge, fence or other barrier. Same-facility routes were assigned
zero modeled network meters.

The model uses one Campus Map coordinate per facility, not a verified door. It
does not model indoor travel, elevation, construction, crowds or route
preference. Excluding ways tagged indoor does not prove that every retained way
is outdoors, because OpenStreetMap tags can be incomplete or incorrect.

## Bicycle network and routes

The bicycle graph uses the same OSM snapshot but a separate filter. It excludes
steps, indoor ways, `bicycle=no`, `bicycle=private`, `bicycle=dismount`, and
restricted ways without an explicit bicycle override. Footways and pedestrian
ways are retained only when bicycle access is explicitly `yes`, `designated` or
`permissive`. Generic and bicycle-specific one-way tags are respected, so bike
routes are directional.

Before component filtering, the bicycle graph contained 86,694 nodes and 91,630
edge segments in 194 weakly connected components. Routing used the largest
component with 84,225 nodes and 166,688 directed edges. All 75 facilities
snapped within 75.9 meters, with a 36.1-meter median. All 5,625 directed facility
pairs were connected.

Facility points are not bike racks. The model does not include retrieving or
parking a bicycle, walking it through a restricted area, or verifying whether a
straight facility-to-network connector is legally rideable.

## Potential adjacent meetings

For each physical meeting, the code joined every different physical meeting
that:

- occurred in the same term and on the same weekday;
- began exactly ten minutes after the first meeting ended; and
- had at least one occurrence of that weekday inside the overlap of their active
  date ranges.

The date-overlap join initially produced 284,226 pair rows. It excluded 1
same-class-number pair-date row linking two consecutive CHEMENG 20 meeting
records in the same room under class number 7240. This defensive rule prevents
two meeting records from the same class section from being treated as a
class-to-class transition and left 284,225 rows before recurrence deduplication.

Repeated date blocks for the same ordered class-number pair, facility pair,
weekday and time were then counted once, removing 1,146 duplicate recurrences
and leaving 283,079 ordered potential pairs. Every pair had a route in both
connected networks. Each pair receives equal weight. These are possible schedule
combinations, not evidence that a student enrolled in either or both classes.

### Course-level examples

The four examples in the article are selected reproducibly from different-building
pairs. The code chooses the pair closest to the overall median among routes of
eight minutes or less, the pair closest to 9.5 minutes among routes from nine to
ten minutes, the pair closest to 12 minutes among routes from 11.5 to 12.5
minutes, and the longest modeled pair. Ties are resolved by weekday, passing
period and class numbers. These cases illustrate the modeled range; they are not
a sample of observed student schedules or trips.

## Student survey

The project compiles 27 responses from people the authors identify as Stanford
students. The [linked Google
Sheet](https://docs.google.com/spreadsheets/d/1gF9X8H8e44hamMNEyIAbUJVcV6Bubre1K2IJJMwd5ZI/edit?gid=1824059912#gid=1824059912)
exported 26 response rows on Aug. 12, 2026. One response retained from the
project's earlier reporting file was not present in that export; it was added
to the normalized file as a separate source batch. Unique respondent IDs leave
27 rows. The checked-in reporting file contains answers but no names or contact
information.

Four respondents received the original questionnaire and 23 received an
expanded version. Fourteen of 27 selected one of the two yes responses to the
lateness question, six selected the close-call response and seven selected
never. Travel mode allowed multiple selections: 21 selected walking, 11 biking
and five an e-scooter.

For the 23 expanded responses, the authors manually coded the open-text impact
answer into one mutually exclusive category: no concrete consequence, missed
class content or an announcement, course-choice effect, or a skipped adjacent
activity such as office hours, a study group or lunch. Eleven described one of
the three concrete consequences: six, two and three responses respectively.
The summary also separately records self-reported transition estimates and
claims of an exact ten-minute class gap; neither was independently verified or
used as an input to the route model.

This is an illustrative convenience sample, not a representative survey. The
authors did not independently verify respondent identities, course pairs,
meeting gaps or travel times. The results describe these 27 responses only and
cannot estimate prevalence among Stanford students. Normalized free-text
answers and coding fields are retained in
`reporting/student_survey_responses.csv`; audited aggregate counts are in
`reports/generated/tables/student_survey_summary.csv`.

## Time slots, enrollment and speed scenarios

Pairs were grouped by their actual published end and start times. The result has
25 distinct end-to-start slots and 92 weekday-slot combinations. Counts of
reported enrollment leaving and arriving at each slot are sums of section
enrollment attached to scheduled physical meetings. They are seat instances,
not unique students, observed attendance or route flows.

### Lecture and discussion timing

[Stanford Academic Advising](https://advising.stanford.edu/current-students/advising-student-handbook/course-catalog)
defines `LEC` as a lecture course and `DIS` as the discussion-section component
of a lecture course. The component analysis uses
eligible section-listing meeting-day rows before room matching, so unresolved
rooms do not disappear from the timing comparison. It includes 2,035 LEC rows
and 911 DIS rows.

Start times were grouped into five fixed bins: before 10:30 a.m., 10:30 to 11:59
a.m., noon to 2:29 p.m., 2:30 to 4:29 p.m., and 4:30 p.m. or later. Median start
times and Thursday/Friday shares were calculated directly from the same rows.
A section scheduled on multiple weekdays contributes one row per listed
weekday; these counts therefore describe the published timetable rather than
unique sections, students or attendance.

The route comparison then filters the main pair table to the 62,525 possible
pairs for which both origin and destination components are `LEC` or `DIS`. It
reports pair counts, median and 90th-percentile route times, and shares within
and above ten minutes for `LEC` to `LEC`, `LEC` to `DIS`, `DIS` to `LEC` and
`DIS` to `DIS`. These remain equally weighted possible meeting pairs, not
observed student transitions.

### Subject-area locations

The ExploreCourses subject index supplied 253 code-label pairs. Stanford's
[SIRIS terminology](https://siris.stanford.edu/sites/g/files/sbiybj16456/files/media/file/common-terms-in-siris-student-analytics.pdf)
says a subject usually represents a domain of study offered by an academic
organization but can instead identify a curricular category. The analysis uses
the term "subject area" and does not treat every code as a formal department.

The location table groups the 5,848 mapped section-listing meeting-day rows by
published subject code and Campus Map facility. For each subject, it reports the
share at every mapped facility and ranks the facilities by row count. The chart
shows the most-used facility for the 15 subject areas with the largest mapped
row totals. Cross-listed listings remain under each published subject code, and
the 178 eligible rows with unresolved room labels are excluded from this
geographic comparison.

For the route comparison, every deduplicated physical meeting retains all of
its published subject codes. Each possible pair is attributed to every subject
represented at its origin for outgoing measures and every subject represented
at its destination for incoming measures. The resulting table covers 161
subject areas and reports pair counts, median and 90th-percentile route times,
and shares within and above ten minutes in both directions. Because a
cross-listed physical meeting can belong to several subject codes, counts
across subject rows must not be added to recover the campus-wide denominator.

### Large-enrollment screen

[Stanford Student Services](https://studentservices.stanford.edu/my-academics/enroll-classes/enrollment-troubleshooting)
says cross-listed classes are typically scheduled as combined sections sharing
a time and place and describes total enrollment as spanning the combined
sections. For records grouped into one physical meeting,
the analysis sums the reported section enrollment and retains the combined
course labels.

The screen starts from the same routed possible meeting pairs as the main
analysis. It keeps different-building combinations for which both physical
meetings report at least 100 enrolled, then collapses identical
course-time-building combinations that recur on multiple weekdays. The result
is 187 unique combinations; 15 exceed ten modeled minutes at 3 mph. The smaller
of the two reported enrollment values is shown only to demonstrate that both
meetings pass the threshold. It is not a co-enrollment estimate, a traffic count
or evidence that any student took both meetings.

Enrollment is not used to weight route pairs. A valid student weight would
require co-enrollment: the number of students taking both the origin and
destination sections. Multiplying, averaging or taking the minimum of two class
sizes would create an unsupported estimate of that missing overlap.

Network distance was converted to time at 2, 3 and 4 miles per hour. These are
sensitivity scenarios, not measured population groups and not labels for
disabled or nondisabled students.

A second scenario reserves two of the ten minutes for leaving and entering
buildings, so the modeled network route must take eight minutes or less. The two-minute
allowance is illustrative, not an empirical estimate. Same-building travel is
also imperfectly represented, because vertical and indoor movement can take
more than the allowance.

The same pair denominator was also tested with 12- and 15-minute time budgets.
At 3 mph, 84.4% of pairs fit within 10 route minutes, 91.4% within 12 and 97.5%
within 15. With two minutes reserved for buildings, the corresponding shares
are 70.6%, 84.4% and 94.3%. The 12-minute case is hypothetical. The 15-minute
case is a historical comparison with the AY 2021-22 meeting pattern documented
in prior Daily reporting and its linked schedule sheet; it is not a current
policy claim or an analysis of 2021 course locations.

Bicycle distance was converted at 6, 8 and 10 mph. Stanford's published maximum
in the central Pedestrian Zone is 10 mph; none of the three speeds is presented
as an observed campus average. The bicycle two-minute scenario represents
illustrative handling and building-transition time, not a measured estimate.

## Principal limitations

- No student-level schedules or co-enrollment are available.
- The API reports section enrollment, but those counts cannot identify actual
  class-to-class student flows.
- Published times and rooms can change, and Axess may differ from the snapshot.
- Cross-listing deduplication is rule-based and may not capture every
  administrative duplicate.
- A shortest network route may not be the route a person takes.
- Campus Map coordinates are facility points rather than audited entrances.
- Straight-line facility-to-network connectors are not path-verified and may
  cross barriers.
- Neither graph was validated as a wheelchair-routing network or against
  accessible building entrances.
- Indoor and corridor tags are filtered when present, but OSM tags can be missing
  or incorrect.
- Unmapped rooms are excluded, which can introduce geographic bias.
- Facility-level aggregation can combine named spaces inside one Campus Map
  facility.
- Routing is limited to the largest connected OSM walking component; it is not
  evidence that every modeled segment is the route a student would choose.
- The bicycle graph does not model bike availability, racks, parking, mounting,
  dismounting or field-verified legal access.
- Across all 30,835 highway ways in the saved OSM snapshot, 51 ways (0.17%) have
  a `wheelchair` tag and 128 (0.42%) have an `incline` tag. OSM documents these
  at <https://wiki.openstreetmap.org/wiki/Key:wheelchair> and
  <https://wiki.openstreetmap.org/wiki/Key:incline>. Missing tags do not establish
  that a way is inaccessible or flat. No wheelchair travel-time result is reported. Use
  Stanford's Campus Access Guide for building-specific access information.
- The model does not measure lateness, instructor behavior, buses, weather,
  construction or crowding.

## Reproduction

From the project directory:

```bash
make install
make test
make all
make audit
```

The collector is cached and rate-limited. `reports/generated/validation.json`
contains collection and routing counts;
`reports/generated/analysis_summary.json` contains the figures used in the
article. `reports/generated/claim_audit.json` maps reported claims to evidence,
assumptions and unsupported inferences. Its external-context section records
source URLs, supporting claims, check dates and verification statuses; CI
validates those records but does not refetch the web. Refreshing source data
can change every result.
