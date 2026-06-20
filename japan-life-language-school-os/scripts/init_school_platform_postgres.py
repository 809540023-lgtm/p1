from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from school_platform.config import load_settings
from school_platform.repository import PostgresRepository


def main() -> None:
    settings = load_settings()
    if not settings.postgres_dsn:
        raise SystemExit("SCHOOL_PLATFORM_POSTGRES_DSN is required")
    repository = PostgresRepository(settings.postgres_dsn)
    readiness = repository.initialize()
    print(readiness)


if __name__ == "__main__":
    main()
