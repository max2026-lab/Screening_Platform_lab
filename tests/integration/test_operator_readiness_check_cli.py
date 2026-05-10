import json
from pathlib import Path

from lawful_anomaly_screening.ops import operator_readiness as readiness
from lawful_anomaly_screening.cli import main


def _fake_settings(tmp_path: Path):
    class FakeSettings:
        db_path = tmp_path / "data" / "sqlite" / "db.sqlite3"
        baseline_path = tmp_path / "config" / "baselines" / "baseline.json"
        logging_config_path = tmp_path / "config" / "logging" / "logging.yaml"
        export_precision_path = tmp_path / "config" / "exports" / "precision.json"
        endpoints_path = tmp_path / "config" / "sources" / "endpoints.json"
        geofence_policy_path = tmp_path / "config" / "legal" / "geofence.json"
        preprocessing_config_path = tmp_path / "config" / "sources" / "preprocessing.json"
    return FakeSettings()


def test_happy_path_all_passes(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    # Create all parent directories
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="both")
    assert result["status"] == "pass"
    assert (out / "operator_readiness_check.json").exists()
    assert (out / "operator_readiness_check.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2
    assert not any("SHA256SUMS.txt" in line for line in sums_lines)

    # JSON report must include artifact manifest and warnings/failures
    json_report = json.loads((out / "operator_readiness_check.json").read_text(encoding="utf-8"))
    assert "artifact_manifest" in json_report
    assert isinstance(json_report["warnings"], list)
    assert isinstance(json_report["failures"], list)
    manifest = json_report["artifact_manifest"]
    json_entry = next((a for a in manifest if a["name"] == "operator_readiness_check.json"), None)
    assert json_entry is not None
    assert json_entry["sha256"] is None
    md_entry = next((a for a in manifest if a["name"] == "operator_readiness_check.md"), None)
    assert md_entry is not None
    assert md_entry["sha256"] is not None
    sums_entry = next((a for a in manifest if a["name"] == "SHA256SUMS.txt"), None)
    assert sums_entry is not None
    assert sums_entry["sha256"] is None


def test_missing_storage_path_fails(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    # Make db_path parent missing
    fake.db_path = tmp_path / "nonexistent" / "db.sqlite3"
    # Ensure other paths exist
    for attr in ("baseline_path", "logging_config_path", "export_precision_path",
                 "endpoints_path", "geofence_policy_path", "preprocessing_config_path"):
        val = getattr(fake, attr)
        val.parent.mkdir(parents=True, exist_ok=True)
        if val.suffix:
            val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="json")
    assert result["status"] == "fail"
    assert any("db_path" in r and "does not exist" in r for r in result["reasons"])


def test_unsafe_export_config_fails(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    monkeypatch.setenv("EXPORT_UNCONFIRMED_COORDINATE_MODE", "exact")
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="json")
    assert result["status"] == "fail"
    assert any("exact" in r and "obfuscated" in r for r in result["reasons"])


def test_format_json_only(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="json")
    assert result["status"] == "pass"
    assert (out / "operator_readiness_check.json").exists()
    assert not (out / "operator_readiness_check.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1

    json_report = json.loads((out / "operator_readiness_check.json").read_text(encoding="utf-8"))
    manifest = json_report["artifact_manifest"]
    names = [a["name"] for a in manifest]
    assert "operator_readiness_check.json" in names
    assert "operator_readiness_check.md" not in names
    assert "SHA256SUMS.txt" in names
    json_entry = next(a for a in manifest if a["name"] == "operator_readiness_check.json")
    assert json_entry["sha256"] is None


def test_format_markdown_only(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="markdown")
    assert result["status"] == "pass"
    assert not (out / "operator_readiness_check.json").exists()
    assert (out / "operator_readiness_check.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_both(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="both")
    assert result["status"] == "pass"
    assert (out / "operator_readiness_check.json").exists()
    assert (out / "operator_readiness_check.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2

    json_report = json.loads((out / "operator_readiness_check.json").read_text(encoding="utf-8"))
    manifest = json_report["artifact_manifest"]
    json_entry = next(a for a in manifest if a["name"] == "operator_readiness_check.json")
    assert json_entry["sha256"] is None
    md_entry = next(a for a in manifest if a["name"] == "operator_readiness_check.md")
    assert md_entry["sha256"] is not None
    sums_entry = next(a for a in manifest if a["name"] == "SHA256SUMS.txt")
    assert sums_entry["sha256"] is None


def test_no_db_mutation(monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix and attr != "db_path":
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    # Ensure DB file does not exist before check
    assert not fake.db_path.exists()
    out = tmp_path / "out"
    result = readiness.run_operator_readiness_check(output_dir=out, fmt="json")
    assert result["status"] == "pass"
    # DB file should still not exist
    assert not fake.db_path.exists()


def test_cli_happy_path(capsys, monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = main([
        "operator-readiness-check",
        "--output-dir", str(out),
        "--format", "both",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert (out / "operator_readiness_check.json").exists()
    assert (out / "SHA256SUMS.txt").exists()


def test_cli_missing_path_fails(capsys, monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    fake.db_path = tmp_path / "missing" / "db.sqlite3"
    for attr in ("baseline_path", "logging_config_path", "export_precision_path",
                 "endpoints_path", "geofence_policy_path", "preprocessing_config_path"):
        val = getattr(fake, attr)
        val.parent.mkdir(parents=True, exist_ok=True)
        if val.suffix:
            val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    out = tmp_path / "out"
    result = main([
        "operator-readiness-check",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"


def test_cli_unsafe_config_fails(capsys, monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    monkeypatch.setenv("EXPORT_UNCONFIRMED_COORDINATE_MODE", "exact")
    out = tmp_path / "out"
    result = main([
        "operator-readiness-check",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"


def test_cli_no_db_access(capsys, monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))
    out = tmp_path / "out"
    result = main([
        "operator-readiness-check",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert not (tmp_path / "missing.sqlite3").exists()


def test_cli_default_output_dir(capsys, monkeypatch, tmp_path):
    fake = _fake_settings(tmp_path)
    for attr in dir(fake):
        if attr.startswith("_"):
            continue
        val = getattr(fake, attr)
        if isinstance(val, Path):
            val.parent.mkdir(parents=True, exist_ok=True)
            if val.suffix:
                val.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readiness, "load_settings", lambda: fake)
    # Change cwd so .operator-readiness is created inside tmp_path
    monkeypatch.chdir(tmp_path)
    result = main([
        "operator-readiness-check",
        "--format", "json",
    ])
    assert result == 0
    assert (tmp_path / ".operator-readiness" / "operator_readiness_check.json").exists()
