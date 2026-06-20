from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _check(name: str, ok: bool, detail: str) -> dict[str, object]:
    return {"name": name, "ok": ok, "detail": detail}


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    body = None
    merged_headers = {"User-Agent": "JapanLifeLanguageSchoolOS-Smoke/1.0"}
    if headers:
        merged_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"
    request = Request(f"{base_url.rstrip('/')}{path}", data=body, headers=merged_headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            status_code = getattr(response, "status", 200)
            raw = response.read().decode("utf-8")
            return status_code, json.loads(raw) if raw.strip() else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return exc.code, None
    except (URLError, TimeoutError):
        return 0, None


def run_deployment_smoke(base_url: str, email: str, password: str) -> dict[str, object]:
    normalized_base_url = base_url.rstrip("/")
    checks: list[dict[str, object]] = []

    progress_status, progress = _request_json(normalized_base_url, "/school-platform/api/progress")
    progress_payload = (progress or {}).get("data", {})
    checks.append(
        _check(
            "progress_api",
            progress_status == 200 and int(progress_payload.get("tests_passing", 0)) >= 66,
            f"status={progress_status}, tests_passing={progress_payload.get('tests_passing', 'n/a')}",
        )
    )

    storage_status, storage = _request_json(normalized_base_url, "/school-platform/api/system/storage")
    storage_payload = (storage or {}).get("data", {})
    checks.append(
        _check(
            "system_storage",
            storage_status == 200
            and bool(storage_payload.get("readiness", {}).get("ready"))
            and "payment_provider" in storage_payload
            and "notification_providers" in storage_payload,
            f"status={storage_status}, backend={storage_payload.get('backend', 'n/a')}",
        )
    )

    ops_status, ops = _request_json(normalized_base_url, "/school-platform/api/system/operational-readiness")
    ops_payload = (ops or {}).get("data", {})
    checks.append(
        _check(
            "operational_readiness",
            ops_status == 200 and bool(ops_payload.get("ready_for_operations")),
            f"status={ops_status}, mode={ops_payload.get('current_mode', 'n/a')}",
        )
    )

    courses_status, courses = _request_json(normalized_base_url, "/school-platform/api/public/courses")
    course_count = len((courses or {}).get("data", []))
    checks.append(_check("public_courses", courses_status == 200 and course_count >= 1, f"status={courses_status}, courses={course_count}"))

    classes_status, classes = _request_json(normalized_base_url, "/school-platform/api/public/classes/open")
    class_count = len((classes or {}).get("data", []))
    checks.append(_check("open_classes", classes_status == 200 and class_count >= 1, f"status={classes_status}, classes={class_count}"))

    login_status, login = _request_json(
        normalized_base_url,
        "/school-platform/api/auth/login",
        method="POST",
        payload={"email": email, "password": password},
    )
    token = ((login or {}).get("data") or {}).get("access_token")
    checks.append(_check("auth_login", login_status == 200 and bool(token), f"status={login_status}"))

    if token:
        auth_headers = {"Authorization": f"Bearer {token}"}
        secured_checks = [
            ("reports_overview", "/school-platform/api/reports/overview"),
            ("weekly_summary", "/school-platform/api/reports/weekly-summary"),
            ("ai_status", "/school-platform/api/ai/status"),
            ("recruiting_jobs", "/school-platform/api/recruiting/jobs"),
            ("finance_overview", "/school-platform/api/finance/overview"),
            ("messages_overview", "/school-platform/api/messages/overview"),
        ]
        for name, path in secured_checks:
            status_code, payload = _request_json(normalized_base_url, path, headers=auth_headers)
            ok = status_code == 200
            if name == "messages_overview":
                ok = ok and "providers" in ((payload or {}).get("data") or {})
            checks.append(_check(name, ok, f"status={status_code}"))

    return {
        "base_url": normalized_base_url,
        "auth_email": email,
        "checks": checks,
        "success": all(bool(item["ok"]) for item in checks),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("SCHOOL_PLATFORM_BASE_URL", "http://127.0.0.1:8011"))
    parser.add_argument("--email", default=os.getenv("SCHOOL_PLATFORM_SMOKE_EMAIL", "manager@jls.local"))
    parser.add_argument("--password", default=os.getenv("SCHOOL_PLATFORM_SMOKE_PASSWORD", "manager123"))
    args = parser.parse_args()

    report = run_deployment_smoke(args.base_url, args.email, args.password)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
