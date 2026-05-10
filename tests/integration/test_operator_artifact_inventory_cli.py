import json
from pathlib import Path

from lawful_anomaly_screening.ops import operator_artifact_inventory as inventory
from lawful_anomaly_screening.cli import main


def test_happy_path_passes():
    root = Path(".test-operator-artifact-inventory/happy")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "cache").mkdir()
    (root / "manifests").mkdir()
    (root / "artifacts").mkdir()
    (root / "exports" / "public").mkdir(parents=True)
    (root / "exports" / "reviewer").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "data").mkdir()

    artifact_dir = root / "artifacts"
    small_file = artifact_dir / "manifest.json"
    small_file.write_text('{"ok": true}', encoding="utf-8")
    sha = inventory._sha256_file(small_file)
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text(f"{sha}  manifest.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="both")
    assert result["status"] == "pass"
    assert (out / "operator_artifact_inventory.json").exists()
    assert (out / "operator_artifact_inventory.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2
    assert not any("SHA256SUMS.txt" in line for line in sums_lines)

    json_report = json.loads((out / "operator_artifact_inventory.json").read_text(encoding="utf-8"))
    assert json_report["schema"]["version"] == "v1.17.0"
    assert json_report["checks"]["root_exists"] is True
    assert json_report["checks"]["folder_presence"]["cache"] is True
    assert json_report["warnings"] == []
    assert json_report["failures"] == []


def test_missing_root_fails():
    root = Path(".test-operator-artifact-inventory/missing")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "fail"
    assert (out / "operator_artifact_inventory.json").exists()
    assert any("does not exist" in f for f in result["failures"])


def test_hash_mismatch_fails():
    root = Path(".test-operator-artifact-inventory/hash_mismatch")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    small_file = artifact_dir / "manifest.json"
    small_file.write_text('{"ok": true}', encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text(f"{'0'*64}  manifest.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "fail"
    assert any("hash mismatch" in f for f in result["failures"])


def test_missing_checksum_target_fails():
    root = Path(".test-operator-artifact-inventory/missing_target")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text(f"{'0'*64}  missing.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "fail"
    assert any("missing target" in f for f in result["failures"])


def test_malformed_checksum_line_warns():
    root = Path(".test-operator-artifact-inventory/malformed")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text("badline\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "warn"
    assert any("badline" in w for w in result["warnings"])
    assert result["failures"] == []


def test_checksum_subdir_ref_warns():
    root = Path(".test-operator-artifact-inventory/subdir_ref")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    subdir = artifact_dir / "subdir"
    subdir.mkdir()
    target = subdir / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  subdir/file.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "warn"
    assert any("nonlocal" in w.lower() and "subdir/file.json" in w for w in result["warnings"])
    assert result["failures"] == []


def test_checksum_parent_ref_warns():
    root = Path(".test-operator-artifact-inventory/parent_ref")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    target = root / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  ../file.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "warn"
    assert any("nonlocal" in w.lower() and "../file.json" in w for w in result["warnings"])
    assert result["failures"] == []


def test_checksum_absolute_ref_warns():
    root = Path(".test-operator-artifact-inventory/abs_ref")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    target = root / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  /absolute/path/file.json\n", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "warn"
    assert any("nonlocal" in w.lower() and "/absolute/path/file.json" in w for w in result["warnings"])
    assert result["failures"] == []


def test_export_safety_warning():
    root = Path(".test-operator-artifact-inventory/safety")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    public_dir = root / "exports" / "public"
    public_dir.mkdir(parents=True)
    unsafe_file = public_dir / "exact_coordinates.json"
    unsafe_file.write_text("{}", encoding="utf-8")

    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "warn"
    assert any("exact" in w.lower() and "public" in w.lower() for w in result["warnings"])


def test_format_json_only():
    root = Path(".test-operator-artifact-inventory/json_only")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "pass"
    assert (out / "operator_artifact_inventory.json").exists()
    assert not (out / "operator_artifact_inventory.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_markdown_only():
    root = Path(".test-operator-artifact-inventory/md_only")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="markdown")
    assert result["status"] == "pass"
    assert not (out / "operator_artifact_inventory.json").exists()
    assert (out / "operator_artifact_inventory.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_both():
    root = Path(".test-operator-artifact-inventory/both")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="both")
    assert result["status"] == "pass"
    assert (out / "operator_artifact_inventory.json").exists()
    assert (out / "operator_artifact_inventory.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2


def test_read_only_no_mutation():
    root = Path(".test-operator-artifact-inventory/readonly")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    source_file = root / "source.txt"
    source_file.write_text("source", encoding="utf-8")
    out = root / ".operator-artifact-inventory"
    result = inventory.run_operator_artifact_inventory(root=root, output_dir=out, fmt="json")
    assert result["status"] == "pass"
    assert source_file.read_text(encoding="utf-8") == "source"


# --- CLI tests ---


def test_cli_happy_path(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cache").mkdir()
    (root / "manifests").mkdir()
    (root / "artifacts").mkdir()
    (root / "exports" / "public").mkdir(parents=True)
    (root / "exports" / "reviewer").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "data").mkdir()
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "both",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    out = root / ".operator-artifact-inventory"
    assert (out / "operator_artifact_inventory.json").exists()
    assert (out / "SHA256SUMS.txt").exists()


def test_cli_missing_root_fails(capsys, tmp_path):
    root = tmp_path / "missing"
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"


def test_cli_hash_mismatch_fails(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    small_file = artifact_dir / "manifest.json"
    small_file.write_text('{"ok": true}', encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text(f"{'0'*64}  manifest.json\n", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"


def test_cli_malformed_checksum_line_warns(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sums_file.write_text("badline\n", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("badline" in w for w in payload["warnings"])


def test_cli_checksum_subdir_ref_warns(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    subdir = artifact_dir / "subdir"
    subdir.mkdir()
    target = subdir / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  subdir/file.json\n", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("nonlocal" in w.lower() and "subdir/file.json" in w for w in payload["warnings"])


def test_cli_checksum_parent_ref_warns(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    target = root / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  ../file.json\n", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("nonlocal" in w.lower() and "../file.json" in w for w in payload["warnings"])


def test_cli_checksum_absolute_ref_warns(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir()
    target = root / "file.json"
    target.write_text("{}", encoding="utf-8")
    sums_file = artifact_dir / "SHA256SUMS.txt"
    sha = inventory._sha256_file(target)
    sums_file.write_text(f"{sha}  /absolute/path/file.json\n", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("nonlocal" in w.lower() and "/absolute/path/file.json" in w for w in payload["warnings"])


def test_cli_export_safety_warning(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    public_dir = root / "exports" / "public"
    public_dir.mkdir(parents=True)
    unsafe_file = public_dir / "exact_coordinates.json"
    unsafe_file.write_text("{}", encoding="utf-8")
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("exact" in w.lower() for w in payload["warnings"])


def test_cli_default_output_dir(capsys, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cache").mkdir()
    (root / "manifests").mkdir()
    (root / "artifacts").mkdir()
    (root / "exports" / "public").mkdir(parents=True)
    (root / "exports" / "reviewer").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "data").mkdir()
    result = main([
        "operator-artifact-inventory",
        "--root", str(root),
        "--format", "json",
    ])
    assert result == 0
    out = root / ".operator-artifact-inventory"
    assert (out / "operator_artifact_inventory.json").exists()
