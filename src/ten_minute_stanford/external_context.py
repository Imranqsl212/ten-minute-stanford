from __future__ import annotations

VERIFICATION_SCOPE = (
    "Manual live content and HTTP verification; automated audits validate source "
    "classification and registry consistency but do not refetch the web."
)

_SOURCE_ENTRIES = (
    {
        "checked_on": "2026-08-04",
        "id": "explorecourses_schedule",
        "supports": (
            "Winter 2026 class numbers, meeting dates, weekdays, times, modalities "
            "and room labels used by the analysis."
        ),
        "url": "https://explorecourses.stanford.edu/",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "explorecourses_about",
        "supports": (
            "Schedule View contains current-year scheduled classes; ExploreCourses "
            "states that it refreshes daily and that data are no more than 24 hours "
            "old, while Axess has the latest scheduling information."
        ),
        "url": "https://explorecourses.stanford.edu/about",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-07",
        "id": "stanford_course_catalog_components",
        "supports": (
            "Stanford Academic Advising defines LEC as a lecture course and DIS "
            "as the discussion-section component of a lecture course, and notes "
            "that students usually enroll in each required component."
        ),
        "url": (
            "https://advising.stanford.edu/current-students/advising-student-"
            "handbook/course-catalog"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-07",
        "id": "stanford_enrollment_components",
        "supports": (
            "Stanford Student Services says cross-listed classes are typically "
            "scheduled as combined sections that meet at the same time and place, "
            "and explains that total enrollment spans the combined sections."
        ),
        "url": (
            "https://studentservices.stanford.edu/my-academics/enroll-classes/"
            "enrollment-troubleshooting"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-07",
        "id": "stanford_siris_common_terms",
        "supports": (
            "Stanford SIRIS defines class components, cross-listed classes and "
            "course-offering subjects; it notes that a subject usually represents "
            "a domain of study but can instead identify a curricular category."
        ),
        "url": (
            "https://siris.stanford.edu/sites/g/files/sbiybj16456/files/media/"
            "file/common-terms-in-siris-student-analytics.pdf"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "explorecourses_python_api",
        "supports": (
            "This is the landing page for the mentor-recommended third-party package; "
            "it is an implementation reference, not an official Stanford source."
        ),
        "url": "https://github.com/jeremyephron/explore-courses-api",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "explorecourses_api_request_code",
        "supports": (
            "The third-party request implementation queries Stanford ExploreCourses "
            "with the xml-20200810 view, active-course filter, department filter and "
            "academic-year parameter."
        ),
        "url": (
            "https://github.com/jeremyephron/explore-courses-api/blob/master/"
            "explorecourses/course_connection.py"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "explorecourses_api_field_mapping",
        "supports": (
            "The third-party XML classes map currentClassSize, maxClassSize and "
            "schedule dates, times, days and locations."
        ),
        "url": (
            "https://github.com/jeremyephron/explore-courses-api/blob/master/"
            "explorecourses/classes.py"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "campus_map",
        "supports": (
            "Facility IDs, result labels, addresses and coordinates used to resolve "
            "ExploreCourses room labels."
        ),
        "url": "https://campus-map.stanford.edu/",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "campus_map_faq",
        "supports": (
            "Campus Map supports searches by building or room name or number, "
            "facility ID and address; Stanford LBRE develops and maintains it."
        ),
        "url": "https://campus-map.stanford.edu/faq/FAQ.html",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "osm_license",
        "supports": (
            "OpenStreetMap data are licensed under ODbL; users must credit "
            "OpenStreetMap and contributors and make the license clear."
        ),
        "url": "https://www.openstreetmap.org/copyright",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "overpass_api",
        "supports": (
            "Overpass API is a read-only interface for selecting OpenStreetMap data; "
            "it was the retrieval mechanism for the checked-in OSM snapshot."
        ),
        "url": "https://wiki.openstreetmap.org/wiki/Overpass_API",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "osm_wheelchair_tag",
        "supports": (
            "OpenStreetMap documents wheelchair as an explicit, non-default access "
            "tag and identifies additional physical-way properties relevant to "
            "wheelchair routing."
        ),
        "url": "https://wiki.openstreetmap.org/wiki/Key:wheelchair",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "osm_incline_tag",
        "supports": (
            "OpenStreetMap documents incline as the tag for a way's grade, slope or "
            "incline and explains its directional interpretation."
        ),
        "url": "https://wiki.openstreetmap.org/wiki/Key:incline",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "bulletin_unit_of_credit",
        "supports": (
            "Stanford assumes that a class ends ten minutes early to allow movement "
            "to the next class."
        ),
        "url": "https://bulletin.stanford.edu/pages/oCRJSOUvJspMtKMq0G4L",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "bulletin_standard_meeting_patterns",
        "supports": (
            "Stanford describes standard class meeting patterns as common meeting "
            "times intended to reduce course conflicts; its current grid is marked "
            "effective Autumn 2024. The policy also says "
            "classroom space is assigned for efficient use and room characteristics "
            "and sets a 75% enrollment-to-capacity threshold."
        ),
        "url": (
            "https://bulletin.stanford.edu/academic-polices/courses/"
            "standard-meeting-patterns"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "admission_class_change_advice",
        "supports": (
            "Stanford admission guidance says classes often end ten minutes before "
            "the half-hour and warns visitors about class-change bike traffic."
        ),
        "url": "https://admit.stanford.edu/advice",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "stanford_bicycle_laws",
        "supports": (
            "Stanford sets a 10 mph maximum bicycle speed in the Pedestrian Zone "
            "and lists campus locations where bicycle riding is prohibited."
        ),
        "url": (
            "https://transportation.stanford.edu/getting-stanford/bike/education/"
            "comply-bike-laws"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "stanford_bikeways_map",
        "supports": (
            "Stanford publishes a campus Bikeways Map revised in October 2024; "
            "it is context, not geometry used by the OSM route calculation."
        ),
        "url": (
            "https://transportation.stanford.edu/sites/g/files/sbiybj27281/files/"
            "media/file/bikeways-map.pdf"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "stanford_campus_access_guide",
        "supports": (
            "Stanford's Campus Access Guide provides venue-specific accessible "
            "entrance and disability access information and describes itself as ongoing."
        ),
        "url": "https://maps.stanford.edu/ada/",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "stanford_suggested_travel_routes",
        "supports": (
            "Stanford Public Safety describes suggested pedestrian and bicycle "
            "routes as accessible, lighted, paved and visible."
        ),
        "url": "https://police.stanford.edu/suggested-travel-routes.html",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "daily_data_section",
        "supports": (
            "The Daily publishes data stories and supplies the project's editorial "
            "comparison set."
        ),
        "url": "https://stanforddaily.com/category/data94305/",
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "daily_prior_schedule_reporting",
        "supports": (
            "Attributed historical reporting says the prior University-approved "
            "calendar used 50- and 80-minute meetings with ten-minute commuting "
            "breaks, while the AY 2021-22 return to in-person instruction used 60- "
            "and 90-minute slots with 15-minute breaks intended to reduce hallway "
            "density. It also reports student experiences with schedule overlaps."
        ),
        "url": (
            "https://stanforddaily.com/2021/09/14/"
            "overlapping-class-meeting-times-leave-students-stressed/"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-05",
        "id": "ay2021_meeting_pattern_sheet",
        "supports": (
            "Historical Google Sheet titled OFFICIAL Standard Meeting Patterns "
            "AY21-22, linked from the Daily story as a scheduling document provided "
            "by a University spokesperson. Its visible Opt 4 grid includes 60-minute "
            "starts at 8:30, 9:45 and 11:00 and 90-minute starts at 9:45 and 11:30, "
            "examples that display 15-minute intervals. It is "
            "not evidence of current policy, courses, rooms or student travel."
        ),
        "url": (
            "https://docs.google.com/spreadsheets/d/"
            "1Gxv03c2yyypmCF1Hot5VJ9f3Wi5LADMyjLsmiABhNsQ/"
            "edit?gid=1166637319#gid=1166637319"
        ),
        "verification_status": "verified_live",
    },
    {
        "checked_on": "2026-08-04",
        "id": "daily_submission_guidelines",
        "supports": "The linked page is The Daily's public submission information page.",
        "url": "https://stanforddaily.com/submitting-to-the-daily/",
        "verification_status": "verified_live",
    },
)

_SOURCE_CLASSIFICATION = {
    "explorecourses_schedule": ("official_stanford", "analysis_input", True),
    "explorecourses_about": ("official_stanford", "source_description", True),
    "stanford_course_catalog_components": (
        "official_stanford",
        "source_description",
        True,
    ),
    "stanford_enrollment_components": (
        "official_stanford",
        "source_description",
        True,
    ),
    "stanford_siris_common_terms": (
        "official_stanford",
        "technical_documentation",
        True,
    ),
    "explorecourses_python_api": (
        "third_party_code",
        "implementation_reference",
        False,
    ),
    "explorecourses_api_request_code": (
        "third_party_code",
        "implementation_reference",
        False,
    ),
    "explorecourses_api_field_mapping": (
        "third_party_code",
        "implementation_reference",
        False,
    ),
    "campus_map": ("official_stanford", "analysis_input", True),
    "campus_map_faq": ("official_stanford", "source_description", True),
    "osm_license": ("external_open_data", "analysis_input_attribution", False),
    "overpass_api": ("external_open_data", "technical_documentation", False),
    "osm_wheelchair_tag": (
        "external_open_data",
        "technical_documentation",
        False,
    ),
    "osm_incline_tag": (
        "external_open_data",
        "technical_documentation",
        False,
    ),
    "bulletin_unit_of_credit": (
        "official_stanford",
        "policy_or_guidance",
        True,
    ),
    "bulletin_standard_meeting_patterns": (
        "official_stanford",
        "policy_or_guidance",
        True,
    ),
    "admission_class_change_advice": (
        "official_stanford",
        "policy_or_guidance",
        True,
    ),
    "stanford_bicycle_laws": (
        "official_stanford",
        "policy_or_guidance",
        True,
    ),
    "stanford_bikeways_map": ("official_stanford", "context_only", True),
    "stanford_campus_access_guide": (
        "official_stanford",
        "policy_or_guidance",
        True,
    ),
    "stanford_suggested_travel_routes": (
        "official_stanford",
        "context_only",
        True,
    ),
    "daily_data_section": ("editorial_context", "editorial_context_only", False),
    "daily_prior_schedule_reporting": (
        "editorial_context",
        "editorial_context_only",
        False,
    ),
    "ay2021_meeting_pattern_sheet": (
        "editorial_context",
        "editorial_context_only",
        False,
    ),
    "daily_submission_guidelines": (
        "editorial_context",
        "editorial_context_only",
        False,
    ),
}

EXTERNAL_CONTEXT_SOURCES = tuple(
    {
        **source,
        "source_class": _SOURCE_CLASSIFICATION[source["id"]][0],
        "evidence_use": _SOURCE_CLASSIFICATION[source["id"]][1],
        "supports_stanford_claim": _SOURCE_CLASSIFICATION[source["id"]][2],
    }
    for source in _SOURCE_ENTRIES
)
