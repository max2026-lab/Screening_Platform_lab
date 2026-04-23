from lawful_anomaly_screening.exports.precision_policy import allow_exact_coordinates, redacted_for_public


def test_public_export_never_precise():
    assert redacted_for_public() is True
    assert allow_exact_coordinates("public") is False
    assert allow_exact_coordinates("shared") is False
    assert allow_exact_coordinates("reviewer") is True
    assert allow_exact_coordinates("internal") is True
    assert allow_exact_coordinates("field") is True
