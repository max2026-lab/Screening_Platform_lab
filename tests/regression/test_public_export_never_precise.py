import json

from lawful_anomaly_screening.exports.precision_policy import (
    allow_exact_coordinates,
    apply_precision_to_centroid,
    redacted_for_public,
)
from lawful_anomaly_screening.settings import load_settings


def test_public_export_never_precise():
    assert redacted_for_public() is True
    assert allow_exact_coordinates("public") is False
    assert allow_exact_coordinates("shared") is False
    assert allow_exact_coordinates("reviewer") is True
    assert allow_exact_coordinates("internal") is True
    assert allow_exact_coordinates("field") is True
    assert apply_precision_to_centroid([1234.0, 2789.0], "public") == [1000.0, 3000.0]


def test_report_pdf_allows_exact_precision_option():
    tiers = json.loads(load_settings().export_precision_path.read_text(encoding="utf-8"))
    report_pdf = tiers["report_pdf"]
    assert report_pdf["precision"] == "configurable"
    assert report_pdf["allow_exact_coordinates"] is True
    assert report_pdf["default_precision"] == "restricted"
    assert "restricted" in report_pdf["allowed_precision_values"]
    assert "exact" in report_pdf["allowed_precision_values"]
