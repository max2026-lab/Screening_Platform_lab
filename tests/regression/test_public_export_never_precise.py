from lawful_anomaly_screening.exports.precision_policy import redacted_for_public


def test_public_export_never_precise():
    assert redacted_for_public() is True
