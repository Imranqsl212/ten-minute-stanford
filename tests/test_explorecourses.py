import pandas as pd

from ten_minute_stanford.explorecourses import (
    discover_subject_catalog,
    discover_subjects,
    parse_schedule_page,
    result_count,
    split_invalid_meeting_rows,
)
from ten_minute_stanford.explorecourses_api import parse_explorecourses_xml


def test_discover_subjects() -> None:
    html = """
    <a href="m_search?q=CS">Computer Science (CS)</a>
    <a href="m_search?q=MS%26E">Management Science &amp; Engineering (MS&amp;E)</a>
    <a href="search?q=not+a+subject">Ignore</a>
    """
    assert discover_subjects(html) == ["CS", "MS&E"]
    assert discover_subject_catalog(html) == [
        {"subject_code": "CS", "subject_name": "Computer Science"},
        {
            "subject_code": "MS&E",
            "subject_name": "Management Science & Engineering",
        },
    ]


def test_parse_schedule_page_expands_weekdays() -> None:
    html = """
    <div class="resultsSummary">1 - 1 of 1 results for:</div>
    <div class="searchResult">
      <div class="courseInfo">
        <span class="courseNumber">TEST 101:</span>
        <span class="courseTitle">A Test Course</span>
        <div class="sectionDetails">
          TEST 101 | 3 units | Class # 12345 | Section 01 |
          Grading: Letter | LEC | Session: 2025-2026 Autumn 1 |
          In Person | Students enrolled: 20 / 30
          09/22/2025 - 12/05/2025 Mon, Wed 9:30 AM - 10:20 AM at
          <a href="http://campus-map.stanford.edu/?srch=320-105">320-105</a>
          with Example, A. (PI) Instructors: Example, A. (PI)
        </div>
      </div>
    </div>
    """
    sections, meetings = parse_schedule_page(
        html,
        academic_year="20252026",
        term="Autumn",
        subject_query="TEST",
        source_url="https://example.test",
    )
    assert result_count(html) == 1
    assert len(sections) == 1
    assert sections[0]["class_number"] == "12345"
    assert sections[0]["enrolled"] == 20
    assert sections[0]["component"] == "LEC"
    assert [meeting["day"] for meeting in meetings] == ["Mon", "Wed"]
    assert meetings[0]["start_minutes"] == 570
    assert meetings[0]["end_minutes"] == 620
    assert meetings[0]["room"] == "320-105"


def test_cancelled_section_is_preserved_for_audit() -> None:
    html = """
    <div class="searchResult-noBorder">
      <span class="courseNumber">TEST 9:</span><span class="courseTitle">Cancelled</span>
      <div class="sectionDetails">
        TEST 9 | Class # 999 (CANCELLED) | Section 01 |
        Grading: Satisfactory/No Credit | SEM | Session: 2025-2026 Winter 1 |
        In Person | Students enrolled: 0 / 12
      </div>
    </div>
    """
    sections, meetings = parse_schedule_page(
        html,
        academic_year="20252026",
        term="Winter",
        subject_query="TEST",
        source_url="https://example.test",
    )
    assert sections[0]["cancelled"] is True
    assert meetings == []


def test_keyword_matches_from_other_subjects_are_rejected() -> None:
    html = """
    <div class="searchResult">
      <span class="courseNumber">OTHER 1:</span><span class="courseTitle">Not Requested</span>
      <div class="sectionDetails">
        OTHER 1 | Class # 1 | Section 01 | Grading: Letter | LEC |
        Session: 2025-2026 Winter 1 | In Person | Students enrolled: 1 / 1
      </div>
    </div>
    """
    sections, meetings = parse_schedule_page(
        html,
        academic_year="20252026",
        term="Winter",
        subject_query="TEST",
        source_url="https://example.test",
    )
    assert sections == []
    assert meetings == []


