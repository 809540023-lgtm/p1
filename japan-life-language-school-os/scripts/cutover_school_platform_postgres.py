from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from school_platform.config import load_settings
from school_platform.repository import JsonRepository, PostgresRepository, TABLE_SPECS
from school_platform.snapshot_migration import normalize_snapshot_for_postgres
from smoke_test_school_platform_postgres import run_smoke_checks
from verify_school_platform_postgres_row_writes import run_row_write_probe


def _state_counts(payload: dict[str, object]) -> dict[str, int]:
    return {spec.state_key: len(payload.get(spec.state_key, [])) for spec in TABLE_SPECS}


def main() -> None:
    settings = load_settings()
    if not settings.postgres_dsn:
        raise SystemExit("SCHOOL_PLATFORM_POSTGRES_DSN is required")

    json_repo = JsonRepository(settings.json_path)
    source_payload = json_repo.load()
    if source_payload is None:
        raise SystemExit("No JSON snapshot found to migrate")
    normalized_payload, normalization_report = normalize_snapshot_for_postgres(source_payload)

    source_counts = _state_counts(source_payload)
    normalized_counts = _state_counts(normalized_payload)
    postgres_repo = PostgresRepository(settings.postgres_dsn)
    readiness_before = postgres_repo.readiness()
    readiness_after_init = postgres_repo.initialize()
    postgres_repo.save(normalized_payload)
    target_payload = postgres_repo.load() or {}
    target_counts = _state_counts(target_payload)
    mismatches = {
        state_key: {"source": normalized_counts[state_key], "target": target_counts[state_key]}
        for state_key in normalized_counts
        if normalized_counts[state_key] != target_counts[state_key]
    }
    smoke = run_smoke_checks(postgres_repo)
    row_write_probe = run_row_write_probe(postgres_repo)
    success = not mismatches and all(bool(item["ok"]) for item in smoke["checks"]) and bool(row_write_probe["success"])
    report = {
        "success": success,
        "source_json_path": settings.json_path,
        "readiness_before": readiness_before,
        "readiness_after_init": readiness_after_init,
        "source_counts": source_counts,
        "normalized_counts": normalized_counts,
        "target_counts": target_counts,
        "normalization_report": normalization_report,
        "mismatches": mismatches,
        "smoke": smoke,
        "row_write_probe": row_write_probe,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
