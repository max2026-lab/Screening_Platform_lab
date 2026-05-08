from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


FORBIDDEN_GEOMETRY_KEYS = {
    "centroid",
    "clipped_geometry",
    "bounds",
    "coordinates",
}

REQUIRED_SIDECAR_FIELDS = {
    "schema_version",
    "run_id",
    "export_record_id",
    "audience",
    "precision_tier",
    "exact_coordinates_included",
    "artifact_name",
    "artifact_path",
    "bundle_name",
    "bundle_path",
    "bundle_sha256",
    "bundle_members",
    "audit_manifest_hash",
    "candidate_count",
    "files",
}

EXPECTED_FILE_KINDS = {
    "report_markdown",
    "bundle_zip",
    "audit_manifest",
    "checksum_manifest",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _resolve_path(path_str: str, export_root: Path) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (export_root / path).resolve()


def verify_export_bundle(
    bundle_manifest_path: str,
    export_root: Path | None = None,
) -> dict:
    reasons: list[str] = []
    export_root = export_root or Path.cwd()

    manifest_file = _resolve_path(bundle_manifest_path, export_root)

    # 1. Manifest file must exist
    if not manifest_file.exists():
        return {
            "status": "fail",
            "bundle_manifest_path": str(manifest_file).replace("\\", "/"),
            "reasons": [f"Sidecar manifest not found: {manifest_file}"],
        }

    # 2. JSON must parse
    try:
        sidecar_text = manifest_file.read_text(encoding="utf-8")
        sidecar = json.loads(sidecar_text)
    except json.JSONDecodeError as exc:
        return {
            "status": "fail",
            "bundle_manifest_path": str(manifest_file).replace("\\", "/"),
            "reasons": [f"Sidecar manifest is not valid JSON: {exc}"],
        }
    except Exception as exc:
        return {
            "status": "fail",
            "bundle_manifest_path": str(manifest_file).replace("\\", "/"),
            "reasons": [f"Failed to read sidecar manifest: {exc}"],
        }

    if not isinstance(sidecar, dict):
        return {
            "status": "fail",
            "bundle_manifest_path": str(manifest_file).replace("\\", "/"),
            "reasons": ["Sidecar manifest must contain a JSON object"],
        }

    # 3. Required fields check
    missing_fields = REQUIRED_SIDECAR_FIELDS - set(sidecar.keys())
    if missing_fields:
        reasons.append(f"Missing required sidecar fields: {', '.join(sorted(missing_fields))}")

    # 4. Schema version
    schema_version = sidecar.get("schema_version")
    if schema_version != "v1.7_report_bundle_manifest":
        reasons.append(
            f"schema_version must be v1.7_report_bundle_manifest, got {schema_version!r}"
        )

    # 5. Forbidden geometry keys (standalone JSON key check)
    forbidden_found = {key for key in FORBIDDEN_GEOMETRY_KEYS if f'"{key}"' in sidecar_text}
    if forbidden_found:
        reasons.append(
            f"Sidecar contains forbidden geometry keys: {', '.join(sorted(forbidden_found))}"
        )

    # 6. Audience must be report_pdf
    audience = sidecar.get("audience")
    if audience != "report_pdf":
        reasons.append(f"audience must be report_pdf, got {audience!r}")

    # 7. Path/name validations
    bundle_path_str = sidecar.get("bundle_path", "")
    bundle_name = sidecar.get("bundle_name", "")
    if bundle_path_str and not str(bundle_path_str).endswith(".zip"):
        reasons.append(f"bundle_path must end with .zip, got {bundle_path_str!r}")
    if bundle_name and not str(bundle_name).endswith(".zip"):
        reasons.append(f"bundle_name must end with .zip, got {bundle_name!r}")

    expected_manifest_name = f"{bundle_name}.manifest.json"
    if manifest_file.name != expected_manifest_name:
        reasons.append(
            f"Sidecar filename must be {expected_manifest_name!r}, got {manifest_file.name!r}"
        )

    # File verification booleans
    bundle_sha256_valid = True
    bundle_members_valid = True
    sidecar_files_valid = True
    sha256sums_valid = True

    artifact_path_str = sidecar.get("artifact_path", "")
    artifact_path = _resolve_path(artifact_path_str, export_root) if artifact_path_str else None
    bundle_path = _resolve_path(bundle_path_str, export_root) if bundle_path_str else None

    # 8. Markdown report exists
    if artifact_path is not None and not artifact_path.exists():
        reasons.append(f"Markdown report not found at artifact_path: {artifact_path}")
        bundle_sha256_valid = False
        sidecar_files_valid = False
        sha256sums_valid = False

    # 9. ZIP bundle exists
    if bundle_path is not None and not bundle_path.exists():
        reasons.append(f"ZIP bundle not found at bundle_path: {bundle_path}")
        bundle_sha256_valid = False
        bundle_members_valid = False
        sidecar_files_valid = False
        sha256sums_valid = False

    actual_bundle_sha256 = None
    zip_members = None
    zip_audit_manifest_bytes = None
    zip_sha256sums_bytes = None

    if bundle_path is not None and bundle_path.exists():
        actual_bundle_sha256 = _sha256_file(bundle_path)
        expected_bundle_sha256 = sidecar.get("bundle_sha256", "")
        if actual_bundle_sha256 != expected_bundle_sha256:
            bundle_sha256_valid = False
            reasons.append(
                f"bundle_sha256 mismatch: expected {expected_bundle_sha256}, got {actual_bundle_sha256}"
            )

        try:
            with zipfile.ZipFile(bundle_path, "r") as zf:
                zip_members = sorted(zf.namelist())
                expected_members = sorted(sidecar.get("bundle_members", []))
                if zip_members != expected_members:
                    bundle_members_valid = False
                    reasons.append(
                        f"bundle_members mismatch: expected {expected_members}, got {zip_members}"
                    )

                if "audit_manifest.json" in zf.namelist():
                    zip_audit_manifest_bytes = zf.read("audit_manifest.json")
                    try:
                        json.loads(zip_audit_manifest_bytes.decode("utf-8"))
                    except json.JSONDecodeError:
                        reasons.append("audit_manifest.json inside ZIP is not valid JSON")
                        sha256sums_valid = False
                else:
                    reasons.append("ZIP missing audit_manifest.json")
                    sha256sums_valid = False

                if "SHA256SUMS.txt" in zf.namelist():
                    zip_sha256sums_bytes = zf.read("SHA256SUMS.txt")
                else:
                    reasons.append("ZIP missing SHA256SUMS.txt")
                    sha256sums_valid = False
        except zipfile.BadZipFile:
            bundle_sha256_valid = False
            bundle_members_valid = False
            sidecar_files_valid = False
            sha256sums_valid = False
            reasons.append(f"bundle_path is not a valid ZIP file: {bundle_path}")

    # 10. SHA256SUMS validation
    if sha256sums_valid and zip_sha256sums_bytes is not None and artifact_path is not None and artifact_path.exists():
        sha256sums_text = zip_sha256sums_bytes.decode("utf-8")
        entries: dict[str, str] = {}
        for raw_line in sha256sums_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt malformed line: {raw_line}")
                continue
            entries[parts[1]] = parts[0]

        artifact_name = sidecar.get("artifact_name", "")
        if artifact_name:
            actual_report_hash = _sha256_file(artifact_path)
            if entries.get(artifact_name) != actual_report_hash:
                sha256sums_valid = False
                reasons.append(
                    f"SHA256SUMS.txt hash mismatch for {artifact_name}: expected {entries.get(artifact_name)}, got {actual_report_hash}"
                )

        if zip_audit_manifest_bytes is not None:
            actual_audit_hash = _sha256_bytes(zip_audit_manifest_bytes)
            if entries.get("audit_manifest.json") != actual_audit_hash:
                sha256sums_valid = False
                reasons.append(
                    f"SHA256SUMS.txt hash mismatch for audit_manifest.json: expected {entries.get('audit_manifest.json')}, got {actual_audit_hash}"
                )

    # 11. Sidecar files list validation
    files = sidecar.get("files", [])
    if not isinstance(files, list):
        sidecar_files_valid = False
        reasons.append("files must be a list")
    else:
        actual_kinds = {f.get("kind") for f in files if isinstance(f, dict)}
        if actual_kinds != EXPECTED_FILE_KINDS:
            sidecar_files_valid = False
            reasons.append(
                f"files kinds mismatch: expected {sorted(EXPECTED_FILE_KINDS)}, got {sorted(actual_kinds)}"
            )
        if len(files) != 4:
            sidecar_files_valid = False
            reasons.append(f"files must have exactly 4 entries, got {len(files)}")

        # Validate each file entry hash
        if artifact_path is not None and artifact_path.exists():
            actual_report_hash = _sha256_file(artifact_path)
            report_entry = next((f for f in files if f.get("kind") == "report_markdown"), None)
            if report_entry is not None:
                if report_entry.get("sha256") != actual_report_hash:
                    sidecar_files_valid = False
                    reasons.append(
                        f"sidecar files report_markdown sha256 mismatch: expected {report_entry.get('sha256')}, got {actual_report_hash}"
                    )
            else:
                sidecar_files_valid = False
                reasons.append("sidecar files missing report_markdown entry")

        if actual_bundle_sha256 is not None:
            bundle_entry = next((f for f in files if f.get("kind") == "bundle_zip"), None)
            if bundle_entry is not None:
                if bundle_entry.get("sha256") != actual_bundle_sha256:
                    sidecar_files_valid = False
                    reasons.append(
                        f"sidecar files bundle_zip sha256 mismatch: expected {bundle_entry.get('sha256')}, got {actual_bundle_sha256}"
                    )
            else:
                sidecar_files_valid = False
                reasons.append("sidecar files missing bundle_zip entry")

        if zip_audit_manifest_bytes is not None:
            actual_audit_hash = _sha256_bytes(zip_audit_manifest_bytes)
            audit_entry = next((f for f in files if f.get("kind") == "audit_manifest"), None)
            if audit_entry is not None:
                if audit_entry.get("sha256") != actual_audit_hash:
                    sidecar_files_valid = False
                    reasons.append(
                        f"sidecar files audit_manifest sha256 mismatch: expected {audit_entry.get('sha256')}, got {actual_audit_hash}"
                    )
            else:
                sidecar_files_valid = False
                reasons.append("sidecar files missing audit_manifest entry")

        if zip_sha256sums_bytes is not None:
            actual_sums_hash = _sha256_bytes(zip_sha256sums_bytes)
            sums_entry = next((f for f in files if f.get("kind") == "checksum_manifest"), None)
            if sums_entry is not None:
                if sums_entry.get("sha256") != actual_sums_hash:
                    sidecar_files_valid = False
                    reasons.append(
                        f"sidecar files checksum_manifest sha256 mismatch: expected {sums_entry.get('sha256')}, got {actual_sums_hash}"
                    )
            else:
                sidecar_files_valid = False
                reasons.append("sidecar files missing checksum_manifest entry")

    # Audit manifest hash cross-check
    if zip_audit_manifest_bytes is not None:
        audit_manifest_hash = sidecar.get("audit_manifest_hash")
        if audit_manifest_hash:
            audit_manifest_from_zip = json.loads(zip_audit_manifest_bytes.decode("utf-8"))
            hash_payload = dict(audit_manifest_from_zip)
            hash_payload.pop("created_at", None)
            hash_payload.pop("audit_manifest_hash", None)
            actual_audit_manifest_hash = hashlib.sha256(
                json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if actual_audit_manifest_hash != audit_manifest_hash:
                sha256sums_valid = False
                reasons.append(
                    f"audit_manifest_hash mismatch: sidecar says {audit_manifest_hash}, recomputed {actual_audit_manifest_hash}"
                )

    status = "pass" if not reasons else "fail"
    checked_file_count = 4

    result = {
        "status": status,
        "bundle_manifest_path": str(manifest_file).replace("\\", "/"),
        "artifact_path": str(artifact_path).replace("\\", "/") if artifact_path else None,
        "bundle_path": str(bundle_path).replace("\\", "/") if bundle_path else None,
        "schema_version": schema_version,
        "run_id": sidecar.get("run_id"),
        "export_record_id": sidecar.get("export_record_id"),
        "bundle_sha256_valid": bundle_sha256_valid,
        "bundle_members_valid": bundle_members_valid,
        "sidecar_files_valid": sidecar_files_valid,
        "sha256sums_valid": sha256sums_valid,
        "forbidden_geometry_keys_absent": not bool(forbidden_found),
        "checked_file_count": checked_file_count,
        "reasons": reasons if reasons else [],
    }

    if status == "pass":
        result["reasons"] = []

    return result


def render_bundle_verify_markdown(result: dict) -> str:
    lines = [
        "# Export Bundle Verification",
        "",
        f"- Status: `{result['status']}`",
        f"- Bundle manifest path: `{result.get('bundle_manifest_path', '')}`",
        f"- Bundle path: `{result.get('bundle_path', '')}`",
        f"- Checked file count: `{result.get('checked_file_count', 0)}`",
        "",
        "## Checks",
        "",
        f"- bundle_sha256_valid: `{result.get('bundle_sha256_valid', False)}`",
        f"- bundle_members_valid: `{result.get('bundle_members_valid', False)}`",
        f"- sidecar_files_valid: `{result.get('sidecar_files_valid', False)}`",
        f"- sha256sums_valid: `{result.get('sha256sums_valid', False)}`",
        f"- forbidden_geometry_keys_absent: `{result.get('forbidden_geometry_keys_absent', False)}`",
        "",
        "## Reasons",
        "",
    ]
    for reason in result.get("reasons", []):
        lines.append(f"- {reason}")
    if not result.get("reasons"):
        lines.append("- All checks passed")
    return "\n".join(lines) + "\n"


def discover_bundle_manifests(reports_dir: Path) -> list[Path]:
    if not reports_dir.exists():
        return []
    manifests = sorted(reports_dir.rglob("*.zip.manifest.json"))
    return sorted(manifests, key=lambda p: str(p))


def load_manifest_list(manifest_list_path: Path) -> list[str]:
    if not manifest_list_path.exists():
        return []
    text = manifest_list_path.read_text(encoding="utf-8")
    # Strip BOM if present
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    paths: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line)
    return paths


def verify_export_bundle_batch(
    *,
    reports_dir: Path | None = None,
    manifest_list: list[str] | None = None,
    manifest_list_path: str | None = None,
    export_root: Path | None = None,
    fail_fast: bool = False,
) -> dict:
    export_root = export_root or Path.cwd()
    reasons: list[str] = []

    manifest_paths: list[Path] = []
    reports_dir_resolved: Path | None = None

    if reports_dir is not None:
        reports_dir_resolved = _resolve_path(str(reports_dir), export_root)
        manifest_paths = discover_bundle_manifests(reports_dir_resolved)
    elif manifest_list is not None:
        for path_str in manifest_list:
            manifest_paths.append(_resolve_path(path_str, export_root))
    else:
        reasons.append("Either reports_dir or manifest_list must be provided")

    if not reasons and not manifest_paths:
        reasons.append("No sidecar manifests found")

    results: list[dict] = []
    passed_count = 0
    failed_count = 0
    checked_file_count = 0

    for manifest_path in manifest_paths:
        single_result = verify_export_bundle(
            bundle_manifest_path=str(manifest_path),
            export_root=export_root,
        )
        results.append(single_result)
        checked_file_count += single_result.get("checked_file_count", 0)
        if single_result["status"] == "pass":
            passed_count += 1
        else:
            failed_count += 1
            if fail_fast:
                break

    status = "pass" if failed_count == 0 and not reasons else "fail"
    if failed_count > 0:
        reasons.append(f"{failed_count} bundle verification failed")

    return {
        "status": status,
        "export_root": str(export_root).replace("\\", "/"),
        "reports_dir": str(reports_dir_resolved).replace("\\", "/") if reports_dir_resolved else None,
        "manifest_list": manifest_list_path,
        "manifest_count": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "checked_file_count": checked_file_count,
        "fail_fast": fail_fast,
        "results": results,
        "reasons": reasons,
    }


def render_bundle_verify_batch_markdown(result: dict) -> str:
    lines = [
        "# Export Bundle Batch Verification",
        "",
        f"- Status: `{result['status']}`",
        f"- Export root: `{result.get('export_root', '')}`",
    ]
    if result.get("reports_dir"):
        lines.append(f"- Reports dir: `{result['reports_dir']}`")
    if result.get("manifest_list"):
        lines.append(f"- Manifest list: `{result['manifest_list']}`")
    lines.extend([
        f"- Manifest count: `{result.get('manifest_count', 0)}`",
        f"- Passed count: `{result.get('passed_count', 0)}`",
        f"- Failed count: `{result.get('failed_count', 0)}`",
        f"- Checked file count: `{result.get('checked_file_count', 0)}`",
        f"- Fail fast: `{result.get('fail_fast', False)}`",
        "",
        "## Failed Bundles",
        "",
    ])
    failed = [r for r in result.get("results", []) if r["status"] != "pass"]
    if failed:
        for f in failed:
            lines.append(f"- `{f.get('bundle_manifest_path', '')}`")
            for reason in f.get("reasons", []):
                lines.append(f"  - {reason}")
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Reasons",
        "",
    ])
    for reason in result.get("reasons", []):
        lines.append(f"- {reason}")
    if not result.get("reasons"):
        lines.append("- All checks passed")
    return "\n".join(lines) + "\n"
