from pathlib import Path

FORBIDDEN = ("redis", "rq", "celery", "airflow")


def test_no_queue_packages_or_imports():
    config_and_project_files = [Path("pyproject.toml"), *Path("config").rglob("*.*")]
    for path in config_and_project_files:
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN:
            assert forbidden not in text, f"{forbidden} found in {path}"

    for path in Path("src").rglob("*.py"):
        import_lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("import ") or stripped.startswith("from "):
                import_lines.append(stripped)
        imports_blob = "\n".join(import_lines)
        for forbidden in FORBIDDEN:
            assert forbidden not in imports_blob, f"{forbidden} import found in {path}"
