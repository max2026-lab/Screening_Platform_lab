import json
from pathlib import Path

from lawful_anomaly_screening.exports.precision_policy import allow_exact_coordinates, redacted_for_public


def test_public_export_never_precise():
    assert redacted_for_public() is True
    assert allow_exact_coordinates("public") is False
    assert allow_exact_coordinates("shared") is False
    assert allow_exact_coordinates("reviewer") is True
    assert allow_exact_coordinates("internal") is True
    assert allow_exact_coordinates("field") is True


def test_report_pdf_allows_exact_precision_option():
    tiers = json.loads(Path("config/exports/precision_tiers.json").read_text(encoding="utf-8"))
    report_pdf = tiers["report_pdf"]
    assert report_pdf["precision"] == "configurable"
    assert report_pdf["allow_exact_coordinates"] is True
    assert "restricted" in report_pdf["allowed_precision_values"]
    assert "exact" in report_pdf["allowed_precision_values"]
