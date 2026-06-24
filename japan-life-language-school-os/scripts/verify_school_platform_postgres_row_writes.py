from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from uuid import uuid4

sys.path.append(str(Path(__file__).resolve().parents[1]))

from school_platform.config import load_settings
from school_platform.repository import PostgresRepository, TABLE_SPEC_BY_KEY


def _cleanup(repository: PostgresRepository, table_name: str, row_id: str) -> None:
    repository.initialize()
    with repository._connect() as conn:  # noqa: SLF001
        with conn.cursor() as cur:
            cur.execute(f"delete from {table_name} where id = %s", (row_id,))
        conn.commit()


def run_row_write_probe(repository: PostgresRepository) -> dict[str, object]:
    now = datetime.now().astimezone().isoformat()
    notification_id = str(uuid4())
    ai_log_id = str(uuid4())
    submission_id = str(uuid4())
    verification_attempt_id = str(uuid4())
    probe_email = f"probe+{notification_id[:8]}@jls.local"
    probe_module = f"row_write_probe_{ai_log_id[:8]}"
    assignment_id = str(uuid4())
    student_id = str(uuid4())

    repository.upsert_state_rows(
        "notifications",
        [
            {
                "id": notification_id,
                "user_email": probe_email,
                "channel": "in_app",
                "type": "row_write_probe",
                "title": "row_write_probe_created",
                "content": "initial insert",
                "status": "queued",
                "created_at": now,
                "attempt_count": 0,
                "last_attempt_at": None,
                "delivered_at": None,
                "updated_at": now,
            }
        ],
    )
    repository.upsert_state_rows(
        "notifications",
        [
            {
                "id": notification_id,
                "user_email": probe_email,
                "channel": "in_app",
                "type": "row_write_probe",
                "title": "row_write_probe_updated",
                "content": "upsert update",
                "status": "sent",
                "created_at": now,
                "attempt_count": 1,
                "last_attempt_at": now,
                "delivered_at": now,
                "updated_at": now,
            }
        ],
    )
    notification_rows = [item for item in repository.list_notifications(probe_email) if str(item["id"]) == notification_id]

    repository.upsert_state_rows(
        "ai_logs",
        [
            {
                "id": ai_log_id,
                "module_name": probe_module,
                "actor_email": probe_email,
                "action_name": "probe_insert",
                "input_summary": "initial",
                "output_summary": "created",
                "created_at": now,
            }
        ],
    )
    repository.upsert_state_rows(
        "ai_logs",
        [
            {
                "id": ai_log_id,
                "module_name": probe_module,
                "actor_email": probe_email,
                "action_name": "probe_update",
                "input_summary": "updated",
                "output_summary": "updated",
                "created_at": now,
            }
        ],
    )
    ai_log_rows = [item for item in repository.list_ai_logs(probe_module) if str(item["id"]) == ai_log_id]

    repository.upsert_state_rows(
        "assignment_submissions",
        [
            {
                "id": submission_id,
                "assignment_id": assignment_id,
                "student_id": student_id,
                "content": "probe submission",
                "status": "submitted",
                "submitted_at": now,
                "feedback": None,
                "score": None,
            }
        ],
    )
    repository.upsert_state_rows(
        "assignment_submissions",
        [
            {
                "id": submission_id,
                "assignment_id": assignment_id,
                "student_id": student_id,
                "content": "probe submission revised",
                "status": "graded",
                "submitted_at": now,
                "feedback": "probe feedback",
                "score": 95,
            }
        ],
    )
    submission_rows = [item for item in repository.list_assignment_submissions(student_id=student_id) if str(item["id"]) == submission_id]

    repository.upsert_state_rows(
        "teacher_verification_attempts",
        [
            {
                "id": verification_attempt_id,
                "teacher_name": "Aki Mori",
                "teacher_email": "aki@jls.local",
                "score": 84,
                "passed": False,
                "required_score": 85,
                "question_ids": [str(uuid4())],
                "answers": {"q1": "A"},
                "weak_section_slugs": ["platform-ops"],
                "unlocked_permission": False,
                "submitted_at": now,
                "reviewer_note": "retry_required",
            }
        ],
    )
    repository.upsert_state_rows(
        "teacher_verification_attempts",
        [
            {
                "id": verification_attempt_id,
                "teacher_name": "Aki Mori",
                "teacher_email": "aki@jls.local",
                "score": 92,
                "passed": True,
                "required_score": 85,
                "question_ids": [str(uuid4())],
                "answers": {"q1": "B"},
                "weak_section_slugs": [],
                "unlocked_permission": True,
                "submitted_at": now,
                "reviewer_note": "passed",
            }
        ],
    )
    verification_rows = [
        item
        for item in repository.list_teacher_verification_attempts("Aki Mori")
        if str(item["id"]) == verification_attempt_id
    ]

    checks = [
        {
            "name": "notifications.upsert",
            "ok": len(notification_rows) == 1 and notification_rows[0]["title"] == "row_write_probe_updated" and notification_rows[0]["status"] == "sent" and notification_rows[0]["attempt_count"] == 1,
            "detail": f"rows={len(notification_rows)}",
        },
        {
            "name": "ai_logs.upsert",
            "ok": len(ai_log_rows) == 1 and ai_log_rows[0]["action_name"] == "probe_update",
            "detail": f"rows={len(ai_log_rows)}",
        },
        {
            "name": "assignment_submissions.upsert",
            "ok": len(submission_rows) == 1 and submission_rows[0]["status"] == "graded" and submission_rows[0]["score"] == 95,
            "detail": f"rows={len(submission_rows)}",
        },
        {
            "name": "teacher_verification_attempts.upsert",
            "ok": len(verification_rows) == 1 and verification_rows[0]["score"] == 92 and bool(verification_rows[0]["unlocked_permission"]),
            "detail": f"rows={len(verification_rows)}",
        },
    ]

    _cleanup(repository, TABLE_SPEC_BY_KEY["notifications"].table_name, notification_id)
    _cleanup(repository, TABLE_SPEC_BY_KEY["ai_logs"].table_name, ai_log_id)
    _cleanup(repository, TABLE_SPEC_BY_KEY["assignment_submissions"].table_name, submission_id)
    _cleanup(repository, TABLE_SPEC_BY_KEY["teacher_verification_attempts"].table_name, verification_attempt_id)

    return {"checks": checks, "success": all(bool(item["ok"]) for item in checks)}


def main() -> None:
    settings = load_settings()
    if not settings.postgres_dsn:
        raise SystemExit("SCHOOL_PLATFORM_POSTGRES_DSN is required")

    repository = PostgresRepository(settings.postgres_dsn)
    report = run_row_write_probe(repository)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
