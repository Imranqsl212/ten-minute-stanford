from ten_minute_stanford.audit import audit_publication


def test_publication_audit_recomputes_checked_in_claims() -> None:
    report = audit_publication(check_raw=False, write=False)

    assert report["status"] == "pass"
    assert report["checks"]["publication_files_checked"] == 9
    assert report["checks"]["route_matrix_rows"] == 75**2
    assert report["checks"]["route_distances_separately_verified"] == 75**2
    assert report["checks"]["bicycle_route_distances_separately_verified"] == 75**2
    assert report["checks"]["external_context_sources_checked"] == 25
    assert report["checks"]["external_source_class_counts"] == {
        "editorial_context": 4,
        "external_open_data": 4,
        "official_stanford": 14,
        "third_party_code": 3,
    }
    assert report["checks"]["explorecourses_subject_codes"] == 253
    assert report["checks"]["explorecourses_schedule_responses"] == 579
    assert report["checks"]["course_transition_cases_checked"] == 4
    assert report["checks"]["passing_period_scenarios_checked"] == 18
    assert report["checks"]["raw_section_rows_reparsed"] == 27_197
    assert report["checks"]["walking_network_components_before_filter"] == 222
    assert report["checks"]["walking_network_graph_nodes"] == 114_337
    assert report["checks"]["same_class_number_pair_rows_excluded"] == 1
    assert report["checks"]["meeting_rows_with_enrollment_values"] == 6_876
    assert report["checks"]["section_rows_with_enrollment_values"] == 27_197
    assert report["checks"]["actual_passing_period_time_slots"] == 25
    assert report["checks"]["weekday_passing_period_time_slots"] == 92
    assert report["checks"]["large_enrollment_combinations_checked"] == 187
    assert report["checks"]["student_survey_responses_checked"] == 27
    assert report["checks"]["component_schedule_rows_checked"] == 2_946
    assert report["checks"]["component_transition_pairs_checked"] == 62_525
    assert report["checks"]["subject_area_transition_rows_checked"] == 161
