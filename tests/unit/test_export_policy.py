from lawful_anomaly_screening.exports.precision_policy import (
    allow_exact_coordinates,
    apply_precision_to_centroid,
    build_artifact_name,
    build_bundle_name,
    resolve_export_policy,
    sanitize_candidate_for_export,
)


def test_public_and_shared_exports_obfuscate_to_one_kilometer():
    centroid = [1234.0, 2789.0]

    assert apply_precision_to_centroid(centroid, "public") == [1000.0, 3000.0]
    assert apply_precision_to_centroid(centroid, "shared") == [1000.0, 3000.0]
    assert allow_exact_coordinates("public") is False
    assert allow_exact_coordinates("shared") is False


def test_reviewer_internal_and_field_precision_rules():
    centroid = [1234.0, 2789.0]

    assert apply_precision_to_centroid(centroid, "reviewer") == centroid
    assert apply_precision_to_centroid(centroid, "internal") == centroid
    assert apply_precision_to_centroid(centroid, "field") == centroid
    assert allow_exact_coordinates("reviewer") is True
    assert allow_exact_coordinates("internal") is True
    assert allow_exact_coordinates("field") is True


def test_report_pdf_precision_supports_restricted_and_exact():
    restricted_policy = resolve_export_policy("report_pdf", "restricted")
    exact_policy = resolve_export_policy("report_pdf", "exact")

    assert restricted_policy.precision_tier == "restricted"
    assert restricted_policy.coordinate_resolution_m == 100
    assert restricted_policy.exact_coordinates_included is False
    assert exact_policy.precision_tier == "exact"
    assert exact_policy.coordinate_resolution_m is None
    assert exact_policy.exact_coordinates_included is True
    assert apply_precision_to_centroid([1234.0, 2789.0], "report_pdf", "restricted") == [1200.0, 2800.0]
    assert apply_precision_to_centroid([1234.0, 2789.0], "report_pdf", "exact") == [1234.0, 2789.0]


def test_artifact_names_do_not_embed_exact_coordinates_outside_reviewer_contexts():
    centroid = [1234.0, 2789.0]

    reviewer_name = build_artifact_name(
        run_id="run-001",
        audience="reviewer",
        artifact_kind="export",
        centroid=centroid,
        extension="json",
    )
    public_name = build_artifact_name(
        run_id="run-001",
        audience="public",
        artifact_kind="export",
        centroid=centroid,
        extension="json",
    )
    field_bundle = build_bundle_name(
        run_id="run-001",
        audience="field",
        artifact_kind="export",
        centroid=centroid,
    )

    assert "e1234_n2789" in reviewer_name
    assert "e1000_n3000" in public_name
    assert "e1200_n2800" in field_bundle


def test_unconfirmed_candidate_coordinates_are_sanitized_for_non_reviewer_exports():
    candidate = {
        "candidate_id": "candidate-001",
        "centroid": [1234.0, 2789.0],
        "bounds": [1201.0, 2705.0, 1281.0, 2879.0],
    }

    public_candidate = sanitize_candidate_for_export(candidate, "public")
    reviewer_candidate = sanitize_candidate_for_export(candidate, "reviewer")

    assert public_candidate["centroid"] == [1000.0, 3000.0]
    assert reviewer_candidate["centroid"] == [1234.0, 2789.0]
