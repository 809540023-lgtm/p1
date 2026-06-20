from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Protocol

from school_platform.config import SchoolPlatformSettings


@dataclass(frozen=True)
class TableSpec:
    state_key: str
    table_name: str
    columns: tuple[str, ...]
    json_columns: tuple[str, ...] = ()


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
DOMAIN_TABLE_SQL = SQL_DIR / "japanese_school_platform_domain_tables.sql"
SNAPSHOT_TABLE_SQL = SQL_DIR / "japanese_school_platform_snapshot_store.sql"
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
INIT_SCRIPT = SCRIPT_DIR / "init_school_platform_postgres.py"
MIGRATE_SCRIPT = SCRIPT_DIR / "migrate_school_platform_json_to_postgres.py"
SMOKE_TEST_SCRIPT = SCRIPT_DIR / "smoke_test_school_platform_postgres.py"
CUTOVER_SCRIPT = SCRIPT_DIR / "cutover_school_platform_postgres.py"
DEPLOYMENT_SMOKE_SCRIPT = SCRIPT_DIR / "smoke_test_school_platform_deployment.py"
ROW_WRITE_PROBE_SCRIPT = SCRIPT_DIR / "verify_school_platform_postgres_row_writes.py"


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("staff", "school_platform_staff", ("id", "name", "role", "department", "title")),
    TableSpec(
        "users",
        "school_platform_users",
        ("id", "email", "name", "password_hash", "role", "staff_id", "permissions", "status", "parent_user_id", "account_type", "scope_label", "note"),
        ("permissions",),
    ),
    TableSpec(
        "courses",
        "school_platform_courses",
        ("id", "slug", "name", "course_type", "level", "delivery_mode", "price", "short_description", "objectives", "highlights", "modules", "teacher_names"),
        ("objectives", "highlights", "modules", "teacher_names"),
    ),
    TableSpec(
        "classes",
        "school_platform_classes",
        ("id", "course_id", "course_slug", "name", "teacher_name", "start_date", "end_date", "weekday", "start_time", "end_time", "capacity", "enrolled_count", "location_label", "status"),
    ),
    TableSpec(
        "leads",
        "school_platform_leads",
        (
            "id",
            "name",
            "phone",
            "email",
            "line_id",
            "source_channel",
            "campaign_name",
            "interested_course_slug",
            "budget_range",
            "japanese_level",
            "study_goal",
            "departure_plan_date",
            "intent_score",
            "win_probability",
            "status",
            "assigned_staff_name",
            "last_contact_at",
            "next_follow_up_at",
            "notes",
            "created_at",
            "updated_at",
        ),
    ),
    TableSpec("lead_logs", "school_platform_lead_logs", ("id", "lead_id", "staff_name", "contact_method", "content", "next_action", "created_at")),
    TableSpec("students", "school_platform_students", ("id", "chinese_name", "email", "phone", "japanese_level", "study_goal", "status", "created_at")),
    TableSpec("enrollments", "school_platform_enrollments", ("id", "student_id", "class_id", "status", "payment_status", "list_price", "paid_amount", "created_at")),
    TableSpec(
        "payments",
        "school_platform_payments",
        (
            "id",
            "enrollment_id",
            "order_no",
            "amount",
            "payment_method",
            "status",
            "provider",
            "provider_payment_id",
            "checkout_url",
            "client_token",
            "currency",
            "provider_status",
            "checkout_expires_at",
            "last_reconciled_at",
            "provider_last_error",
            "paid_at",
            "created_at",
            "updated_at",
        ),
    ),
    TableSpec("job_positions", "school_platform_job_positions", ("id", "title", "department", "employment_type", "location_label", "salary_range", "summary", "requirements", "status", "created_at"), ("requirements",)),
    TableSpec("applicants", "school_platform_applicants", ("id", "position_id", "name", "email", "phone", "resume_link", "note", "ai_match_score", "interview_status", "created_at")),
    TableSpec("interviews", "school_platform_interviews", ("id", "applicant_id", "interview_at", "interviewer_name", "format", "status", "feedback", "created_at")),
    TableSpec(
        "onboarding_records",
        "school_platform_onboarding_records",
        ("id", "applicant_id", "owner_name", "stage", "start_date", "probation_status", "probation_end_date", "checklist_items", "notes", "created_at", "updated_at"),
        ("checklist_items",),
    ),
    TableSpec("assignments", "school_platform_assignments", ("id", "class_id", "title", "content", "due_at", "created_by", "created_at")),
    TableSpec("assignment_submissions", "school_platform_assignment_submissions", ("id", "assignment_id", "student_id", "content", "status", "submitted_at", "feedback", "score")),
    TableSpec("attendance_records", "school_platform_attendance", ("id", "class_id", "student_id", "class_date", "status", "note", "marked_by", "created_at")),
    TableSpec("exams", "school_platform_exams", ("id", "class_id", "title", "exam_type", "instructions", "total_score", "due_at", "created_by", "created_at")),
    TableSpec("exam_submissions", "school_platform_exam_submissions", ("id", "exam_id", "student_id", "content", "status", "submitted_at", "feedback", "score", "graded_by")),
    TableSpec(
        "teaching_session_records",
        "school_platform_teaching_session_records",
        (
            "id",
            "class_id",
            "teacher_name",
            "class_date",
            "summary",
            "materials_link",
            "homework_summary",
            "next_class_focus",
            "student_risk_notes",
            "approval_status",
            "review_note",
            "reviewed_by",
            "submitted_at",
            "reviewed_at",
            "created_at",
            "updated_at",
        ),
        ("student_risk_notes",),
    ),
    TableSpec("ai_logs", "school_platform_ai_logs", ("id", "module_name", "actor_email", "action_name", "input_summary", "output_summary", "created_at")),
    TableSpec(
        "notifications",
        "school_platform_notifications",
        (
            "id",
            "user_email",
            "channel",
            "type",
            "title",
            "content",
            "status",
            "created_at",
            "external_recipient",
            "provider",
            "provider_message_id",
            "error_message",
            "attempt_count",
            "last_attempt_at",
            "delivered_at",
            "updated_at",
        ),
    ),
)

