from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from school_platform.config import load_settings
from school_platform.repository import JsonRepository, PostgresRepository
from school_platform.snapshot_migration import normalize_snapshot_for_postgres


def main() -> None:
    settings = load_settings()
    if not settings.postgres_dsn:
        raise SystemExit("SCHOOL_PLATFORM_POSTGRES_DSN is required")
    json_repo = JsonRepository(settings.json_path)
    payload = json_repo.load()
    if payload is None:
        raise SystemExit("No JSON snapshot found to migrate")
    normalized_payload, report = normalize_snapshot_for_postgres(payload)
    postgres_repo = PostgresRepository(settings.postgres_dsn)
    postgres_repo.initialize()
    postgres_repo.save(normalized_payload)
    print({"migrated": True, "keys": list(normalized_payload.keys()), "normalization_report": report})


if __name__ == "__main__":
    main()