def test_mobile_page_filters_term_and_infers_modality() -> None:
    html = """
    <div class="resultsSummary">1 - 1 of 1 results for:</div>
    <div class="searchResult">
      <span class="courseNumber">TEST 8:</span><span class="courseTitle">Mobile</span>
      <div class="sectionContainer">
        <h3 class="sectionContainerTerm">2025-2026 Autumn</h3>
        <div class="sectionDetails">
          TEST 8 | Class # 100 | Section 01 | Grading: Letter | LEC
          09/22/2025 - 12/05/2025 Mon 9:30 AM - 10:20 AM at 200-002
        </div>
      </div>
      <div class="sectionContainer">
        <h3 class="sectionContainerTerm">2025-2026 Winter</h3>
        <div class="sectionDetails">
          TEST 8 | Class # 200 | Section 01 | Grading: Letter | LEC
          01/05/2026 - 03/13/2026 Tue, Thu 1:30 PM - 2:20 PM at 160-318
        </div>
      </div>
    </div>
    """
    sections, meetings = parse_schedule_page(
        html,
        academic_year="20252026",
        term="Winter",
        subject_query="TEST",
        source_url="https://example.test",
    )
    assert [section["class_number"] for section in sections] == ["200"]
    assert sections[0]["component"] == "LEC"
    assert sections[0]["modality"] == "In Person"
    assert sections[0]["enrolled"] is None
    assert [meeting["day"] for meeting in meetings] == ["Tue", "Thu"]


def test_mobile_cancellation_note_is_detected() -> None:
    html = """
    <div class="searchResult">
      <span class="courseNumber">TEST 9:</span><span class="courseTitle">Cancelled</span>
      <div class="sectionContainer">
        <h3 class="sectionContainerTerm">2025-2026 Winter</h3>
        <div class="sectionDetails">
          TEST 9 | Class # 999 | Section 01 | Grading: Letter | DIS
          Notes: This class section has been cancelled!
        </div>
      </div>
    </div>
    """
    sections, _meetings = parse_schedule_page(
        html,
        academic_year="20252026",
        term="Winter",
        subject_query="TEST",
        source_url="https://example.test",
    )
    assert sections[0]["cancelled"] is True


def test_invalid_dates_and_zero_duration_meetings_are_separated() -> None:
    meetings = pd.DataFrame(
        [
            {
                "term": "Winter",
                "date_start": "2026-01-05",
                "date_end": "2026-03-13",
                "start_minutes": 570,
                "end_minutes": 620,
            },
            {
                "term": "Winter",
                "date_start": "2025-01-05",
                "date_end": "2026-03-13",
                "start_minutes": 570,
                "end_minutes": 620,
            },
            {
                "term": "Winter",
                "date_start": "2026-01-05",
                "date_end": "2026-03-13",
                "start_minutes": 900,
                "end_minutes": 900,
            },
        ]
    )

    valid, invalid_dates, invalid_times = split_invalid_meeting_rows(
        meetings, "20252026"
    )

    assert len(valid) == 1
    assert len(invalid_dates) == 1
    assert len(invalid_times) == 1


def test_xml_api_parser_filters_term_and_extracts_enrollment() -> None:
    xml = """
    <xml><courses><course>
      <subject>TEST</subject><code>101</code><title>API Test</title>
      <sections>
        <section>
          <classId>12345</classId><term>2025-2026 Winter</term>
          <sectionNumber>01</sectionNumber><component>LEC</component>
          <currentClassSize>24</currentClassSize><maxClassSize>30</maxClassSize>
          <currentWaitlistSize>2</currentWaitlistSize><maxWaitlistSize>5</maxWaitlistSize>
          <enrollStatus>Open</enrollStatus><instructionMode>P</instructionMode>
          <schedules><schedule>
            <startDate>Jan 5, 2026</startDate><endDate>Mar 13, 2026</endDate>
            <startTime>9:30:00 AM</startTime><endTime>10:20:00 AM</endTime>
            <location>320-105</location><days>Monday Wednesday</days>
          </schedule></schedules>
        </section>
        <section>
          <classId>99999</classId><term>2025-2026 Autumn</term>
        </section>
      </sections>
    </course></courses></xml>
    """

    sections, schedules = parse_explorecourses_xml(
        xml,
        academic_year="20252026",
        term="Winter",
        subject_query="TEST",
        source_url="https://example.test/xml",
    )

    assert len(sections) == 1
    assert sections[0]["class_number"] == "12345"
    assert sections[0]["enrolled"] == 24
    assert sections[0]["capacity"] == 30
    assert [row["day"] for row in schedules] == ["Mon", "Wed"]
    assert schedules[0]["start_minutes"] == 570
    assert schedules[0]["end_minutes"] == 620
    assert schedules[0]["room"] == "320-105"
