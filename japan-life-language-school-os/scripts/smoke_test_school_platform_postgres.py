from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from school_platform.config import load_settings
from school_platform.repository import PostgresRepository


def run_smoke_checks(repository: PostgresRepository) -> dict[str, object]:
    readiness = repository.readiness()
    courses = repository.list_courses()
    classes = repository.list_classes()
    leads = repository.list_leads()
    notifications = repository.list_notifications()
    onboarding_records = repository.list_onboarding_records()
    checks = [
        {
            "name": "readiness.ready",
            "ok": bool(readiness.get("ready")),
            "detail": readiness.get("message"),
        },
        {
            "name": "courses.readable",
            "ok": len(courses) >= 1,
            "detail": f"courses={len(courses)}",
        },
        {
            "name": "classes.readable",
            "ok": len(classes) >= 1,
            "detail": f"classes={len(classes)}",
        },
        {
            "name": "leads.readable",
            "ok": len(leads) >= 1,
            "detail": f"leads={len(leads)}",
        },
        {
            "name": "notifications.readable",
            "ok": len(notifications) >= 0,
            "detail": f"notifications={len(notifications)}",
        },
        {
            "name": "onboarding_records.readable",
            "ok": len(onboarding_records) >= 0,
            "detail": f"onboarding_records={len(onboarding_records)}",
        },
        {
            "name": "row_level_write_supported",
            "ok": repository.row_level_write_supported(),
            "detail": f"mutation_tables={len(repository.mutation_tables())}",
        },
    ]
    return {"readiness": readiness, "checks": checks}


def main() -> None:
    settings = load_settings()
    if not settings.postgres_dsn:
        raise SystemExit("SCHOOL_PLATFORM_POSTGRES_DSN is required")

    repository = PostgresRepository(settings.postgres_dsn)
    report = run_smoke_checks(repository)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(bool(item["ok"]) for item in report["checks"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