TABLE_SPEC_BY_KEY = {spec.state_key: spec for spec in TABLE_SPECS}


class StateRepository(Protocol):
    backend_name: str
    repository_mode: str

    def load(self) -> dict[str, Any] | None: ...

    def save(self, payload: dict[str, Any]) -> None: ...

    def save_state_keys(self, payload: dict[str, Any], state_keys: tuple[str, ...]) -> None: ...

    def readiness(self) -> dict[str, Any]: ...

    def initialize(self) -> dict[str, Any]: ...

    def migration_artifacts(self) -> dict[str, Any]: ...

    def query_supported(self) -> bool: ...

    def partial_write_supported(self) -> bool: ...

    def row_level_write_supported(self) -> bool: ...

    def mutation_tables(self) -> list[str]: ...


class JsonRepository:
    backend_name = "json"
    repository_mode = "snapshot_file"

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except JSONDecodeError:
            return None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_state_keys(self, payload: dict[str, Any], state_keys: tuple[str, ...]) -> None:
        self.save(payload)

    def readiness(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "repository_mode": self.repository_mode,
            "ready": True,
            "driver_installed": True,
            "dsn_present": False,
            "connectable": True,
            "initialized": True,
            "tables_ready": False,
            "message": "JSON repository is active.",
        }

    def initialize(self) -> dict[str, Any]:
        if not self.path.exists():
            self.save({})
        return self.readiness()

    def migration_artifacts(self) -> dict[str, Any]:
        return {
            "sql_domain_tables": str(DOMAIN_TABLE_SQL),
            "sql_snapshot_store": str(SNAPSHOT_TABLE_SQL),
            "init_script": str(INIT_SCRIPT),
            "migrate_script": str(MIGRATE_SCRIPT),
            "smoke_test_script": str(SMOKE_TEST_SCRIPT),
            "cutover_script": str(CUTOVER_SCRIPT),
            "deployment_smoke_script": str(DEPLOYMENT_SMOKE_SCRIPT),
            "row_write_probe_script": str(ROW_WRITE_PROBE_SCRIPT),
            "domain_sql_present": DOMAIN_TABLE_SQL.exists(),
            "snapshot_sql_present": SNAPSHOT_TABLE_SQL.exists(),
            "init_script_present": INIT_SCRIPT.exists(),
            "migrate_script_present": MIGRATE_SCRIPT.exists(),
            "smoke_test_script_present": SMOKE_TEST_SCRIPT.exists(),
            "cutover_script_present": CUTOVER_SCRIPT.exists(),
            "deployment_smoke_script_present": DEPLOYMENT_SMOKE_SCRIPT.exists(),
            "row_write_probe_script_present": ROW_WRITE_PROBE_SCRIPT.exists(),
        }

    def query_supported(self) -> bool:
        return False

    def partial_write_supported(self) -> bool:
        return False

    def row_level_write_supported(self) -> bool:
        return False

    def mutation_tables(self) -> list[str]:
        return []


