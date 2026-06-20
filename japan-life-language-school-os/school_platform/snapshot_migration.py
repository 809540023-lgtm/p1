from __future__ import annotations

import copy
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _dedupe_by_key(rows: list[dict[str, Any]], key_field: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chosen: dict[Any, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for row in rows:
        key = row.get(key_field)
        if key is None:
            continue
        if key in chosen:
            dropped.append(chosen[key])
        chosen[key] = row
    kept = list(chosen.values())
    return kept, dropped


def analyze_snapshot_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    duplicate_groups: list[dict[str, Any]] = []
    rules = {
        "users": ("email",),
        "courses": ("slug",),
        "payments": ("order_no",),
    }
    for state_key, fields in rules.items():
        rows = payload.get(state_key, [])
        for field in fields:
            values = [row.get(field) for row in rows if row.get(field) is not None]
            duplicates = [
                {"field": field, "value": value, "count": count}
                for value, count in Counter(values).items()
                if count > 1
            ]
            if duplicates:
                duplicate_groups.append(
                    {
                        "state_key": state_key,
                        "field": field,
                        "duplicate_count": len(duplicates),
                        "samples": duplicates[:10],
                    }
                )
    return {
        "ready": len(duplicate_groups) == 0,
        "duplicate_groups": duplicate_groups,
        "duplicate_group_count": len(duplicate_groups),
    }


def normalize_snapshot_for_postgres(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = copy.deepcopy(payload)
    report = {
        "before": analyze_snapshot_integrity(payload),
        "dropped_rows": [],
        "course_id_remaps": 0,
    }

    courses = [row for row in normalized.get("courses", []) if isinstance(row, dict)]
    if courses:
        canonical_by_slug: dict[str, dict[str, Any]] = {}
        old_to_new_course_ids: dict[str, str] = {}
        dropped_courses: list[dict[str, Any]] = []
        for course in courses:
            slug = course.get("slug")
            if not slug:
                continue
            existing = canonical_by_slug.get(slug)
            if existing is not None:
                dropped_courses.append(existing)
                old_to_new_course_ids[str(existing.get("id"))] = str(course.get("id"))
            canonical_by_slug[slug] = course
        normalized["courses"] = list(canonical_by_slug.values())
        if dropped_courses:
            report["dropped_rows"].append(
                {
                    "state_key": "courses",
                    "field": "slug",
                    "dropped_count": len(dropped_courses),
                    "samples": [{"slug": item.get("slug"), "id": item.get("id")} for item in dropped_courses[:10]],
                }
            )
        classes = [row for row in normalized.get("classes", []) if isinstance(row, dict)]
        for class_item in classes:
            course_slug = class_item.get("course_slug")
            canonical_course = canonical_by_slug.get(str(course_slug)) if course_slug is not None else None
            if canonical_course and class_item.get("course_id") != canonical_course.get("id"):
                class_item["course_id"] = canonical_course.get("id")
                report["course_id_remaps"] += 1

    for state_key, field in (("users", "email"), ("payments", "order_no")):
        rows = [row for row in normalized.get(state_key, []) if isinstance(row, dict)]
        if not rows:
            continue
        deduped_rows, dropped = _dedupe_by_key(rows, field)
        normalized[state_key] = deduped_rows
        if dropped:
            report["dropped_rows"].append(
                {
                    "state_key": state_key,
                    "field": field,
                    "dropped_count": len(dropped),
                    "samples": [{field: item.get(field), "id": item.get("id")} for item in dropped[:10]],
                }
            )

    report["after"] = analyze_snapshot_integrity(normalized)
    report["ready"] = bool(report["after"]["ready"])
    return normalized, report


def snapshot_integrity_from_json(path: str) -> dict[str, Any]:
    payload_path = Path(path)
    if not payload_path.exists():
        return {
            "ready": True,
            "duplicate_groups": [],
            "duplicate_group_count": 0,
            "source_json_path": str(payload_path),
            "present": False,
        }
    raw = payload_path.read_text(encoding="utf-8")
    if not raw.strip():
        return {
            "ready": True,
            "duplicate_groups": [],
            "duplicate_group_count": 0,
            "source_json_path": str(payload_path),
            "present": True,
            "empty": True,
        }
    payload = json.loads(raw)
    report = analyze_snapshot_integrity(payload)
    report["source_json_path"] = str(payload_path)
    report["present"] = True
    report["empty"] = False
    return report