class PostgresRepository:
    backend_name = "postgres"
    repository_mode = "domain_tables"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for postgres repository") from exc
        return psycopg.connect(self.dsn)

    def _execute_sql_file(self, path: Path) -> None:
        sql = path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
        with self._connect() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
            conn.commit()

    def _delete_all(self, cur) -> None:
        for spec in reversed(TABLE_SPECS):
            cur.execute(f"delete from {spec.table_name}")

    def _serialize_row(self, spec: TableSpec, record: dict[str, Any]) -> list[Any]:
        row: list[Any] = []
        for column in spec.columns:
            value = record.get(column)
            if column in spec.json_columns:
                row.append(json.dumps(value or [], ensure_ascii=False))
            else:
                row.append(value)
        return row

    def _query_rows(self, spec: TableSpec, where_sql: str = "", params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.initialize()
        columns_sql = ", ".join(spec.columns)
        sql = f"select {columns_sql} from {spec.table_name}"
        if where_sql:
            sql += f" where {where_sql}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = []
                for row in cur.fetchall():
                    item = dict(zip(spec.columns, row, strict=True))
                    for column in spec.json_columns:
                        value = item.get(column)
                        if isinstance(value, str):
                            item[column] = json.loads(value)
                    rows.append(item)
                return rows

    def _insert_rows(self, cur, spec: TableSpec, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        columns_sql = ", ".join(spec.columns)
        placeholders_sql = ", ".join(["%s"] * len(spec.columns))
        values = [self._serialize_row(spec, row) for row in rows]
        cur.executemany(
            f"insert into {spec.table_name} ({columns_sql}) values ({placeholders_sql})",
            values,
        )

    def _upsert_rows(self, cur, spec: TableSpec, rows: list[dict[str, Any]], key_columns: tuple[str, ...] = ("id",)) -> None:
        if not rows:
            return
        columns_sql = ", ".join(spec.columns)
        placeholders_sql = ", ".join(["%s"] * len(spec.columns))
        conflict_sql = ", ".join(key_columns)
        update_columns = [column for column in spec.columns if column not in key_columns]
        if update_columns:
            update_sql = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
            sql = (
                f"insert into {spec.table_name} ({columns_sql}) values ({placeholders_sql}) "
                f"on conflict ({conflict_sql}) do update set {update_sql}"
            )
        else:
            sql = (
                f"insert into {spec.table_name} ({columns_sql}) values ({placeholders_sql}) "
                f"on conflict ({conflict_sql}) do nothing"
            )
        values = [self._serialize_row(spec, row) for row in rows]
        cur.executemany(sql, values)

    def _replace_state_keys(self, cur, payload: dict[str, Any], state_keys: tuple[str, ...]) -> None:
        selected_specs = [TABLE_SPEC_BY_KEY[key] for key in state_keys if key in TABLE_SPEC_BY_KEY]
        for spec in reversed(selected_specs):
            cur.execute(f"delete from {spec.table_name}")
        for spec in selected_specs:
            rows = payload.get(spec.state_key, [])
            self._insert_rows(cur, spec, rows)

    def initialize(self) -> dict[str, Any]:
        self._execute_sql_file(DOMAIN_TABLE_SQL)
        return self.readiness()

    def load(self) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cur:
                payload = {spec.state_key: self._query_rows(spec) for spec in TABLE_SPECS}
        if not any(payload.values()):
            return None
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._delete_all(cur)
                for spec in TABLE_SPECS:
                    rows = payload.get(spec.state_key, [])
                    self._insert_rows(cur, spec, rows)
            conn.commit()

    def save_state_keys(self, payload: dict[str, Any], state_keys: tuple[str, ...]) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._replace_state_keys(cur, payload, state_keys)
            conn.commit()

    def readiness(self) -> dict[str, Any]:
        driver_installed = _psycopg_installed()
        if not self.dsn:
            return {
                "backend": self.backend_name,
                "repository_mode": self.repository_mode,
                "ready": False,
                "driver_installed": driver_installed,
                "dsn_present": False,
                "connectable": False,
                "initialized": False,
                "tables_ready": False,
                "message": "Postgres DSN is missing.",
            }
        if not driver_installed:
            return {
                "backend": self.backend_name,
                "repository_mode": self.repository_mode,
                "ready": False,
                "driver_installed": False,
                "dsn_present": True,
                "connectable": False,
                "initialized": False,
                "tables_ready": False,
                "message": "psycopg is not installed.",
            }
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    table_states = []
                    for spec in TABLE_SPECS:
                        cur.execute("select to_regclass(%s)", (f"public.{spec.table_name}",))
                        row = cur.fetchone()
                        table_states.append(bool(row and row[0]))
            tables_ready = all(table_states)
            return {
                "backend": self.backend_name,
                "repository_mode": self.repository_mode,
                "ready": tables_ready,
                "driver_installed": True,
                "dsn_present": True,
                "connectable": True,
                "initialized": tables_ready,
                "tables_ready": tables_ready,
                "table_count": len(TABLE_SPECS),
                "message": "Postgres domain tables are ready." if tables_ready else "Connection ok, domain tables not initialized yet.",
            }
        except Exception as exc:
            return {
                "backend": self.backend_name,
                "repository_mode": self.repository_mode,
                "ready": False,
                "driver_installed": True,
                "dsn_present": True,
                "connectable": False,
                "initialized": False,
                "tables_ready": False,
                "message": f"Connection failed: {exc}",
            }

    def migration_artifacts(self) -> dict[str, Any]:
        return {
            "sql_domain_tables": str(DOMAIN_TABLE_SQL),
            "sql_snapshot_store": str(SNAPSHOT_TABLE_SQL),
            "init_script": str(INIT_SCRIPT),
            "migrate_script": str(MIGRATE_SCRIPT),
            "smoke_test_script": str(SMOKE_TEST_SCRIPT),
            "cutover_script": str(CUTOVER_SCRIPT),
            "deployment_smoke_script": str(DEPLOYMENT_SMOKE_SCRIPT),
            "row_write_probe_script": str(ROW_WRITE_PROBE_SCRIPT),
            "domain_sql_present": DOMAIN_TABLE_SQL.exists(),
            "snapshot_sql_present": SNAPSHOT_TABLE_SQL.exists(),
            "init_script_present": INIT_SCRIPT.exists(),
            "migrate_script_present": MIGRATE_SCRIPT.exists(),
            "smoke_test_script_present": SMOKE_TEST_SCRIPT.exists(),
            "cutover_script_present": CUTOVER_SCRIPT.exists(),
            "deployment_smoke_script_present": DEPLOYMENT_SMOKE_SCRIPT.exists(),
            "row_write_probe_script_present": ROW_WRITE_PROBE_SCRIPT.exists(),
        }

    def query_supported(self) -> bool:
        return True

    def partial_write_supported(self) -> bool:
        return True

    def row_level_write_supported(self) -> bool:
        return True

    def mutation_tables(self) -> list[str]:
        return [spec.state_key for spec in TABLE_SPECS]

    def upsert_state_rows(
        self,
        state_key: str,
        rows: list[dict[str, Any]],
        key_columns: tuple[str, ...] = ("id",),
    ) -> int:
        spec = TABLE_SPEC_BY_KEY[state_key]
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_rows(cur, spec, rows, key_columns)
            conn.commit()
        return len(rows)

    def list_courses(self) -> list[dict[str, Any]]:
        return self._query_rows(TABLE_SPEC_BY_KEY["courses"])

    def get_course(self, slug: str) -> dict[str, Any] | None:
        rows = self._query_rows(TABLE_SPEC_BY_KEY["courses"], "slug = %s", (slug,))
        return rows[0] if rows else None

    def list_classes(self, status: str | None = None, course_slug: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if course_slug:
            clauses.append("course_slug = %s")
            params.append(course_slug)
        where_sql = " and ".join(clauses)
        return self._query_rows(TABLE_SPEC_BY_KEY["classes"], where_sql, tuple(params))

    def list_staff(self, role: str | None = None) -> list[dict[str, Any]]:
        where_sql = "role = %s" if role else ""
        params: tuple[Any, ...] = (role,) if role else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["staff"], where_sql, params)

    def list_leads(self, status: str | None = None) -> list[dict[str, Any]]:
        where_sql = "status = %s" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["leads"], where_sql, params)

    def get_lead(self, lead_id: str) -> dict[str, Any] | None:
        rows = self._query_rows(TABLE_SPEC_BY_KEY["leads"], "id = %s", (lead_id,))
        return rows[0] if rows else None

    def list_lead_logs(self, lead_id: str) -> list[dict[str, Any]]:
        return self._query_rows(TABLE_SPEC_BY_KEY["lead_logs"], "lead_id = %s", (lead_id,))

    def list_notifications(self, user_email: str | None = None) -> list[dict[str, Any]]:
        where_sql = "user_email = %s" if user_email else ""
        params: tuple[Any, ...] = (user_email,) if user_email else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["notifications"], where_sql, params)

    def get_student_by_email(self, email: str) -> dict[str, Any] | None:
        self.initialize()
        spec = TABLE_SPEC_BY_KEY["students"]
        columns_sql = ", ".join(spec.columns)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select {columns_sql} from {spec.table_name} where lower(email) = lower(%s) order by created_at desc limit 1",
                    (email,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return dict(zip(spec.columns, row, strict=True))

    def list_enrollments(self, student_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "student_id = %s" if student_id else ""
        params: tuple[Any, ...] = (student_id,) if student_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["enrollments"], where_sql, params)

    def list_payments(self, enrollment_ids: list[str] | None = None) -> list[dict[str, Any]]:
        if not enrollment_ids:
            return self._query_rows(TABLE_SPEC_BY_KEY["payments"])
        placeholders = ", ".join(["%s"] * len(enrollment_ids))
        return self._query_rows(TABLE_SPEC_BY_KEY["payments"], f"enrollment_id in ({placeholders})", tuple(enrollment_ids))

    def list_job_positions(self, status: str | None = None) -> list[dict[str, Any]]:
        where_sql = "status = %s" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["job_positions"], where_sql, params)

    def get_job_position(self, position_id: str) -> dict[str, Any] | None:
        rows = self._query_rows(TABLE_SPEC_BY_KEY["job_positions"], "id = %s", (position_id,))
        return rows[0] if rows else None

    def list_applicants(self, position_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "position_id = %s" if position_id else ""
        params: tuple[Any, ...] = (position_id,) if position_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["applicants"], where_sql, params)

    def list_interviews(self, applicant_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "applicant_id = %s" if applicant_id else ""
        params: tuple[Any, ...] = (applicant_id,) if applicant_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["interviews"], where_sql, params)

    def list_onboarding_records(self, applicant_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "applicant_id = %s" if applicant_id else ""
        params: tuple[Any, ...] = (applicant_id,) if applicant_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["onboarding_records"], where_sql, params)

    def list_ai_logs(self, module_name: str | None = None) -> list[dict[str, Any]]:
        where_sql = "module_name = %s" if module_name else ""
        params: tuple[Any, ...] = (module_name,) if module_name else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["ai_logs"], where_sql, params)

    def list_assignments(self, class_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "class_id = %s" if class_id else ""
        params: tuple[Any, ...] = (class_id,) if class_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["assignments"], where_sql, params)

    def list_assignment_submissions(
        self,
        student_id: str | None = None,
        assignment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if student_id:
            clauses.append("student_id = %s")
            params.append(student_id)
        if assignment_id:
            clauses.append("assignment_id = %s")
            params.append(assignment_id)
        return self._query_rows(TABLE_SPEC_BY_KEY["assignment_submissions"], " and ".join(clauses), tuple(params))

    def list_attendance(self, student_id: str | None = None, class_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if student_id:
            clauses.append("student_id = %s")
            params.append(student_id)
        if class_id:
            clauses.append("class_id = %s")
            params.append(class_id)
        return self._query_rows(TABLE_SPEC_BY_KEY["attendance_records"], " and ".join(clauses), tuple(params))

    def list_exams(self, class_id: str | None = None) -> list[dict[str, Any]]:
        where_sql = "class_id = %s" if class_id else ""
        params: tuple[Any, ...] = (class_id,) if class_id else ()
        return self._query_rows(TABLE_SPEC_BY_KEY["exams"], where_sql, params)

    def list_exam_submissions(
        self,
        student_id: str | None = None,
        exam_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if student_id:
            clauses.append("student_id = %s")
            params.append(student_id)
        if exam_id:
            clauses.append("exam_id = %s")
            params.append(exam_id)
        return self._query_rows(TABLE_SPEC_BY_KEY["exam_submissions"], " and ".join(clauses), tuple(params))

    def list_teaching_session_records(
        self,
        class_id: str | None = None,
        teacher_name: str | None = None,
        approval_status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if class_id:
            clauses.append("class_id = %s")
            params.append(class_id)
        if teacher_name:
            clauses.append("teacher_name = %s")
            params.append(teacher_name)
        if approval_status:
            clauses.append("approval_status = %s")
            params.append(approval_status)
        return self._query_rows(TABLE_SPEC_BY_KEY["teaching_session_records"], " and ".join(clauses), tuple(params))


def _psycopg_installed() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


def repository_readiness(settings: SchoolPlatformSettings) -> dict[str, Any]:
    if settings.storage_backend == "postgres":
        return PostgresRepository(settings.postgres_dsn or "").readiness()
    return JsonRepository(settings.json_path).readiness()


def build_repository(settings: SchoolPlatformSettings) -> StateRepository:
    if settings.storage_backend == "postgres":
        if not settings.postgres_dsn:
            raise RuntimeError("SCHOOL_PLATFORM_POSTGRES_DSN is required when storage backend is postgres")
        return PostgresRepository(settings.postgres_dsn)
    return JsonRepository(settings.json_path)
