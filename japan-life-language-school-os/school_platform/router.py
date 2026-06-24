from __future__ import annotations

import mimetypes
from datetime import date, datetime, time
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ValidationError

from school_platform.ai_runtime import SchoolPlatformAiRuntime
from school_platform.auth import auth_service, current_token, get_current_user, require_roles, security
from school_platform.schemas import (
    ApplicantStatusUpdateRequest,
    AssignmentCreateRequest,
    AssignmentSubmissionCreateRequest,
    AttendanceMarkRequest,
    AuthLoginRequest,
    BroadcastMessageRequest,
    ClassUpsertRequest,
    CourseModuleUpsertRequest,
    CourseUpsertRequest,
    EnrollmentCreate,
    ExamCreateRequest,
    ExamSubmissionCreateRequest,
    InterviewCreateRequest,
    InterviewUpdateRequest,
    JobPositionCreateRequest,
    LessonPlanDraftRequest,
    LeadAssignmentRequest,
    LeadStatusChangeRequest,
    NotificationCreate,
    NotificationStatusUpdateRequest,
    OnboardingUpsertRequest,
    PaymentIntentCreate,
    PaymentWebhookPayload,
    ApplicantCreateRequest,
    SubmissionGradeRequest,
    SupportReplyRequest,
    SubAccountCreateRequest,
    TeachingMaterialRecord,
    TeachingSessionReviewRequest,
    TeachingSessionUpsertRequest,
    TeachingMaterialUpsertRequest,
    TeacherVerificationSubmitRequest,
    TrialBookingCreate,
)
from school_platform.services import (
    AccountAdminService,
    AdmissionsService,
    AiAssistantService,
    AnalyticsService,
    CatalogService,
    ConsultantWorkspaceService,
    CourseContentService,
    CurriculumAdminService,
    ExecutiveDashboardService,
    FinanceService,
    LeadWorkflowService,
    NotificationService,
    PlatformStatusService,
    PublicAdmissionsService,
    RecruitingService,
    SchedulingService,
    StaffOpsService,
    StudentAdminService,
    TeacherWorkspaceService,
    TeacherVerificationService,
    TeachingOpsService,
    StudentSupportService,
    StudentPortalService,
)
from school_platform.store import store

class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


_MAX_MATERIAL_UPLOAD_BYTES = 15 * 1024 * 1024


router = APIRouter(prefix="/school-platform", tags=["school-platform"])
api_router = APIRouter(prefix="/api", default_response_class=Utf8JSONResponse)
catalog_service = CatalogService(store)
admissions_service = AdmissionsService(store)
student_portal_service = StudentPortalService(store, catalog_service, admissions_service)
platform_status_service = PlatformStatusService(store)
finance_service = FinanceService(store)
teaching_ops_service = TeachingOpsService(store, catalog_service, student_portal_service)
teacher_workspace_service = TeacherWorkspaceService(catalog_service, teaching_ops_service, store)
teacher_verification_service = TeacherVerificationService(store)
lead_workflow_service = LeadWorkflowService(store, admissions_service)
curriculum_admin_service = CurriculumAdminService(store)
notification_service = NotificationService(store)
public_admissions_service = PublicAdmissionsService(store, catalog_service)
school_platform_ai_runtime = SchoolPlatformAiRuntime()
ai_assistant_service = AiAssistantService(store, admissions_service, catalog_service, student_portal_service, school_platform_ai_runtime)
student_support_service = StudentSupportService(student_portal_service, notification_service)
student_admin_service = StudentAdminService(student_portal_service)
recruiting_service = RecruitingService(store)
analytics_service = AnalyticsService(store, recruiting_service, school_platform_ai_runtime, teaching_ops_service, student_portal_service)
staff_ops_service = StaffOpsService(admissions_service, catalog_service, teaching_ops_service, teacher_workspace_service)
consultant_workspace_service = ConsultantWorkspaceService(admissions_service)
scheduling_service = SchedulingService(catalog_service)
course_content_service = CourseContentService(store, catalog_service)
executive_dashboard_service = ExecutiveDashboardService(
    admissions_service,
    catalog_service,
    finance_service,
    teaching_ops_service,
    staff_ops_service,
    student_admin_service,
    recruiting_service,
    analytics_service,
)
account_admin_service = AccountAdminService(store)


class LeadLogCreate(BaseModel):
    staff_name: str
    contact_method: str
    content: str
    next_action: str | None = None


def _format_jpy(amount: float) -> str:
    return f"JPY {amount:,.0f}"


def _split_multivalue_text(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()]


def _materials_storage_root() -> Path:
    root = Path(store.settings.materials_storage_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize_material_file_name(raw_name: str) -> str:
    file_name = Path(raw_name or "").name.strip() or "material.bin"
    sanitized = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "-" for ch in file_name)
    return sanitized.strip(".-") or "material.bin"


def _store_uploaded_material_file(course_slug: str, class_id: UUID | None, uploaded_file: UploadFile) -> dict[str, object]:
    raw_name = Path(uploaded_file.filename or "").name or "material.bin"
    data = uploaded_file.file.read(_MAX_MATERIAL_UPLOAD_BYTES + 1)
    uploaded_file.file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded material file is empty")
    if len(data) > _MAX_MATERIAL_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Uploaded material file exceeds 15 MB limit")

    root = _materials_storage_root()
    safe_name = _sanitize_material_file_name(raw_name)
    subdir = root / course_slug / (f"class-{class_id}" if class_id else "course-library")
    subdir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4()}-{safe_name}"
    target = subdir / stored_name
    target.write_bytes(data)
    return {
        "file_name": raw_name,
        "stored_path": str(target.relative_to(root)),
        "mime_type": uploaded_file.content_type or mimetypes.guess_type(raw_name)[0] or "application/octet-stream",
        "file_size_bytes": len(data),
    }


def _material_access_href(material_id: UUID, email: str | None = None, teacher_name: str | None = None) -> str:
    base = f"/school-platform/materials/{material_id}/download"
    query: dict[str, str] = {}
    if email:
        query["email"] = email
    if teacher_name:
        query["teacher_name"] = teacher_name
    if not query:
        return base
    return f"{base}?{urlencode(query)}"


def _material_asset_html(
    material: TeachingMaterialRecord,
    *,
    email: str | None = None,
    teacher_name: str | None = None,
    label: str = "下載教材",
) -> str:
    actions = [f"<a href='{escape(_material_access_href(material.id, email, teacher_name))}'>{escape(label)}</a>"]
    if material.storage_kind == "uploaded_file" and material.file_name:
        actions.append(f"<span class='chip'>檔案 {escape(material.file_name)}</span>")
    if material.material_url and material.storage_kind == "external_url":
        actions.append(f"<span class='chip'>外部連結</span>")
    elif material.material_url:
        actions.append(f"<span class='chip'>含來源連結</span>")
    return f"<p>{' / '.join(actions)}</p>"


def _material_source_html(material: TeachingMaterialRecord) -> str:
    if not material.material_url or material.storage_kind == "external_url":
        return ""
    return f"<p>來源：<a href='{escape(material.material_url)}'>{escape(material.material_url)}</a></p>"


def _optional_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if credentials is None:
        return None
    return auth_service.current_user(credentials.credentials)


def _assert_material_access(material: TeachingMaterialRecord, *, email: str | None, teacher_name: str | None, user) -> None:
    if user is not None and user.role in {"super_admin", "manager", "consultant", "teacher"}:
        return
    if teacher_name and material.owner_type == "teacher" and material.created_by == teacher_name and material.status != "archived":
        return
    if material.status != "published":
        raise HTTPException(status_code=403, detail="Material is not published")
    if material.visibility == "public":
        return
    if material.visibility == "enrolled_only" and email:
        try:
            if student_portal_service.student_has_material_access(email, material):
                return
        except KeyError:
            pass
    raise HTTPException(status_code=403, detail="Material access denied")


def _resolve_uploaded_material_path(stored_path: str) -> Path:
    root = _materials_storage_root().resolve()
    target = (root / stored_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid material path")
    return target


def _create_material_from_form(
    *,
    course_slug: str,
    class_id: UUID | None,
    title: str,
    description: str,
    material_url: str,
    owner_type: str,
    visibility: str,
    created_by: str,
    uploaded_file: UploadFile | None,
) -> TeachingMaterialRecord:
    normalized_url = material_url.strip() or None
    upload_meta: dict[str, object] = {}
    storage_kind = "external_url"
    if uploaded_file is not None and uploaded_file.filename:
        upload_meta = _store_uploaded_material_file(course_slug, class_id, uploaded_file)
        storage_kind = "uploaded_file"
    elif uploaded_file is not None:
        uploaded_file.file.close()
    if normalized_url is None and not upload_meta:
        raise HTTPException(status_code=400, detail="Provide a material URL or upload a file")

    payload = TeachingMaterialUpsertRequest(
        course_slug=course_slug,
        class_id=class_id,
        title=title,
        description=description,
        material_url=normalized_url,
        storage_kind=storage_kind,
        file_name=upload_meta.get("file_name"),
        stored_path=upload_meta.get("stored_path"),
        mime_type=upload_meta.get("mime_type"),
        file_size_bytes=upload_meta.get("file_size_bytes"),
        owner_type=owner_type,
        visibility=visibility,
        status="published",
        created_by=created_by,
    )
    try:
        return course_content_service.create_material(payload)
    except Exception:
        if upload_meta.get("stored_path"):
            candidate = _materials_storage_root() / str(upload_meta["stored_path"])
            if candidate.exists():
                candidate.unlink()
        raise


def _risk_pill(level: str, label: str | None = None) -> str:
    labels = {"low": "低風險", "medium": "中風險", "high": "高風險"}
    text = labels.get(level, level)
    if label:
        text = f"{label} {text}"
    return f"<span class='risk-pill {escape(level)}'>{escape(text)}</span>"


def _render_portal_nav_cards(items: list[dict[str, str]]) -> str:
    return "".join(
        "<a class='portal-nav-card' "
        f"href='{escape(item['href'])}'>"
        f"<span class='portal-nav-kicker'>{escape(item['kicker'])}</span>"
        f"<strong>{escape(item['title'])}</strong>"
        f"<p>{escape(item['note'])}</p>"
        "</a>"
        for item in items
    )


def _render_task_items(items: list[dict[str, str]]) -> str:
    return "".join(
        "<article class='task-item'>"
        f"<span class='task-marker'>{escape(item['index'])}</span>"
        "<div class='task-content'>"
        f"<strong>{escape(item['title'])}</strong>"
        f"<p>{escape(item['note'])}</p>"
        "</div>"
        "</article>"
        for item in items
    )


def _franchise_vap_blueprint() -> dict[str, object]:
    return {
        "slogan": "不是因為你不會使用 AI 機器人，而是因為你不知道 AI 機器人到底可以做什麼。",
        "hero_title": "AI-aging 加盟招商 VAP",
        "hero_subtitle": "把加盟招商從傳統廣告導向，改成 AI agents 精準找人、教育內容建立信任、學員分享持續放大的全新營運模式。",
        "positioning": [
            "首頁先推加盟招商，再把 AI Edge 優勢與教學交付串成一條成交流程。",
            "不再靠誇張廣告轟炸，而是持續找到真正有日本生活、工作與日文需求的人。",
            "線上推廣、線下交流、實體教育與 AI agent 並行，讓加盟夥伴更快形成營收節奏。",
        ],
        "vap_cards": [
            {
                "kicker": "Value",
                "title": "找到固定、正確的日文需求者",
                "body": "我們的招生邏輯不是把廣告喊更大，而是透過 AI-aging 模式，把需求辨識、內容導流與後續跟進做得更精準。",
            },
            {
                "kicker": "AI-aging",
                "title": "10 到 100 個 AI agents 的招商編制",
                "body": "可依地區、族群、主題與渠道部署 10 到 100 個 AI agents，同步覆蓋傳統營運會做的搜尋、內容鋪陳、社群互動與跟進節奏。",
            },
            {
                "kicker": "Proof",
                "title": "用學習交付把加盟收入做穩",
                "body": "不只賣加盟，而是把實體交流、線上學習、日語生活融入與 AI Edge 練習區一起交付，讓加盟主有更完整的成交與續報基礎。",
            },
        ],
        "agent_stack": [
            "需求搜尋 agents：持續找出在日生活、求職、創業與家屬陪讀相關的日文需求者。",
            "內容互動 agents：依場景投放日語學習、赴日生活、面試與社群互動內容。",
            "跟進轉換 agents：用 CRM 節奏推進加盟說明、試聽、報名與區域合作洽談。",
            "學員分享 agents：把已在學學員的分享、推薦碼與激勵任務變成穩定的口碑飛輪。",
        ],
        "ai_edge_points": [
            "AI Edge 機器人不只幫總部招生，也讓學生在學習過程中參與推廣。",
            "學員透過分享任務、推薦碼、社群貼文與交流活動獲得激勵、贈品與新課程。",
            "推廣行為與學習動機被設計成同一個循環，形成與傳統行銷完全不同的擴散模式。",
        ],
        "training_rights": [
            "加盟費：JPY 100,000 / 區，大阪先切十區試點。",
            "加盟即含 6 小時 AI agent 行銷陪跑，直接教加盟者怎麼把 AI 用在招生與經營。",
            "加盟即含 1 場加盟主實體開營訓練，讓團隊在線下快速對齊品牌、話術與流程。",
            "加盟即含 20 小時加盟主線上營運培訓，讓團隊能持續複製與擴張。",
        ],
        "share_loop": [
            "學生學習後立刻有可分享的內容與任務，不只是單純上課。",
            "分享成功可獲得激勵、贈品、額外學習資源或新課程。",
            "加盟主可從學員分享數據看到哪個班級、哪個地區最有擴散力。",
        ],
    }


def _shell_navigation() -> str:
    items = [
        ("/school-platform", "平台首頁", "品牌、招生與課程入口"),
        ("/school-platform/franchise-vap", "加盟 VAP", "AI-aging 招商與 AI Edge 優勢"),
        ("/school-platform/courses", "課程產品", "課程線、班級與報名"),
        ("/school-platform/admin", "營運後台", "招生、財務、教務總覽"),
        ("/school-platform/admin/course-content", "內容治理", "平台核心課綱與教師補充內容"),
        ("/school-platform/operational-readiness", "今日可營運", "目前哪些模組已可直接操作"),
        ("/school-platform/admin/subaccounts", "子帳號中心", "主帳號與子帳號管理"),
        ("/school-platform/progress", "開發進度", "目前已完成與接續項目"),
        ("/school-platform/system", "系統狀態", "資料層與整合 readiness"),
        ("/school-platform/launch-readiness", "上線檢查", "正式 deploy 前 blocker"),
        ("/school-platform/admin/messages", "訊息中心", "Email、LINE、站內通知"),
        ("/school-platform/admin/finance", "財務中心", "付款、營收與對帳"),
    ]
    return "".join(
        "<a class='nav-link' "
        f"href='{escape(path)}' data-nav-prefix='{escape(path)}'>"
        f"<span class='nav-link-title'>{escape(label)}</span>"
        f"<span class='nav-link-note'>{escape(note)}</span>"
        "</a>"
        for path, label, note in items
    )


def _page_shell(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="zh-Hant">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{escape(title)}</title>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800;900&family=Noto+Serif+JP:wght@600;700;900&display=swap" rel="stylesheet" />
        <style>
          :root {{
            --bg: #f4eee4;
            --bg-deep: #e8ddcb;
            --paper: rgba(255, 252, 247, .9);
            --paper-strong: #fffdfa;
            --paper-muted: rgba(248, 242, 234, .92);
            --ink: #13231f;
            --muted: #5a6864;
            --line: rgba(39, 58, 54, .12);
            --line-strong: rgba(39, 58, 54, .22);
            --accent: #c35d34;
            --accent-strong: #a44322;
            --accent-soft: rgba(195, 93, 52, .12);
            --forest: #234b44;
            --forest-strong: #18332f;
            --forest-soft: rgba(35, 75, 68, .1);
            --gold: #c79a48;
            --gold-soft: rgba(199, 154, 72, .16);
            --ok: #1f7a5b;
            --warn: #c2761f;
            --danger: #b13a32;
            --shadow-lg: 0 26px 70px rgba(28, 31, 27, .14);
            --shadow-md: 0 16px 38px rgba(28, 31, 27, .1);
            --shadow-sm: 0 10px 24px rgba(28, 31, 27, .08);
          }}
          * {{ box-sizing: border-box; }}
          body {{
            margin: 0;
            font-family: "Noto Sans TC", ui-sans-serif, sans-serif;
            background:
              radial-gradient(circle at 0% 0%, rgba(195,93,52,.18), transparent 24%),
              radial-gradient(circle at 84% 10%, rgba(35,75,68,.16), transparent 22%),
              radial-gradient(circle at 100% 100%, rgba(199,154,72,.12), transparent 24%),
              linear-gradient(180deg, #fbf7f0 0%, var(--bg) 48%, #ede3d4 100%);
            color: var(--ink);
            min-height: 100vh;
          }}
          body::before {{
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
              linear-gradient(rgba(255,255,255,.2) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,.14) 1px, transparent 1px);
            background-size: 34px 34px;
            mask-image: linear-gradient(180deg, rgba(0,0,0,.34), transparent 80%);
          }}
          body::after {{
            content: "";
            position: fixed;
            top: -180px;
            right: -120px;
            width: 520px;
            height: 520px;
            border-radius: 999px;
            pointer-events: none;
            background:
              radial-gradient(circle, rgba(255,255,255,.55) 0%, rgba(255,255,255,.16) 36%, transparent 68%);
            filter: blur(6px);
          }}
          a {{ color: var(--accent); text-decoration: none; }}
          button {{ font: inherit; }}
          .wrap {{ max-width: 1440px; margin: 0 auto; padding: 24px 24px 80px; }}
          .topbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 24px;
            padding: 16px 20px;
            border: 1px solid rgba(255,255,255,.62);
            border-radius: 30px;
            background: rgba(255,252,247,.8);
            box-shadow: var(--shadow-md);
            backdrop-filter: blur(18px);
            position: sticky;
            top: 18px;
            z-index: 30;
          }}
          .brand-lockup {{ display: flex; align-items: center; gap: 14px; }}
          .brand-mark {{
            width: 56px;
            height: 56px;
            border-radius: 20px;
            display: grid;
            place-items: center;
            background:
              linear-gradient(145deg, rgba(195,93,52,.98), rgba(35,75,68,.94));
            color: #fff8f1;
            font-family: "Noto Serif JP", serif;
            font-size: 25px;
            font-weight: 900;
            box-shadow: 0 14px 30px rgba(88, 39, 21, .24);
          }}
          .brand-stack {{ display: grid; gap: 3px; }}
          .brand-link {{
            color: var(--forest);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .15em;
            text-transform: uppercase;
          }}
          .brand-subtitle {{
            color: var(--muted);
            font-size: 15px;
            font-weight: 700;
          }}
          .topbar-actions {{
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 12px;
            flex-wrap: wrap;
          }}
          .lang-switcher {{
            display: inline-flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
          }}
          .lang-label {{
            font-size: 12px;
            color: var(--muted);
            font-weight: 700;
          }}
          .lang-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(39, 58, 54, .12);
            background: rgba(255,255,255,.94);
            color: var(--forest);
            font-size: 13px;
            font-weight: 700;
          }}
          .lang-pill.active {{
            color: var(--accent-strong);
            background: linear-gradient(135deg, rgba(195,93,52,.14), rgba(199,154,72,.18));
            border-color: rgba(195,93,52,.2);
          }}
          .utility-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 15px;
            border-radius: 999px;
            background: rgba(35,75,68,.08);
            color: var(--forest);
            border: 1px solid rgba(35,75,68,.12);
            font-size: 13px;
            font-weight: 800;
          }}
          .layout {{
            display: grid;
            grid-template-columns: 312px minmax(0, 1fr);
            gap: 24px;
            align-items: start;
          }}
          .rail {{
            position: sticky;
            top: 112px;
            display: grid;
            gap: 18px;
          }}
          .rail-card {{
            border: 1px solid rgba(255,255,255,.58);
            border-radius: 28px;
            padding: 20px;
            background: rgba(255,252,247,.82);
            box-shadow: var(--shadow-md);
            backdrop-filter: blur(16px);
          }}
          .rail-card:first-child {{
            background:
              linear-gradient(155deg, rgba(24,51,47,.96), rgba(35,75,68,.92)),
              radial-gradient(circle at top right, rgba(199,154,72,.18), transparent 38%);
            border-color: rgba(255,255,255,.16);
          }}
          .rail-card:first-child h3,
          .rail-card:first-child p {{
            color: rgba(255,250,243,.92);
          }}
          .rail-card:first-child .rail-label {{
            color: rgba(255,220,167,.88);
          }}
          .rail-card h3 {{
            margin: 8px 0 10px;
            font-family: "Noto Serif JP", serif;
            font-size: 22px;
            line-height: 1.3;
          }}
          .rail-card p {{
            margin: 0;
            font-size: 14px;
            line-height: 1.8;
          }}
          .rail-label {{
            font-size: 11px;
            letter-spacing: .16em;
            text-transform: uppercase;
            color: var(--accent);
            font-weight: 900;
          }}
          .nav-list {{
            display: grid;
            gap: 10px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.76), rgba(248,242,234,.9));
          }}
          .nav-link {{
            display: grid;
            gap: 6px;
            padding: 14px 15px;
            border-radius: 20px;
            border: 1px solid rgba(39, 58, 54, .08);
            background: rgba(255,255,255,.74);
            color: var(--ink);
            transition: transform .18s ease, border-color .18s ease, background .18s ease, box-shadow .18s ease;
          }}
          .nav-link:hover {{
            transform: translateY(-2px);
            border-color: rgba(195,93,52,.18);
            background: rgba(255,255,255,.95);
            box-shadow: 0 14px 28px rgba(55, 39, 24, .08);
          }}
          .nav-link.active {{
            border-color: rgba(195,93,52,.16);
            background:
              linear-gradient(135deg, rgba(195,93,52,.14), rgba(199,154,72,.12)),
              rgba(255,255,255,.98);
            box-shadow: inset 0 0 0 1px rgba(255,255,255,.44);
          }}
          .nav-link-title {{
            font-size: 14px;
            font-weight: 800;
            color: var(--forest);
          }}
          .nav-link-note {{
            font-size: 12px;
            color: var(--muted);
            line-height: 1.55;
          }}
          .mini-kpi-list {{
            display: grid;
            gap: 10px;
            margin-top: 14px;
          }}
          .mini-kpi {{
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 10px 0;
            border-bottom: 1px dashed rgba(255,255,255,.14);
            color: var(--muted);
            font-size: 13px;
          }}
          .nav-list .mini-kpi,
          .content .mini-kpi {{
            border-bottom-color: rgba(39, 58, 54, .12);
          }}
          .mini-kpi:last-child {{
            border-bottom: none;
            padding-bottom: 0;
          }}
          .mini-kpi strong {{
            color: var(--ink);
            font-size: 14px;
          }}
          .content {{
            min-width: 0;
            display: grid;
            gap: 22px;
          }}
          .hero, .section {{
            position: relative;
            overflow: hidden;
            background: var(--paper);
            border: 1px solid rgba(255,255,255,.58);
            border-radius: 32px;
            padding: 30px;
            box-shadow: var(--shadow-lg);
            backdrop-filter: blur(12px);
          }}
          .hero {{
            background:
              linear-gradient(180deg, rgba(255,253,249,.92), rgba(247,241,232,.9)),
              radial-gradient(circle at top right, rgba(199,154,72,.12), transparent 34%);
          }}
          .section {{
            background:
              linear-gradient(180deg, rgba(255,255,252,.9), rgba(247,241,233,.84));
          }}
          .hero::before,
          .section::before {{
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 6px;
            background: linear-gradient(90deg, var(--accent), var(--gold), var(--forest));
            opacity: .92;
          }}
          .hero::after,
          .section::after {{
            content: "";
            position: absolute;
            right: -80px;
            top: -90px;
            width: 240px;
            height: 240px;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(255,255,255,.46) 0%, transparent 68%);
            pointer-events: none;
          }}
          .section {{ margin-top: 0; }}
          .eyebrow {{
            font-size: 11px;
            letter-spacing: .16em;
            text-transform: uppercase;
            color: var(--accent-strong);
            font-weight: 900;
          }}
          h1 {{
            margin: 12px 0;
            font-family: "Noto Serif JP", serif;
            font-size: clamp(38px, 4.4vw, 62px);
            line-height: 1.02;
            letter-spacing: -.03em;
          }}
          h2 {{
            margin: 0 0 12px;
            font-family: "Noto Serif JP", serif;
            font-size: 28px;
            line-height: 1.18;
          }}
          h3 {{
            margin: 10px 0;
            font-size: 21px;
            line-height: 1.32;
          }}
          p {{
            color: var(--muted);
            line-height: 1.82;
            font-size: 15px;
            margin: 0;
          }}
          .hero p + p,
          .section p + p {{
            margin-top: 10px;
          }}
          code {{
            background: rgba(244, 237, 227, .96);
            padding: 3px 8px;
            border-radius: 10px;
          }}
          .hero-grid {{
            display: grid;
            grid-template-columns: minmax(0, 1.32fr) minmax(300px, .9fr);
            gap: 22px;
            align-items: stretch;
          }}
          .hero-panel {{
            position: relative;
            border: 1px solid rgba(255,255,255,.14);
            border-radius: 28px;
            padding: 20px;
            background:
              linear-gradient(155deg, rgba(24,51,47,.98), rgba(35,75,68,.94)),
              radial-gradient(circle at top right, rgba(199,154,72,.18), transparent 42%);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.06);
          }}
          .hero-panel h2 {{
            color: rgba(255,250,243,.98);
            font-size: 24px;
            margin-bottom: 10px;
          }}
          .hero-panel p,
          .hero-panel .mini-kpi,
          .hero-panel .label {{
            color: rgba(244,238,229,.72);
          }}
          .hero-panel .mini-kpi {{
            border-bottom-color: rgba(255,255,255,.12);
          }}
          .hero-panel .mini-kpi strong {{
            color: rgba(255,250,243,.98);
          }}
          .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px; }}
          .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            border: none;
            cursor: pointer;
            padding: 13px 18px;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--accent), var(--accent-strong));
            color: #fff;
            font-weight: 800;
            box-shadow: 0 12px 24px rgba(195,93,52,.22);
            transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease;
          }}
          .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 18px 30px rgba(195,93,52,.24);
          }}
          .btn.alt {{
            background: rgba(255,255,255,.96);
            color: var(--forest);
            border: 1px solid rgba(39, 58, 54, .12);
            box-shadow: 0 12px 26px rgba(28,31,27,.08);
          }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }}
          .grid.two {{ grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); }}
          .card {{
            position: relative;
            background: rgba(255,255,255,.94);
            border: 1px solid rgba(39, 58, 54, .08);
            border-radius: 26px;
            padding: 20px;
            box-shadow: var(--shadow-sm);
            transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
          }}
          .card:hover {{
            transform: translateY(-2px);
            border-color: rgba(195,93,52,.14);
            box-shadow: 0 18px 36px rgba(28,31,27,.09);
          }}
          .card::after {{
            content: "";
            position: absolute;
            inset: 0;
            border-radius: inherit;
            border: 1px solid rgba(255,255,255,.52);
            pointer-events: none;
          }}
          .meta {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
          .chip {{
            display: inline-flex;
            align-items: center;
            padding: 7px 11px;
            border-radius: 999px;
            background: linear-gradient(135deg, rgba(35,75,68,.1), rgba(199,154,72,.16));
            color: var(--forest-strong);
            font-size: 12px;
            font-weight: 800;
          }}
          .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 16px; }}
          .stat {{
            background:
              linear-gradient(180deg, rgba(255,255,255,.96), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(195,93,52,.09), transparent 40%);
            border: 1px solid rgba(39, 58, 54, .08);
            border-radius: 24px;
            padding: 18px;
            box-shadow: var(--shadow-sm);
          }}
          .label {{ font-size: 11px; letter-spacing: .16em; text-transform: uppercase; color: var(--muted); font-weight: 800; }}
          .value {{
            margin-top: 10px;
            font-family: "Noto Serif JP", serif;
            font-size: clamp(28px, 3vw, 40px);
            font-weight: 900;
            line-height: 1.05;
            color: var(--ink);
          }}
          ul.clean {{ margin: 0; padding-left: 20px; color: var(--muted); }}
          .list {{ display: grid; gap: 12px; }}
          .status-paid {{ color: var(--ok); font-weight: 800; }}
          .status-pending {{ color: var(--warn); font-weight: 800; }}
          .status {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 7px 10px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 900;
            letter-spacing: .12em;
            text-transform: uppercase;
          }}
          .status.completed, .status.ready {{
            background: rgba(31,122,91,.12);
            color: var(--ok);
          }}
          .status.in_progress, .status.warning {{
            background: rgba(194,118,31,.12);
            color: var(--warn);
          }}
          .status.planned {{
            background: rgba(97,112,107,.14);
            color: var(--muted);
          }}
          .status.blocker {{
            background: rgba(177,58,50,.12);
            color: var(--danger);
          }}
          .status-card.ready {{ box-shadow: inset 0 0 0 1px rgba(31,122,91,.08), var(--shadow-sm); }}
          .status-card.warning {{ box-shadow: inset 0 0 0 1px rgba(194,118,31,.08), var(--shadow-sm); }}
          .status-card.blocker {{ box-shadow: inset 0 0 0 1px rgba(177,58,50,.08), var(--shadow-sm); }}
          .status-card.completed {{ box-shadow: inset 0 0 0 1px rgba(31,122,91,.08), var(--shadow-sm); }}
          .status-card.in_progress {{ box-shadow: inset 0 0 0 1px rgba(194,118,31,.08), var(--shadow-sm); }}
          .status-card.planned {{ box-shadow: inset 0 0 0 1px rgba(97,112,107,.08), var(--shadow-sm); }}
          .price {{
            margin-top: 14px;
            font-family: "Noto Serif JP", serif;
            font-size: 30px;
            font-weight: 900;
            color: var(--forest);
          }}
          .feature-grid, .route-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
            gap: 18px;
          }}
          .feature-tile, .route-card {{
            display: grid;
            gap: 10px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.97), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(195,93,52,.08), transparent 42%);
            border: 1px solid rgba(39, 58, 54, .08);
            border-radius: 24px;
            padding: 20px;
            color: var(--ink);
            box-shadow: var(--shadow-sm);
            min-height: 220px;
            transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
          }}
          .feature-tile:hover,
          .route-card:hover {{
            transform: translateY(-3px);
            border-color: rgba(195,93,52,.16);
            box-shadow: 0 20px 38px rgba(28,31,27,.1);
          }}
          .tile-kicker, .route-label {{
            font-size: 12px;
            letter-spacing: .12em;
            text-transform: uppercase;
            color: var(--accent-strong);
            font-weight: 900;
          }}
          .feature-tile strong {{
            font-size: 20px;
            color: var(--forest);
          }}
          .route-card h3 {{
            font-size: 22px;
            color: var(--forest-strong);
            margin: 0;
          }}
          .feature-tile p, .route-card p {{
            margin: 0;
            color: var(--muted);
            line-height: 1.72;
          }}
          .section-head {{
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 18px;
            flex-wrap: wrap;
            margin-bottom: 18px;
          }}
          .section-head h2 {{
            margin-bottom: 0;
          }}
          .section-subtitle {{
            max-width: 640px;
          }}
          .hero-note-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 14px;
            margin-top: 22px;
          }}
          .hero-note {{
            padding: 16px;
            border-radius: 22px;
            border: 1px solid rgba(39, 58, 54, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.94), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(199,154,72,.12), transparent 42%);
            box-shadow: var(--shadow-sm);
          }}
          .hero-note-label {{
            display: block;
            font-size: 11px;
            font-weight: 900;
            letter-spacing: .16em;
            text-transform: uppercase;
            color: var(--accent-strong);
          }}
          .hero-note-value {{
            display: block;
            margin-top: 10px;
            font-family: "Noto Serif JP", serif;
            font-size: 24px;
            line-height: 1.15;
            color: var(--forest-strong);
          }}
          .hero-note-detail {{
            display: block;
            margin-top: 8px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.65;
          }}
          .command-board {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin-top: 18px;
          }}
          .command-card {{
            display: grid;
            gap: 8px;
            padding: 15px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,.14);
            background: rgba(255,255,255,.07);
            color: rgba(255,250,243,.92);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
            transition: transform .18s ease, background .18s ease, border-color .18s ease;
          }}
          .command-card:hover {{
            transform: translateY(-2px);
            background: rgba(255,255,255,.11);
            border-color: rgba(255,255,255,.2);
          }}
          .command-card span {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: .14em;
            color: rgba(255,220,167,.88);
            font-weight: 900;
          }}
          .command-card strong {{
            font-size: 17px;
            line-height: 1.35;
            color: rgba(255,250,243,.98);
          }}
          .legend {{
            display: grid;
            gap: 10px;
            margin-top: 14px;
          }}
          .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--muted);
          }}
          .dot {{
            width: 12px;
            height: 12px;
            border-radius: 999px;
            display: inline-block;
          }}
          .dot.completed {{ background: var(--ok); }}
          .dot.in_progress {{ background: var(--warn); }}
          .dot.planned {{ background: var(--muted); }}
          .helper-list {{
            display: grid;
            gap: 8px;
            margin-top: 14px;
            color: var(--muted);
          }}
          form.stack {{ display: grid; gap: 12px; }}
          label.field {{ display: grid; gap: 6px; color: var(--muted); font-size: 14px; }}
          input, select, textarea {{
            width: 100%;
            border: 1px solid rgba(39, 58, 54, .12);
            border-radius: 18px;
            padding: 12px 14px;
            background: rgba(255,255,255,.96);
            color: var(--ink);
            font: inherit;
          }}
          input:focus, select:focus, textarea:focus {{
            outline: none;
            border-color: rgba(195,93,52,.4);
            box-shadow: 0 0 0 4px rgba(195,93,52,.1);
          }}
          textarea {{ min-height: 100px; resize: vertical; }}
          :root {{
            --bg: #f5efe6;
            --bg-deep: #e8dcca;
            --paper: rgba(255, 252, 247, .9);
            --paper-strong: #fffdf8;
            --paper-muted: rgba(248, 242, 234, .94);
            --ink: #132721;
            --muted: #5a6965;
            --line: rgba(31, 53, 49, .1);
            --line-strong: rgba(31, 53, 49, .18);
            --accent: #cc5432;
            --accent-strong: #9e311b;
            --accent-soft: rgba(204, 84, 50, .1);
            --forest: #194741;
            --forest-strong: #0d302c;
            --forest-soft: rgba(25, 71, 65, .1);
            --gold: #cb9c44;
            --gold-soft: rgba(203, 156, 68, .15);
            --ok: #1d7a5b;
            --warn: #bd751a;
            --danger: #b13a32;
            --shadow-lg: 0 34px 86px rgba(21, 29, 27, .15);
            --shadow-md: 0 18px 44px rgba(21, 29, 27, .12);
            --shadow-sm: 0 12px 28px rgba(21, 29, 27, .08);
          }}
          body {{
            background:
              radial-gradient(circle at 10% 12%, rgba(204,84,50,.16), transparent 24%),
              radial-gradient(circle at 100% 0%, rgba(25,71,65,.18), transparent 28%),
              radial-gradient(circle at 88% 86%, rgba(203,156,68,.16), transparent 24%),
              linear-gradient(180deg, #fbf7f1 0%, #f5eee4 42%, #ebdfcf 100%);
          }}
          body::before {{
            background-image:
              linear-gradient(rgba(255,255,255,.22) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,.14) 1px, transparent 1px);
            background-size: 42px 42px;
            opacity: .7;
          }}
          body::after {{
            top: -140px;
            right: -90px;
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(255,255,255,.62) 0%, rgba(255,255,255,.18) 38%, transparent 72%);
            filter: blur(12px);
          }}
          .wrap {{
            max-width: 1480px;
            padding: 28px 24px 88px;
          }}
          .topbar {{
            gap: 22px;
            padding: 18px 22px;
            border: 1px solid rgba(255,255,255,.16);
            border-radius: 34px;
            background:
              linear-gradient(135deg, rgba(10,34,31,.96), rgba(26,68,63,.93) 54%, rgba(89,38,22,.92)),
              radial-gradient(circle at top right, rgba(203,156,68,.24), transparent 34%);
            box-shadow: 0 24px 60px rgba(15, 24, 22, .24);
            backdrop-filter: blur(20px);
          }}
          .topbar::before {{
            content: "";
            position: absolute;
            inset: 0;
            border-radius: inherit;
            border: 1px solid rgba(255,255,255,.08);
            pointer-events: none;
          }}
          .brand-stack {{
            gap: 5px;
          }}
          .brand-mark {{
            width: 60px;
            height: 60px;
            border-radius: 22px;
            background:
              linear-gradient(145deg, rgba(255,255,255,.2), rgba(255,255,255,.06)),
              linear-gradient(145deg, rgba(204,84,50,.94), rgba(203,156,68,.86), rgba(25,71,65,.92));
            box-shadow: 0 18px 34px rgba(6, 18, 16, .22);
          }}
          .brand-link {{
            color: rgba(255,247,238,.96);
            font-size: 12px;
            letter-spacing: .18em;
          }}
          .brand-subtitle {{
            color: rgba(255,240,226,.84);
            font-size: 16px;
          }}
          .brand-caption {{
            color: rgba(235, 221, 205, .72);
            font-size: 12px;
            font-weight: 700;
            letter-spacing: .06em;
          }}
          .topbar-actions {{
            gap: 14px;
          }}
          .signal-strip {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
          }}
          .signal-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(255,255,255,.08);
            border: 1px solid rgba(255,255,255,.12);
            color: rgba(255,241,228,.86);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .04em;
          }}
          .lang-label {{
            color: rgba(234, 221, 208, .72);
          }}
          .lang-pill {{
            padding: 10px 14px;
            border: 1px solid rgba(255,255,255,.12);
            background: rgba(255,255,255,.08);
            color: rgba(255,248,241,.86);
            box-shadow: none;
          }}
          .lang-pill.active {{
            color: #fff6ef;
            background: linear-gradient(135deg, rgba(204,84,50,.5), rgba(203,156,68,.28));
            border-color: rgba(255,255,255,.2);
          }}
          .utility-pill {{
            background: rgba(255,255,255,.1);
            color: rgba(255,248,241,.94);
            border: 1px solid rgba(255,255,255,.12);
            box-shadow: none;
          }}
          .layout {{
            grid-template-columns: 324px minmax(0, 1fr);
            gap: 28px;
          }}
          .rail {{
            top: 122px;
            gap: 20px;
          }}
          .rail-card {{
            border-radius: 30px;
            padding: 22px;
            border: 1px solid rgba(255,255,255,.58);
            background:
              linear-gradient(180deg, rgba(255,255,255,.9), rgba(247,241,232,.84));
            box-shadow: var(--shadow-md);
          }}
          .rail-card:first-child {{
            background:
              linear-gradient(165deg, rgba(10,34,31,.98), rgba(25,71,65,.96)),
              radial-gradient(circle at top right, rgba(203,156,68,.26), transparent 42%);
            box-shadow: 0 24px 46px rgba(8, 18, 16, .24);
          }}
          .rail-chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 16px;
          }}
          .rail-chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 7px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,.08);
            border: 1px solid rgba(255,255,255,.12);
            color: rgba(255,239,223,.82);
            font-size: 11px;
            font-weight: 800;
            letter-spacing: .08em;
          }}
          .nav-list {{
            gap: 12px;
            padding: 6px;
            border: 1px solid rgba(255,255,255,.45);
            border-radius: 30px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.8), rgba(244,238,230,.92));
          }}
          .nav-link {{
            padding: 15px 16px;
            border-radius: 22px;
            background: rgba(255,255,255,.76);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.6);
          }}
          .nav-link:hover {{
            transform: translateY(-3px);
            box-shadow: 0 16px 32px rgba(20, 29, 27, .09);
          }}
          .nav-link.active {{
            border-color: rgba(204,84,50,.16);
            background:
              linear-gradient(135deg, rgba(204,84,50,.14), rgba(203,156,68,.1)),
              rgba(255,255,255,.98);
            box-shadow: 0 16px 28px rgba(20, 29, 27, .08);
          }}
          .mini-kpi-list {{
            gap: 12px;
            margin-top: 16px;
          }}
          .mini-kpi {{
            padding: 12px 0;
          }}
          .content {{
            gap: 24px;
          }}
          .hero, .section {{
            border-radius: 36px;
            padding: 32px;
            border: 1px solid rgba(255,255,255,.6);
            box-shadow: var(--shadow-lg);
            backdrop-filter: blur(14px);
          }}
          .hero {{
            background:
              linear-gradient(180deg, rgba(255,253,249,.94), rgba(244,238,229,.9)),
              radial-gradient(circle at top right, rgba(203,156,68,.16), transparent 34%),
              radial-gradient(circle at left center, rgba(25,71,65,.08), transparent 38%);
          }}
          .section {{
            background:
              linear-gradient(180deg, rgba(255,255,252,.92), rgba(246,240,232,.86));
          }}
          .hero::before,
          .section::before {{
            height: 7px;
            background: linear-gradient(90deg, #d04c2b 0%, #d4a448 48%, #1b5a52 100%);
          }}
          .hero::after,
          .section::after {{
            right: -70px;
            top: -76px;
            width: 250px;
            height: 250px;
            background: radial-gradient(circle, rgba(255,255,255,.54) 0%, rgba(255,255,255,.14) 54%, transparent 74%);
          }}
          h1 {{
            margin: 12px 0 14px;
            font-size: clamp(42px, 4.8vw, 68px);
            line-height: .98;
            letter-spacing: -.04em;
          }}
          h2 {{
            font-size: 31px;
            margin-bottom: 10px;
          }}
          h3 {{
            font-size: 22px;
          }}
          p {{
            color: #53645f;
            font-size: 15px;
          }}
          code {{
            background: rgba(243, 237, 229, .95);
            border: 1px solid rgba(31, 53, 49, .08);
          }}
          .hero-grid {{
            grid-template-columns: minmax(0, 1.2fr) minmax(340px, .92fr);
            gap: 24px;
          }}
          .hero-panel {{
            padding: 24px;
            border-radius: 30px;
            border: 1px solid rgba(255,255,255,.14);
            background:
              linear-gradient(165deg, rgba(10,34,31,.98), rgba(26,68,63,.95)),
              radial-gradient(circle at top right, rgba(203,156,68,.26), transparent 44%);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 24px 44px rgba(10, 20, 18, .2);
          }}
          .actions {{
            gap: 14px;
            margin-top: 22px;
          }}
          .btn {{
            padding: 14px 20px;
            background: linear-gradient(135deg, var(--accent), var(--accent-strong));
            box-shadow: 0 14px 28px rgba(204,84,50,.24);
          }}
          .btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 20px 36px rgba(204,84,50,.26);
          }}
          .btn.alt {{
            background: rgba(255,255,255,.96);
            color: var(--forest-strong);
            border: 1px solid rgba(31, 53, 49, .1);
            box-shadow: 0 12px 26px rgba(20, 29, 27, .08);
          }}
          .grid,
          .grid.two,
          .feature-grid,
          .route-grid {{
            gap: 20px;
          }}
          .card {{
            border-radius: 28px;
            padding: 22px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.96), rgba(247,241,233,.92)),
              radial-gradient(circle at top right, rgba(203,156,68,.1), transparent 42%);
            box-shadow: var(--shadow-sm);
          }}
          .card::before {{
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 4px;
            border-radius: 28px 28px 0 0;
            background: linear-gradient(90deg, rgba(204,84,50,.9), rgba(203,156,68,.84), rgba(25,71,65,.84));
            opacity: .9;
          }}
          .meta {{
            gap: 10px;
            margin-top: 14px;
          }}
          .chip {{
            padding: 8px 12px;
            background: linear-gradient(135deg, rgba(25,71,65,.1), rgba(203,156,68,.14));
            color: var(--forest-strong);
          }}
          .stat-grid {{
            gap: 18px;
          }}
          .stat {{
            position: relative;
            overflow: hidden;
            border-radius: 26px;
            padding: 20px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.98), rgba(245,239,231,.94)),
              radial-gradient(circle at top right, rgba(204,84,50,.12), transparent 38%);
          }}
          .stat::after {{
            content: "";
            position: absolute;
            right: -30px;
            bottom: -36px;
            width: 110px;
            height: 110px;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(203,156,68,.16), transparent 66%);
          }}
          .value {{
            letter-spacing: -.04em;
          }}
          ul.clean {{
            line-height: 1.86;
          }}
          ul.clean li + li {{
            margin-top: 8px;
          }}
          .feature-tile, .route-card {{
            min-height: 244px;
            padding: 22px;
            border-radius: 28px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(204,84,50,.09), transparent 42%);
          }}
          .feature-tile strong {{
            font-size: 21px;
          }}
          .route-card {{
            align-content: start;
          }}
          .route-card h3 {{
            font-size: 23px;
          }}
          .route-card-foot {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-top: auto;
            padding-top: 14px;
            border-top: 1px dashed rgba(31, 53, 49, .12);
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .05em;
          }}
          .route-card-foot strong {{
            color: var(--accent-strong);
            font-size: 13px;
          }}
          .section-head {{
            margin-bottom: 20px;
            padding-bottom: 2px;
          }}
          .hero-note-grid {{
            gap: 16px;
            margin-top: 24px;
          }}
          .hero-note {{
            border-radius: 24px;
            padding: 18px;
          }}
          .hero-note-value {{
            font-size: 26px;
          }}
          .command-board {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
          }}
          .command-card {{
            gap: 10px;
            padding: 16px;
            border-radius: 22px;
            background: rgba(255,255,255,.08);
          }}
          .command-card p {{
            margin: 0;
            color: rgba(240, 231, 219, .76);
            font-size: 12px;
            line-height: 1.6;
          }}
          .content article:not(.card):not(.hero-panel):not(.hero-note):not(.rail-card):not(.route-card):not(.feature-tile):not(.command-card):not(.lane-card):not(.journey-card) {{
            position: relative;
            padding: 24px;
            border-radius: 28px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.95), rgba(246,241,233,.9));
            box-shadow: var(--shadow-sm);
          }}
          .content article:not(.card):not(.hero-panel):not(.hero-note):not(.rail-card):not(.route-card):not(.feature-tile):not(.command-card):not(.lane-card):not(.journey-card)::before {{
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 4px;
            border-radius: 28px 28px 0 0;
            background: linear-gradient(90deg, rgba(25,71,65,.88), rgba(203,156,68,.78), rgba(204,84,50,.84));
          }}
          .content article:not(.card):not(.hero-panel):not(.hero-note):not(.rail-card):not(.route-card):not(.feature-tile):not(.command-card):not(.lane-card):not(.journey-card) h2:first-child,
          .content article:not(.card):not(.hero-panel):not(.hero-note):not(.rail-card):not(.route-card):not(.feature-tile):not(.command-card):not(.lane-card):not(.journey-card) h3:first-child {{
            margin-top: 0;
          }}
          .hero-badge-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 18px;
          }}
          .hero-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(25,71,65,.08);
            border: 1px solid rgba(25,71,65,.1);
            color: var(--forest-strong);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .04em;
          }}
          .lane-grid {{
            display: grid;
            gap: 12px;
            margin-top: 18px;
          }}
          .lane-card {{
            display: grid;
            gap: 6px;
            padding: 14px 16px;
            border-radius: 20px;
            background: rgba(255,255,255,.08);
            border: 1px solid rgba(255,255,255,.1);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
          }}
          .lane-index {{
            font-size: 11px;
            letter-spacing: .16em;
            text-transform: uppercase;
            color: rgba(255,220,167,.88);
            font-weight: 900;
          }}
          .lane-title {{
            color: rgba(255,250,243,.98);
            font-size: 17px;
            font-weight: 800;
          }}
          .lane-note {{
            color: rgba(240,231,219,.76);
            font-size: 13px;
            line-height: 1.6;
          }}
          .journey-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 18px;
          }}
          .journey-card {{
            position: relative;
            padding: 22px;
            border-radius: 28px;
            background:
              linear-gradient(180deg, rgba(255,255,255,.98), rgba(245,239,230,.92)),
              radial-gradient(circle at top right, rgba(25,71,65,.08), transparent 42%);
            border: 1px solid rgba(31, 53, 49, .08);
            box-shadow: var(--shadow-sm);
          }}
          .journey-step {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 52px;
            padding: 7px 10px;
            border-radius: 999px;
            background: linear-gradient(135deg, rgba(204,84,50,.14), rgba(203,156,68,.18));
            color: var(--accent-strong);
            font-size: 11px;
            font-weight: 900;
            letter-spacing: .14em;
          }}
          .journey-title {{
            margin: 16px 0 10px;
            font-size: 20px;
            color: var(--forest-strong);
            font-weight: 800;
          }}
          .journey-note {{
            margin: 0;
            color: var(--muted);
            line-height: 1.72;
          }}
          .workspace-hero-grid {{
            display: grid;
            grid-template-columns: minmax(0, 1.18fr) minmax(320px, .9fr);
            gap: 22px;
            align-items: stretch;
          }}
          .workspace-copy {{
            display: grid;
            gap: 14px;
            min-width: 0;
          }}
          .workspace-panel {{
            position: relative;
            overflow: hidden;
            display: grid;
            gap: 18px;
            padding: 24px;
            border-radius: 30px;
            border: 1px solid rgba(255,255,255,.14);
            background:
              linear-gradient(165deg, rgba(10,34,31,.98), rgba(26,68,63,.95)),
              radial-gradient(circle at top right, rgba(203,156,68,.26), transparent 44%);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 24px 44px rgba(10, 20, 18, .2);
          }}
          .workspace-panel::after {{
            content: "";
            position: absolute;
            right: -40px;
            bottom: -48px;
            width: 150px;
            height: 150px;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(255,255,255,.14), transparent 68%);
            pointer-events: none;
          }}
          .workspace-panel h2 {{
            margin: 0;
            color: rgba(255,250,243,.98);
            font-size: 26px;
          }}
          .workspace-panel p,
          .workspace-panel .label,
          .workspace-panel .mini-kpi,
          .workspace-panel .data-point span,
          .workspace-panel .task-content p {{
            color: rgba(240,231,219,.76);
          }}
          .workspace-panel .task-content strong,
          .workspace-panel .data-point strong {{
            color: rgba(255,250,243,.98);
          }}
          .workspace-panel .task-item {{
            background: rgba(255,255,255,.08);
            border-color: rgba(255,255,255,.08);
          }}
          .workspace-panel .task-marker {{
            background: linear-gradient(135deg, rgba(204,84,50,.22), rgba(203,156,68,.3));
            color: rgba(255,249,243,.98);
          }}
          .workspace-panel .data-point {{
            border-bottom-color: rgba(255,255,255,.12);
          }}
          .workspace-panel .portal-nav-card {{
            background: rgba(255,255,255,.08);
            border-color: rgba(255,255,255,.1);
          }}
          .workspace-panel .portal-nav-card strong,
          .workspace-panel .portal-nav-card p {{
            color: rgba(255,250,243,.92);
          }}
          .workspace-panel .portal-nav-kicker {{
            color: rgba(255,220,167,.88);
          }}
          .portal-nav-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
          }}
          .portal-nav-card {{
            display: grid;
            gap: 10px;
            min-height: 182px;
            padding: 20px;
            border-radius: 26px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(25,71,65,.08), transparent 42%);
            box-shadow: var(--shadow-sm);
            color: var(--ink);
            transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
          }}
          .portal-nav-card:hover {{
            transform: translateY(-3px);
            border-color: rgba(204,84,50,.16);
            box-shadow: 0 18px 36px rgba(20, 29, 27, .1);
          }}
          .portal-nav-kicker {{
            font-size: 11px;
            letter-spacing: .14em;
            text-transform: uppercase;
            color: var(--accent-strong);
            font-weight: 900;
          }}
          .portal-nav-card strong {{
            font-size: 20px;
            color: var(--forest-strong);
            line-height: 1.3;
          }}
          .portal-nav-card p {{
            margin: 0;
            color: var(--muted);
            line-height: 1.68;
            font-size: 14px;
          }}
          .task-list {{
            display: grid;
            gap: 12px;
          }}
          .task-item {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 14px;
            border-radius: 20px;
            border: 1px solid rgba(31, 53, 49, .08);
            background: rgba(255,255,255,.88);
            box-shadow: inset 0 1px 0 rgba(255,255,255,.5);
          }}
          .task-marker {{
            flex: 0 0 auto;
            width: 32px;
            height: 32px;
            border-radius: 999px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, rgba(204,84,50,.14), rgba(203,156,68,.22));
            color: var(--accent-strong);
            font-size: 12px;
            font-weight: 900;
            letter-spacing: .06em;
          }}
          .task-content {{
            display: grid;
            gap: 4px;
            min-width: 0;
          }}
          .task-content strong {{
            color: var(--forest-strong);
            font-size: 15px;
            line-height: 1.45;
          }}
          .task-content p {{
            margin: 0;
            font-size: 13px;
            line-height: 1.62;
          }}
          .data-points {{
            display: grid;
            gap: 10px;
          }}
          .data-point {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            padding: 10px 0;
            border-bottom: 1px dashed rgba(31, 53, 49, .12);
          }}
          .data-point:last-child {{
            border-bottom: none;
            padding-bottom: 0;
          }}
          .data-point span {{
            color: var(--muted);
            font-size: 13px;
            line-height: 1.5;
          }}
          .data-point strong {{
            color: var(--forest-strong);
            font-size: 15px;
            text-align: right;
          }}
          .focus-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 18px;
          }}
          .focus-card {{
            padding: 20px;
            border-radius: 24px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.96), rgba(247,241,233,.92));
            box-shadow: var(--shadow-sm);
          }}
          .focus-card h3 {{
            margin: 0 0 8px;
            color: var(--forest-strong);
          }}
          .focus-card p {{
            margin: 0;
          }}
          .focus-card .meta {{
            margin-top: 12px;
          }}
          .risk-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 7px 11px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 900;
            letter-spacing: .04em;
          }}
          .risk-pill.low {{
            background: rgba(31,122,91,.12);
            color: var(--ok);
          }}
          .risk-pill.medium {{
            background: rgba(194,118,31,.12);
            color: var(--warn);
          }}
          .risk-pill.high {{
            background: rgba(177,58,50,.12);
            color: var(--danger);
          }}
          .note-stack {{
            display: grid;
            gap: 12px;
          }}
          .note-card {{
            padding: 16px 18px;
            border-radius: 22px;
            border: 1px solid rgba(31, 53, 49, .08);
            background: rgba(255,255,255,.9);
            box-shadow: var(--shadow-sm);
          }}
          .note-card strong {{
            display: block;
            color: var(--forest-strong);
            margin-bottom: 6px;
            font-size: 15px;
          }}
          .note-card p {{
            margin: 0;
            font-size: 13px;
            line-height: 1.66;
          }}
          .timeline-list {{
            display: grid;
            gap: 14px;
          }}
          .timeline-item {{
            position: relative;
            display: grid;
            grid-template-columns: 44px minmax(0, 1fr);
            gap: 14px;
            padding: 18px 18px 18px 0;
          }}
          .timeline-item::before {{
            content: "";
            position: absolute;
            left: 21px;
            top: 44px;
            bottom: -12px;
            width: 1px;
            background: linear-gradient(180deg, rgba(204,84,50,.18), rgba(25,71,65,.1));
          }}
          .timeline-item:last-child::before {{
            display: none;
          }}
          .timeline-badge {{
            position: relative;
            z-index: 1;
            width: 44px;
            height: 44px;
            border-radius: 999px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, rgba(204,84,50,.14), rgba(203,156,68,.2));
            color: var(--accent-strong);
            font-size: 11px;
            font-weight: 900;
            letter-spacing: .12em;
            text-transform: uppercase;
            box-shadow: inset 0 1px 0 rgba(255,255,255,.5);
          }}
          .timeline-card {{
            padding: 18px 20px;
            border-radius: 24px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.97), rgba(246,241,233,.92));
            box-shadow: var(--shadow-sm);
          }}
          .timeline-card h3 {{
            margin: 0 0 8px;
            color: var(--forest-strong);
            font-size: 19px;
          }}
          .timeline-card p {{
            margin: 0;
            line-height: 1.7;
          }}
          .timeline-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
          }}
          .subtle-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 7px 10px;
            border-radius: 999px;
            background: rgba(25,71,65,.08);
            border: 1px solid rgba(25,71,65,.08);
            color: var(--forest-strong);
            font-size: 12px;
            font-weight: 800;
          }}
          .subtle-badge.warn {{
            background: rgba(194,118,31,.12);
            color: var(--warn);
            border-color: rgba(194,118,31,.1);
          }}
          .subtle-badge.danger {{
            background: rgba(177,58,50,.12);
            color: var(--danger);
            border-color: rgba(177,58,50,.1);
          }}
          .subtle-badge.ok {{
            background: rgba(31,122,91,.12);
            color: var(--ok);
            border-color: rgba(31,122,91,.1);
          }}
          .schedule-board {{
            display: grid;
            gap: 14px;
          }}
          .schedule-card {{
            display: grid;
            gap: 12px;
            padding: 20px;
            border-radius: 26px;
            border: 1px solid rgba(31, 53, 49, .08);
            background:
              linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,241,233,.92)),
              radial-gradient(circle at top right, rgba(203,156,68,.1), transparent 40%);
            box-shadow: var(--shadow-sm);
          }}
          .schedule-card h3 {{
            margin: 0;
            color: var(--forest-strong);
          }}
          .schedule-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }}
          .schedule-line {{
            margin: 0;
            color: var(--muted);
            line-height: 1.68;
          }}
          .split-panel-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 18px;
          }}
          form.stack .btn {{
            width: fit-content;
          }}
          @media (max-width: 900px) {{
            .layout {{ grid-template-columns: 1fr; }}
            .rail {{
              position: static;
              order: 2;
            }}
            .content {{
              order: 1;
            }}
            .hero-grid, .grid, .grid.two, .stat-grid, .feature-grid, .route-grid, .command-board {{ grid-template-columns: 1fr; }}
            .topbar {{
              align-items: flex-start;
              flex-direction: column;
              position: static;
            }}
            .wrap {{ padding-left: 16px; padding-right: 16px; }}
            .section-head {{
              align-items: flex-start;
            }}
          }}
          @media (max-width: 640px) {{
            h1 {{ font-size: 32px; }}
            .hero, .section {{ padding: 24px 18px; border-radius: 26px; }}
            .topbar {{ padding: 14px; border-radius: 24px; }}
            .brand-lockup {{ align-items: flex-start; }}
            .brand-mark {{ width: 48px; height: 48px; font-size: 22px; }}
            .wrap {{ padding-top: 16px; }}
          }}
          @media (max-width: 900px) {{
            .topbar-actions {{
              width: 100%;
              align-items: flex-start;
              justify-content: flex-start;
            }}
            .signal-strip {{
              width: 100%;
            }}
            .command-board,
            .journey-grid,
            .workspace-hero-grid {{
              grid-template-columns: 1fr;
            }}
          }}
          @media (max-width: 640px) {{
            .brand-caption {{
              line-height: 1.55;
            }}
            .signal-pill,
            .hero-badge,
            .chip {{
              font-size: 11px;
            }}
            .hero, .section {{
              padding: 22px 18px;
            }}
            .card,
            .feature-tile,
            .route-card,
            .journey-card {{
              padding: 18px;
            }}
          }}
        </style>
      </head>
      <body>
        <div class="wrap">
          <div class="topbar">
            <div class="brand-lockup">
              <div class="brand-mark">日</div>
              <div class="brand-stack">
                <a class="brand-link" href="/school-platform">Japan Life Language School OS</a>
                <div class="brand-subtitle">AI 化日語補習班營運平台</div>
                <div class="brand-caption">加盟招商 · 日語教學 · CRM · 教務 · 財務 · AI 助理</div>
              </div>
            </div>
            <div class="topbar-actions">
              <div class="signal-strip">
                <span class="signal-pill">招商入口</span>
                <span class="signal-pill">學員教學</span>
                <span class="signal-pill">營運後台</span>
              </div>
              <a class="utility-pill" href="/school-platform/progress">開發進度</a>
              <div class="lang-switcher" aria-label="language-switcher">
                <span class="lang-label">語言切換</span>
                <a id="lang-hant-link" class="lang-pill" href="#">繁體中文</a>
                <a id="lang-hans-link" class="lang-pill" href="#">簡體中文</a>
              </div>
            </div>
          </div>
          <div class="layout">
            <aside class="rail">
              <article class="rail-card">
                <div class="rail-label">平台定位</div>
                <h3>從招生站，走到整間學校的營運 OS</h3>
                <p>這不是單頁招生網站，而是把招生、課程、教師、付款、客服、招聘與 AI 助理串成一套可擴張的校務平台。</p>
                <div class="rail-chip-row">
                  <span class="rail-chip">招生</span>
                  <span class="rail-chip">教務</span>
                  <span class="rail-chip">學員</span>
                  <span class="rail-chip">加盟</span>
                  <span class="rail-chip">AI</span>
                </div>
              </article>
              <nav class="rail-card nav-list">
                <div class="rail-label">功能導覽</div>
                {_shell_navigation()}
              </nav>
              <article class="rail-card">
                <div class="rail-label">平台脈搏</div>
                <div class="mini-kpi-list">
                  <div class="mini-kpi"><span>招生漏斗</span><strong>名單集中追蹤</strong></div>
                  <div class="mini-kpi"><span>教務營運</span><strong>班級 / 教材 / 作業</strong></div>
                  <div class="mini-kpi"><span>財務閉環</span><strong>報名 / 付款 / 對帳</strong></div>
                  <div class="mini-kpi"><span>AI 升級</span><strong>教案 / 通知 / 分析</strong></div>
                </div>
              </article>
            </aside>
            <main class="content">{body}</main>
          </div>
        </div>
        <script>
          (() => {{
            const currentUrl = new URL(window.location.href);
            const currentLang = currentUrl.searchParams.get("lang") === "zh-Hans" ? "zh-Hans" : "zh-Hant";
            const normalizeSchoolPlatformUrl = (rawUrl) => {{
              if (!rawUrl || !rawUrl.startsWith("/school-platform")) {{
                return rawUrl;
              }}
              const target = new URL(rawUrl, window.location.origin);
              if (currentLang === "zh-Hans") {{
                target.searchParams.set("lang", "zh-Hans");
              }} else {{
                target.searchParams.delete("lang");
              }}
              return `${{target.pathname}}${{target.search}}${{target.hash}}`;
            }};

            const hantUrl = new URL(window.location.href);
            hantUrl.searchParams.delete("lang");
            const hansUrl = new URL(window.location.href);
            hansUrl.searchParams.set("lang", "zh-Hans");

            const hantLink = document.getElementById("lang-hant-link");
            const hansLink = document.getElementById("lang-hans-link");
            if (hantLink) {{
              hantLink.setAttribute("href", `${{hantUrl.pathname}}${{hantUrl.search}}${{hantUrl.hash}}`);
              hantLink.classList.toggle("active", currentLang === "zh-Hant");
            }}
            if (hansLink) {{
              hansLink.setAttribute("href", `${{hansUrl.pathname}}${{hansUrl.search}}${{hansUrl.hash}}`);
              hansLink.classList.toggle("active", currentLang === "zh-Hans");
            }}

            document.querySelectorAll('a[href^="/school-platform"]').forEach((node) => {{
              if (node.id === "lang-hant-link" || node.id === "lang-hans-link") {{
                return;
              }}
              node.setAttribute("href", normalizeSchoolPlatformUrl(node.getAttribute("href")));
            }});

            document.querySelectorAll('form[action^="/school-platform"]').forEach((node) => {{
              node.setAttribute("action", normalizeSchoolPlatformUrl(node.getAttribute("action")));
            }});

            const navLinks = Array.from(document.querySelectorAll('.nav-link[data-nav-prefix]'));
            let activeLink = null;
            let activeLength = -1;
            navLinks.forEach((node) => {{
              const prefix = node.getAttribute('data-nav-prefix') || '';
              const matches = window.location.pathname === prefix || window.location.pathname.startsWith(prefix + '/');
              if (matches && prefix.length > activeLength) {{
                activeLength = prefix.length;
                activeLink = node;
              }}
            }});
            if (activeLink) {{
              activeLink.classList.add('active');
            }}

            document.documentElement.setAttribute("lang", currentLang);
          }})();
        </script>
      </body>
    </html>
    """


@router.get("", response_class=HTMLResponse)
def school_platform_home() -> str:
    home = catalog_service.home_payload()
    metrics = admissions_service.dashboard_metrics()
    franchise_report = analytics_service.franchise_group_report()
    demo_student_email = "web-enrollment@example.com"
    demo_teacher_name = "Aki Mori"
    demo_consultant_name = "Mika Chen"
    student_portal_url = f"/school-platform/student-portal?{urlencode({'email': demo_student_email})}"
    student_progress_url = f"/school-platform/my-progress?{urlencode({'email': demo_student_email})}"
    student_ai_url = f"/school-platform/ai-practice?{urlencode({'email': demo_student_email})}"
    teacher_portal_url = f"/school-platform/teacher-portal?{urlencode({'teacher_name': demo_teacher_name})}"
    consultant_portal_url = f"/school-platform/consultant-portal?{urlencode({'staff_name': demo_consultant_name})}"

    role_hubs = [
        {
            "kicker": "Growth",
            "title": "我要看加盟招商",
            "body": "適合先看品牌怎麼對外招商、加盟主張怎麼說、以及加盟數據目前做到哪裡。",
            "chips": ["加盟夥伴", "招商顧問", "品牌入口"],
            "actions": [
                ("/school-platform/franchise-vap", "加盟招商 VAP"),
                ("/school-platform/admin/reports/franchise", "加盟組報表"),
            ],
        },
        {
            "kicker": "Student",
            "title": "我要看學員學日文的平台",
            "body": "直接進學員端，看課程、作業、測驗、AI 練習、學習進度與通知。",
            "chips": ["學員端", "教學入口", "示範帳號"],
            "actions": [
                (student_portal_url, "學員中心"),
                (student_ai_url, "AI 練習區"),
            ],
        },
        {
            "kicker": "Teacher",
            "title": "我要看老師授課的平台",
            "body": "看老師怎麼管理班級、批改作業、批改測驗與追蹤教學任務。",
            "chips": ["教師端", "批改", "班級詳情"],
            "actions": [
                (teacher_portal_url, "教師工作台"),
                ("/school-platform/admin/teaching", "教務管理"),
            ],
        },
        {
            "kicker": "Operations",
            "title": "我要看校務與營運後台",
            "body": "適合看招生、學員、財務、客服、AI 與招聘整體營運狀態。",
            "chips": ["行政", "主管", "CRM / 財務 / 報表"],
            "actions": [
                ("/school-platform/admin", "營運後台總覽"),
                ("/school-platform/admin/executive", "主管工作台"),
            ],
        },
        {
            "kicker": "Platform",
            "title": "我要看系統與上線狀態",
            "body": "適合檢查資料層 readiness、部署 blocker、DB cutover 與 smoke test。",
            "chips": ["工程", "部署", "readiness"],
            "actions": [
                ("/school-platform/operational-readiness", "今日可營運"),
                ("/school-platform/system", "系統狀態"),
                ("/school-platform/launch-readiness", "正式上線檢查"),
            ],
        },
    ]

    growth_entries = [
        {
            "label": "加盟招商 VAP",
            "path": "/school-platform/franchise-vap",
            "category": "Franchise",
            "audience": "加盟夥伴 / 招商顧問",
            "description": "完整說明 AI-aging 招商模式、AI Edge 優勢、大阪十區加盟與培訓權益。",
        },
        {
            "label": "加盟組招商報表",
            "path": "/school-platform/admin/reports/franchise",
            "category": "Growth Data",
            "audience": "主管 / 招商",
            "description": "查看三個加盟組的招商漏斗、已售區域、加盟收入與月費狀態。",
        },
        {
            "label": "課程總覽",
            "path": "/school-platform/courses",
            "category": "Public",
            "audience": "潛在學員",
            "description": "查看所有日文課程、價格、授課方式與課程詳情入口。",
        },
        {
            "label": "免費試聽預約",
            "path": "/school-platform/trial-booking",
            "category": "Admissions",
            "audience": "潛在學員",
            "description": "預約試聽、建立 lead，並把資料導入 CRM 跟進流程。",
        },
        {
            "label": "正式報名",
            "path": "/school-platform/enrollment",
            "category": "Enrollment",
            "audience": "準學員",
            "description": "填寫報名資料、選班、建立訂單並進入付款流程。",
        },
    ]
    learning_entries = [
        {
            "label": "學員中心",
            "path": student_portal_url,
            "category": "Student",
            "audience": "學員",
            "description": "查看我的課程、課表、作業、測驗、通知、付款與客服入口。",
        },
        {
            "label": "學習進度",
            "path": student_progress_url,
            "category": "Student Progress",
            "audience": "學員 / 教務",
            "description": "查看作業、測驗、出缺勤、整體評估與學習風險。",
        },
        {
            "label": "AI 練習區",
            "path": student_ai_url,
            "category": "AI Learning",
            "audience": "學員",
            "description": "做情境對話、句型練習、自我檢查與課後複習。",
        },
        {
            "label": "教師工作台",
            "path": teacher_portal_url,
            "category": "Teacher",
            "audience": "教師",
            "description": "查看授課班級、待評分作業、待評分測驗與教學任務。",
        },
        {
            "label": "教務管理",
            "path": "/school-platform/admin/teaching",
            "category": "Teaching Ops",
            "audience": "教務 / 教師",
            "description": "集中管理作業、測驗、點名與教師課後紀錄審核。",
        },
    ]
    operations_entries = [
        {
            "label": "營運後台總覽",
            "path": "/school-platform/admin",
            "category": "Operations",
            "audience": "行政 / 主管",
            "description": "把招生、教務、財務、客服、AI、招聘整理成總入口。",
        },
        {
            "label": "主管工作台",
            "path": "/school-platform/admin/executive",
            "category": "Executive",
            "audience": "主管",
            "description": "用營運摘要、警示、學習追蹤與加盟追蹤做決策。",
        },
        {
            "label": "顧問工作台",
            "path": consultant_portal_url,
            "category": "Consultant",
            "audience": "招生顧問",
            "description": "處理 hot leads、跟進隊列、AI 話術草稿與案件詳情。",
        },
        {
            "label": "報表中心",
            "path": "/school-platform/admin/reports",
            "category": "Analytics",
            "audience": "主管 / 行政",
            "description": "彙整營收、轉換、線上學習與加盟組招商資料。",
        },
        {
            "label": "財務中心",
            "path": "/school-platform/admin/finance",
            "category": "Finance",
            "audience": "財務 / 行政",
            "description": "查看訂單、付款狀態、金流 readiness 與營收概覽。",
        },
        {
            "label": "訊息中心",
            "path": "/school-platform/admin/messages",
            "category": "Communications",
            "audience": "客服 / 行政",
            "description": "集中管理 Email、LINE、站內通知與廣播訊息。",
        },
        {
            "label": "招聘管理",
            "path": "/school-platform/admin/recruiting",
            "category": "HR",
            "audience": "HR / 主管",
            "description": "查看職缺、應徵者、面試、錄取與 onboarding 進度。",
        },
    ]
    platform_entries = [
        {
            "label": "今日可營運",
            "path": "/school-platform/operational-readiness",
            "category": "Operations Readiness",
            "audience": "主管 / 營運 / 工程",
            "description": "分開顯示今天能不能直接操作平台，以及 production 外部整合還差哪些。",
        },
        {
            "label": "系統狀態",
            "path": "/school-platform/system",
            "category": "Platform",
            "audience": "工程 / 主管",
            "description": "查看 storage backend、資料 readiness、金流與通知整合狀態。",
        },
        {
            "label": "正式上線檢查",
            "path": "/school-platform/launch-readiness",
            "category": "Launch",
            "audience": "工程 / 主管",
            "description": "確認 deploy blocker、smoke test、DB cutover 與外部整合待辦。",
        },
        {
            "label": "開發進度",
            "path": "/school-platform/progress",
            "category": "Build Progress",
            "audience": "全體",
            "description": "查看目前完成模組、下一步與可直接驗證的功能入口。",
        },
        {
            "label": "最近開發紀錄",
            "path": "/school-platform/activity",
            "category": "Activity",
            "audience": "全體",
            "description": "用中文查看最近補上的頁面、流程與營運模組。",
        },
    ]
    hero_notes = [
        {
            "label": "今日招生節奏",
            "value": f"{metrics.today_new_leads} 筆新名單",
            "detail": f"本週已安排 {metrics.this_week_trial_bookings} 場試聽，顧問可以直接從熱名單往下推進。",
        },
        {
            "label": "本週報名進站",
            "value": f"{metrics.this_week_enrollments} 筆報名",
            "detail": "從試聽、正式報名到付款資料都已串進同一套 CRM 與後台流程。",
        },
        {
            "label": "加盟試點狀態",
            "value": f"{franchise_report.summary.sold_regions}/{franchise_report.summary.total_regions} 區",
            "detail": f"目前有 {franchise_report.summary.total_partner_count} 組活躍加盟夥伴可持續追蹤。",
        },
    ]
    quick_start_cards = [
        {
            "kicker": "Franchise",
            "title": "加盟招商 VAP",
            "note": "先看 AI-aging 招商故事與大阪十區方案。",
            "path": "/school-platform/franchise-vap",
        },
        {
            "kicker": "Student",
            "title": "學員學習平台",
            "note": "直接查看課程、作業、通知與 AI 練習區。",
            "path": student_portal_url,
        },
        {
            "kicker": "Teacher",
            "title": "教師工作台",
            "note": "進入授課、批改、教學紀錄與班級詳情。",
            "path": teacher_portal_url,
        },
        {
            "kicker": "Ops",
            "title": "營運後台總覽",
            "note": "集中處理 CRM、報表、財務、客服與招聘。",
            "path": "/school-platform/admin",
        },
    ]
    hero_badges = [
        "AI-aging 加盟招商",
        "學員學習平台",
        "教師授課工作台",
        "營運後台",
        "系統 readiness",
    ]
    platform_lanes = [
        {
            "index": "01",
            "title": "加盟招商",
            "note": "用首頁級 VAP、區域代理條件、AI 招商優勢與加盟報表承接成長入口。",
        },
        {
            "index": "02",
            "title": "學員學習",
            "note": "把課程、作業、測驗、AI 練習與進度追蹤收在同一個入口。",
        },
        {
            "index": "03",
            "title": "教師教學",
            "note": "教師可直接管理班級、批改作業測驗與提交課後紀錄。",
        },
        {
            "index": "04",
            "title": "營運管理",
            "note": "CRM、訊息、財務、招聘、主管報表與行政流程集中操作。",
        },
        {
            "index": "05",
            "title": "系統控台",
            "note": "查看部署、資料層、整合 readiness 與目前正式上線差距。",
        },
    ]
    journey_cards = [
        {
            "step": "Step 01",
            "title": "AI 找到需求者",
            "note": "網站、試聽、推薦與加盟導流，把真正需要日文與赴日支援的人收進同一套漏斗。",
        },
        {
            "step": "Step 02",
            "title": "顧問推進成交",
            "note": "顧問用 CRM、AI 話術與預約流程，把名單往試聽、報名與付款持續推進。",
        },
        {
            "step": "Step 03",
            "title": "學習交付發生",
            "note": "學員中心、教師工作台、作業測驗與 AI 練習，讓教學與學習紀錄實際留下來。",
        },
        {
            "step": "Step 04",
            "title": "報表回饋營運",
            "note": "主管從招生、教務、加盟與學習報表回看瓶頸，再反推下一輪招生與課程策略。",
        },
    ]

    def _render_route_cards(items: list[dict[str, str]]) -> str:
        return "".join(
            "<a class='route-card' "
            f"href='{escape(item['path'])}'>"
            f"<span class='route-label'>{escape(item['category'])}</span>"
            f"<h3>{escape(item['label'])}</h3>"
            f"<p>{escape(item['description'])}</p>"
            f"<div class='meta'><span class='chip'>{escape(item['audience'])}</span><span class='chip'>點此進入</span></div>"
            "<div class='route-card-foot'><span>模組入口</span><strong>立即查看</strong></div>"
            "</a>"
            for item in items
        )

    def _render_role_cards(items: list[dict[str, object]]) -> str:
        cards = []
        for item in items:
            chips_html = "".join(f"<span class='chip'>{escape(str(chip))}</span>" for chip in item["chips"])
            actions_html = "".join(
                f"<a class='btn alt' href='{escape(path)}'>{escape(label)}</a>"
                for path, label in item["actions"]
            )
            cards.append(
                "<article class='card'>"
                f"<div class='eyebrow'>{escape(str(item['kicker']))}</div>"
                f"<h3>{escape(str(item['title']))}</h3>"
                f"<p>{escape(str(item['body']))}</p>"
                f"<div class='meta'>{chips_html}</div>"
                f"<div class='actions'>{actions_html}</div>"
                "</article>"
            )
        return "".join(cards)

    role_cards = _render_role_cards(role_hubs)
    hero_note_cards = "".join(
        "<article class='hero-note'>"
        f"<span class='hero-note-label'>{escape(item['label'])}</span>"
        f"<span class='hero-note-value'>{escape(item['value'])}</span>"
        f"<span class='hero-note-detail'>{escape(item['detail'])}</span>"
        "</article>"
        for item in hero_notes
    )
    hero_badge_html = "".join(f"<span class='hero-badge'>{escape(item)}</span>" for item in hero_badges)
    lane_cards_html = "".join(
        "<article class='lane-card'>"
        f"<span class='lane-index'>{escape(item['index'])}</span>"
        f"<strong class='lane-title'>{escape(item['title'])}</strong>"
        f"<p class='lane-note'>{escape(item['note'])}</p>"
        "</article>"
        for item in platform_lanes
    )
    journey_cards_html = "".join(
        "<article class='journey-card'>"
        f"<span class='journey-step'>{escape(item['step'])}</span>"
        f"<h3 class='journey-title'>{escape(item['title'])}</h3>"
        f"<p class='journey-note'>{escape(item['note'])}</p>"
        "</article>"
        for item in journey_cards
    )
    quick_start_html = "".join(
        "<a class='command-card' "
        f"href='{escape(item['path'])}'>"
        f"<span>{escape(item['kicker'])}</span>"
        f"<strong>{escape(item['title'])}</strong>"
        f"<p>{escape(item['note'])}</p>"
        "</a>"
        for item in quick_start_cards
    )
    course_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(course.course_type)} / {escape(course.level)}</div>"
        f"<h3>{escape(course.name)}</h3>"
        f"<p>{escape(course.short_description)}</p>"
        f"<div class='price'>{_format_jpy(course.price)}</div>"
        f"<div class='meta'><span class='chip'>{escape(course.delivery_mode)}</span><span class='chip'>學員端可查看</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/courses/{escape(course.slug)}'>查看課程詳情</a></div>"
        "</article>"
        for course in home.featured_courses[:4]
    )
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Platform Entry Map / {escape(home.brand_name)}</div>
            <h1>平台入口總覽</h1>
            <p>這個首頁不是單一宣傳頁，而是整個 AI 日語補習班平台的入口中樞。加盟招商、課程招生、學員學習、教師授課、營運管理與系統檢查，都要在第一眼就看懂、看得到、進得去。</p>
            <p>你可以依角色找入口，也可以依工作流切入。這一版把所有主要動線重新排成清楚的商業平台地圖，讓加盟主、顧問、教師與管理區一進來就知道往哪裡走。</p>
            <div class="hero-badge-row">{hero_badge_html}</div>
            <div class="actions">
              <a class="btn" href="{student_portal_url}">學員中心</a>
              <a class="btn alt" href="{teacher_portal_url}">教師工作台</a>
              <a class="btn alt" href="/school-platform/admin">營運後台</a>
              <a class="btn alt" href="/school-platform/franchise-vap">加盟招商 VAP</a>
            </div>
            <div class="hero-note-grid">{hero_note_cards}</div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">Platform Lanes</div>
            <h2>五條主營運動線</h2>
            <p>平台不只是一堆連結，而是五條彼此銜接的營運動線。先看整張地圖，再點進你今天要處理的角色入口。</p>
            <div class="lane-grid">{lane_cards_html}</div>
            <div class="command-board">{quick_start_html}</div>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>對外成長</span><strong>加盟 / 課程 / 試聽 / 報名</strong></div>
              <div class="mini-kpi"><span>學員教學</span><strong>學員中心 / AI 練習 / 進度</strong></div>
              <div class="mini-kpi"><span>營運管理</span><strong>CRM / 財務 / 訊息 / 招聘</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Role Hubs</div>
            <h2>角色入口</h2>
          </div>
          <p class="section-subtitle">如果你現在不是要看全部頁面，而是想直接進入某一種工作流，先從這裡點最不會迷路。</p>
        </div>
        <div class="grid two">{role_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Operating Loop</div>
            <h2>平台怎麼把招生一路接到教學與營收</h2>
          </div>
          <p class="section-subtitle">這不是只把頁面排漂亮，而是把加盟招商、招生 CRM、教學交付與營運報表串成真正會運作的閉環。</p>
        </div>
        <div class="journey-grid">{journey_cards_html}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Growth Layer</div>
            <h2>對外成長入口</h2>
          </div>
          <p class="section-subtitle">這一區是給潛在學員、加盟夥伴與招生導流使用的前台入口。</p>
        </div>
        <div class="route-grid">{_render_route_cards(growth_entries)}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Learning Layer</div>
            <h2>學習與教學入口</h2>
          </div>
          <p class="section-subtitle">這一區是日文教學平台本體，學員端與教師端都在這裡。</p>
        </div>
        <div class="route-grid">{_render_route_cards(learning_entries)}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Operations Layer</div>
            <h2>營運與管理入口</h2>
          </div>
          <p class="section-subtitle">這一區適合行政、招生顧問、主管、財務、客服與 HR 團隊使用。</p>
        </div>
        <div class="route-grid">{_render_route_cards(operations_entries)}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Platform Layer</div>
            <h2>系統與開發入口</h2>
          </div>
          <p class="section-subtitle">這一區適合檢查部署、資料層、進度與最近開發狀態。</p>
        </div>
        <div class="route-grid">{_render_route_cards(platform_entries)}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Live Snapshot</div>
            <h2>目前平台快照</h2>
          </div>
          <p class="section-subtitle">把招生、營收與加盟試點濃縮成一眼能看的營運數字。</p>
        </div>
        <div class="stat-grid">
          <div class="stat"><div class="label">今日新名單</div><div class="value">{metrics.today_new_leads}</div></div>
          <div class="stat"><div class="label">本週試聽</div><div class="value">{metrics.this_week_trial_bookings}</div></div>
          <div class="stat"><div class="label">本週報名</div><div class="value">{metrics.this_week_enrollments}</div></div>
          <div class="stat"><div class="label">已收營收</div><div class="value">{_format_jpy(metrics.paid_revenue_total)}</div></div>
          <div class="stat"><div class="label">活躍加盟夥伴</div><div class="value">{franchise_report.summary.total_partner_count}</div></div>
          <div class="stat"><div class="label">已售區域</div><div class="value">{franchise_report.summary.sold_regions}/{franchise_report.summary.total_regions}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Course Samples</div>
            <h2>課程示範入口</h2>
          </div>
          <p class="section-subtitle">如果你要直接看「日文教學內容」長什麼樣，從這些課程卡片進入最快。</p>
        </div>
        <div class="grid">{course_cards}</div>
      </section>
    """
    return _page_shell("AI 日語補習班營運平台 MVP", body)


@router.get("/franchise-vap", response_class=HTMLResponse)
def school_platform_franchise_vap_page() -> str:
    franchise_vap = _franchise_vap_blueprint()
    franchise_report = analytics_service.franchise_group_report()
    vap_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(str(item['kicker']))}</div>"
        f"<h3>{escape(str(item['title']))}</h3>"
        f"<p>{escape(str(item['body']))}</p>"
        "</article>"
        for item in franchise_vap["vap_cards"]
    )
    positioning_items = "".join(f"<li>{escape(str(item))}</li>" for item in franchise_vap["positioning"])
    agent_stack_items = "".join(f"<li>{escape(str(item))}</li>" for item in franchise_vap["agent_stack"])
    training_items = "".join(f"<li>{escape(str(item))}</li>" for item in franchise_vap["training_rights"])
    ai_edge_items = "".join(f"<li>{escape(str(item))}</li>" for item in franchise_vap["ai_edge_points"])
    share_loop_items = "".join(f"<li>{escape(str(item))}</li>" for item in franchise_vap["share_loop"])
    group_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.partner_type)}</div>"
        f"<h3>{escape(item.group_name)}</h3>"
        f"<p>加盟夥伴 {item.partner_count} / 已售區域 {item.sold_regions}/{item.total_regions or item.sold_regions}</p>"
        f"<div class='meta'><span class='chip'>名單 {item.total_leads}</span><span class='chip'>成交 {item.enrolled_leads}</span><span class='chip'>轉換率 {item.conversion_rate:g}%</span></div>"
        f"<div class='meta'><span class='chip'>加盟收入 {_format_jpy(item.booked_join_fee_revenue_jpy)}</span><span class='chip'>月費 {_format_jpy(item.monthly_recurring_revenue_jpy)}</span></div>"
        f"<p>目前重點：{escape(item.next_focus)}</p>"
        "</article>"
        for item in franchise_report.groups
    )
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Franchise VAP / AI-aging Growth</div>
            <h1>{escape(str(franchise_vap['hero_title']))}</h1>
            <p>{escape(str(franchise_vap['hero_subtitle']))}</p>
            <p>{escape(str(franchise_vap['slogan']))}</p>
            <div class="meta">
              <span class="chip">首頁主推加盟招商</span>
              <span class="chip">AI Edge 獨家優勢</span>
              <span class="chip">線上 + 線下學習導入日本社會</span>
              <span class="chip">學生分享激勵機制</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/reports/franchise">查看加盟組報表</a>
              <a class="btn alt" href="/school-platform/admin/executive">回主管工作台</a>
              <a class="btn alt" href="/school-platform">回首頁</a>
            </div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">VAP Snapshot</div>
            <h2>把加盟條件、AI 優勢與營運證據一次講清楚</h2>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>大阪試點</span><strong>10 區</strong></div>
              <div class="mini-kpi"><span>加盟費</span><strong>JPY 100,000 / 區</strong></div>
              <div class="mini-kpi"><span>AI agents</span><strong>10 - 100</strong></div>
              <div class="mini-kpi"><span>AI 行銷陪跑</span><strong>6 小時</strong></div>
              <div class="mini-kpi"><span>實體開營訓練</span><strong>1 場</strong></div>
              <div class="mini-kpi"><span>線上營運培訓</span><strong>20 小時</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>VAP 主敘事</h2>
        <p>這一頁不是傳統加盟說明書，而是要明確傳達我們的主張：招商方式已經變成 AI-aging 模式，核心在於精準找對需求者、快速建立信任、持續把分享變成擴散。</p>
        <div class="grid">{vap_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Positioning</div>
            <h3>AI-aging 不是多打一點廣告</h3>
            <ul class="clean">{positioning_items}</ul>
          </article>
          <article class="card">
            <div class="eyebrow">Agent Stack</div>
            <h3>10 到 100 個 AI agents 的分工方式</h3>
            <ul class="clean">{agent_stack_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">AI Edge</div>
            <h3>AI Edge 學員推廣引擎</h3>
            <ul class="clean">{ai_edge_items}</ul>
          </article>
          <article class="card">
            <div class="eyebrow">Student Referral Loop</div>
            <h3>學習與分享同時發生</h3>
            <ul class="clean">{share_loop_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Partner Rights</div>
            <h3>加盟主啟動權益包</h3>
            <ul class="clean">{training_items}</ul>
          </article>
          <article class="card">
            <div class="eyebrow">Operating Outcome</div>
            <h3>為什麼這套模式更容易進入日本社會語境</h3>
            <ul class="clean">
              <li>在線上推廣階段先建立需求與信任，再把人導入線下或直播交流。</li>
              <li>讓學員在日語學習的同時接觸真實生活、工作與社會互動場景。</li>
              <li>加盟主不是只賣課，而是在經營一個會自己擴散的學習社群與生活入口。</li>
            </ul>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>目前三個加盟組的營運面</h2>
        <p>這不是抽象提案，管理區已經能直接追蹤三個加盟組的招商漏斗、已售區域與加盟收入。</p>
        <div class="stat-grid">
          <div class="stat"><div class="label">加盟組</div><div class="value">{franchise_report.summary.total_groups}</div></div>
          <div class="stat"><div class="label">活躍夥伴</div><div class="value">{franchise_report.summary.total_partner_count}</div></div>
          <div class="stat"><div class="label">已售區域</div><div class="value">{franchise_report.summary.sold_regions}/{franchise_report.summary.total_regions}</div></div>
          <div class="stat"><div class="label">加盟收入</div><div class="value">{_format_jpy(franchise_report.summary.booked_join_fee_revenue_jpy)}</div></div>
          <div class="stat"><div class="label">月費 MRR</div><div class="value">{_format_jpy(franchise_report.summary.monthly_recurring_revenue_jpy)}</div></div>
          <div class="stat"><div class="label">綜合轉換率</div><div class="value">{franchise_report.summary.blended_conversion_rate:g}%</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{group_cards}</div>
      </section>
    """
    return _page_shell("加盟招商 VAP", body)


@router.get("/courses", response_class=HTMLResponse)
def school_platform_courses_page() -> str:
    courses = catalog_service.list_courses()
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(course.course_type)} / {escape(course.level)}</div>"
        f"<h3>{escape(course.name)}</h3>"
        f"<p>{escape(course.short_description)}</p>"
        "<div class='meta'>"
        f"<span class='chip'>{_format_jpy(course.price)}</span>"
        f"<span class='chip'>{escape(course.delivery_mode)}</span>"
        "</div>"
        f"<div class='actions'><a class='btn' href='/school-platform/courses/{escape(course.slug)}'>查看課程詳情</a></div>"
        "</article>"
        for course in courses
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Course Catalog</div>
        <h1>課程總覽</h1>
        <p>這裡把目前可招生的日語課程整理成中文網頁介面，方便你直接看產品是不是已經開始成形。</p>
        <div class="actions">
          <a class="btn" href="/school-platform">回平台首頁</a>
          <a class="btn alt" href="/school-platform/api/public/courses">查看課程 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid">{cards}</div>
      </section>
    """
    return _page_shell("課程總覽", body)


@router.get("/courses/{slug}", response_class=HTMLResponse)
def school_platform_course_detail_page(slug: str) -> str:
    try:
        snapshot = course_content_service.snapshot(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    course = snapshot.course
    classes = catalog_service.classes_for_course(slug)
    class_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(class_item.name)}</h3>"
        f"<p>老師：{escape(class_item.teacher_name)} / 上課：{escape(class_item.weekday)} {escape(class_item.start_time.strftime('%H:%M'))}-{escape(class_item.end_time.strftime('%H:%M'))}</p>"
        f"<p>期間：{escape(class_item.start_date.isoformat())} 至 {escape(class_item.end_date.isoformat())}</p>"
        f"<div class='meta'><span class='chip'>名額 {class_item.enrolled_count}/{class_item.capacity}</span><span class='chip'>{escape(class_item.location_label)}</span></div>"
        "</article>"
        for class_item in classes
    ) or "<article class='card'><h3>尚無開放班級</h3><p>這門課已建檔，但目前沒有可報名班級。</p></article>"
    objectives = "".join(f"<li>{escape(item)}</li>" for item in course.objectives)
    highlights = "".join(f"<li>{escape(item)}</li>" for item in course.highlights)
    modules = "".join(
        "<li>"
        f"<strong>{escape(item.title)}</strong>"
        f"<p>{escape(item.description)}</p>"
        + (f"<p><a href='{escape(item.material_url)}'>{escape(item.material_url)}</a></p>" if item.material_url else "")
        + "</li>"
        for item in snapshot.core_modules
    ) or "".join(f"<li>{escape(item)}</li>" for item in course.modules)
    platform_materials = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>平台核心教材 / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, label='查看教材')}"
        f"{_material_source_html(item)}"
        "</article>"
        for item in snapshot.platform_materials
    ) or "<article class='card'><h3>目前沒有公開平台教材</h3></article>"
    teacher_materials = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>教師補充內容 / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, label='查看教材')}"
        f"{_material_source_html(item)}"
        f"<div class='meta'><span class='chip'>{escape(item.created_by)}</span></div>"
        "</article>"
        for item in snapshot.teacher_materials
    ) or "<article class='card'><h3>目前沒有教師補充內容</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">{escape(course.course_type)} / {escape(course.level)}</div>
        <h1>{escape(course.name)}</h1>
        <p>{escape(course.short_description)}</p>
        <div class="meta">
          <span class="chip">{_format_jpy(course.price)}</span>
          <span class="chip">{escape(course.delivery_mode)}</span>
          <span class="chip">教師：{escape(", ".join(course.teacher_names) or "待定")}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/courses">回課程總覽</a>
          <a class="btn alt" href="/school-platform/trial-booking?course_slug={escape(course.slug)}">預約這門課試聽</a>
          <a class="btn alt" href="/school-platform/enrollment?course_slug={escape(course.slug)}">直接報名這門課</a>
          <a class="btn alt" href="/school-platform/api/public/courses/{escape(course.slug)}">查看課程 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>課程目標</h2>
            <ul class="clean">{objectives}</ul>
          </article>
          <article class="card">
            <h2>課程亮點</h2>
            <ul class="clean">{highlights}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>平台核心章節</h2>
        <article class="card">
          <ul class="clean">{modules}</ul>
        </article>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Platform-Owned Content</div>
            <h2>平台標準教材</h2>
          </div>
          <p class="section-subtitle">這些是平台自有的核心教材與標準資源，不會因不同老師而完全改掉。</p>
        </div>
        <div class="grid two">{platform_materials}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Teacher Supplement</div>
            <h2>教師補充內容</h2>
          </div>
          <p class="section-subtitle">這些是老師依班級實際狀況補充的延伸內容，會與平台核心內容分開呈現。</p>
        </div>
        <div class="grid two">{teacher_materials}</div>
      </section>
      <section class="section">
        <h2>目前可報名班級</h2>
        <div class="grid two">{class_cards}</div>
      </section>
    """
    return _page_shell(course.name, body)


@router.get("/materials/{material_id}/download")
def school_platform_material_download(
    material_id: UUID,
    email: str | None = Query(default=None),
    teacher_name: str | None = Query(default=None),
    user=Depends(_optional_current_user),
):
    try:
        material = catalog_service.get_teaching_material(material_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Material not found") from exc
    _assert_material_access(material, email=email, teacher_name=teacher_name, user=user)
    if material.storage_kind == "uploaded_file" and material.stored_path:
        target = _resolve_uploaded_material_path(material.stored_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Uploaded material file not found")
        return FileResponse(
            target,
            media_type=material.mime_type or "application/octet-stream",
            filename=material.file_name or target.name,
        )
    if material.material_url:
        return RedirectResponse(url=material.material_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    raise HTTPException(status_code=404, detail="Material asset not found")


@router.get("/trial-booking", response_class=HTMLResponse)
def school_platform_trial_booking_page(course_slug: str | None = Query(default=None)) -> str:
    courses = catalog_service.list_courses()
    slots = public_admissions_service.trial_slots(course_slug)
    course_options = "".join(
        f"<option value='{escape(item.slug)}' {'selected' if item.slug == course_slug else ''}>{escape(item.name)} ({escape(item.level)})</option>"
        for item in courses
    )
    slot_options = "".join(
        f"<option value='{item.starts_at.isoformat()}'>{escape(item.label)} / {escape(item.starts_at.strftime('%Y-%m-%d %H:%M'))}</option>"
        for item in slots
    )
    if not slot_options:
        slot_options = "<option value=''>目前沒有可預約時段</option>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Trial Booking</div>
        <h1>免費試聽預約</h1>
        <p>這裡把試聽預約流程做成中文網頁表單，填完就會直接建立 lead、指派顧問並排入提醒。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/courses">回課程總覽</a>
          <a class="btn alt" href="/school-platform/api/public/trial-slots">查看時段 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>試聽預約表單</h2>
            <form class="stack" method="post" action="/school-platform/trial-booking/create">
              <label class="field">姓名
                <input type="text" name="name" placeholder="例如：王小美" />
              </label>
              <label class="field">Email
                <input type="email" name="email" placeholder="you@example.com" />
              </label>
              <label class="field">電話
                <input type="text" name="phone" placeholder="09xxxxxxxx" />
              </label>
              <label class="field">LINE ID
                <input type="text" name="line_id" placeholder="選填" />
              </label>
              <label class="field">想試聽的課程
                <select name="course_slug">{course_options}</select>
              </label>
              <label class="field">可預約時段
                <select name="slot_start_at">{slot_options}</select>
              </label>
              <label class="field">目前程度
                <select name="japanese_level">
                  <option value="beginner">beginner</option>
                  <option value="N5">N5</option>
                  <option value="N4">N4</option>
                  <option value="N3">N3</option>
                </select>
              </label>
              <label class="field">學習目標
                <textarea name="study_goal" placeholder="例如：赴日前想先學租屋、看病、購物會話"></textarea>
              </label>
              <button class="btn" type="submit">送出試聽預約</button>
            </form>
          </article>
          <article class="card">
            <h2>送出後系統會做什麼</h2>
            <ul class="clean">
              <li>建立 lead 名單並標記為 <code>trial_booked</code></li>
              <li>自動指派招生顧問</li>
              <li>新增 CRM 跟進紀錄</li>
              <li>排入試聽前一天提醒通知</li>
            </ul>
          </article>
        </div>
      </section>
    """
    return _page_shell("免費試聽預約", body)


@router.post("/trial-booking/create")
def school_platform_trial_booking_submit(
    name: str = Form(...),
    email: str = Form(default=""),
    phone: str = Form(default=""),
    line_id: str = Form(default=""),
    course_slug: str = Form(...),
    slot_start_at: str = Form(...),
    japanese_level: str = Form(default=""),
    study_goal: str = Form(default=""),
):
    payload = TrialBookingCreate(
        name=name,
        email=email or None,
        phone=phone or None,
        line_id=line_id or None,
        course_slug=course_slug,
        slot_start_at=datetime.fromisoformat(slot_start_at),
        japanese_level=japanese_level or None,
        study_goal=study_goal or None,
    )
    booking = public_admissions_service.create_trial_booking(payload)
    query = urlencode(
        {
            "booking_id": str(booking.booking_id),
            "lead_id": str(booking.lead_id),
            "staff": booking.assigned_staff_name,
            "next_follow_up_at": booking.next_follow_up_at.isoformat(),
        }
    )
    return RedirectResponse(url=f"/school-platform/trial-booking/success?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/trial-booking/success", response_class=HTMLResponse)
def school_platform_trial_booking_success_page(
    booking_id: str = Query(...),
    lead_id: str = Query(...),
    staff: str = Query(...),
    next_follow_up_at: str = Query(...),
) -> str:
    body = f"""
      <section class="hero">
        <div class="eyebrow">Trial Booking Success</div>
        <h1>試聽預約已送出</h1>
        <p>系統已替你建立試聽預約、CRM 名單與顧問指派，後續會依照設定時間自動提醒。</p>
        <div class="meta">
          <span class="chip">booking_id: {escape(booking_id)}</span>
          <span class="chip">lead_id: {escape(lead_id)}</span>
          <span class="chip">顧問：{escape(staff)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/trial-booking">再預約一筆</a>
          <a class="btn alt" href="/school-platform/admin/leads">查看招生名單</a>
        </div>
      </section>
      <section class="section">
        <article class="card">
          <h2>下一步</h2>
          <p>預計下次跟進時間：<code>{escape(next_follow_up_at)}</code></p>
          <p>這一筆資料已經進入招生 CRM，顧問可直接在後台查看與更新。</p>
        </article>
      </section>
    """
    return _page_shell("試聽預約成功", body)


@router.get("/enrollment", response_class=HTMLResponse)
def school_platform_enrollment_page(course_slug: str | None = Query(default=None)) -> str:
    classes = catalog_service.open_classes()
    if course_slug:
        classes = [item for item in classes if item.course_slug == course_slug]
    class_options = "".join(
        f"<option value='{item.id}'>{escape(item.name)} / {escape(item.course_slug)} / {escape(item.weekday)} / {escape(item.location_label)}</option>"
        for item in classes
    )
    if not class_options:
        class_options = "<option value=''>目前沒有可報名班級</option>"
    course_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.course_slug)} / {escape(item.weekday)} / {escape(item.location_label)}</p>"
        f"<div class='meta'><span class='chip'>名額 {item.enrolled_count}/{item.capacity}</span><span class='chip'>{escape(item.start_date.isoformat())}</span></div>"
        "</article>"
        for item in classes[:4]
    ) or "<article class='card'><h3>目前沒有班級</h3><p>請先回課程頁選擇其他課程或之後再試。</p></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Enrollment</div>
        <h1>正式報名</h1>
        <p>這裡會直接建立學員、報名紀錄、付款訂單與通知，讓前台招生主流程可以從網頁直接走完。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/courses">回課程總覽</a>
          <a class="btn alt" href="/school-platform/trial-booking">先預約試聽</a>
          <a class="btn alt" href="/school-platform/api/public/classes/open">查看開放班級 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>報名表單</h2>
            <form class="stack" method="post" action="/school-platform/enrollment/create">
              <label class="field">中文姓名
                <input type="text" name="chinese_name" placeholder="例如：林小雅" />
              </label>
              <label class="field">Email
                <input type="email" name="email" placeholder="you@example.com" />
              </label>
              <label class="field">電話
                <input type="text" name="phone" placeholder="09xxxxxxxx" />
              </label>
              <label class="field">班級
                <select name="class_id">{class_options}</select>
              </label>
              <label class="field">日語程度
                <select name="japanese_level">
                  <option value="beginner">beginner</option>
                  <option value="N5">N5</option>
                  <option value="N4">N4</option>
                  <option value="N3">N3</option>
                </select>
              </label>
              <label class="field">學習目標
                <textarea name="study_goal" placeholder="例如：赴日前先完成生活與工作面試會話"></textarea>
              </label>
              <label class="field">付款方式
                <select name="payment_method">
                  <option value="card">card</option>
                  <option value="transfer">transfer</option>
                  <option value="cash">cash</option>
                </select>
              </label>
              <button class="btn" type="submit">建立報名與付款單</button>
            </form>
          </article>
          <article class="card">
            <h2>目前可報名班級</h2>
            <div class="list">{course_cards}</div>
          </article>
        </div>
      </section>
    """
    return _page_shell("正式報名", body)


@router.post("/enrollment/create")
def school_platform_enrollment_submit(
    chinese_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(default=""),
    class_id: str = Form(...),
    japanese_level: str = Form(default=""),
    study_goal: str = Form(default=""),
    payment_method: str = Form(default="card"),
):
    enrollment = finance_service.create_enrollment(
        EnrollmentCreate(
            chinese_name=chinese_name,
            email=email,
            phone=phone or None,
            class_id=UUID(class_id),
            japanese_level=japanese_level or None,
            study_goal=study_goal or None,
            payment_method=payment_method,
        )
    )
    query = urlencode(
        {
            "student_email": email,
            "order_no": enrollment.order_no,
            "status": enrollment.status,
            "payment_status": enrollment.payment_status,
        }
    )
    return RedirectResponse(url=f"/school-platform/enrollment/success?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/enrollment/success", response_class=HTMLResponse)
def school_platform_enrollment_success_page(
    student_email: str = Query(...),
    order_no: str = Query(...),
    status_value: str = Query(..., alias="status"),
    payment_status: str = Query(...),
) -> str:
    body = f"""
      <section class="hero">
        <div class="eyebrow">Enrollment Success</div>
        <h1>報名申請已建立</h1>
        <p>系統已建立學員、報名紀錄與付款訂單，下一步可以直接進學員中心查看資料。</p>
        <div class="meta">
          <span class="chip">學員：{escape(student_email)}</span>
          <span class="chip">訂單：{escape(order_no)}</span>
          <span class="chip">報名狀態：{escape(status_value)}</span>
          <span class="chip">付款狀態：{escape(payment_status)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/payment?email={escape(student_email)}&order_no={escape(order_no)}">前往付款中心</a>
          <a class="btn" href="/school-platform/student-portal?email={escape(student_email)}">打開學員中心</a>
          <a class="btn alt" href="/school-platform/admin">回營運後台</a>
        </div>
      </section>
      <section class="section">
        <article class="card">
          <h2>下一步</h2>
          <p>這筆報名已經同步建立通知與付款資料，後續可透過付款 API 或 webhook 把狀態推進到 <code>paid</code>。</p>
        </article>
      </section>
    """
    return _page_shell("報名成功", body)


@router.get("/jobs", response_class=HTMLResponse)
def school_platform_jobs_page(position_id: UUID | None = Query(default=None)) -> str:
    jobs = recruiting_service.list_jobs(status="open")
    selected_id = position_id or (jobs[0].id if jobs else None)
    selected_job = next((item for item in jobs if item.id == selected_id), jobs[0] if jobs else None)
    job_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.department)} / {escape(item.employment_type)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.location_label)}</span><span class='chip'>{escape(item.salary_range)}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/jobs?position_id={item.id}'>應徵這個職缺</a></div>"
        "</article>"
        for item in jobs
    ) or "<article class='card'><h3>目前沒有開放職缺</h3></article>"
    requirement_list = "".join(f"<li>{escape(item)}</li>" for item in (selected_job.requirements if selected_job else []))
    apply_block = (
        f"""
        <article class="card">
          <h2>投遞履歷</h2>
          <p>目前選擇職缺：<code>{escape(selected_job.title)}</code></p>
          <form class="stack" method="post" action="/school-platform/jobs/apply">
            <input type="hidden" name="position_id" value="{selected_job.id}" />
            <label class="field">姓名
              <input type="text" name="name" />
            </label>
            <label class="field">Email
              <input type="email" name="email" />
            </label>
            <label class="field">電話
              <input type="text" name="phone" />
            </label>
            <label class="field">履歷連結
              <input type="text" name="resume_link" placeholder="Google Drive / Notion / PDF link" />
            </label>
            <label class="field">補充說明
              <textarea name="note" placeholder="簡單說明你的教學或招生經驗"></textarea>
            </label>
            <button class="btn" type="submit">送出應徵</button>
          </form>
        </article>
        <article class="card">
          <h2>需求條件</h2>
          <ul class="clean">{requirement_list}</ul>
        </article>
        """
        if selected_job
        else "<article class='card'><h2>投遞履歷</h2><p>目前沒有可投遞的職缺。</p></article>"
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Recruiting</div>
        <h1>加入 AI 日語補習班團隊</h1>
        <p>這裡提供公開職缺與線上投遞表單，後台會同步進入招聘看板與面試流程。</p>
        <div class="actions">
          <a class="btn" href="/school-platform">回平台首頁</a>
          <a class="btn alt" href="/school-platform/api/public/jobs">查看職缺 JSON</a>
        </div>
      </section>
      <section class="section">
        <h2>開放職缺</h2>
        <div class="grid two">{job_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">{apply_block}</div>
      </section>
    """
    return _page_shell("招聘頁", body)


@router.post("/jobs/apply")
def school_platform_jobs_apply_submit(
    position_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(default=""),
    resume_link: str = Form(default=""),
    note: str = Form(default=""),
):
    applicant = recruiting_service.create_applicant(
        ApplicantCreateRequest(
            position_id=UUID(position_id),
            name=name,
            email=email,
            phone=phone or None,
            resume_link=resume_link or None,
            note=note or None,
        )
    )
    query = urlencode({"applicant_id": str(applicant.id), "email": email})
    return RedirectResponse(url=f"/school-platform/jobs/success?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs/success", response_class=HTMLResponse)
def school_platform_jobs_success_page(applicant_id: UUID = Query(...), email: str = Query(...)) -> str:
    body = f"""
      <section class="hero">
        <div class="eyebrow">Application Submitted</div>
        <h1>應徵資料已送出</h1>
        <p>系統已建立應徵者資料並同步通知招聘後台，下一步可由主管安排面試。</p>
        <div class="meta">
          <span class="chip">Applicant ID：{applicant_id}</span>
          <span class="chip">{escape(email)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/jobs">回招聘頁</a>
          <a class="btn alt" href="/school-platform/admin/recruiting">查看招聘看板</a>
        </div>
      </section>
    """
    return _page_shell("應徵成功", body)


@router.get("/payment", response_class=HTMLResponse)
def school_platform_payment_page(
    email: str = Query(...),
    order_no: str = Query(...),
    client_token: str | None = Query(default=None),
    checkout_url: str | None = Query(default=None),
    reminder_sent: str | None = Query(default=None),
    payment_result: str | None = Query(default=None),
    payment_error: str | None = Query(default=None),
    reconcile_result: str | None = Query(default=None),
    reconcile_message: str | None = Query(default=None),
) -> str:
    try:
        payments = student_portal_service.student_payments(email)
        notifications = student_portal_service.student_notifications(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    payment = next((item for item in payments if item.order_no == order_no), None)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment_notifications = [
        item for item in notifications if order_no in item.content or item.type in {"enrollment_created", "payment_status_updated"}
    ][:4]
    payment_provider_status = finance_service.payment_provider_status()
    effective_client_token = client_token or payment.client_token
    effective_checkout_url = checkout_url or payment.checkout_url
    notification_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.channel)}</span><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.provider or 'internal')}</span></div>"
        "</article>"
        for item in payment_notifications
    ) or "<article class='card'><h3>尚無付款通知</h3></article>"
    token_block = (
        (
            "<article class='card'>"
            "<h3>Stripe Checkout 已建立</h3>"
            f"<p><code>{escape(effective_client_token or '')}</code></p>"
            f"<p><a class='btn' href='{escape(effective_checkout_url or '#')}' target='_blank' rel='noreferrer'>前往 Stripe 付款頁</a></p>"
            "<p>這是正式外部金流 checkout session；完成付款後會回到本頁並透過 webhook 回寫狀態。</p>"
            "</article>"
        )
        if effective_checkout_url
        else (
            f"<article class='card'><h3>最新 client token</h3><p><code>{escape(effective_client_token)}</code></p><p>這是目前使用中的 payment intent token。</p></article>"
            if effective_client_token
            else "<article class='card'><h3>尚未建立 payment intent</h3><p>可先點下面按鈕建立付款 session 或 mock token。</p></article>"
        )
    )
    reminder_block = (
        "<article class='card'><h3>付款提醒已寄出</h3><p>系統已新增一筆付款提醒通知，學員可回到通知中心查看。</p></article>"
        if reminder_sent
        else ""
    )
    reconcile_block = (
        (
            f"<article class='card'><h3>Stripe 同步完成</h3><p>{escape(reconcile_message or '已重新抓取最新 Stripe Checkout 狀態。')}</p></article>"
            if reconcile_result == "success"
            else (
                f"<article class='card'><h3>Stripe 同步未完成</h3><p>{escape(reconcile_message or '目前還無法同步 Stripe 狀態。')}</p></article>"
                if reconcile_result == "error"
                else ""
            )
        )
    )
    payment_result_block = (
        "<article class='card'><h3>付款已完成返回</h3><p>若 webhook 已成功抵達，訂單狀態會更新為 paid；若狀態還沒變更，可稍候重新整理本頁。</p></article>"
        if payment_result == "success"
        else (
            "<article class='card'><h3>付款流程已取消</h3><p>本次外部付款未完成，你可以重新建立 checkout session 再次付款。</p></article>"
            if payment_result == "cancel"
            else (
                f"<article class='card'><h3>付款 session 建立失敗</h3><p>{escape(payment_error)}</p></article>"
                if payment_error
                else ""
            )
        )
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Payment Center</div>
        <h1>付款中心</h1>
        <p>這頁把報名後的付款流程做成可操作的中文介面，現在可以直接查訂單、建立正式 Stripe Checkout 或 mock intent，並查看 webhook 回寫結果。</p>
        <div class="meta">
          <span class="chip">學員：{escape(email)}</span>
          <span class="chip">訂單：{escape(payment.order_no)}</span>
          <span class="chip">方式：{escape(payment.payment_method)}</span>
          <span class="chip">狀態：{escape(payment.status)}</span>
          <span class="chip">provider：{escape(payment.provider or 'mock')}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
          <a class="btn alt" href="/school-platform/admin">回營運後台</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>訂單摘要</h2>
            <p>金額：{_format_jpy(payment.amount)}</p>
            <p>建立時間：{escape(payment.created_at.isoformat())}</p>
            <p>已付款時間：{escape(payment.paid_at.isoformat()) if payment.paid_at else '尚未付款'}</p>
            <p>provider_status：{escape(payment.provider_status or payment.status)}</p>
            <p>checkout_expires_at：{escape(payment.checkout_expires_at.isoformat()) if payment.checkout_expires_at else '未提供'}</p>
            <p>last_reconciled_at：{escape(payment.last_reconciled_at.isoformat()) if payment.last_reconciled_at else '尚未同步'}</p>
            <p>provider_last_error：{escape(payment.provider_last_error) if payment.provider_last_error else '無'}</p>
          </article>
          {token_block}
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>金流 readiness</h2>
            <p>provider：<code>{escape(str(payment_provider_status['provider']))}</code></p>
            <p>ready：<code>{escape(str(payment_provider_status['ready']).lower())}</code></p>
            <p>currency：<code>{escape(str(payment_provider_status['currency']))}</code></p>
            <p>provider_mode：<code>{escape(str(payment_provider_status['provider_mode']))}</code></p>
            <p>reconciliation_supported：<code>{escape(str(payment_provider_status['reconciliation_supported']).lower())}</code></p>
            <p>message：{escape(str(payment_provider_status['message']))}</p>
          </article>
          {(payment_result_block or reconcile_block) or "<article class='card'><h3>付款流程回傳</h3><p>尚未從外部金流返回。</p></article>"}
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>建立付款 Session</h2>
            <form class="stack" method="post" action="/school-platform/payment/intent">
              <input type="hidden" name="email" value="{escape(email)}" />
              <input type="hidden" name="order_no" value="{escape(payment.order_no)}" />
              <input type="hidden" name="enrollment_id" value="{payment.enrollment_id}" />
              <input type="hidden" name="payment_method" value="{escape(payment.payment_method)}" />
              <button class="btn" type="submit">建立付款 session</button>
            </form>
          </article>
          <article class="card">
            <h2>重新同步 Stripe 狀態</h2>
            <form class="stack" method="post" action="/school-platform/payment/reconcile">
              <input type="hidden" name="email" value="{escape(email)}" />
              <input type="hidden" name="order_no" value="{escape(payment.order_no)}" />
              <input type="hidden" name="payment_id" value="{payment.id}" />
              <button class="btn alt" type="submit">向 Stripe 重新同步</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>模擬付款狀態更新</h2>
            <form class="stack" method="post" action="/school-platform/payment/update">
              <input type="hidden" name="email" value="{escape(email)}" />
              <input type="hidden" name="order_no" value="{escape(payment.order_no)}" />
              <label class="field">更新狀態
                <select name="payment_status">
                  <option value="paid">paid</option>
                  <option value="failed">failed</option>
                  <option value="refunded">refunded</option>
                </select>
              </label>
              <button class="btn" type="submit">送出 webhook 模擬</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>重新寄送付款提醒</h2>
            <form class="stack" method="post" action="/school-platform/payment/remind">
              <input type="hidden" name="email" value="{escape(email)}" />
              <input type="hidden" name="order_no" value="{escape(payment.order_no)}" />
              <button class="btn" type="submit">寄送付款提醒</button>
            </form>
          </article>
          {reminder_block or "<article class='card'><h3>提醒狀態</h3><p>尚未重新寄送提醒。</p></article>"}
        </div>
      </section>
      <section class="section">
        <h2>相關通知</h2>
        <div class="grid two">{notification_cards}</div>
      </section>
    """
    return _page_shell("付款中心", body)


@router.post("/payment/intent")
def school_platform_payment_intent_submit(
    email: str = Form(...),
    order_no: str = Form(...),
    enrollment_id: str = Form(...),
    payment_method: str = Form(...),
):
    try:
        intent = finance_service.create_payment_intent(
            PaymentIntentCreate(
                enrollment_id=UUID(enrollment_id),
                payment_method=payment_method,
            )
        )
    except RuntimeError as exc:
        query = urlencode({"email": email, "order_no": order_no, "payment_error": str(exc)})
        return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)
    if intent.checkout_url and intent.provider != "mock":
        return RedirectResponse(url=intent.checkout_url, status_code=status.HTTP_303_SEE_OTHER)
    query = urlencode({"email": email, "order_no": order_no, "client_token": intent.client_token})
    return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/payment/reconcile")
def school_platform_payment_reconcile_submit(
    email: str = Form(...),
    order_no: str = Form(...),
    payment_id: str = Form(...),
):
    try:
        result = finance_service.reconcile_payment(UUID(payment_id))
    except RuntimeError as exc:
        query = urlencode({"email": email, "order_no": order_no, "reconcile_result": "error", "reconcile_message": str(exc)})
        return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Payment not found") from exc
    message = result.get("reason") or (
        "Stripe 狀態已同步，付款狀態有更新。"
        if result.get("status_changed")
        else "Stripe 狀態已同步，目前付款狀態沒有變化。"
    )
    query = urlencode({"email": email, "order_no": order_no, "reconcile_result": "success", "reconcile_message": str(message)})
    return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/payment/update")
def school_platform_payment_update_submit(
    email: str = Form(...),
    order_no: str = Form(...),
    payment_status: str = Form(...),
):
    finance_service.apply_payment_webhook(PaymentWebhookPayload(order_no=order_no, status=payment_status))
    query = urlencode({"email": email, "order_no": order_no})
    return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/payment/remind")
def school_platform_payment_remind_submit(
    email: str = Form(...),
    order_no: str = Form(...),
):
    student_support_service.send_payment_reminder(email, order_no)
    query = urlencode({"email": email, "order_no": order_no, "reminder_sent": "1"})
    return RedirectResponse(url=f"/school-platform/payment?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/student-portal", response_class=HTMLResponse)
def school_platform_student_portal_page(email: str = Query(...)) -> str:
    try:
        dashboard = student_portal_service.student_dashboard(email)
        classes = student_portal_service.student_classes(email)
        materials = student_portal_service.student_materials(email)
        payments = student_portal_service.student_payments(email)
        notifications = student_portal_service.student_notifications(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    classes = sorted(classes, key=lambda item: (item.start_date, item.start_time, item.name))
    materials = sorted(materials, key=lambda item: (item.owner_type != "platform", item.title.lower()))
    notifications = sorted(notifications, key=lambda item: item.created_at, reverse=True)
    pending_payment_count = sum(1 for item in payments if item.status != "paid")
    paid_payment_count = sum(1 for item in payments if item.status == "paid")
    unread_notification_count = sum(1 for item in notifications if item.status != "read")
    platform_material_count = sum(1 for item in materials if item.owner_type == "platform")
    teacher_material_count = sum(1 for item in materials if item.owner_type == "teacher")
    next_class = classes[0] if classes else None
    student_level = dashboard.student.japanese_level or "程度待建立"
    study_goal = dashboard.student.study_goal or "以日本生活日語與實戰溝通為主要學習方向。"
    learning_nav_cards = _render_portal_nav_cards(
        [
            {
                "kicker": "Schedule",
                "title": "我的課表",
                "note": "先看下一堂課、時間、地點與目前綁定班級。",
                "href": f"/school-platform/my-schedule?email={escape(email)}",
            },
            {
                "kicker": "Assignments",
                "title": "作業中心",
                "note": "檢查待提交作業、提交內容與老師回饋。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
            {
                "kicker": "Exams",
                "title": "測驗中心",
                "note": "查看待提交測驗、成績與各題練習成果。",
                "href": f"/school-platform/my-exams?email={escape(email)}",
            },
            {
                "kicker": "Materials",
                "title": "教材中心",
                "note": "集中查看平台講義、班級補充教材與可下載檔案。",
                "href": f"/school-platform/my-materials?email={escape(email)}",
            },
            {
                "kicker": "Progress",
                "title": "學習進度",
                "note": "把作業、測驗、出缺勤與風險整合成一個面板。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "AI Practice",
                "title": "AI 練習區",
                "note": "依主題快速生成生活情境對話與口說練習。",
                "href": f"/school-platform/ai-practice?email={escape(email)}",
            },
            {
                "kicker": "Support",
                "title": "通知與客服",
                "note": "查看訊息、付款提醒、課程通知與客服需求。",
                "href": f"/school-platform/notifications-center?email={escape(email)}",
            },
        ]
    )
    learning_tasks: list[dict[str, str]] = []
    if next_class is not None:
        learning_tasks.append(
            {
                "index": "01",
                "title": f"先確認下一堂 {next_class.name}",
                "note": f"{next_class.weekday} {next_class.start_time.strftime('%H:%M')} 開始，地點在 {next_class.location_label}，先把時間留出來。",
            }
        )
    if pending_payment_count:
        learning_tasks.append(
            {
                "index": "02",
                "title": f"還有 {pending_payment_count} 筆付款待處理",
                "note": "建議先打開付款中心確認目前訂單狀態，避免影響後續分班與通知。",
            }
        )
    if unread_notification_count:
        learning_tasks.append(
            {
                "index": "03",
                "title": f"有 {unread_notification_count} 則通知還沒處理",
                "note": "先確認開課提醒、作業通知或客服回覆，避免漏掉班級更新。",
            }
        )
    if len(learning_tasks) < 3:
        learning_tasks.append(
            {
                "index": f"0{len(learning_tasks) + 1}",
                "title": "安排一段 AI 練習時間",
                "note": "如果今天沒有急件，建議先用 AI 練習區複習生活會話，維持連續輸入與輸出。",
            }
        )
    class_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.course_slug)} / {escape(item.weekday)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.location_label)} / {escape(item.start_time.strftime('%H:%M'))}-{escape(item.end_time.strftime('%H:%M'))}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.start_date.isoformat())}</span><span class='chip'>{escape(item.teacher_name)}</span><span class='chip'>{item.enrolled_count}/{item.capacity}</span></div>"
        f"<div class='actions'><a class='btn alt' href='/school-platform/my-schedule?email={escape(email)}'>查看課表</a></div>"
        "</article>"
        for item in classes
    ) or "<article class='card'><h3>目前沒有課程</h3><p>這位學員目前沒有綁定班級。</p></article>"
    material_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.owner_type)} / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, email=email, label='開啟教材')}"
        f"{_material_source_html(item)}"
        f"<div class='meta'><span class='chip'>{escape(item.course_slug)}</span><span class='chip'>{escape(item.created_by)}</span></div>"
        "</article>"
        for item in materials[:6]
    ) or "<article class='card'><h3>目前沒有教材</h3><p>這位學員目前還沒有可查看的教材資料。</p></article>"
    payment_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.payment_method)} / {escape(item.provider or 'internal')}</div>"
        f"<h3>{escape(item.order_no)}</h3>"
        f"<p>付款方式：{escape(item.payment_method)} / 金額：{_format_jpy(item.amount)}</p>"
        f"<p class='status-{'paid' if item.status == 'paid' else 'pending'}'>狀態：{escape(item.status)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.currency or 'JPY')}</span><span class='chip'>{escape(item.provider_status or item.status)}</span></div>"
        "</article>"
        for item in payments
    ) or "<article class='card'><h3>尚無付款資料</h3></article>"
    notification_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.channel)} / {escape(item.type)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        "</article>"
        for item in notifications[:6]
    ) or "<article class='card'><h3>尚無通知</h3></article>"
    payment_action = (
        f"<a class='btn alt' href='/school-platform/payment?email={escape(email)}&order_no={escape(payments[0].order_no)}'>付款中心</a>"
        if payments
        else ""
    )
    pulse_points = [
        ("進行中課程", str(len(dashboard.active_courses))),
        ("教材總數", str(len(materials))),
        ("已完成付款", str(paid_payment_count)),
        ("待處理付款", str(pending_payment_count)),
        ("通知與提醒", str(dashboard.notification_count)),
        (
            "下一堂課",
            f"{next_class.weekday} {next_class.start_time.strftime('%H:%M')}" if next_class else "尚未排課",
        ),
    ]
    pulse_point_html = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in pulse_points
    )
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Student Portal</div>
            <h1>學員中心總覽</h1>
            <p>這裡不是只有資料列表，而是把學員今天最需要處理的課程、作業、測驗、AI 練習、付款與通知集中成同一個學習工作台。</p>
            <div class="meta">
              <span class="chip">{escape(dashboard.student.chinese_name)}</span>
              <span class="chip">{escape(dashboard.student.email)}</span>
              <span class="chip">{escape(dashboard.student.status)}</span>
              <span class="chip">{escape(student_level)}</span>
              {_risk_pill("medium" if pending_payment_count or unread_notification_count else "low", "目前節奏")}
            </div>
            <div class="note-card">
              <strong>目前學習目標</strong>
              <p>{escape(study_goal)}</p>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/my-schedule?email={escape(email)}">我的課表</a>
              <a class="btn alt" href="/school-platform/my-materials?email={escape(email)}">教材中心</a>
              <a class="btn alt" href="/school-platform/my-progress?email={escape(email)}">學習進度</a>
              <a class="btn alt" href="/school-platform/ai-practice?email={escape(email)}">AI 練習區</a>
              {payment_action}
              <a class="btn alt" href="/school-platform/help-center?email={escape(email)}">客服需求</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Learning Pulse</div>
            <h2>這週先把節奏抓穩</h2>
            <div class="data-points">{pulse_point_html}</div>
            <div class="task-list">{_render_task_items(learning_tasks[:3])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Learning Workspace</div>
            <h2>學習工作台捷徑</h2>
          </div>
          <p class="section-subtitle">如果你今天不是要看全部資料，而是想直接開始做事，先從這些入口進去最快。</p>
        </div>
        <div class="portal-nav-grid">{learning_nav_cards}</div>
      </section>
      <section class="section">
        <h2>學員摘要</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">進行中課程</div><div class="value">{len(dashboard.active_courses)}</div></div>
          <div class="stat"><div class="label">教材總數</div><div class="value">{len(materials)}</div></div>
          <div class="stat"><div class="label">平台教材</div><div class="value">{platform_material_count}</div></div>
          <div class="stat"><div class="label">教師補充</div><div class="value">{teacher_material_count}</div></div>
          <div class="stat"><div class="label">付款紀錄</div><div class="value">{len(payments)}</div></div>
          <div class="stat"><div class="label">待付款</div><div class="value">{pending_payment_count}</div></div>
          <div class="stat"><div class="label">通知數量</div><div class="value">{dashboard.notification_count}</div></div>
          <div class="stat"><div class="label">未讀通知</div><div class="value">{unread_notification_count}</div></div>
          <div class="stat"><div class="label">已完成付款</div><div class="value">{paid_payment_count}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">My Classes</div>
            <h2>我的課程</h2>
          </div>
          <p class="section-subtitle">把目前綁定班級、授課老師、地點與時間整理在一起，方便快速確認上課節奏。</p>
        </div>
        <div class="grid two">{class_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Materials</div>
            <h2>我的教材</h2>
          </div>
          <p class="section-subtitle">平台標準講義與老師針對你所在班級補充的教材，現在都可以從同一區直接打開。</p>
        </div>
        <div class="grid two">{material_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Payments</div>
            <h2>我的付款</h2>
          </div>
          <p class="section-subtitle">付款中心除了看狀態，也能對照目前訂單、幣別與 provider 狀態，避免漏掉待付款訂單。</p>
        </div>
        <div class="grid two">{payment_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Notifications</div>
            <h2>最新通知</h2>
          </div>
          <p class="section-subtitle">開課提醒、付款提醒、客服回覆與班級通知都會先在這裡彙整。</p>
        </div>
        <div class="grid two">{notification_cards}</div>
      </section>
    """
    return _page_shell("學員中心", body)


@router.get("/ai-practice", response_class=HTMLResponse)
def school_platform_ai_practice_page(
    email: str = Query(...),
    theme: str = Query(default="藥局與購物生活會話"),
) -> str:
    try:
        student = student_portal_service.get_student_by_email(email)
        practice = ai_assistant_service.practice_conversation(email, theme)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    goal_items = "".join(f"<li>{escape(item)}</li>" for item in practice.goals)
    phrase_items = "".join(f"<li>{escape(item)}</li>" for item in practice.key_phrases)
    hint_items = "".join(f"<li>{escape(item)}</li>" for item in practice.hints)
    review_items = "".join(f"<li>{escape(item)}</li>" for item in practice.review_checklist)
    practice_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Portal",
                "title": "回學員中心",
                "note": "回到學員工作台，接著安排作業、測驗或課表。",
                "href": f"/school-platform/student-portal?email={escape(email)}",
            },
            {
                "kicker": "Progress",
                "title": "看學習進度",
                "note": "把本次 AI 練習和整體作業、測驗、出勤放在一起看。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "Assignments",
                "title": "作業中心",
                "note": "練習完可以直接回作業中心，把今天的輸出補齊。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
        ]
    )
    practice_steps = "".join(
        (
            "<article class='journey-card'>"
            f"<span class='journey-step'>Step 0{index}</span>"
            f"<h3 class='journey-title'>{escape(title)}</h3>"
            f"<p class='journey-note'>{escape(note)}</p>"
            "</article>"
        )
        for index, (title, note) in enumerate(
            [
                ("先讀情境設定", "先理解這次要練的是什麼情境、目標和 AI 開場，不要急著直接回答。"),
                ("開口做一次完整回答", "照著關鍵句型先說一版，再用自己的詞彙微調成更自然的表達。"),
                ("照自我檢查回看", "最後用 checklist 檢查敬語、關鍵詞與句型有沒有完整出現。"),
            ],
            start=1,
        )
    )
    practice_points = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("學員", practice.student_name),
            ("等級", practice.level),
            ("主題", theme),
            ("情境標題", practice.scenario_title),
        ]
    )
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">AI Practice Zone</div>
            <h1>AI 練習區</h1>
            <p>這裡會依照學員程度與主題，快速生成一段可直接開口練習的日語情境對話草稿，讓你不用想很久就能立刻開始說。</p>
            <div class="meta">
              <span class="chip">{escape(practice.student_name)}</span>
              <span class="chip">{escape(practice.student_email)}</span>
              <span class="chip">{escape(practice.level)}</span>
              <span class="chip">{escape(theme)}</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/api/student/ai-practice?email={escape(email)}&theme={escape(theme)}">查看練習 JSON</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Scenario Pulse</div>
            <h2>先把這次情境說順</h2>
            <div class="data-points">{practice_points}</div>
            <div class="note-card">
              <strong>AI 開場</strong>
              <p>{escape(practice.ai_opening)}</p>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Practice Workflow</div>
            <h2>練習順序</h2>
          </div>
          <p class="section-subtitle">先理解情境，再開口練，再做自我檢查，這樣學習效果會比直接看答案更穩。</p>
        </div>
        <div class="journey-grid">{practice_steps}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Quick Routes</div>
            <h2>學習捷徑</h2>
          </div>
          <p class="section-subtitle">如果你練完想立刻切去其他學習頁，這幾個入口最快。</p>
        </div>
        <div class="portal-nav-grid">{practice_nav}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>重新生成主題</h2>
            <form class="stack" method="get" action="/school-platform/ai-practice">
              <input type="hidden" name="email" value="{escape(email)}" />
              <label class="field">主題
                <input type="text" name="theme" value="{escape(theme)}" />
              </label>
              <button class="btn" type="submit">更新練習主題</button>
            </form>
          </article>
          <article class="card">
            <h2>情境摘要</h2>
            <p>標題：{escape(practice.scenario_title)}</p>
            <p>情境：{escape(practice.situation)}</p>
            <p>AI 開場：{escape(practice.ai_opening)}</p>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>本次練習目標</h2>
            <ul class="clean">{goal_items}</ul>
          </article>
          <article class="card">
            <h2>關鍵句型</h2>
            <ul class="clean">{phrase_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>練習提示</h2>
            <ul class="clean">{hint_items}</ul>
          </article>
          <article class="card">
            <h2>自我檢查</h2>
            <ul class="clean">{review_items}</ul>
          </article>
        </div>
      </section>
    """
    return _page_shell("AI 練習區", body)


@router.get("/my-progress", response_class=HTMLResponse)
def school_platform_student_progress_page(email: str = Query(...)) -> str:
    try:
        snapshot = teaching_ops_service.student_progress(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    assignment_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.class_name)} / {escape(item.status)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>截止時間：{escape(item.due_at.isoformat())}</p>"
        + (
            f"<p><code>分數：{item.score:g} / 評語：{escape(item.feedback or '待補')}</code></p>"
            if item.score is not None
            else "<p><code>目前尚未評分</code></p>"
        )
        + "</article>"
        for item in snapshot.assignments[:6]
    ) or "<article class='card'><h3>目前沒有作業紀錄</h3></article>"
    exam_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.class_name)} / {escape(item.exam_type)} / {escape(item.status)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>總分：{item.total_score:g} / 截止時間：{escape(item.due_at.isoformat())}</p>"
        + (
            f"<p><code>分數：{item.score:g} / 評語：{escape(item.feedback or '待補')}</code></p>"
            if item.score is not None
            else "<p><code>目前尚未評分</code></p>"
        )
        + "</article>"
        for item in snapshot.exams[:6]
    ) or "<article class='card'><h3>目前沒有測驗紀錄</h3></article>"
    attendance_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.class_name)}</div>"
        f"<h3>{escape(item.status)}</h3>"
        f"<p>上課日期：{escape(item.class_date.isoformat())}</p>"
        f"<p>{escape(item.note or '無備註')}</p>"
        "</article>"
        for item in snapshot.attendance[:6]
    ) or "<article class='card'><h3>目前沒有出缺勤紀錄</h3></article>"
    score_block = f"{snapshot.summary.overall_score:g}" if snapshot.summary.overall_score is not None else "N/A"
    assignment_avg_block = f"{snapshot.summary.assignment_average:g}" if snapshot.summary.assignment_average is not None else "N/A"
    exam_avg_block = f"{snapshot.summary.exam_average:g}" if snapshot.summary.exam_average is not None else "N/A"
    pending_assignment_count = snapshot.summary.assignment_total - snapshot.summary.assignment_submitted
    pending_exam_count = snapshot.summary.exam_total - snapshot.summary.exam_submitted
    progress_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Assignments",
                "title": "補作業",
                "note": "直接去作業中心處理還沒提交或還沒看回饋的項目。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
            {
                "kicker": "Exams",
                "title": "補測驗",
                "note": "把待提交測驗、成績與老師評語整理在同一區。",
                "href": f"/school-platform/my-exams?email={escape(email)}",
            },
            {
                "kicker": "Attendance",
                "title": "看出缺勤",
                "note": "如果風險來自出席率，先看點名紀錄最直接。",
                "href": f"/school-platform/my-attendance?email={escape(email)}",
            },
            {
                "kicker": "AI Practice",
                "title": "做 AI 練習",
                "note": "如果今天沒有急件，先做一輪口說練習維持輸出。",
                "href": f"/school-platform/ai-practice?email={escape(email)}",
            },
        ]
    )
    progress_tasks = [
        {
            "index": "01",
            "title": f"先處理 {max(pending_assignment_count, 0)} 筆待補作業",
            "note": "作業是最直接反映持續學習的區塊，先補齊通常最有幫助。",
        },
        {
            "index": "02",
            "title": f"再看 {max(pending_exam_count, 0)} 筆待補測驗",
            "note": "測驗結果會直接影響整體評估，建議和作業一起補完。",
        },
        {
            "index": "03",
            "title": "依照系統建議調整節奏",
            "note": snapshot.summary.recommended_action,
        },
    ]
    progress_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("學員", snapshot.student.chinese_name),
            ("學習風險", {"low": "低風險", "medium": "中風險", "high": "高風險"}.get(snapshot.summary.risk_level, snapshot.summary.risk_level)),
            ("主要弱點", snapshot.summary.weak_spot),
            ("整體評估", score_block),
            ("出席率", f"{snapshot.summary.attendance_rate:g}%"),
        ]
    )
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Learning Progress</div>
            <h1>學習進度中心</h1>
            <p>這裡把作業、測驗、出缺勤與目前風險整合成一個學員可直接看的學習面板，讓你知道下一步應該先補哪裡。</p>
            <div class="meta">
              <span class="chip">{escape(snapshot.student.chinese_name)}</span>
              <span class="chip">{escape(snapshot.student.email)}</span>
              {_risk_pill(snapshot.summary.risk_level, "學習狀態")}
              <span class="chip">弱點：{escape(snapshot.summary.weak_spot)}</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-assignments?email={escape(email)}">作業中心</a>
              <a class="btn alt" href="/school-platform/my-exams?email={escape(email)}">測驗中心</a>
              <a class="btn alt" href="/school-platform/my-attendance?email={escape(email)}">出缺勤</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Progress Pulse</div>
            <h2>先補最會拉低節奏的地方</h2>
            <div class="data-points">{progress_pulse}</div>
            <div class="task-list">{_render_task_items(progress_tasks)}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Recovery Routes</div>
            <h2>補強捷徑</h2>
          </div>
          <p class="section-subtitle">如果你現在知道自己卡住在哪，就直接從對應頁面補齊，不用繞一圈再找。</p>
        </div>
        <div class="portal-nav-grid">{progress_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">整體學習評估</div><div class="value">{score_block}</div></div>
          <div class="stat"><div class="label">作業平均</div><div class="value">{assignment_avg_block}</div></div>
          <div class="stat"><div class="label">測驗平均</div><div class="value">{exam_avg_block}</div></div>
          <div class="stat"><div class="label">出席率</div><div class="value">{snapshot.summary.attendance_rate:g}%</div></div>
          <div class="stat"><div class="label">待補作業</div><div class="value">{snapshot.summary.assignment_total - snapshot.summary.assignment_submitted}</div></div>
          <div class="stat"><div class="label">待補測驗</div><div class="value">{snapshot.summary.exam_total - snapshot.summary.exam_submitted}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">System Guidance</div>
            <h2>系統建議</h2>
          </div>
          <p class="section-subtitle">這段建議是把目前風險、出席、作業與測驗狀態綜合後得出的下一步。</p>
        </div>
        <article class="focus-card">
          <h3>目前最建議的行動</h3>
          <p>{escape(snapshot.summary.recommended_action)}</p>
        </article>
      </section>
      <section class="section">
        <h2>作業進度</h2>
        <div class="grid two">{assignment_cards}</div>
      </section>
      <section class="section">
        <h2>測驗進度</h2>
        <div class="grid two">{exam_cards}</div>
      </section>
      <section class="section">
        <h2>最近出缺勤</h2>
        <div class="grid two">{attendance_cards}</div>
      </section>
    """
    return _page_shell("學習進度中心", body)


@router.get("/my-materials", response_class=HTMLResponse)
def school_platform_student_materials_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    materials = student_portal_service.student_materials(email)
    platform_count = sum(1 for item in materials if item.owner_type == "platform")
    teacher_count = sum(1 for item in materials if item.owner_type == "teacher")
    uploaded_count = sum(1 for item in materials if item.storage_kind == "uploaded_file")
    materials_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Portal",
                "title": "回學員中心",
                "note": "回到學員工作台，接著安排課表、作業或通知。",
                "href": f"/school-platform/student-portal?email={escape(email)}",
            },
            {
                "kicker": "Progress",
                "title": "學習進度",
                "note": "看完教材後，如果要安排今天先補哪塊，直接回進度中心。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "Assignments",
                "title": "作業中心",
                "note": "教材讀完後，可以直接回作業區完成輸出。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
            {
                "kicker": "Notifications",
                "title": "通知中心",
                "note": "如果教材有補發、更新或調整提醒，通知中心會先看到。",
                "href": f"/school-platform/notifications-center?email={escape(email)}",
            },
        ]
    )
    material_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.course_slug)} / {escape(item.owner_type)} / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, email=email, label='下載或開啟教材')}"
        f"{_material_source_html(item)}"
        f"<div class='meta'><span class='chip'>{escape(item.created_by)}</span><span class='chip'>{escape(item.storage_kind)}</span></div>"
        "</article>"
        for item in materials
    ) or "<article class='card'><h3>目前沒有教材</h3><p>等班級建立講義或平台教材後，這裡會自動出現可查看資源。</p></article>"
    material_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("教材總數", str(len(materials))),
            ("平台教材", str(platform_count)),
            ("教師補充", str(teacher_count)),
            ("可下載檔案", str(uploaded_count)),
        ]
    )
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Materials Center</div>
            <h1>教材中心</h1>
            <p>這裡把平台標準教材與老師針對班級補充的內容集中在一起，讓學員不用再從通知、課後訊息或外部連結到處找講義。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              <span class="chip">教材 {len(materials)}</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-progress?email={escape(email)}">學習進度</a>
              <a class="btn alt" href="/school-platform/my-assignments?email={escape(email)}">作業中心</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Materials Pulse</div>
            <h2>先把今天會用到的教材抓出來</h2>
            <div class="data-points">{material_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":"先看平台核心教材","note":"這些通常是本課程最穩定的標準資源，適合先建立主軸。"},{"index":"02","title":"再看老師補充內容","note":"如果這週老師有補新的情境講義，通常會更貼近目前班級的卡點。"},{"index":"03","title":"教材讀完就回作業或測驗","note":"把輸入和輸出接在一起，學習節奏會比只收講義更穩。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Materials Routes</div>
            <h2>教材相關捷徑</h2>
          </div>
          <p class="section-subtitle">看完教材後，常常會接著去補進度、寫作業或確認通知，這些入口先幫你排在前面。</p>
        </div>
        <div class="portal-nav-grid">{materials_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">教材總數</div><div class="value">{len(materials)}</div></div>
          <div class="stat"><div class="label">平台教材</div><div class="value">{platform_count}</div></div>
          <div class="stat"><div class="label">教師補充</div><div class="value">{teacher_count}</div></div>
          <div class="stat"><div class="label">可下載檔案</div><div class="value">{uploaded_count}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{material_cards}</div>
      </section>
    """
    return _page_shell("教材中心", body)


@router.get("/my-assignments", response_class=HTMLResponse)
def school_platform_student_assignments_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    assignments = teaching_ops_service.student_assignments(email)
    summary = teaching_ops_service.assignment_submission_summary(email)
    submissions = {item.assignment_id: item for item in teaching_ops_service.student_assignment_submissions(email)}
    assignment_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Progress",
                "title": "回學習進度",
                "note": "先看整體風險，再決定今天要優先補哪幾份作業。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "Exams",
                "title": "測驗中心",
                "note": "如果作業補完了，就接著處理測驗與口說稿。",
                "href": f"/school-platform/my-exams?email={escape(email)}",
            },
            {
                "kicker": "AI Practice",
                "title": "AI 練習區",
                "note": "先練一輪，再回來寫作業通常會更順手。",
                "href": f"/school-platform/ai-practice?email={escape(email)}",
            },
        ]
    )
    assignment_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("作業總數", str(summary["total"])),
            ("已提交", str(summary["submitted"])),
            ("待提交", str(summary["pending"])),
            ("學員", student.chinese_name),
        ]
    )
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.due_at.isoformat())}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<div class='meta'><span class='chip'>{'已提交' if item.id in submissions else '待提交'}</span></div>"
            + (
                f"<p><code>提交時間：{escape(submissions[item.id].submitted_at.isoformat())}</code></p>"
                if item.id in submissions
                else (
                    f"<form class='stack' method='post' action='/school-platform/my-assignments/{item.id}/submit'>"
                    f"<input type='hidden' name='email' value='{escape(email)}' />"
                    "<label class='field'>作業內容"
                    "<textarea name='content' placeholder='輸入你的作業內容'></textarea>"
                    "</label>"
                    "<button class='btn' type='submit'>提交作業</button>"
                    "</form>"
                )
            )
            + "</article>"
        )
        for item in assignments
    ) or "<article class='card'><h3>目前沒有作業</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Assignments Center</div>
            <h1>作業中心</h1>
            <p>這裡集中顯示學員目前的作業、截止時間與提交狀態，讓你能很快知道哪些作業要先補、哪些已經在等老師回饋。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              {_risk_pill("medium" if summary["pending"] else "low", "作業節奏")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-attendance?email={escape(email)}">出缺勤</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Assignments Pulse</div>
            <h2>先把待提交的清乾淨</h2>
            <div class="data-points">{assignment_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":f"今天先補 {summary['pending']} 份作業","note":"如果今天時間有限，先把最接近截止時間的作業處理掉。"},{"index":"02","title":"已提交的回頭看評語","note":"如果老師已回饋，可以順手把常犯問題記下來。"},{"index":"03","title":"作業卡住就去 AI 練習","note":"先練一輪口說或句型，再回來寫通常更容易完成。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Assignment Routes</div>
            <h2>作業相關捷徑</h2>
          </div>
          <p class="section-subtitle">如果你今天要接著補測驗、看總進度或先做 AI 練習，這裡可以直接跳轉。</p>
        </div>
        <div class="portal-nav-grid">{assignment_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">作業總數</div><div class="value">{summary['total']}</div></div>
          <div class="stat"><div class="label">已提交</div><div class="value">{summary['submitted']}</div></div>
          <div class="stat"><div class="label">待提交</div><div class="value">{summary['pending']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("作業中心", body)


@router.post("/my-assignments/{assignment_id}/submit")
def school_platform_assignment_submit(
    assignment_id: UUID,
    email: str = Form(...),
    content: str = Form(...),
):
    try:
        teaching_ops_service.submit_assignment(assignment_id, AssignmentSubmissionCreateRequest(email=email, content=content))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assignment or student not found") from exc
    query = urlencode({"email": email})
    return RedirectResponse(url=f"/school-platform/my-assignments?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/my-exams", response_class=HTMLResponse)
def school_platform_student_exams_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    exams = teaching_ops_service.student_exams(email)
    summary = teaching_ops_service.exam_submission_summary(email)
    submissions = {item.exam_id: item for item in teaching_ops_service.student_exam_submissions(email)}
    exam_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Progress",
                "title": "回學習進度",
                "note": "先看整體評估，再決定今天要優先補哪一份測驗。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "Assignments",
                "title": "作業中心",
                "note": "如果測驗補完了，就切回作業區把學習節奏接起來。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
            {
                "kicker": "AI Practice",
                "title": "AI 練習區",
                "note": "測驗前先做主題口說練習，常常能更快進入狀態。",
                "href": f"/school-platform/ai-practice?email={escape(email)}",
            },
        ]
    )
    exam_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("測驗總數", str(summary["total"])),
            ("已提交", str(summary["submitted"])),
            ("待提交", str(summary["pending"])),
            ("學員", student.chinese_name),
        ]
    )
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.exam_type)} / {escape(item.due_at.isoformat())}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.instructions)}</p>"
            f"<div class='meta'><span class='chip'>總分 {item.total_score:g}</span><span class='chip'>{'已提交' if item.id in submissions else '待提交'}</span></div>"
            + (
                f"<p><code>提交時間：{escape(submissions[item.id].submitted_at.isoformat())}</code></p>"
                + (
                    f"<p><code>分數：{submissions[item.id].score:g} / 評語：{escape(submissions[item.id].feedback or '待補')}</code></p>"
                    if submissions[item.id].score is not None
                    else ""
                )
                if item.id in submissions
                else (
                    f"<form class='stack' method='post' action='/school-platform/my-exams/{item.id}/submit'>"
                    f"<input type='hidden' name='email' value='{escape(email)}' />"
                    "<label class='field'>測驗答案"
                    "<textarea name='content' placeholder='輸入你的測驗答案或口說稿'></textarea>"
                    "</label>"
                    "<button class='btn' type='submit'>提交測驗</button>"
                    "</form>"
                )
            )
            + "</article>"
        )
        for item in exams
    ) or "<article class='card'><h3>目前沒有測驗</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Exams Center</div>
            <h1>測驗中心</h1>
            <p>這裡集中顯示學員目前的測驗、截止時間、提交狀態與老師評分結果，讓你知道哪些測驗還沒交、哪些已經有成績。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              {_risk_pill("medium" if summary["pending"] else "low", "測驗節奏")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-assignments?email={escape(email)}">作業中心</a>
              <a class="btn alt" href="/school-platform/my-attendance?email={escape(email)}">出缺勤</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Exam Pulse</div>
            <h2>先把待提交測驗處理掉</h2>
            <div class="data-points">{exam_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":f"今天要補 {summary['pending']} 份測驗","note":"測驗常常直接影響整體評估，建議先完成最接近截止時間的那一份。"},{"index":"02","title":"有評語就回頭看一次","note":"如果老師已經批改，建議把容易出錯的句型重新寫一遍。"},{"index":"03","title":"口說卡住就先用 AI 練習","note":"先把情境講順，再回來提交測驗內容，通常會更快。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Exam Routes</div>
            <h2>測驗相關捷徑</h2>
          </div>
          <p class="section-subtitle">如果你今天還要補作業、看總進度或先做口說練習，這裡可以快速切換。</p>
        </div>
        <div class="portal-nav-grid">{exam_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">測驗總數</div><div class="value">{summary['total']}</div></div>
          <div class="stat"><div class="label">已提交</div><div class="value">{summary['submitted']}</div></div>
          <div class="stat"><div class="label">待提交</div><div class="value">{summary['pending']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("測驗中心", body)


@router.post("/my-exams/{exam_id}/submit")
def school_platform_exam_submit(
    exam_id: UUID,
    email: str = Form(...),
    content: str = Form(...),
):
    try:
        teaching_ops_service.submit_exam(exam_id, ExamSubmissionCreateRequest(email=email, content=content))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exam or student not found") from exc
    query = urlencode({"email": email})
    return RedirectResponse(url=f"/school-platform/my-exams?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/my-attendance", response_class=HTMLResponse)
def school_platform_student_attendance_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    records = teaching_ops_service.student_attendance(email)
    summary = teaching_ops_service.attendance_summary(email)
    attendance_rate = (summary["present"] / summary["total"] * 100) if summary["total"] else 0
    attendance_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Progress",
                "title": "回學習進度",
                "note": "如果出席率正在拖累整體評估，先回總面板確認影響程度。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
            {
                "kicker": "Assignments",
                "title": "作業中心",
                "note": "出席率確認完後，可以回作業區把補交節奏接上。",
                "href": f"/school-platform/my-assignments?email={escape(email)}",
            },
            {
                "kicker": "Support",
                "title": "通知中心",
                "note": "如果有請假或補課安排，記得同步看通知和客服回覆。",
                "href": f"/school-platform/notifications-center?email={escape(email)}",
            },
        ]
    )
    attendance_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("總紀錄", str(summary["total"])),
            ("出席率", f"{attendance_rate:.0f}%"),
            ("缺席", str(summary["absent"])),
            ("遲到", str(summary["late"])),
            ("請假", str(summary["leave"])),
        ]
    )
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.class_date.isoformat())}</div>"
        f"<h3>{escape(item.status)}</h3>"
        f"<p>{escape(item.note or '無備註')}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.marked_by)}</span></div>"
        "</article>"
        for item in records
    ) or "<article class='card'><h3>目前沒有出缺勤紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Attendance Center</div>
            <h1>出缺勤</h1>
            <p>這裡顯示學員目前的點名紀錄，讓你能快速確認出席狀態，並知道風險是不是來自上課節奏不穩。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              {_risk_pill("high" if attendance_rate < 70 and summary["total"] else "medium" if attendance_rate < 85 and summary["total"] else "low", "出席狀態")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-assignments?email={escape(email)}">作業中心</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Attendance Pulse</div>
            <h2>把出席節奏看清楚</h2>
            <div class="data-points">{attendance_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":"先看最近幾次點名","note":"如果最近連續 late 或 absent，建議先確認是不是固定時段有問題。"},{"index":"02","title":"出席不穩就回看通知","note":"補課、調課與課程提醒通常會先出現在通知中心。"},{"index":"03","title":"把出席率和作業一起看","note":"很多時候出席不穩也會連動作業延遲，建議一起檢查。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Attendance Routes</div>
            <h2>出席相關捷徑</h2>
          </div>
          <p class="section-subtitle">如果你看完點名後想直接回總進度、補作業或確認通知，這裡可以快速切換。</p>
        </div>
        <div class="portal-nav-grid">{attendance_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">總紀錄</div><div class="value">{summary['total']}</div></div>
          <div class="stat"><div class="label">出席</div><div class="value">{summary['present']}</div></div>
          <div class="stat"><div class="label">缺席</div><div class="value">{summary['absent']}</div></div>
          <div class="stat"><div class="label">遲到</div><div class="value">{summary['late']}</div></div>
          <div class="stat"><div class="label">請假</div><div class="value">{summary['leave']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("出缺勤", body)


@router.get("/my-history", response_class=HTMLResponse)
def school_platform_student_history_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    history = student_portal_service.student_history(email)
    counts = {
        "enrollment": sum(1 for item in history if item.kind == "enrollment"),
        "payment": sum(1 for item in history if item.kind == "payment"),
        "notification": sum(1 for item in history if item.kind == "notification"),
    }
    history_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Portal",
                "title": "回學員中心",
                "note": "回到學員工作台，從今天要處理的任務繼續往下做。",
                "href": f"/school-platform/student-portal?email={escape(email)}",
            },
            {
                "kicker": "Notifications",
                "title": "通知中心",
                "note": "如果想從歷程回到實際訊息內容，通知中心會更直接。",
                "href": f"/school-platform/notifications-center?email={escape(email)}",
            },
            {
                "kicker": "Schedule",
                "title": "我的課表",
                "note": "回看歷程之後，如果想確認現在的上課安排，可以直接切去課表。",
                "href": f"/school-platform/my-schedule?email={escape(email)}",
            },
        ]
    )
    history_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("歷程總數", str(len(history))),
            ("報名事件", str(counts["enrollment"])),
            ("付款事件", str(counts["payment"])),
            ("通知事件", str(counts["notification"])),
        ]
    )
    badge_map = {"enrollment": "報名", "payment": "付款", "notification": "通知"}
    timeline_html = "".join(
        "<article class='timeline-item'>"
        f"<div class='timeline-badge'>{escape(badge_map.get(item.kind, item.kind)[:2])}</div>"
        "<div class='timeline-card'>"
        f"<div class='eyebrow'>{escape(item.kind)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.detail)}</p>"
        f"<div class='timeline-meta'><span class='chip'>{escape(item.at.isoformat())}</span></div>"
        "</div>"
        "</article>"
        for item in history
    ) or "<article class='card'><h3>尚無歷程</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Student History</div>
            <h1>我的歷程</h1>
            <p>這裡會把報名、付款、通知等重要事件整理成時間線，方便學員回看自己從報名到現在的整條軌跡。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              <span class="chip">歷程 {len(history)} 筆</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/notifications-center?email={escape(email)}">通知中心</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">History Pulse</div>
            <h2>從事件時間線看自己走到哪裡</h2>
            <div class="data-points">{history_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":"先看最近三筆事件","note":"先掌握最近發生了什麼，再決定要不要回通知或課表處理。"},{"index":"02","title":"付款與報名要一起對照","note":"如果想確認狀態是否一致，付款事件和報名事件最值得一起看。"},{"index":"03","title":"有疑問就回通知中心","note":"歷程是摘要；如果要看完整內容，通知中心會更直接。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">History Routes</div>
            <h2>歷程相關捷徑</h2>
          </div>
          <p class="section-subtitle">看完時間線後，如果你要回通知、課表或學員中心，不需要再往上找入口。</p>
        </div>
        <div class="portal-nav-grid">{history_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">歷程總數</div><div class="value">{len(history)}</div></div>
          <div class="stat"><div class="label">報名事件</div><div class="value">{counts['enrollment']}</div></div>
          <div class="stat"><div class="label">付款事件</div><div class="value">{counts['payment']}</div></div>
          <div class="stat"><div class="label">通知事件</div><div class="value">{counts['notification']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Timeline</div>
            <h2>事件時間線</h2>
          </div>
          <p class="section-subtitle">所有重要事件都依時間倒序排列，方便你從最近的事件一路回看。</p>
        </div>
        <div class="timeline-list">{timeline_html}</div>
      </section>
    """
    return _page_shell("我的歷程", body)


@router.get("/help-center", response_class=HTMLResponse)
def school_platform_help_center_page(email: str = Query(...)) -> str:
    student = student_portal_service.get_student_by_email(email)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    notifications = student_portal_service.student_notifications(email)[:4]
    recent_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.channel)}</span><span class='chip'>{escape(item.status)}</span></div>"
        "</article>"
        for item in notifications
    ) or "<article class='card'><h3>尚無通知紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Help Center</div>
        <h1>客服需求中心</h1>
        <p>學員可以在這裡提交需求，系統會自動建立內部通知並回送確認通知。</p>
        <div class="meta">
          <span class="chip">{escape(student.chinese_name)}</span>
          <span class="chip">{escape(student.email)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
          <a class="btn alt" href="/school-platform/notifications-center?email={escape(email)}">通知中心</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>提交需求</h2>
            <form class="stack" method="post" action="/school-platform/help-center/submit">
              <input type="hidden" name="email" value="{escape(email)}" />
              <label class="field">主題
                <select name="topic">
                  <option value="排課問題">排課問題</option>
                  <option value="付款問題">付款問題</option>
                  <option value="請假需求">請假需求</option>
                  <option value="教材需求">教材需求</option>
                </select>
              </label>
              <label class="field">偏好聯絡方式
                <select name="preferred_channel">
                  <option value="email">email</option>
                  <option value="line">line</option>
                  <option value="in_app">in_app</option>
                </select>
              </label>
              <label class="field">需求內容
                <textarea name="message" placeholder="輸入你的需求或想請客服協助的內容"></textarea>
              </label>
              <button class="btn" type="submit">送出客服需求</button>
            </form>
          </article>
          <article class="card">
            <h2>最近通知</h2>
            <div class="list">{recent_cards}</div>
          </article>
        </div>
      </section>
    """
    return _page_shell("客服需求中心", body)


@router.post("/help-center/submit")
def school_platform_help_center_submit(
    email: str = Form(...),
    topic: str = Form(...),
    preferred_channel: str = Form(default="email"),
    message: str = Form(...),
):
    result = student_support_service.create_support_request(email, topic, message, preferred_channel)
    query = urlencode(
        {
            "email": email,
            "request_id": str(result["request"].id),
            "topic": topic,
        }
    )
    return RedirectResponse(url=f"/school-platform/help-center/success?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/help-center/success", response_class=HTMLResponse)
def school_platform_help_center_success_page(
    email: str = Query(...),
    request_id: str = Query(...),
    topic: str = Query(...),
) -> str:
    body = f"""
      <section class="hero">
        <div class="eyebrow">Support Request Sent</div>
        <h1>客服需求已送出</h1>
        <p>系統已建立內部通知並回送確認給學員，後續可在通知中心查看。</p>
        <div class="meta">
          <span class="chip">{escape(email)}</span>
          <span class="chip">request_id: {escape(request_id)}</span>
          <span class="chip">主題：{escape(topic)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/notifications-center?email={escape(email)}">查看通知中心</a>
          <a class="btn alt" href="/school-platform/help-center?email={escape(email)}">再送一筆需求</a>
        </div>
      </section>
    """
    return _page_shell("客服需求已送出", body)


@router.get("/my-schedule", response_class=HTMLResponse)
def school_platform_student_schedule_page(email: str = Query(...)) -> str:
    try:
        student = student_portal_service.get_student_by_email(email)
        schedule = student_portal_service.student_schedule(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    next_class = schedule[0] if schedule else None
    teacher_count = len({item.teacher_name for item in schedule})
    location_count = len({item.location_label for item in schedule})
    schedule_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Portal",
                "title": "回學員中心",
                "note": "回到學員工作台，接著查看作業、通知或付款。",
                "href": f"/school-platform/student-portal?email={escape(email)}",
            },
            {
                "kicker": "Notifications",
                "title": "通知中心",
                "note": "如果最近有調課、提醒或補課資訊，先去通知中心確認。",
                "href": f"/school-platform/notifications-center?email={escape(email)}",
            },
            {
                "kicker": "History",
                "title": "我的歷程",
                "note": "想回看報名、付款與通知事件時，從這裡最快。",
                "href": f"/school-platform/my-history?email={escape(email)}",
            },
            {
                "kicker": "Progress",
                "title": "學習進度",
                "note": "確認課表後，如果要安排今天學習節奏，可以直接回進度中心。",
                "href": f"/school-platform/my-progress?email={escape(email)}",
            },
        ]
    )
    schedule_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("班級數", str(len(schedule))),
            ("授課老師", str(teacher_count)),
            ("上課地點", str(location_count)),
            (
                "下一堂課",
                f"{next_class.weekday} {next_class.start_time.strftime('%H:%M')}" if next_class else "尚未排課",
            ),
        ]
    )
    cards = "".join(
        "<article class='schedule-card'>"
        f"<div class='eyebrow'>{escape(item.course_slug)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p class='schedule-line'>日期：{escape(item.start_date.isoformat())} 至 {escape(item.end_date.isoformat())}</p>"
        f"<p class='schedule-line'>時間：{escape(item.weekday)} / {escape(item.start_time.strftime('%H:%M'))}-{escape(item.end_time.strftime('%H:%M'))}</p>"
        f"<div class='schedule-meta'><span class='chip'>{escape(item.location_label)}</span><span class='chip'>{escape(item.teacher_name)}</span><span class='chip'>{item.enrolled_count}/{item.capacity}</span></div>"
        "</article>"
        for item in schedule
    ) or "<article class='card'><h3>目前沒有排課</h3><p>這位學員還沒有綁定任何班級。</p></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Student Schedule</div>
            <h1>我的課表</h1>
            <p>這頁集中顯示學員目前已綁定的班級與上課時段，讓你先把本週要去的課、時間、老師與地點一次看清楚。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              {_risk_pill("medium" if not schedule else "low", "排課狀態")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/notifications-center?email={escape(email)}">通知中心</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Schedule Pulse</div>
            <h2>先確認最近要上的課</h2>
            <div class="data-points">{schedule_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":"先確認下一堂課時間","note":"把最近一堂課的時間和地點先確認好，避免遺漏或遲到。"},{"index":"02","title":"看通知是否有調課資訊","note":"如果最近有改課、補課或連結更新，通常會先在通知中心看到。"},{"index":"03","title":"排課確認後回學習進度","note":"課表穩定後，再安排今天要補的作業、測驗或 AI 練習。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Schedule Routes</div>
            <h2>課表相關捷徑</h2>
          </div>
          <p class="section-subtitle">看完課表後，如果你要立刻切去通知、歷程或總進度，這裡不用再回上一頁找。</p>
        </div>
        <div class="portal-nav-grid">{schedule_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">班級數</div><div class="value">{len(schedule)}</div></div>
          <div class="stat"><div class="label">授課老師</div><div class="value">{teacher_count}</div></div>
          <div class="stat"><div class="label">上課地點</div><div class="value">{location_count}</div></div>
          <div class="stat"><div class="label">下一堂課</div><div class="value">{escape(next_class.start_time.strftime('%H:%M')) if next_class else 'N/A'}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Class Schedule</div>
            <h2>目前排課</h2>
          </div>
          <p class="section-subtitle">這裡把每個班級的週期、時間、老師與地點完整列出來，方便直接對照你的實際上課節奏。</p>
        </div>
        <div class="schedule-board">{cards}</div>
      </section>
    """
    return _page_shell("我的課表", body)


@router.get("/notifications-center", response_class=HTMLResponse)
def school_platform_notifications_center_page(email: str = Query(...)) -> str:
    try:
        student = student_portal_service.get_student_by_email(email)
        notifications = student_portal_service.student_notifications(email)
        summary = student_portal_service.student_notification_summary(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    notifications = sorted(notifications, key=lambda item: item.created_at, reverse=True)
    unread_count = sum(1 for item in notifications if item.status != "read")
    read_count = sum(1 for item in notifications if item.status == "read")
    failed_count = sum(1 for item in notifications if item.status == "failed")
    sent_count = sum(1 for item in notifications if item.status == "sent")
    notifications_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Schedule",
                "title": "我的課表",
                "note": "如果通知牽涉調課或開課提醒，先切回課表確認影響。",
                "href": f"/school-platform/my-schedule?email={escape(email)}",
            },
            {
                "kicker": "History",
                "title": "我的歷程",
                "note": "想回看整條事件時間線時，可以從歷程頁接著看。",
                "href": f"/school-platform/my-history?email={escape(email)}",
            },
            {
                "kicker": "Support",
                "title": "客服需求",
                "note": "如果通知內容需要回覆或處理，直接切去客服需求中心。",
                "href": f"/school-platform/help-center?email={escape(email)}",
            },
        ]
    )
    notification_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("通知總數", str(summary["total"])),
            ("未讀", str(unread_count)),
            ("已讀", str(read_count)),
            ("待發送", str(summary["queued"])),
            ("已送達", str(sent_count)),
        ]
    )
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.type)} / {escape(item.channel)}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
            + (
                f"<form class='stack' method='post' action='/school-platform/notifications-center/{item.id}/read'>"
                f"<input type='hidden' name='email' value='{escape(email)}' />"
                "<button class='btn alt' type='submit'>標記已讀</button>"
                "</form>"
                if item.status != "read"
                else "<p><code>已讀</code></p>"
            )
            + "</article>"
        )
        for item in notifications
    ) or "<article class='card'><h3>尚無通知</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Notifications Center</div>
            <h1>通知中心</h1>
            <p>這頁整理學員收到的報名、付款、開課與系統通知，讓你從學員端集中查看哪些訊息已處理、哪些還需要你動作。</p>
            <div class="meta">
              <span class="chip">{escape(student.chinese_name)}</span>
              <span class="chip">{escape(student.email)}</span>
              {_risk_pill("medium" if unread_count or summary["queued"] else "low", "通知節奏")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/student-portal?email={escape(email)}">回學員中心</a>
              <a class="btn alt" href="/school-platform/my-schedule?email={escape(email)}">我的課表</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Notifications Pulse</div>
            <h2>先把未讀與待處理訊息清掉</h2>
            <div class="data-points">{notification_pulse}</div>
            <div class="task-list">{_render_task_items([{"index":"01","title":f"先處理 {unread_count} 則未讀通知","note":"先看開課、付款與調課相關通知，通常最會影響接下來的安排。"},{"index":"02","title":f"再看 {summary['queued']} 則待發送提醒","note":"如果還有 queued 訊息，代表有些提醒正在等待送出或同步。"},{"index":"03","title":"需要回覆就切去客服需求","note":"如果通知內容需要你確認或追問，直接在客服需求中心接著處理。"}])}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Notification Routes</div>
            <h2>通知相關捷徑</h2>
          </div>
          <p class="section-subtitle">通知看完後，常常會接著要確認課表、回看歷程或提交客服需求，這裡可以直接切換。</p>
        </div>
        <div class="portal-nav-grid">{notifications_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">通知總數</div><div class="value">{summary['total']}</div></div>
          <div class="stat"><div class="label">待發送</div><div class="value">{summary['queued']}</div></div>
          <div class="stat"><div class="label">Email 通知</div><div class="value">{summary['email']}</div></div>
          <div class="stat"><div class="label">LINE 通知</div><div class="value">{summary['line']}</div></div>
          <div class="stat"><div class="label">站內通知</div><div class="value">{summary['in_app']}</div></div>
          <div class="stat"><div class="label">已讀</div><div class="value">{read_count}</div></div>
          <div class="stat"><div class="label">失敗</div><div class="value">{failed_count}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">All Notifications</div>
            <h2>全部通知</h2>
          </div>
          <p class="section-subtitle">這裡會把你收到的通知依時間倒序排好，未讀訊息可以直接在卡片上標記已讀。</p>
        </div>
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("通知中心", body)


@router.post("/notifications-center/{notification_id}/read")
def school_platform_notification_mark_read_submit(
    notification_id: UUID,
    email: str = Form(...),
):
    try:
        student_support_service.mark_notification_read(email, notification_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc
    query = urlencode({"email": email})
    return RedirectResponse(url=f"/school-platform/notifications-center?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin", response_class=HTMLResponse)
def school_platform_admin_preview_page() -> str:
    metrics = admissions_service.dashboard_metrics()
    module_tiles = "".join(
        [
            "<a class='feature-tile' href='/school-platform/franchise-vap'><span class='tile-kicker'>Franchise Growth</span><strong>加盟招商 VAP</strong><p>首頁級招商敘事、AI-aging 模式、AI Edge 優勢與十區加盟條件集中展示。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/leads'><span class='tile-kicker'>招生營運</span><strong>招生名單</strong><p>查看名單狀態、顧問分配、跟進節奏與試聽轉換。</p></a>",
            "<a class='feature-tile' href='/school-platform/consultant-portal?staff_name=Mika%20Chen'><span class='tile-kicker'>顧問桌面</span><strong>顧問工作台</strong><p>用顧問視角處理 hot leads、follow-up queue 與 AI 話術草稿。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/students'><span class='tile-kicker'>學員 CRM</span><strong>學員管理</strong><p>把學員、付款、通知、歷程與學習風險集中查看。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/subaccounts'><span class='tile-kicker'>Account Ops</span><strong>子帳號中心</strong><p>讓主帳號可以開多個子帳號，分配區域、角色與登入權限。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/finance'><span class='tile-kicker'>財務營運</span><strong>財務中心</strong><p>看報名、付款、待收款與退款，並串進 Stripe readiness。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/teaching'><span class='tile-kicker'>教務協同</span><strong>教務管理</strong><p>管理作業、測驗、點名與教師課後紀錄審核。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/messages'><span class='tile-kicker'>訊息協作</span><strong>訊息中心</strong><p>集中 Email、LINE、站內通知、重送與單筆 retry。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/recruiting'><span class='tile-kicker'>人才招募</span><strong>招聘管理</strong><p>職缺、應徵者、面試與錄用建議都在這裡持續落成。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/reports'><span class='tile-kicker'>經營分析</span><strong>報表中心</strong><p>查看營收、轉換、教務與主管週報的彙整輸出。</p></a>",
            "<a class='feature-tile' href='/school-platform/admin/ai-center'><span class='tile-kicker'>AI 中控</span><strong>AI 助理中心</strong><p>查看 AI 教案、follow-up、學習練習與 provider 狀態。</p></a>",
        ]
    )
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">營運總覽</div>
            <h1>營運後台總覽</h1>
            <p>這裡不再只是很多管理按鈕，而是把加盟招商、招生、學員、財務、教務、客服、AI 與招聘分成可直接操作的控制台。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/franchise-vap">打開加盟招商 VAP</a>
              <a class="btn alt" href="/school-platform/admin/reports/franchise">加盟組報表</a>
              <a class="btn" href="/school-platform/admin/leads">前往招生名單</a>
              <a class="btn alt" href="/school-platform/admin/subaccounts">管理子帳號</a>
              <a class="btn alt" href="/school-platform/admin/executive">打開主管工作台</a>
              <a class="btn alt" href="/school-platform/admin/support-inbox">查看客服收件箱</a>
            </div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">今日 / 本週</div>
            <h2>主管第一眼要看的營運摘要</h2>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>今日新名單</span><strong>{metrics.today_new_leads}</strong></div>
              <div class="mini-kpi"><span>本週試聽</span><strong>{metrics.this_week_trial_bookings}</strong></div>
              <div class="mini-kpi"><span>本週報名</span><strong>{metrics.this_week_enrollments}</strong></div>
              <div class="mini-kpi"><span>已收營收</span><strong>{_format_jpy(metrics.paid_revenue_total)}</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>今日與本週重點</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">今日新名單</div><div class="value">{metrics.today_new_leads}</div></div>
          <div class="stat"><div class="label">本週試聽</div><div class="value">{metrics.this_week_trial_bookings}</div></div>
          <div class="stat"><div class="label">本週報名</div><div class="value">{metrics.this_week_enrollments}</div></div>
          <div class="stat"><div class="label">已收營收</div><div class="value">{_format_jpy(metrics.paid_revenue_total)}</div></div>
          <div class="stat"><div class="label">待跟進</div><div class="value">{metrics.pending_follow_ups}</div></div>
          <div class="stat"><div class="label">開放班級</div><div class="value">{metrics.active_classes}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>控制台分區</h2>
        <p>把你最常切換的模組整理成卡片式控制台，視覺上會比一整排按鈕更接近正式產品。</p>
        <div class="feature-grid">{module_tiles}</div>
      </section>
    """
    return _page_shell("營運後台總覽", body)


@router.get("/admin/teaching", response_class=HTMLResponse)
def school_platform_admin_teaching_page() -> str:
    classes = catalog_service.open_classes()
    assignments = teaching_ops_service.list_assignments()
    exams = teaching_ops_service.list_exams()
    session_records = teaching_ops_service.list_teaching_session_records()
    pending_session_records = [item for item in session_records if item.approval_status == "submitted"]
    class_options = "".join(
        f"<option value='{item.id}'>{escape(item.name)} / {escape(item.course_slug)}</option>"
        for item in classes
    )
    assignment_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.created_by)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.due_at.isoformat())}</span></div>"
        "</article>"
        for item in assignments[:6]
    ) or "<article class='card'><h3>目前沒有作業</h3></article>"
    exam_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.exam_type)} / {escape(item.created_by)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.instructions)}</p>"
        f"<div class='meta'><span class='chip'>總分 {item.total_score:g}</span><span class='chip'>{escape(item.due_at.isoformat())}</span></div>"
        "</article>"
        for item in exams[:6]
    ) or "<article class='card'><h3>目前沒有測驗</h3></article>"
    pending_session_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.teacher_name)} / {escape(item.class_date.isoformat())}</div>"
        f"<h3>{escape(next((class_item.name for class_item in classes if class_item.id == item.class_id), '未知班級'))}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<p>作業：{escape(item.homework_summary or '尚未填寫')}</p>"
        f"<p>高風險學員：{escape(' / '.join(item.student_risk_notes) or '無')}</p>"
        f"<form class='stack' method='post' action='/school-platform/admin/teaching/session-records/{item.id}/review'>"
        "<label class='field'>審核結果"
        "<select name='approval_status_value'>"
        "<option value='approved'>approved</option>"
        "<option value='revision_requested'>revision_requested</option>"
        "</select>"
        "</label>"
        "<label class='field'>主管回覆<textarea name='review_note' placeholder='例如：請補上弱勢學員追蹤與教材連結'></textarea></label>"
        "<label class='field'>審核者<input type='text' name='reviewed_by' value='Yuki Wang' /></label>"
        "<button class='btn' type='submit'>送出審核</button>"
        "</form>"
        "</article>"
        for item in pending_session_records[:6]
    ) or "<article class='card'><h3>目前沒有待審核課後紀錄</h3></article>"
    session_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.approval_status)} / {escape(item.class_date.isoformat())}</div>"
        f"<h3>{escape(next((class_item.name for class_item in classes if class_item.id == item.class_id), '未知班級'))}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<p>主管回覆：{escape(item.review_note or '尚未回覆')}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.teacher_name)}</span><span class='chip'>{escape(item.reviewed_by or '待審核')}</span></div>"
        "</article>"
        for item in session_records[:6]
    ) or "<article class='card'><h3>目前沒有課後紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Teaching Ops</div>
        <h1>教務管理</h1>
        <p>這裡先把作業、測驗、評分、出缺勤點名與教師課後紀錄審核做成後台可操作頁。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/assignments">查看作業 JSON</a>
          <a class="btn alt" href="/school-platform/api/exams">查看測驗 JSON</a>
          <a class="btn alt" href="/school-platform/admin/student-progress">查看學習進度</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>發布作業</h2>
            <form class="stack" method="post" action="/school-platform/admin/teaching/assignments/create">
              <label class="field">班級
                <select name="class_id">{class_options}</select>
              </label>
              <label class="field">作業標題
                <input type="text" name="title" />
              </label>
              <label class="field">作業內容
                <textarea name="content"></textarea>
              </label>
              <label class="field">截止時間
                <input type="datetime-local" name="due_at" />
              </label>
              <label class="field">發布者
                <input type="text" name="created_by" value="Yuki Wang" />
              </label>
              <button class="btn" type="submit">建立作業</button>
            </form>
          </article>
          <article class="card">
            <h2>建立測驗</h2>
            <form class="stack" method="post" action="/school-platform/admin/teaching/exams/create">
              <label class="field">班級
                <select name="class_id">{class_options}</select>
              </label>
              <label class="field">測驗標題
                <input type="text" name="title" />
              </label>
              <label class="field">測驗類型
                <select name="exam_type">
                  <option value="quiz">quiz</option>
                  <option value="speaking_quiz">speaking_quiz</option>
                  <option value="mock_interview">mock_interview</option>
                </select>
              </label>
              <label class="field">說明
                <textarea name="instructions"></textarea>
              </label>
              <label class="field">總分
                <input type="number" step="1" name="total_score" value="100" />
              </label>
              <label class="field">截止時間
                <input type="datetime-local" name="due_at" />
              </label>
              <label class="field">建立者
                <input type="text" name="created_by" value="Aki Mori" />
              </label>
              <button class="btn" type="submit">建立測驗</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>點名</h2>
            <form class="stack" method="post" action="/school-platform/admin/teaching/attendance/mark">
              <label class="field">班級
                <select name="class_id">{class_options}</select>
              </label>
              <label class="field">學生 Email
                <input type="email" name="student_email" />
              </label>
              <label class="field">上課日期
                <input type="date" name="class_date" />
              </label>
              <label class="field">狀態
                <select name="status_value">
                  <option value="present">present</option>
                  <option value="absent">absent</option>
                  <option value="late">late</option>
                  <option value="leave">leave</option>
                </select>
              </label>
              <label class="field">備註
                <textarea name="note"></textarea>
              </label>
              <label class="field">點名者
                <input type="text" name="marked_by" value="Yuki Wang" />
              </label>
              <button class="btn" type="submit">送出點名</button>
            </form>
          </article>
          <article class="card">
            <h2>教師工作台入口</h2>
            <p>從這裡可以進到教師自己的待評分區，查看哪些作業與測驗還沒批改。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/teacher-portal?teacher_name=Aki%20Mori">打開 Aki Mori 工作台</a>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>最新作業</h2>
        <div class="grid two">{assignment_cards}</div>
      </section>
      <section class="section">
        <h2>最新測驗</h2>
        <div class="grid two">{exam_cards}</div>
      </section>
      <section class="section">
        <h2>待審核課後紀錄</h2>
        <div class="grid two">{pending_session_cards}</div>
      </section>
      <section class="section">
        <h2>最近課後紀錄</h2>
        <div class="grid two">{session_cards}</div>
      </section>
    """
    return _page_shell("教務管理", body)


@router.get("/admin/student-progress", response_class=HTMLResponse)
def school_platform_admin_student_progress_page() -> str:
    items = teaching_ops_service.student_progress_overview()
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.risk_level)} / {escape(item.weak_spot)}</div>"
            f"<h3>{escape(item.chinese_name)}</h3>"
            f"<p>{escape(item.email)}</p>"
            f"<div class='meta'><span class='chip'>整體評估 {(f'{item.overall_score:g}' if item.overall_score is not None else 'N/A')}</span><span class='chip'>出席率 {item.attendance_rate:g}%</span></div>"
            f"<div class='meta'><span class='chip'>待補作業 {item.pending_assignments}</span><span class='chip'>待補測驗 {item.pending_exams}</span></div>"
            f"<div class='actions'><a class='btn' href='/school-platform/my-progress?email={escape(item.email)}'>查看學員進度</a></div>"
            "</article>"
        )
        for item in items
    ) or "<article class='card'><h3>目前沒有學員資料</h3></article>"
    high_risk = sum(1 for item in items if item.risk_level == "high")
    medium_risk = sum(1 for item in items if item.risk_level == "medium")
    average_score_items = [item.overall_score for item in items if item.overall_score is not None]
    average_score = f"{(sum(average_score_items) / len(average_score_items)):.1f}" if average_score_items else "N/A"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Learning Progress Admin</div>
        <h1>學習進度總覽</h1>
        <p>這裡讓教務、老師與主管快速看到目前學員的整體進度、缺交風險與出席狀況。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/admin/teaching">回教務管理</a>
          <a class="btn alt" href="/school-platform/api/admin/student-progress">查看進度 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">學員數</div><div class="value">{len(items)}</div></div>
          <div class="stat"><div class="label">高風險</div><div class="value">{high_risk}</div></div>
          <div class="stat"><div class="label">中風險</div><div class="value">{medium_risk}</div></div>
          <div class="stat"><div class="label">平均整體評估</div><div class="value">{average_score}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("學習進度總覽", body)


@router.get("/admin/students", response_class=HTMLResponse)
def school_platform_admin_students_page() -> str:
    snapshot = student_admin_service.overview()
    summary = snapshot.summary
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.student.status)} / {escape(item.student.japanese_level or 'unassigned')}</div>"
            f"<h3>{escape(item.student.chinese_name)}</h3>"
            f"<p>{escape(item.student.email)}</p>"
            f"<div class='meta'><span class='chip'>進行中課程 {item.active_course_count}</span><span class='chip'>報名 {item.enrollment_count}</span><span class='chip'>付款 {item.payment_count}</span></div>"
            f"<div class='meta'><span class='chip'>待付款 {item.pending_payment_count}</span><span class='chip'>通知 {item.notification_count}</span><span class='chip'>待處理 {item.queued_notification_count}</span></div>"
            f"<div class='actions'><a class='btn' href='/school-platform/admin/students/detail?{urlencode({'email': item.student.email})}'>查看學員檔案</a><a class='btn alt' href='/school-platform/my-progress?{urlencode({'email': item.student.email})}'>查看學員進度</a></div>"
            "</article>"
        )
        for item in snapshot.items
    ) or "<article class='card'><h3>目前沒有學員資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Student Admin</div>
        <h1>學員管理</h1>
        <p>這裡把學員名單、付款狀態、通知與最近活動整合成營運後台可直接查閱的工作頁。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/admin/students">查看學員 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">學員總數</div><div class="value">{summary.total_students}</div></div>
          <div class="stat"><div class="label">進行中學員</div><div class="value">{summary.active_students}</div></div>
          <div class="stat"><div class="label">待付款學員</div><div class="value">{summary.pending_payment_students}</div></div>
          <div class="stat"><div class="label">待處理通知</div><div class="value">{summary.queued_notification_students}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>學員名單</h2>
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("學員管理", body)


@router.get("/admin/students/detail", response_class=HTMLResponse)
def school_platform_admin_student_detail_page(email: str = Query(...)) -> str:
    try:
        snapshot = student_admin_service.detail(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    item = snapshot.item
    class_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(class_item.course_slug)} / {escape(class_item.teacher_name)}</div>"
            f"<h3>{escape(class_item.name)}</h3>"
            f"<p>{escape(class_item.weekday)} {escape(class_item.start_time.strftime('%H:%M'))}-{escape(class_item.end_time.strftime('%H:%M'))}</p>"
            f"<div class='meta'><span class='chip'>{escape(class_item.location_label)}</span><span class='chip'>{escape(class_item.status)}</span></div>"
            "</article>"
        )
        for class_item in snapshot.classes
    ) or "<article class='card'><h3>目前沒有進行中課程</h3></article>"
    payment_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(payment.status)} / {escape(payment.payment_method)}</div>"
            f"<h3>{escape(payment.order_no)}</h3>"
            f"<p>金額 {_format_jpy(payment.amount)}</p>"
            f"<div class='meta'><span class='chip'>{escape((payment.paid_at or payment.created_at).isoformat())}</span></div>"
            "</article>"
        )
        for payment in snapshot.payments[:6]
    ) or "<article class='card'><h3>目前沒有付款紀錄</h3></article>"
    history_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(event.kind)}</div>"
            f"<h3>{escape(event.title)}</h3>"
            f"<p>{escape(event.detail)}</p>"
            f"<div class='meta'><span class='chip'>{escape(event.at.isoformat())}</span></div>"
            "</article>"
        )
        for event in snapshot.history[:8]
    ) or "<article class='card'><h3>尚無歷程</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Student Profile</div>
        <h1>學員檔案</h1>
        <p>可直接查看學員的課程、付款、通知與最近歷程，讓顧問、客服與主管共用同一份學員視圖。</p>
        <div class="meta">
          <span class="chip">{escape(item.student.chinese_name)}</span>
          <span class="chip">{escape(item.student.email)}</span>
          <span class="chip">{escape(item.student.japanese_level or 'unassigned')}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/students">回學員管理</a>
          <a class="btn alt" href="/school-platform/admin/messages">前往訊息中心</a>
          <a class="btn alt" href="/school-platform/api/admin/students/detail?{urlencode({'email': item.student.email})}">查看學員詳情 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">報名數</div><div class="value">{item.enrollment_count}</div></div>
          <div class="stat"><div class="label">進行中課程</div><div class="value">{item.active_course_count}</div></div>
          <div class="stat"><div class="label">付款數</div><div class="value">{item.payment_count}</div></div>
          <div class="stat"><div class="label">通知數</div><div class="value">{item.notification_count}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>目前課程</h2>
        <div class="grid two">{class_cards}</div>
      </section>
      <section class="section">
        <h2>最近付款</h2>
        <div class="grid two">{payment_cards}</div>
      </section>
      <section class="section">
        <h2>最近歷程</h2>
        <div class="grid two">{history_cards}</div>
      </section>
    """
    return _page_shell("學員檔案", body)


@router.get("/admin/staff", response_class=HTMLResponse)
def school_platform_admin_staff_page() -> str:
    overview = staff_ops_service.performance_overview()
    summary = overview["summary"]
    items = overview["items"]
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.role)} / {escape(item.department)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.title)}</p>"
        f"<div class='meta'><span class='chip'>指派名單 {item.assigned_leads}</span><span class='chip'>成交 {item.enrolled_leads}</span><span class='chip'>待跟進 {item.pending_follow_ups}</span></div>"
        f"<div class='meta'><span class='chip'>授課班級 {item.active_classes}</span><span class='chip'>作業 {item.assignments_created}</span><span class='chip'>測驗 {item.exams_created}</span><span class='chip'>待評分 {item.pending_reviews}</span></div>"
        + (
            f"<div class='actions'><a class='btn' href='/school-platform/teacher-portal?teacher_name={escape(item.name)}'>查看教師工作台</a></div>"
            if item.role == "teacher"
            else (
                f"<div class='actions'><a class='btn' href='/school-platform/consultant-portal?staff_name={escape(item.name)}'>查看顧問工作台</a></div>"
                if item.role == "consultant"
                else ""
            )
        )
        + "</article>"
        for item in items
    ) or "<article class='card'><h3>目前沒有員工資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Staff Performance</div>
        <h1>員工績效中心</h1>
        <p>這裡把招生顧問、教師與主管目前的工作量與待處理事項整合成主管可以直接看的管理頁。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/admin/staff-performance">查看績效 JSON</a>
          <a class="btn alt" href="/school-platform/admin/teachers">查看教師管理</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">員工總數</div><div class="value">{summary.total_staff}</div></div>
          <div class="stat"><div class="label">招生顧問</div><div class="value">{summary.consultants}</div></div>
          <div class="stat"><div class="label">教師</div><div class="value">{summary.teachers}</div></div>
          <div class="stat"><div class="label">主管</div><div class="value">{summary.managers}</div></div>
          <div class="stat"><div class="label">待跟進總數</div><div class="value">{summary.pending_follow_ups}</div></div>
          <div class="stat"><div class="label">待評分總數</div><div class="value">{summary.pending_reviews}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("員工績效中心", body)


@router.get("/admin/subaccounts", response_class=HTMLResponse)
def school_platform_admin_subaccounts_page(created: str | None = Query(default=None)) -> str:
    snapshot = account_admin_service.directory()
    summary = snapshot.summary
    owner_options = "".join(
        f"<option value='{item.id}'>{escape(item.name)} / {escape(item.email)}</option>"
        for item in snapshot.owners
    )
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{'子帳號' if item.account_type == 'sub_account' else '主帳號'} / {escape(item.role)}</div>"
            f"<h3>{escape(item.name)}</h3>"
            f"<p>登入 Email：{escape(item.email)}</p>"
            + (
                f"<p>隸屬主帳號：{escape(item.parent_user_name or '未指定')}</p>"
                if item.account_type == "sub_account"
                else "<p>這是可以建立多個子帳號的主帳號。</p>"
            )
            + (
                f"<p>區域 / 用途：{escape(item.scope_label)}</p>"
                if item.scope_label
                else ""
            )
            + (
                f"<p>{escape(item.note)}</p>"
                if item.note
                else ""
            )
            + (
                "<div class='meta'>"
                f"<span class='chip'>{escape(item.status)}</span>"
                f"<span class='chip'>權限 {escape(' / '.join(item.permissions) if item.permissions else 'default')}</span>"
                "</div>"
            )
            + "</article>"
        )
        for item in snapshot.items
    ) or "<article class='card'><h3>目前沒有帳號資料</h3></article>"
    created_banner = (
        f"<article class='card'><strong>子帳號已建立：</strong> {escape(created)}</article>"
        if created
        else ""
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Subaccount Center</div>
        <h1>子帳號中心</h1>
        <p>這裡可以讓主帳號開設多個子帳號，分配不同角色、區域與工作用途。之後要給加盟主、區域經理、助理或教師使用，都能走同一套登入結構。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/subaccounts">查看子帳號 JSON</a>
          <a class="btn alt" href="/school-platform/admin/staff">查看員工績效中心</a>
        </div>
      </section>
      {created_banner}
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">帳號總數</div><div class="value">{summary.total_accounts}</div></div>
          <div class="stat"><div class="label">主帳號</div><div class="value">{summary.primary_accounts}</div></div>
          <div class="stat"><div class="label">子帳號</div><div class="value">{summary.sub_accounts}</div></div>
          <div class="stat"><div class="label">啟用中</div><div class="value">{summary.active_accounts}</div></div>
          <div class="stat"><div class="label">停用</div><div class="value">{summary.inactive_accounts}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>建立新子帳號</h2>
            <form class="stack" method="post" action="/school-platform/admin/subaccounts/create">
              <label class="field">主帳號
                <select name="owner_user_id">{owner_options}</select>
              </label>
              <label class="field">姓名
                <input name="name" placeholder="例如：Osaka Zone 01 Assistant" required />
              </label>
              <label class="field">登入 Email
                <input type="email" name="email" placeholder="zone01@example.com" required />
              </label>
              <label class="field">初始密碼
                <input type="text" name="password" placeholder="temp123456" required />
              </label>
              <label class="field">角色
                <select name="role">
                  <option value="consultant">consultant</option>
                  <option value="teacher">teacher</option>
                  <option value="manager">manager</option>
                </select>
              </label>
              <label class="field">狀態
                <select name="status">
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
              <label class="field">區域 / 用途
                <input name="scope_label" placeholder="例如：大阪第 1 區 / 加盟招商助理" />
              </label>
              <label class="field">自訂權限（留白則套用角色預設，每行一個）
                <textarea name="permissions" placeholder="dashboard:read&#10;leads:read&#10;leads:write"></textarea>
              </label>
              <label class="field">備註
                <textarea name="note" placeholder="可記錄這個子帳號的用途、區域、負責對象。"></textarea>
              </label>
              <button class="btn" type="submit">建立子帳號</button>
            </form>
          </article>
          <article class="card">
            <h2>適用方式</h2>
            <div class="helper-list">
              <div>主帳號可對應加盟主、區域負責人或內部主管。</div>
              <div>子帳號可拆給招生助理、教務協調、客服、教師或地區夥伴。</div>
              <div>每個子帳號都有獨立登入 Email 與密碼，不需要共用同一組帳密。</div>
              <div>如果不填權限，系統會自動套用該角色的預設權限。</div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>目前帳號清單</h2>
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("子帳號中心", body)


@router.post("/admin/subaccounts/create")
def school_platform_admin_subaccounts_create_submit(
    owner_user_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    status_value: str = Form(..., alias="status"),
    scope_label: str = Form(default=""),
    permissions: str = Form(default=""),
    note: str = Form(default=""),
):
    try:
        payload = SubAccountCreateRequest(
            owner_user_id=UUID(owner_user_id),
            name=name,
            email=email,
            password=password,
            role=role,
            permissions=_split_multivalue_text(permissions),
            status=status_value,
            scope_label=scope_label or None,
            note=note or None,
        )
        created = account_admin_service.create_sub_account(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Owner account not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    query = urlencode({"created": created.email})
    return RedirectResponse(url=f"/school-platform/admin/subaccounts?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/consultant-portal", response_class=HTMLResponse)
def school_platform_consultant_portal_page(staff_name: str = Query(default="Mika Chen")) -> str:
    snapshot = consultant_workspace_service.dashboard(staff_name)
    summary = snapshot.summary

    def render_lead_card(item) -> str:
        due_label = item.next_follow_up_at.isoformat() if item.next_follow_up_at else "尚未安排"
        latest_log = escape(item.latest_log_summary or "尚未留下跟進紀錄")
        return (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)} / {escape(item.interested_course_slug or '未指定課程')}</div>"
            f"<h3>{escape(item.name)}</h3>"
            f"<p>{latest_log}</p>"
            f"<div class='meta'><span class='chip'>熱度 {item.intent_score:g}</span><span class='chip'>成交率 {item.win_probability:g}%</span></div>"
            f"<p><code>下次跟進：{escape(due_label)}</code></p>"
            f"<div class='actions'><a class='btn' href='/school-platform/consultant-portal/leads/{item.lead_id}?staff_name={escape(summary.consultant_name)}'>打開案件詳情</a></div>"
            "</article>"
        )

    hot_cards = "".join(render_lead_card(item) for item in snapshot.hot_leads) or "<article class='card'><h3>目前沒有高意向名單</h3></article>"
    queue_cards = "".join(render_lead_card(item) for item in snapshot.follow_up_queue) or "<article class='card'><h3>目前沒有待跟進名單</h3></article>"
    recent_cards = "".join(render_lead_card(item) for item in snapshot.recently_updated) or "<article class='card'><h3>目前沒有最近更新名單</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Consultant Workspace</div>
        <h1>招生顧問工作台</h1>
        <p>這裡把顧問最常用的名單熱度、今日待跟進與最近更新集中成一個工作台，不用一直在 leads 列表來回切換。</p>
        <div class="meta">
          <span class="chip">{escape(summary.consultant_name)}</span>
          <span class="chip">已指派 {summary.assigned_leads}</span>
          <span class="chip">高意向 {summary.high_intent_leads}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/leads">回招生名單</a>
          <a class="btn alt" href="/school-platform/admin/staff">回員工績效中心</a>
          <a class="btn alt" href="/school-platform/api/consultant/dashboard?staff_name={escape(summary.consultant_name)}">查看工作台 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">已指派名單</div><div class="value">{summary.assigned_leads}</div></div>
          <div class="stat"><div class="label">逾期待跟進</div><div class="value">{summary.overdue_follow_ups}</div></div>
          <div class="stat"><div class="label">今日要跟進</div><div class="value">{summary.due_today}</div></div>
          <div class="stat"><div class="label">高意向名單</div><div class="value">{summary.high_intent_leads}</div></div>
          <div class="stat"><div class="label">試聽進行中</div><div class="value">{summary.trial_booked_leads}</div></div>
          <div class="stat"><div class="label">已成交</div><div class="value">{summary.enrolled_leads}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>高意向名單</h2>
        <div class="grid two">{hot_cards}</div>
      </section>
      <section class="section">
        <h2>待跟進隊列</h2>
        <div class="grid two">{queue_cards}</div>
      </section>
      <section class="section">
        <h2>最近更新</h2>
        <div class="grid two">{recent_cards}</div>
      </section>
    """
    return _page_shell("招生顧問工作台", body)


@router.get("/consultant-portal/leads/{lead_id}", response_class=HTMLResponse)
def school_platform_consultant_lead_detail_page(lead_id: UUID, staff_name: str = Query(...)) -> str:
    try:
        snapshot = consultant_workspace_service.lead_detail(staff_name, lead_id)
        snapshot = snapshot.model_copy(update={"followup_draft": ai_assistant_service.followup_draft(lead_id)})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Consultant lead not found") from exc

    lead = snapshot.lead
    draft = snapshot.followup_draft
    log_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.contact_method)}</div>"
        f"<h3>{escape(item.staff_name)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<p>下一步：{escape(item.next_action or '待補')}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        "</article>"
        for item in snapshot.logs
    ) or "<article class='card'><h3>尚無跟進紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Consultant Lead Detail</div>
        <h1>顧問案件詳情</h1>
        <p>這裡集中顯示顧問自己的招生案件、歷次跟進與 AI 話術草稿，方便直接接續下一步。</p>
        <div class="meta">
          <span class="chip">{escape(staff_name)}</span>
          <span class="chip">{escape(lead.name)}</span>
          <span class="chip">{escape(lead.status)}</span>
          <span class="chip">熱度 {lead.intent_score:.0f}</span>
          <span class="chip">成交率 {lead.win_probability:.0f}%</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/consultant-portal?staff_name={escape(staff_name)}">回顧問工作台</a>
          <a class="btn alt" href="/school-platform/api/consultant/leads/{lead.id}?staff_name={escape(staff_name)}">查看案件 JSON</a>
          <a class="btn alt" href="/school-platform/api/ai/leads/{lead.id}/followup-draft">查看 AI 草稿 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>案件摘要</h2>
            <p>Email：{escape(lead.email or '未填寫')}</p>
            <p>電話：{escape(lead.phone or '未填寫')}</p>
            <p>LINE：{escape(lead.line_id or '未綁定')}</p>
            <p>課程意向：{escape(lead.interested_course_slug or '未指定')}</p>
            <p>程度：{escape(lead.japanese_level or '未填寫')}</p>
            <p>目標：{escape(lead.study_goal or '未填寫')}</p>
          </article>
          <article class="card">
            <h2>AI 跟進草稿</h2>
            <p>建議渠道：<code>{escape(draft.recommended_channel if draft else 'n/a')}</code></p>
            <p>建議下一步：{escape(draft.next_step if draft else '尚無')}</p>
            <p>LINE 話術草稿：{escape(draft.line_message if draft else '尚無')}</p>
            <p>Email 主旨：{escape(draft.email_subject if draft else '尚無')}</p>
            <p>Email 內容：{escape(draft.email_message if draft else '尚無')}</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>跟進紀錄</h2>
        <div class="grid two">{log_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>更新狀態</h2>
            <form class="stack" method="post" action="/school-platform/consultant-portal/leads/{lead.id}/status">
              <input type="hidden" name="staff_name" value="{escape(staff_name)}" />
              <label class="field">狀態
                <select name="status_value">
                  <option value="new">new</option>
                  <option value="contacted" {'selected' if lead.status == 'contacted' else ''}>contacted</option>
                  <option value="replied" {'selected' if lead.status == 'replied' else ''}>replied</option>
                  <option value="trial_booked" {'selected' if lead.status == 'trial_booked' else ''}>trial_booked</option>
                  <option value="trial_completed" {'selected' if lead.status == 'trial_completed' else ''}>trial_completed</option>
                  <option value="considering" {'selected' if lead.status == 'considering' else ''}>considering</option>
                  <option value="enrolled" {'selected' if lead.status == 'enrolled' else ''}>enrolled</option>
                  <option value="waitlisted" {'selected' if lead.status == 'waitlisted' else ''}>waitlisted</option>
                  <option value="lost" {'selected' if lead.status == 'lost' else ''}>lost</option>
                  <option value="blacklisted" {'selected' if lead.status == 'blacklisted' else ''}>blacklisted</option>
                </select>
              </label>
              <label class="field">下次跟進時間
                <input type="datetime-local" name="next_follow_up_at" />
              </label>
              <label class="field">備註
                <textarea name="note" placeholder="例如：先發 LINE，明天下午再電話追蹤"></textarea>
              </label>
              <button class="btn" type="submit">送出狀態更新</button>
            </form>
          </article>
          <article class="card">
            <h2>新增跟進</h2>
            <form class="stack" method="post" action="/school-platform/consultant-portal/leads/{lead.id}/logs">
              <input type="hidden" name="staff_name" value="{escape(staff_name)}" />
              <label class="field">聯繫方式
                <select name="contact_method">
                  <option value="line">line</option>
                  <option value="call">call</option>
                  <option value="email">email</option>
                  <option value="system">system</option>
                </select>
              </label>
              <label class="field">紀錄內容
                <textarea name="content" placeholder="輸入這次跟進的內容"></textarea>
              </label>
              <label class="field">下一步
                <input type="text" name="next_action" placeholder="例如：後天再確認是否預約試聽" />
              </label>
              <button class="btn" type="submit">新增跟進紀錄</button>
            </form>
          </article>
        </div>
      </section>
    """
    return _page_shell(f"顧問案件詳情 - {lead.name}", body)


@router.post("/consultant-portal/leads/{lead_id}/status")
def school_platform_consultant_lead_status_submit(
    lead_id: UUID,
    staff_name: str = Form(...),
    status_value: str = Form(...),
    next_follow_up_at: str = Form(default=""),
    note: str = Form(default=""),
):
    next_follow_up = datetime.fromisoformat(next_follow_up_at) if next_follow_up_at else None
    payload = LeadStatusChangeRequest(status=status_value, next_follow_up_at=next_follow_up, note=note or None)
    lead_workflow_service.change_status(lead_id, payload)
    query = urlencode({"staff_name": staff_name})
    return RedirectResponse(url=f"/school-platform/consultant-portal/leads/{lead_id}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/consultant-portal/leads/{lead_id}/logs")
def school_platform_consultant_lead_log_submit(
    lead_id: UUID,
    staff_name: str = Form(...),
    contact_method: str = Form(...),
    content: str = Form(...),
    next_action: str = Form(default=""),
):
    lead_workflow_service.add_log(lead_id, staff_name, contact_method, content, next_action or None)
    query = urlencode({"staff_name": staff_name})
    return RedirectResponse(url=f"/school-platform/consultant-portal/leads/{lead_id}?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/finance", response_class=HTMLResponse)
def school_platform_admin_finance_page() -> str:
    snapshot = finance_service.overview()
    summary = snapshot.summary
    enrollment_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)} / {escape(item.payment_status)}</div>"
            f"<h3>{escape(str(item.id)[:8])}</h3>"
            f"<p>班級 ID：{escape(str(item.class_id))}</p>"
            f"<div class='meta'><span class='chip'>定價 {_format_jpy(item.list_price)}</span><span class='chip'>實收 {_format_jpy(item.paid_amount)}</span></div>"
            f"<p><code>建立時間：{escape(item.created_at.isoformat())}</code></p>"
            "</article>"
        )
        for item in snapshot.recent_enrollments
    ) or "<article class='card'><h3>目前沒有報名資料</h3></article>"
    payment_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)} / {escape(item.payment_method)}</div>"
            f"<h3>{escape(item.order_no)}</h3>"
            f"<p>付款單號：{escape(str(item.id)[:8])}</p>"
            f"<div class='meta'><span class='chip'>{_format_jpy(item.amount)}</span></div>"
            f"<p><code>建立時間：{escape(item.created_at.isoformat())}</code></p>"
            + (f"<p><code>付款時間：{escape(item.paid_at.isoformat())}</code></p>" if item.paid_at else "")
            + "</article>"
        )
        for item in snapshot.recent_payments
    ) or "<article class='card'><h3>目前沒有付款資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Finance Center</div>
        <h1>財務中心</h1>
        <p>這裡把報名、付款、待收款與退款狀態整理成主管可直接看的財務入口。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/finance/overview">查看財務 JSON</a>
          <a class="btn alt" href="/school-platform/payment?email=portal@example.com">查看學員付款中心範例</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">報名總數</div><div class="value">{summary.enrollment_total}</div></div>
          <div class="stat"><div class="label">待確認報名</div><div class="value">{summary.pending_enrollments}</div></div>
          <div class="stat"><div class="label">已付款筆數</div><div class="value">{summary.paid_payments}</div></div>
          <div class="stat"><div class="label">待付款筆數</div><div class="value">{summary.pending_payments}</div></div>
          <div class="stat"><div class="label">已收款</div><div class="value">{_format_jpy(summary.paid_revenue)}</div></div>
          <div class="stat"><div class="label">待收款</div><div class="value">{_format_jpy(summary.pending_revenue)}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>最近報名</h2>
        <div class="grid two">{enrollment_cards}</div>
      </section>
      <section class="section">
        <h2>最近付款</h2>
        <div class="grid two">{payment_cards}</div>
      </section>
    """
    return _page_shell("財務中心", body)


@router.get("/admin/messages", response_class=HTMLResponse)
def school_platform_admin_messages_page() -> str:
    summary = notification_service.summary()
    provider_status = notification_service.provider_status()
    if provider_status["email_ready"] and provider_status["email_provider"] != "mock":
        email_status_note = f"Email 外發已接通，目前使用 {provider_status['email_provider']}。"
    else:
        email_status_note = "Email 外發目前仍在示範模式，尚未切到真實 provider。"
    if provider_status["line_ready"]:
        line_status_note = "LINE 外發憑證已補齊，可直接測試訊息送出。"
    else:
        line_status_note = "LINE 外發尚未接通，目前還缺 Messaging API 憑證。"
    smoke_test_email_note = (
        "若不填 recipient，Email smoke test 會優先使用設定好的測試信箱。"
        if provider_status["notification_test_email_present"]
        else "若不填 recipient，Email smoke test 會退回 user_email。"
    )
    smoke_test_line_note = (
        "若不填 recipient，LINE smoke test 會優先使用設定好的測試 user ID。"
        if provider_status["notification_test_line_user_id_present"] or provider_status["line_fallback_user_id_present"]
        else "LINE smoke test 需要填入 LINE user ID，或先補 fallback user。"
    )
    recent_notifications = admissions_service.list_notifications()[:12]
    notification_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.type)} / {escape(item.channel)}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<p>attempt_count：{item.attempt_count} / last_attempt_at：{escape(item.last_attempt_at.isoformat()) if item.last_attempt_at else '尚未送出'}</p>"
            f"<p>error_message：{escape(item.error_message) if item.error_message else '無'}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.user_email or 'broadcast')}</span>"
            + (
                f"<span class='chip'>{escape(item.external_recipient)}</span>"
                if item.external_recipient
                else ""
            )
            + f"<span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.provider or 'internal')}</span><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
            + (
                f"<form method='post' action='/school-platform/admin/messages/{item.id}/retry'><button class='btn alt' type='submit'>重試這筆通知</button></form>"
                if item.status in {"queued", "failed"}
                else ""
            )
            + "</article>"
        )
        for item in recent_notifications
    ) or "<article class='card'><h3>目前沒有通知紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Message Center</div>
        <h1>訊息中心</h1>
        <p>這裡集中處理站內 / Email / LINE 類型通知，支援單一學員或全體學員廣播，方便行政與客服直接操作。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/messages/overview">查看訊息總覽 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">通知總數</div><div class="value">{summary.total_notifications}</div></div>
          <div class="stat"><div class="label">待送出</div><div class="value">{summary.queued_notifications}</div></div>
          <div class="stat"><div class="label">已送達</div><div class="value">{summary.sent_notifications}</div></div>
          <div class="stat"><div class="label">送達失敗</div><div class="value">{summary.failed_notifications}</div></div>
          <div class="stat"><div class="label">已抑制</div><div class="value">{summary.suppressed_notifications}</div></div>
          <div class="stat"><div class="label">已讀</div><div class="value">{summary.read_notifications}</div></div>
          <div class="stat"><div class="label">Email</div><div class="value">{summary.email_notifications}</div></div>
          <div class="stat"><div class="label">LINE</div><div class="value">{summary.line_notifications}</div></div>
          <div class="stat"><div class="label">站內通知</div><div class="value">{summary.in_app_notifications}</div></div>
          <div class="stat"><div class="label">廣播訊息</div><div class="value">{summary.broadcast_notifications}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>發送訊息</h2>
            <form class="stack" method="post" action="/school-platform/admin/messages/send">
              <label class="field">對象
                <select name="audience">
                  <option value="single_student">單一學員</option>
                  <option value="active_students">進行中學員</option>
                  <option value="all_students">全部學員</option>
                  <option value="staff_admin">管理團隊</option>
                </select>
              </label>
              <label class="field">指定 Email（單一學員時使用）
                <input type="email" name="target_email" placeholder="student@example.com" />
              </label>
              <label class="field">渠道
                <select name="channel">
                  <option value="email">email</option>
                  <option value="in_app">in_app</option>
                  <option value="line">line</option>
                </select>
              </label>
              <label class="field">標題
                <input type="text" name="title" />
              </label>
              <label class="field">內容
                <textarea name="content"></textarea>
              </label>
              <button class="btn" type="submit">發送訊息</button>
            </form>
          </article>
          <article class="card">
            <h2>常用模板</h2>
            <ul class="clean">
              <li>開課提醒：提醒學員確認開課時間、教材與上課連結。</li>
              <li>補課通知：提醒學員因課程異動需重新確認上課安排。</li>
              <li>付款提醒：通知待付款學員在截止日前完成付款。</li>
              <li>試聽提醒：提醒試聽學員在指定時間前準備進入教室或 Zoom。</li>
            </ul>
            <p>{escape(email_status_note)}</p>
            <p>{escape(line_status_note)}</p>
            <p>安全護欄：保留網域如 <code>example.com</code>、<code>*.local</code> 會自動標成 <code>suppressed</code>，不會真的往外寄。</p>
            <p>Email provider：<code>{escape(str(provider_status['email_provider']))}</code></p>
            <p>Email ready：<code>{escape(str(provider_status['email_ready']).lower())}</code></p>
            <p>SMTP host present：<code>{escape(str(provider_status['smtp_host_present']).lower())}</code></p>
            <p>Resend key present：<code>{escape(str(provider_status['resend_api_key_present']).lower())}</code></p>
            <p>LINE ready：<code>{escape(str(provider_status['line_ready']).lower())}</code></p>
            <p>LINE fallback user present：<code>{escape(str(provider_status['line_fallback_user_id_present']).lower())}</code></p>
            <p>demo email guardrail：<code>{escape(str(provider_status['demo_email_guardrail_enabled']).lower())}</code></p>
            <p>setup guide：<a href="/school-platform/system">system 頁</a> / <code>docs/japanese-school-platform/15-gmail-line-setup.md</code></p>
            <div class="actions">
              <form method="post" action="/school-platform/admin/messages/drain">
                <button class="btn alt" type="submit">重送 queued 通知</button>
              </form>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>Provider Smoke Test</h2>
            <form class="stack" method="post" action="/school-platform/admin/messages/test">
              <label class="field">渠道
                <select name="channel">
                  <option value="email">email</option>
                  <option value="line">line</option>
                  <option value="in_app">in_app</option>
                </select>
              </label>
              <label class="field">recipient
                <input type="text" name="recipient" placeholder="email 或 LINE user ID；可留空用預設測試對象" />
              </label>
              <label class="field">user_email（稽核 / 對應用）
                <input type="email" name="user_email" value="admin@jls.local" />
              </label>
              <label class="field">標題
                <input type="text" name="title" value="School Platform Provider Smoke Test" />
              </label>
              <label class="field">內容
                <textarea name="content">這是一封用來驗證 School Platform 正式通知設定的測試訊息。</textarea>
              </label>
              <button class="btn" type="submit">送出測試通知</button>
            </form>
            <p>{escape(smoke_test_email_note)}</p>
            <p>{escape(smoke_test_line_note)}</p>
            <p>建議先測 Email，再測 LINE；送出後可直接在下方最近通知紀錄看結果與錯誤訊息。</p>
          </article>
          <article class="card">
            <h2>Gmail SMTP 最短設定</h2>
            <p>如果你要先讓 <code>rokaizumi@gmail.com</code> 開始寄真信，最短是用 Gmail SMTP + App Password。</p>
            <p><code>SCHOOL_PLATFORM_EMAIL_PROVIDER=smtp</code></p>
            <p><code>SCHOOL_PLATFORM_SMTP_HOST=smtp.gmail.com</code></p>
            <p><code>SCHOOL_PLATFORM_SMTP_PORT=587</code></p>
            <p><code>SCHOOL_PLATFORM_SMTP_USERNAME=rokaizumi@gmail.com</code></p>
            <p><code>SCHOOL_PLATFORM_SMTP_FROM_EMAIL=rokaizumi@gmail.com</code></p>
          </article>
          <article class="card">
            <h2>LINE 外發需要什麼</h2>
            <p>LINE 外發不是個人 LINE 密碼，而是 LINE 官方帳號 Messaging API 憑證。</p>
            <p><code>SCHOOL_PLATFORM_LINE_CHANNEL_ACCESS_TOKEN=...</code></p>
            <p><code>SCHOOL_PLATFORM_LINE_CHANNEL_SECRET=...</code></p>
            <p><code>SCHOOL_PLATFORM_LINE_FALLBACK_USER_ID=Uxxxxxxxx...</code></p>
            <p>補完後可用 <code>python3 scripts/test_school_platform_notification_providers.py --channel line --recipient Uxxxxxxxx...</code> 驗證。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>最近通知紀錄</h2>
        <div class="grid two">{notification_cards}</div>
      </section>
    """
    return _page_shell("訊息中心", body)


@router.post("/admin/messages/send")
def school_platform_admin_messages_send_submit(
    audience: str = Form(...),
    channel: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    target_email: str | None = Form(default=None),
):
    try:
        notification_service.broadcast(
            BroadcastMessageRequest(
                audience=audience,
                channel=channel,
                title=title,
                content=content,
                target_email=target_email or None,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Target email required for single student") from exc
    return RedirectResponse(url="/school-platform/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/messages/test")
def school_platform_admin_messages_test_submit(
    channel: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    recipient: str = Form(default=""),
    user_email: str = Form(default=""),
):
    try:
        notification_service.send_test_notification(
            channel=channel,
            title=title,
            content=content,
            recipient=recipient or None,
            user_email=user_email or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/school-platform/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/messages/drain")
def school_platform_admin_messages_drain_submit():
    notification_service.drain_queued_notifications()
    return RedirectResponse(url="/school-platform/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/messages/{notification_id}/retry")
def school_platform_admin_message_retry_submit(notification_id: UUID):
    try:
        notification_service.retry_notification(notification_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc
    return RedirectResponse(url="/school-platform/admin/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/schedule", response_class=HTMLResponse)
def school_platform_admin_schedule_page() -> str:
    snapshot = scheduling_service.overview()
    summary = snapshot.summary
    teacher_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.teacher_name)}</div>"
            f"<h3>授課班級 {item.class_count}</h3>"
            f"<div class='meta'><span class='chip'>每週堂數 {item.weekly_sessions}</span><span class='chip'>每週工時 {item.weekly_hours:g}</span></div>"
            "</article>"
        )
        for item in snapshot.teacher_loads
    ) or "<article class='card'><h3>目前沒有教師排課資料</h3></article>"
    class_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.teacher_name)} / {escape(item.course_slug)}</div>"
            f"<h3>{escape(item.name)}</h3>"
            f"<p>{escape(item.weekday)} {escape(item.start_time.strftime('%H:%M'))}-{escape(item.end_time.strftime('%H:%M'))}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.location_label)}</span><span class='chip'>名額 {item.enrolled_count}/{item.capacity}</span></div>"
            "</article>"
        )
        for item in snapshot.classes[:12]
    ) or "<article class='card'><h3>目前沒有班級資料</h3></article>"
    conflict_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.teacher_name)} / {escape(item.weekday)}</div>"
            f"<h3>{escape(' / '.join(item.class_names))}</h3>"
            f"<p>{escape(item.time_range)}</p>"
            f"<p>{escape(item.overlap_note)}</p>"
            "</article>"
        )
        for item in snapshot.conflicts
    ) or "<article class='card'><h3>目前未偵測到衝堂</h3><p>現有班級安排沒有教師時段重疊。</p></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Scheduling Center</div>
        <h1>排課中心</h1>
        <p>這裡把目前所有開課班級、教師排課負載與衝堂風險集中整理，方便主管直接檢查排課品質。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/admin/classes">回班級管理</a>
          <a class="btn alt" href="/school-platform/api/admin/schedule">查看排課 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">開放班級</div><div class="value">{summary.total_open_classes}</div></div>
          <div class="stat"><div class="label">已排教師</div><div class="value">{summary.teachers_scheduled}</div></div>
          <div class="stat"><div class="label">線上班級</div><div class="value">{summary.online_classes}</div></div>
          <div class="stat"><div class="label">實體班級</div><div class="value">{summary.onsite_classes}</div></div>
          <div class="stat"><div class="label">衝堂數</div><div class="value">{summary.detected_conflicts}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>教師排課負載</h2>
        <div class="grid two">{teacher_cards}</div>
      </section>
      <section class="section">
        <h2>排課衝堂檢查</h2>
        <div class="grid two">{conflict_cards}</div>
      </section>
      <section class="section">
        <h2>班級時段總覽</h2>
        <div class="grid two">{class_cards}</div>
      </section>
    """
    return _page_shell("排課中心", body)


@router.post("/admin/teaching/assignments/create")
def school_platform_admin_assignment_create_submit(
    class_id: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    due_at: str = Form(...),
    created_by: str = Form(default="Yuki Wang"),
):
    teaching_ops_service.create_assignment(
        AssignmentCreateRequest(
            class_id=UUID(class_id),
            title=title,
            content=content,
            due_at=datetime.fromisoformat(due_at),
            created_by=created_by or "Yuki Wang",
        )
    )
    return RedirectResponse(url="/school-platform/admin/teaching", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/teaching/exams/create")
def school_platform_admin_exam_create_submit(
    class_id: str = Form(...),
    title: str = Form(...),
    exam_type: str = Form(...),
    instructions: str = Form(...),
    total_score: float = Form(default=100),
    due_at: str = Form(...),
    created_by: str = Form(default="Aki Mori"),
):
    teaching_ops_service.create_exam(
        ExamCreateRequest(
            class_id=UUID(class_id),
            title=title,
            exam_type=exam_type,
            instructions=instructions,
            total_score=total_score,
            due_at=datetime.fromisoformat(due_at),
            created_by=created_by or "Aki Mori",
        )
    )
    return RedirectResponse(url="/school-platform/admin/teaching", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/teaching/attendance/mark")
def school_platform_admin_attendance_mark_submit(
    class_id: str = Form(...),
    student_email: str = Form(...),
    class_date: str = Form(...),
    status_value: str = Form(...),
    note: str = Form(default=""),
    marked_by: str = Form(default="Yuki Wang"),
):
    try:
        teaching_ops_service.mark_attendance(
            AttendanceMarkRequest(
                class_id=UUID(class_id),
                student_email=student_email,
                class_date=date.fromisoformat(class_date),
                status=status_value,
                note=note or None,
                marked_by=marked_by or "Yuki Wang",
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    return RedirectResponse(url="/school-platform/admin/teaching", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/teaching/session-records/{record_id}/review")
def school_platform_admin_teaching_session_review_submit(
    record_id: UUID,
    approval_status_value: str = Form(...),
    review_note: str = Form(default=""),
    reviewed_by: str = Form(default="Yuki Wang"),
):
    try:
        teaching_ops_service.review_teaching_session_record(
            record_id,
            TeachingSessionReviewRequest(
                approval_status=approval_status_value,
                review_note=review_note or None,
                reviewed_by=reviewed_by or "Yuki Wang",
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Teaching session record not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid teaching session review payload") from exc
    return RedirectResponse(url="/school-platform/admin/teaching", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/leads", response_class=HTMLResponse)
def school_platform_admin_leads_page() -> str:
    leads = admissions_service.list_leads()
    lead_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.status)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>課程意向：{escape(item.interested_course_slug or '未指定')}</p>"
        f"<p>程度：{escape(item.japanese_level or '未填寫')} / 來源：{escape(item.source_channel)}</p>"
        f"<div class='meta'>"
        f"<span class='chip'>熱度 {item.intent_score:.0f}</span>"
        f"<span class='chip'>成交率 {item.win_probability:.0f}%</span>"
        f"<span class='chip'>{escape(item.assigned_staff_name or '未指派')}</span>"
        "</div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/leads/{item.id}'>查看名單詳情</a></div>"
        "</article>"
        for item in leads
    ) or "<article class='card'><h3>目前沒有名單</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Admissions CRM</div>
        <h1>招生名單管理</h1>
        <p>這裡先把名單列表做成可視化頁面，下一步會接 lead 詳頁與跟進紀錄操作。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/leads">查看 leads JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{lead_cards}</div>
      </section>
    """
    return _page_shell("招生名單管理", body)


@router.get("/admin/leads/{lead_id}", response_class=HTMLResponse)
def school_platform_admin_lead_detail_page(lead_id: UUID) -> str:
    try:
        lead = admissions_service.get_lead(lead_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc
    logs = admissions_service.logs_for_lead(lead_id)
    staff_options = "".join(
        f"<option value='{item.id}' {'selected' if item.name == lead.assigned_staff_name else ''}>{escape(item.name)} / {escape(item.title)}</option>"
        for item in admissions_service.list_staff()
        if item.role in {"consultant", "manager"}
    )
    log_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.contact_method)}</div>"
        f"<h3>{escape(item.staff_name)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<p>下一步：{escape(item.next_action or '待補')}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        "</article>"
        for item in logs
    ) or "<article class='card'><h3>尚無跟進紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Lead Detail</div>
        <h1>{escape(lead.name)}</h1>
        <p>這頁會集中顯示名單狀態、熱度、顧問與歷次跟進，方便下一步接真實操作。</p>
        <div class="meta">
          <span class="chip">{escape(lead.status)}</span>
          <span class="chip">熱度 {lead.intent_score:.0f}</span>
          <span class="chip">成交率 {lead.win_probability:.0f}%</span>
          <span class="chip">{escape(lead.assigned_staff_name or '未指派')}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/leads">回名單列表</a>
          <a class="btn alt" href="/school-platform/api/leads/{lead.id}">查看 lead JSON</a>
        </div>
      </section>
      <section class="section">
        <h2>名單摘要</h2>
        <div class="grid two">
          <article class="card">
            <h3>聯絡資訊</h3>
            <p>Email：{escape(lead.email or '未填寫')}</p>
            <p>電話：{escape(lead.phone or '未填寫')}</p>
            <p>LINE：{escape(lead.line_id or '未綁定')}</p>
          </article>
          <article class="card">
            <h3>學習背景</h3>
            <p>課程意向：{escape(lead.interested_course_slug or '未指定')}</p>
            <p>程度：{escape(lead.japanese_level or '未填寫')}</p>
            <p>目標：{escape(lead.study_goal or '未填寫')}</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>跟進紀錄</h2>
        <div class="grid two">{log_cards}</div>
      </section>
      <section class="section">
        <h2>操作區塊</h2>
        <div class="grid two">
          <article class="card">
            <h3>重新指派顧問</h3>
            <form class="stack" method="post" action="/school-platform/admin/leads/{lead.id}/assign">
              <label class="field">顧問
                <select name="staff_id">{staff_options}</select>
              </label>
              <button class="btn" type="submit">送出指派</button>
            </form>
          </article>
          <article class="card">
            <h3>更新狀態</h3>
            <form class="stack" method="post" action="/school-platform/admin/leads/{lead.id}/status">
              <label class="field">狀態
                <select name="status_value">
                  <option value="new">new</option>
                  <option value="contacted">contacted</option>
                  <option value="replied">replied</option>
                  <option value="trial_booked" selected>trial_booked</option>
                  <option value="trial_completed">trial_completed</option>
                  <option value="considering">considering</option>
                  <option value="enrolled">enrolled</option>
                  <option value="waitlisted">waitlisted</option>
                  <option value="lost">lost</option>
                  <option value="blacklisted">blacklisted</option>
                </select>
              </label>
              <label class="field">下次跟進時間
                <input type="datetime-local" name="next_follow_up_at" />
              </label>
              <label class="field">備註
                <textarea name="note" placeholder="例如：已約好明天下午再聯繫"></textarea>
              </label>
              <button class="btn" type="submit">送出狀態更新</button>
            </form>
          </article>
          <article class="card">
            <h3>新增跟進</h3>
            <form class="stack" method="post" action="/school-platform/admin/leads/{lead.id}/logs">
              <label class="field">顧問名稱
                <input type="text" name="staff_name" value="{escape(lead.assigned_staff_name or 'System')}" />
              </label>
              <label class="field">聯繫方式
                <select name="contact_method">
                  <option value="system">system</option>
                  <option value="line">line</option>
                  <option value="call">call</option>
                  <option value="email">email</option>
                </select>
              </label>
              <label class="field">紀錄內容
                <textarea name="content" placeholder="輸入這次跟進的內容"></textarea>
              </label>
              <label class="field">下一步
                <input type="text" name="next_action" placeholder="例如：兩天後再次確認是否預約試聽" />
              </label>
              <button class="btn" type="submit">新增跟進紀錄</button>
            </form>
          </article>
        </div>
      </section>
    """
    return _page_shell(f"名單詳情 - {lead.name}", body)


@router.post("/admin/leads/{lead_id}/assign")
def school_platform_admin_lead_assign_submit(
    lead_id: UUID,
    staff_id: str = Form(...),
):
    lead_workflow_service.assign_lead(lead_id, LeadAssignmentRequest(staff_id=UUID(staff_id)))
    return RedirectResponse(url=f"/school-platform/admin/leads/{lead_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/leads/{lead_id}/status")
def school_platform_admin_lead_status_submit(
    lead_id: UUID,
    status_value: str = Form(...),
    next_follow_up_at: str = Form(default=""),
    note: str = Form(default=""),
):
    next_follow_up = datetime.fromisoformat(next_follow_up_at) if next_follow_up_at else None
    payload = LeadStatusChangeRequest(status=status_value, next_follow_up_at=next_follow_up, note=note or None)
    lead_workflow_service.change_status(lead_id, payload)
    return RedirectResponse(url=f"/school-platform/admin/leads/{lead_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/leads/{lead_id}/logs")
def school_platform_admin_lead_log_submit(
    lead_id: UUID,
    staff_name: str = Form(...),
    contact_method: str = Form(...),
    content: str = Form(...),
    next_action: str = Form(default=""),
):
    lead_workflow_service.add_log(lead_id, staff_name, contact_method, content, next_action or None)
    return RedirectResponse(url=f"/school-platform/admin/leads/{lead_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/classes", response_class=HTMLResponse)
def school_platform_admin_classes_page() -> str:
    classes = catalog_service.open_classes()
    course_options = "".join(
        f"<option value='{escape(item.slug)}'>{escape(item.name)} ({escape(item.slug)})</option>"
        for item in catalog_service.list_courses()
    )
    class_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.course_slug)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>老師：{escape(item.teacher_name)} / 地點：{escape(item.location_label)}</p>"
        f"<p>時間：{escape(item.weekday)} {escape(item.start_time.strftime('%H:%M'))}-{escape(item.end_time.strftime('%H:%M'))}</p>"
        f"<div class='meta'>"
        f"<span class='chip'>名額 {item.enrolled_count}/{item.capacity}</span>"
        f"<span class='chip'>{escape(item.start_date.isoformat())}</span>"
        f"<span class='chip'>{escape(item.status)}</span>"
        "</div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/classes/{item.id}/edit'>編輯班級</a></div>"
        "</article>"
        for item in classes
    ) or "<article class='card'><h3>目前沒有班級</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Classes Management</div>
        <h1>班級管理</h1>
        <p>這裡先把目前所有開放班級整理成管理頁，下一段會接課程管理、教師排課與班級詳頁。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/classes">查看 classes JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{class_cards}</div>
      </section>
      <section class="section">
        <h2>操作區塊</h2>
        <div class="grid two">
          <article class="card">
            <h3>新增班級</h3>
            <form class="stack" method="post" action="/school-platform/admin/classes/create">
              <label class="field">課程
                <select name="course_slug">{course_options}</select>
              </label>
              <label class="field">班級名稱
                <input type="text" name="name" placeholder="例如：7 月晚間班" />
              </label>
              <label class="field">教師名稱
                <input type="text" name="teacher_name" value="Aki Mori" />
              </label>
              <label class="field">開始日期
                <input type="date" name="start_date" />
              </label>
              <label class="field">結束日期
                <input type="date" name="end_date" />
              </label>
              <label class="field">星期
                <input type="text" name="weekday" value="Tue / Thu" />
              </label>
              <label class="field">開始時間
                <input type="time" name="start_time" value="19:30" />
              </label>
              <label class="field">結束時間
                <input type="time" name="end_time" value="21:00" />
              </label>
              <label class="field">容量
                <input type="number" name="capacity" value="16" />
              </label>
              <label class="field">上課地點
                <input type="text" name="location_label" value="Zoom Live" />
              </label>
              <button class="btn" type="submit">建立班級</button>
            </form>
          </article>
          <article class="card">
            <h3>更新班級</h3>
            <p><code>PATCH /school-platform/api/classes/{'{class_id}'}</code></p>
            <p>下一段會把這裡接成真正表單，直接在後台改班級資料。</p>
          </article>
        </div>
      </section>
    """
    return _page_shell("班級管理", body)


@router.post("/admin/classes/create")
def school_platform_admin_class_create_submit(
    course_slug: str = Form(...),
    name: str = Form(...),
    teacher_name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    weekday: str = Form(...),
    start_time_value: str = Form(..., alias="start_time"),
    end_time_value: str = Form(..., alias="end_time"),
    capacity: int = Form(...),
    location_label: str = Form(...),
):
    payload = ClassUpsertRequest(
        course_slug=course_slug,
        name=name,
        teacher_name=teacher_name,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        weekday=weekday,
        start_time=time.fromisoformat(start_time_value),
        end_time=time.fromisoformat(end_time_value),
        capacity=capacity,
        location_label=location_label,
        status="open",
    )
    curriculum_admin_service.create_class(payload)
    return RedirectResponse(url="/school-platform/admin/classes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/classes/{class_id}/edit", response_class=HTMLResponse)
def school_platform_admin_class_edit_page(class_id: UUID) -> str:
    class_item = next((item for item in catalog_service.open_classes() if item.id == class_id), None)
    if class_item is None:
        raise HTTPException(status_code=404, detail="Class not found")
    course_options = "".join(
        f"<option value='{escape(item.slug)}' {'selected' if item.slug == class_item.course_slug else ''}>{escape(item.name)} ({escape(item.slug)})</option>"
        for item in catalog_service.list_courses()
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Class Editor</div>
        <h1>編輯班級</h1>
        <p>這裡可以直接修改班級資料並寫回目前的 store。</p>
      </section>
      <section class="section">
        <article class="card">
          <form class="stack" method="post" action="/school-platform/admin/classes/{class_item.id}/edit">
            <label class="field">課程
              <select name="course_slug">{course_options}</select>
            </label>
            <label class="field">班級名稱
              <input type="text" name="name" value="{escape(class_item.name)}" />
            </label>
            <label class="field">教師名稱
              <input type="text" name="teacher_name" value="{escape(class_item.teacher_name)}" />
            </label>
            <label class="field">開始日期
              <input type="date" name="start_date" value="{class_item.start_date.isoformat()}" />
            </label>
            <label class="field">結束日期
              <input type="date" name="end_date" value="{class_item.end_date.isoformat()}" />
            </label>
            <label class="field">星期
              <input type="text" name="weekday" value="{escape(class_item.weekday)}" />
            </label>
            <label class="field">開始時間
              <input type="time" name="start_time" value="{class_item.start_time.strftime('%H:%M')}" />
            </label>
            <label class="field">結束時間
              <input type="time" name="end_time" value="{class_item.end_time.strftime('%H:%M')}" />
            </label>
            <label class="field">容量
              <input type="number" name="capacity" value="{class_item.capacity}" />
            </label>
            <label class="field">地點
              <input type="text" name="location_label" value="{escape(class_item.location_label)}" />
            </label>
            <button class="btn" type="submit">儲存班級</button>
          </form>
        </article>
      </section>
    """
    return _page_shell("編輯班級", body)


@router.post("/admin/classes/{class_id}/edit")
def school_platform_admin_class_edit_submit(
    class_id: UUID,
    course_slug: str = Form(...),
    name: str = Form(...),
    teacher_name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    weekday: str = Form(...),
    start_time_value: str = Form(..., alias="start_time"),
    end_time_value: str = Form(..., alias="end_time"),
    capacity: int = Form(...),
    location_label: str = Form(...),
):
    payload = ClassUpsertRequest(
        course_slug=course_slug,
        name=name,
        teacher_name=teacher_name,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        weekday=weekday,
        start_time=time.fromisoformat(start_time_value),
        end_time=time.fromisoformat(end_time_value),
        capacity=capacity,
        location_label=location_label,
        status="open",
    )
    curriculum_admin_service.update_class(class_id, payload)
    return RedirectResponse(url="/school-platform/admin/classes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/courses", response_class=HTMLResponse)
def school_platform_admin_courses_page() -> str:
    courses = catalog_service.list_courses()
    course_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.course_type)} / {escape(item.level)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.short_description)}</p>"
        f"<div class='meta'><span class='chip'>{_format_jpy(item.price)}</span><span class='chip'>{escape(item.delivery_mode)}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/courses/{escape(item.slug)}/edit'>編輯課程</a></div>"
        "</article>"
        for item in courses
    ) or "<article class='card'><h3>目前沒有課程</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Courses Management</div>
        <h1>課程管理</h1>
        <p>這裡先把課程資料集中在管理端查看，接下來會把新增與修改課程表單掛上來。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/courses">查看 courses JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{course_cards}</div>
      </section>
      <section class="section">
        <h2>操作區塊</h2>
        <div class="grid two">
          <article class="card">
            <h3>課程內容治理</h3>
            <p>把平台自有核心課綱、平台教材與教師補充內容分開管理，避免課程內容完全失控。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/course-content">打開內容治理頁</a>
            </div>
          </article>
          <article class="card">
            <h3>新增課程</h3>
            <form class="stack" method="post" action="/school-platform/admin/courses/create">
              <label class="field">slug
                <input type="text" name="slug" placeholder="例如：japan-life-intensive" />
              </label>
              <label class="field">課程名稱
                <input type="text" name="name" placeholder="例如：日本生活日語密集班" />
              </label>
              <label class="field">課程類型
                <input type="text" name="course_type" value="生活日語" />
              </label>
              <label class="field">程度
                <input type="text" name="level" value="N5" />
              </label>
              <label class="field">授課模式
                <input type="text" name="delivery_mode" value="online" />
              </label>
              <label class="field">價格（日圓）
                <input type="number" name="price" value="10800" />
              </label>
              <label class="field">短描述
                <textarea name="short_description" placeholder="輸入課程摘要"></textarea>
              </label>
              <label class="field">課程目標
                <textarea name="objectives" placeholder="每行一個目標"></textarea>
              </label>
              <label class="field">課程亮點
                <textarea name="highlights" placeholder="每行一個亮點"></textarea>
              </label>
              <label class="field">章節規劃
                <textarea name="modules" placeholder="每行一個章節"></textarea>
              </label>
              <label class="field">教師名單
                <textarea name="teacher_names" placeholder="每行一位教師"></textarea>
              </label>
              <button class="btn" type="submit">建立課程</button>
            </form>
          </article>
        </div>
      </section>
    """
    return _page_shell("課程管理", body)


@router.post("/admin/courses/create")
def school_platform_admin_course_create_submit(
    slug: str = Form(...),
    name: str = Form(...),
    course_type: str = Form(...),
    level: str = Form(...),
    delivery_mode: str = Form(...),
    price: float = Form(...),
    short_description: str = Form(...),
    objectives: str = Form(default=""),
    highlights: str = Form(default=""),
    modules: str = Form(default=""),
    teacher_names: str = Form(default=""),
):
    payload = CourseUpsertRequest(
        slug=slug,
        name=name,
        course_type=course_type,
        level=level,
        delivery_mode=delivery_mode,
        price=price,
        short_description=short_description,
        objectives=[item.strip() for item in objectives.splitlines() if item.strip()],
        highlights=[item.strip() for item in highlights.splitlines() if item.strip()],
        modules=[item.strip() for item in modules.splitlines() if item.strip()],
        teacher_names=[item.strip() for item in teacher_names.splitlines() if item.strip()],
    )
    curriculum_admin_service.create_course(payload)
    return RedirectResponse(url="/school-platform/admin/courses", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/courses/{slug}/edit", response_class=HTMLResponse)
def school_platform_admin_course_edit_page(slug: str) -> str:
    try:
        course = catalog_service.get_course(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    body = f"""
      <section class="hero">
        <div class="eyebrow">Course Editor</div>
        <h1>編輯課程</h1>
        <p>這裡可以直接修改課程資料並寫回目前的 store。</p>
      </section>
      <section class="section">
        <article class="card">
          <form class="stack" method="post" action="/school-platform/admin/courses/{escape(course.slug)}/edit">
            <label class="field">slug
              <input type="text" name="slug" value="{escape(course.slug)}" />
            </label>
            <label class="field">課程名稱
              <input type="text" name="name" value="{escape(course.name)}" />
            </label>
            <label class="field">課程類型
              <input type="text" name="course_type" value="{escape(course.course_type)}" />
            </label>
            <label class="field">程度
              <input type="text" name="level" value="{escape(course.level)}" />
            </label>
            <label class="field">授課模式
              <input type="text" name="delivery_mode" value="{escape(course.delivery_mode)}" />
            </label>
            <label class="field">價格（日圓）
              <input type="number" name="price" value="{course.price}" />
            </label>
            <label class="field">短描述
              <textarea name="short_description">{escape(course.short_description)}</textarea>
            </label>
            <label class="field">課程目標
              <textarea name="objectives">{escape(chr(10).join(course.objectives))}</textarea>
            </label>
            <label class="field">課程亮點
              <textarea name="highlights">{escape(chr(10).join(course.highlights))}</textarea>
            </label>
            <label class="field">章節規劃
              <textarea name="modules">{escape(chr(10).join(course.modules))}</textarea>
            </label>
            <label class="field">教師名單
              <textarea name="teacher_names">{escape(chr(10).join(course.teacher_names))}</textarea>
            </label>
            <button class="btn" type="submit">儲存課程</button>
          </form>
        </article>
      </section>
    """
    return _page_shell("編輯課程", body)


@router.post("/admin/courses/{slug}/edit")
def school_platform_admin_course_edit_submit(
    slug: str,
    slug_value: str = Form(..., alias="slug"),
    name: str = Form(...),
    course_type: str = Form(...),
    level: str = Form(...),
    delivery_mode: str = Form(...),
    price: float = Form(...),
    short_description: str = Form(...),
    objectives: str = Form(default=""),
    highlights: str = Form(default=""),
    modules: str = Form(default=""),
    teacher_names: str = Form(default=""),
):
    payload = CourseUpsertRequest(
        slug=slug_value,
        name=name,
        course_type=course_type,
        level=level,
        delivery_mode=delivery_mode,
        price=price,
        short_description=short_description,
        objectives=[item.strip() for item in objectives.splitlines() if item.strip()],
        highlights=[item.strip() for item in highlights.splitlines() if item.strip()],
        modules=[item.strip() for item in modules.splitlines() if item.strip()],
        teacher_names=[item.strip() for item in teacher_names.splitlines() if item.strip()],
    )
    updated = curriculum_admin_service.update_course(slug, payload)
    return RedirectResponse(url=f"/school-platform/admin/courses/{updated.slug}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/course-content", response_class=HTMLResponse)
def school_platform_admin_course_content_page() -> str:
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item['course'].course_type)} / {escape(item['course'].level)}</div>"
        f"<h3>{escape(item['course'].name)}</h3>"
        f"<p>核心章節 {item['core_modules']} 個 / 平台教材 {item['platform_materials']} 份 / 教師補充 {item['teacher_materials']} 份</p>"
        f"<div class='meta'><span class='chip'>{'已有教師層' if item['has_teacher_layer'] else '只有平台層'}</span><span class='chip'>{_format_jpy(item['course'].price)}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/course-content/{escape(item['course'].slug)}'>查看內容治理</a></div>"
        "</article>"
        for item in course_content_service.governance_cards()
    ) or "<article class='card'><h3>目前沒有課程內容資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Course Content Governance</div>
        <h1>課程內容治理</h1>
        <p>這裡把平台自有核心內容與教師補充內容拆開管理，讓平台不是只有老師自由上傳，也不是只有空的招生頁。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/courses">回課程管理</a>
          <a class="btn alt" href="/school-platform/api/public/courses/japan-life-starter/content">查看示範內容 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("課程內容治理", body)


@router.get("/admin/course-content/{slug}", response_class=HTMLResponse)
def school_platform_admin_course_content_detail_page(slug: str) -> str:
    try:
        snapshot = course_content_service.snapshot(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    core_module_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>平台核心章節 / 排序 {item.sort_order}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_by)}</span></div>"
        + (f"<p><a href='{escape(item.material_url)}'>{escape(item.material_url)}</a></p>" if item.material_url else "")
        + "</article>"
        for item in snapshot.core_modules
    ) or "<article class='card'><h3>目前沒有核心章節</h3></article>"
    platform_material_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>平台自有教材 / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, label='打開教材')}"
        f"{_material_source_html(item)}"
        f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_by)}</span></div>"
        "</article>"
        for item in snapshot.platform_materials
    ) or "<article class='card'><h3>目前沒有平台教材</h3></article>"
    teacher_material_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>教師補充內容 / {escape(item.visibility)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.description)}</p>"
        f"{_material_asset_html(item, label='打開教材')}"
        f"{_material_source_html(item)}"
        f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_by)}</span></div>"
        "</article>"
        for item in snapshot.teacher_materials
    ) or "<article class='card'><h3>目前沒有教師補充內容</h3></article>"
    governance_notes = "".join(f"<li>{escape(item)}</li>" for item in snapshot.governance_notes)
    body = f"""
      <section class="hero">
        <div class="eyebrow">Course Content Detail</div>
        <h1>{escape(snapshot.course.name)} 內容治理</h1>
        <p>這裡明確區分平台核心課綱、平台標準教材與教師補充內容，後續才能擴成真正可控的教學平台。</p>
        <div class="meta">
          <span class="chip">{escape(snapshot.course.course_type)}</span>
          <span class="chip">{escape(snapshot.course.level)}</span>
          <span class="chip">核心章節 {len(snapshot.core_modules)}</span>
          <span class="chip">平台教材 {len(snapshot.platform_materials)}</span>
          <span class="chip">教師補充 {len(snapshot.teacher_materials)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/course-content">回內容治理總覽</a>
          <a class="btn alt" href="/school-platform/courses/{escape(snapshot.course.slug)}">查看前台課程頁</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>治理原則</h2>
            <ul class="clean">{governance_notes}</ul>
          </article>
          <article class="card">
            <h2>新增平台核心章節</h2>
            <form class="stack" method="post" action="/school-platform/admin/course-content/{escape(snapshot.course.slug)}/modules/create">
              <label class="field">章節名稱
                <input type="text" name="title" placeholder="例如：租屋問答與看房應對" />
              </label>
              <label class="field">章節說明
                <textarea name="description" placeholder="輸入這個章節的核心目標與涵蓋內容"></textarea>
              </label>
              <label class="field">排序
                <input type="number" name="sort_order" value="{len(snapshot.core_modules) + 1}" />
              </label>
              <label class="field">教材連結
                <input type="url" name="material_url" placeholder="https://..." />
              </label>
              <label class="field">建立者
                <input type="text" name="created_by" value="Platform Curriculum Team" />
              </label>
              <button class="btn" type="submit">新增平台章節</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>新增平台標準教材</h2>
            <form class="stack" method="post" enctype="multipart/form-data" action="/school-platform/admin/course-content/{escape(snapshot.course.slug)}/materials/create">
              <input type="hidden" name="owner_type" value="platform" />
              <label class="field">教材名稱
                <input type="text" name="title" placeholder="例如：平台標準生活會話講義" />
              </label>
              <label class="field">教材說明
                <textarea name="description" placeholder="輸入教材用途與適用範圍"></textarea>
              </label>
              <label class="field">教材連結
                <input type="url" name="material_url" placeholder="https://..." />
              </label>
              <label class="field">或上傳教材檔案
                <input type="file" name="uploaded_file" />
              </label>
              <label class="field">可見範圍
                <select name="visibility">
                  <option value="public">public</option>
                  <option value="enrolled_only">enrolled_only</option>
                  <option value="internal">internal</option>
                </select>
              </label>
              <label class="field">建立者
                <input type="text" name="created_by" value="Platform Curriculum Team" />
              </label>
              <button class="btn" type="submit">新增平台教材</button>
            </form>
          </article>
          <article class="card">
            <h2>現況判讀</h2>
            <div class="helper-list">
              <div>平台核心章節：對外產品主軸，不能被教師任意覆寫。</div>
              <div>平台標準教材：可跨班複用的標準資源。</div>
              <div>教師補充內容：針對班級狀況追加，不代表整門課的正式標準。</div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>平台核心章節</h2>
        <div class="grid two">{core_module_cards}</div>
      </section>
      <section class="section">
        <h2>平台標準教材</h2>
        <div class="grid two">{platform_material_cards}</div>
      </section>
      <section class="section">
        <h2>教師補充內容</h2>
        <div class="grid two">{teacher_material_cards}</div>
      </section>
    """
    return _page_shell(f"{snapshot.course.name} 內容治理", body)


@router.post("/admin/course-content/{slug}/modules/create")
def school_platform_admin_course_content_module_create_submit(
    slug: str,
    title: str = Form(...),
    description: str = Form(...),
    sort_order: int = Form(...),
    material_url: str = Form(default=""),
    created_by: str = Form(default="Platform Curriculum Team"),
):
    course_content_service.create_platform_module(
        CourseModuleUpsertRequest(
            course_slug=slug,
            title=title,
            description=description,
            sort_order=sort_order,
            material_url=material_url or None,
            status="published",
            created_by=created_by or "Platform Curriculum Team",
        )
    )
    return RedirectResponse(url=f"/school-platform/admin/course-content/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/course-content/{slug}/materials/create")
def school_platform_admin_course_content_material_create_submit(
    slug: str,
    title: str = Form(...),
    description: str = Form(...),
    material_url: str = Form(default=""),
    visibility: str = Form(default="public"),
    owner_type: str = Form(default="platform"),
    created_by: str = Form(default="Platform Curriculum Team"),
    uploaded_file: UploadFile | None = File(default=None),
):
    try:
        _create_material_from_form(
            course_slug=slug,
            title=title,
            description=description,
            material_url=material_url,
            class_id=None,
            visibility=visibility,
            owner_type=owner_type,
            created_by=created_by or "Platform Curriculum Team",
            uploaded_file=uploaded_file,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/school-platform/admin/course-content/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/teachers", response_class=HTMLResponse)
def school_platform_admin_teachers_page() -> str:
    teachers = admissions_service.list_staff(role="teacher")
    verification_map = {item.teacher_name: item for item in teacher_verification_service.directory()}
    teacher_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.department)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>職稱：{escape(item.title)}</p>"
        f"<p>驗證狀態：<strong>{escape('已通過' if verification_map.get(item.name) and verification_map[item.name].pass_status == 'passed' else '待驗證')}</strong></p>"
        f"<div class='meta'><span class='chip'>{escape(item.role)}</span><span class='chip'>{escape('已解鎖開課權限' if verification_map.get(item.name) and verification_map[item.name].unlocked_permission else '未解鎖')}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/teacher-portal?teacher_name={escape(item.name)}'>打開教師工作台</a><a class='btn alt' href='/school-platform/teacher/verification?teacher_name={escape(item.name)}'>查看教學驗證</a></div>"
        "</article>"
        for item in teachers
    ) or "<article class='card'><h3>目前沒有教師資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Teachers Management</div>
        <h1>教師管理</h1>
        <p>這裡已經能直接打開教師工作台，查看授課班級、待評分作業與測驗，也能檢查教師是否已完成開課驗證。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/admin/teacher-verification">看教師驗證總覽</a>
          <a class="btn alt" href="/school-platform/api/staff">查看 staff JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{teacher_cards}</div>
      </section>
    """
    return _page_shell("教師管理", body)


@router.get("/teacher-portal", response_class=HTMLResponse)
def school_platform_teacher_portal_page(teacher_name: str = Query(...)) -> str:
    dashboard = teacher_workspace_service.dashboard(teacher_name)
    verification_snapshot = teacher_verification_service.snapshot(teacher_name)
    classes = sorted(dashboard["classes"], key=lambda item: (item.weekday, item.start_time, item.name))
    assignments = dashboard["assignments"]
    exams = dashboard["exams"]
    session_records = dashboard["session_records"]
    pending_assignment_reviews = dashboard["pending_assignment_reviews"]
    pending_exam_reviews = dashboard["pending_exam_reviews"]
    summary = dashboard["summary"]
    next_class = classes[0] if classes else None
    teacher_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Classes",
                "title": "授課班級",
                "note": "先看今天要授課的班級、時間、地點和目前班級容量。",
                "href": "#teacher-classes",
            },
            {
                "kicker": "Assignments",
                "title": "待評分作業",
                "note": "快速處理還沒批改的作業，不要讓學員卡在等待回饋。",
                "href": "#assignment-reviews",
            },
            {
                "kicker": "Exams",
                "title": "待評分測驗",
                "note": "把口說稿、測驗答案與評分回饋集中處理。",
                "href": "#exam-reviews",
            },
            {
                "kicker": "Teaching Ops",
                "title": "課後紀錄",
                "note": "確認最近課後紀錄、待審核狀態和主管回覆。",
                "href": "#session-records",
            },
            {
                "kicker": "Verification",
                "title": "開課驗證",
                "note": "先確認是否已通過教師手冊驗證，未通過時就先補讀章節與完成測驗。",
                "href": f"/school-platform/teacher/verification?{urlencode({'teacher_name': teacher_name})}",
            },
            {
                "kicker": "Admin",
                "title": "回教務管理",
                "note": "如果要進一步處理教務總覽，可直接切回教務管理頁。",
                "href": "/school-platform/admin/teaching",
            },
        ]
    )
    teacher_tasks = [
        {
            "index": "01",
            "title": (
                "先完成教師開課驗證"
                if verification_snapshot.pass_status != "passed"
                else f"先處理 {len(pending_assignment_reviews)} 筆待評分作業"
            ),
            "note": (
                "還沒通過驗證時，先補讀手冊並完成測驗，之後再進入正式授課節奏。"
                if verification_snapshot.pass_status != "passed"
                else "作業回饋通常是老師最容易快速推進的任務，先清掉最能減少學員等待。"
            ),
        },
        {
            "index": "02",
            "title": f"再看 {len(pending_exam_reviews)} 筆待評分測驗",
            "note": "測驗成績和回饋會直接影響學員的整體評估與後續學習策略。",
        },
        {
            "index": "03",
            "title": f"確認 {summary['pending_session_reviews']} 筆待主管處理紀錄",
            "note": "如果課後紀錄還在 submitted，建議先補齊材料與高風險學員備註。",
        },
    ]
    teacher_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("授課班級", str(summary["class_count"])),
            ("作業總數", str(summary["assignment_count"])),
            ("測驗總數", str(summary["exam_count"])),
            ("待評分", str(summary["pending_reviews"])),
            ("開課驗證", "已通過" if verification_snapshot.pass_status == "passed" else "待完成"),
            (
                "下一堂課",
                f"{next_class.weekday} {next_class.start_time.strftime('%H:%M')} / {next_class.name}" if next_class else "目前沒有排課",
            ),
        ]
    )
    class_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.course_slug)}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.weekday)} / {escape(item.start_time.strftime('%H:%M'))}-{escape(item.end_time.strftime('%H:%M'))}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.location_label)}</span><span class='chip'>{item.enrolled_count}/{item.capacity}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/teacher/classes/{item.id}?teacher_name={escape(teacher_name)}'>查看班級詳情</a></div>"
        "</article>"
        for item in classes
    ) or "<article class='card'><h3>目前沒有授課班級</h3></article>"
    assignment_map = {item.id: item for item in assignments}
    exam_map = {item.id: item for item in exams}
    assignment_review_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>作業待評分</div>"
        f"<h3>{escape(assignment_map[item.assignment_id].title) if item.assignment_id in assignment_map else '未知作業'}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.submitted_at.isoformat())}</span><span class='chip'>{escape(item.status)}</span></div>"
        f"<form class='stack' method='post' action='/school-platform/teacher/assignment-submissions/{item.id}/grade'>"
        f"<input type='hidden' name='teacher_name' value='{escape(teacher_name)}' />"
        "<label class='field'>分數<input type='number' name='score' step='1' value='85' /></label>"
        "<label class='field'>回饋<textarea name='feedback' placeholder='輸入老師回饋'></textarea></label>"
        f"<input type='hidden' name='graded_by' value='{escape(teacher_name)}' />"
        "<button class='btn' type='submit'>送出評分</button>"
        "</form>"
        "</article>"
        for item in pending_assignment_reviews[:8]
    ) or "<article class='card'><h3>目前沒有待評分作業</h3></article>"
    exam_review_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>測驗待評分</div>"
        f"<h3>{escape(exam_map[item.exam_id].title) if item.exam_id in exam_map else '未知測驗'}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.submitted_at.isoformat())}</span><span class='chip'>{escape(item.status)}</span></div>"
        f"<form class='stack' method='post' action='/school-platform/teacher/exam-submissions/{item.id}/grade'>"
        f"<input type='hidden' name='teacher_name' value='{escape(teacher_name)}' />"
        "<label class='field'>分數<input type='number' name='score' step='1' value='88' /></label>"
        "<label class='field'>回饋<textarea name='feedback' placeholder='輸入老師回饋'></textarea></label>"
        f"<input type='hidden' name='graded_by' value='{escape(teacher_name)}' />"
        "<button class='btn' type='submit'>送出評分</button>"
        "</form>"
        "</article>"
        for item in pending_exam_reviews[:8]
    ) or "<article class='card'><h3>目前沒有待評分測驗</h3></article>"
    session_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.class_date.isoformat())} / {escape(item.approval_status)}</div>"
        f"<h3>{escape(next((class_item.name for class_item in classes if class_item.id == item.class_id), '未知班級'))}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<p>下次課堂焦點：{escape(item.next_class_focus or '尚未填寫')}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.teacher_name)}</span><span class='chip'>{escape(item.reviewed_by or '待主管處理')}</span></div>"
        "</article>"
        for item in session_records[:6]
    ) or "<article class='card'><h3>目前還沒有課後紀錄</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Teacher Workspace</div>
            <h1>{escape(teacher_name)} 教師工作台</h1>
            <p>這裡集中顯示授課班級、待評分作業、待評分測驗與課後紀錄，讓老師可以照著一條順手的教學流程往下做。</p>
            <div class="meta">
              <span class="chip">{escape(teacher_name)}</span>
              <span class="chip">授課班級 {summary['class_count']}</span>
              <span class="chip">待評分 {summary['pending_reviews']}</span>
              <span class="chip">待審核課後紀錄 {summary['pending_session_reviews']}</span>
              <span class="chip">{escape('已通過開課驗證' if verification_snapshot.pass_status == 'passed' else '待完成開課驗證')}</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/teachers">回教師管理</a>
              <a class="btn" href="/school-platform/teacher/verification?{urlencode({'teacher_name': teacher_name})}">打開教學驗證</a>
              <a class="btn alt" href="/school-platform/admin/teaching">回教務管理</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Teaching Pulse</div>
            <h2>今天先把教學節奏跑順</h2>
            <div class="data-points">{teacher_pulse}</div>
            <div class="task-list">{_render_task_items(teacher_tasks)}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Teaching Routes</div>
            <h2>授課工作捷徑</h2>
          </div>
          <p class="section-subtitle">如果你現在知道自己要做哪件事，就直接從對應區塊進去，不需要先滑完整頁。</p>
        </div>
        <div class="portal-nav-grid">{teacher_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">授課班級</div><div class="value">{summary['class_count']}</div></div>
          <div class="stat"><div class="label">作業數</div><div class="value">{summary['assignment_count']}</div></div>
          <div class="stat"><div class="label">測驗數</div><div class="value">{summary['exam_count']}</div></div>
          <div class="stat"><div class="label">待評分</div><div class="value">{summary['pending_reviews']}</div></div>
          <div class="stat"><div class="label">課後紀錄</div><div class="value">{summary['session_record_count']}</div></div>
          <div class="stat"><div class="label">待審核課後紀錄</div><div class="value">{summary['pending_session_reviews']}</div></div>
        </div>
      </section>
      <section id="teacher-classes" class="section">
        <h2>授課班級</h2>
        <div class="grid two">{class_cards}</div>
      </section>
      <section id="assignment-reviews" class="section">
        <h2>待評分作業</h2>
        <div class="grid two">{assignment_review_cards}</div>
      </section>
      <section id="exam-reviews" class="section">
        <h2>待評分測驗</h2>
        <div class="grid two">{exam_review_cards}</div>
      </section>
      <section id="session-records" class="section">
        <h2>最近課後紀錄</h2>
        <div class="grid two">{session_cards}</div>
      </section>
    """
    return _page_shell(f"{teacher_name} 教師工作台", body)


@router.get("/teacher/verification", response_class=HTMLResponse)
def school_platform_teacher_verification_page(teacher_name: str = Query(...)) -> str:
    snapshot = teacher_verification_service.snapshot(teacher_name)
    status_label = {
        "not_started": "尚未測驗",
        "passed": "已通過",
        "retry_required": "需要重測",
    }.get(snapshot.pass_status, snapshot.pass_status)
    latest_score = f"{snapshot.latest_attempt.score:.1f}" if snapshot.latest_attempt else "未作答"
    latest_time = snapshot.latest_attempt.submitted_at.isoformat() if snapshot.latest_attempt else "尚未提交"
    section_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>章節 {index + 1:02d}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<p>預估閱讀：{item.estimated_minutes} 分鐘</p>"
        f"<p>{escape(item.content).replace(chr(10), '<br />')}</p>"
        "</article>"
        for index, item in enumerate(snapshot.manual_sections)
    )
    question_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(question.section_slug)}</div>"
        f"<h3>{escape(question.prompt)}</h3>"
        "<div class='stack'>"
        + "".join(
            "<label class='field'>"
            f"<input type='radio' name='answer_{question.id}' value='{escape(option.split('.')[0])}' /> "
            f"{escape(option)}"
            "</label>"
            for option in question.options
        )
        + "</div></article>"
        for question in snapshot.questions
    )
    action_items = "".join(
        f"<li>{escape(item)}</li>"
        for item in snapshot.recommended_actions
    ) or "<li>目前沒有額外提醒。</li>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Teacher Verification</div>
            <h1>{escape(teacher_name)} 教師教學手冊與開課驗證</h1>
            <p>這裡把教師手冊、黃金口說教學法 SOP 與 AI 協作流程集中在同一頁，完成測驗後就能確認是否已解鎖開課權限。</p>
            <div class="meta">
              <span class="chip">狀態 {escape(status_label)}</span>
              <span class="chip">最新分數 {escape(latest_score)}</span>
              <span class="chip">{escape('已解鎖開課權限' if snapshot.unlocked_permission else '尚未解鎖開課權限')}</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/teacher-portal?{urlencode({'teacher_name': teacher_name})}">回教師工作台</a>
              <a class="btn alt" href="/school-platform/admin/teacher-verification">看管理端總覽</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Verification Pulse</div>
            <h2>先確認能不能正式開課</h2>
            <div class="data-points">
              <div class="data-point"><span>通過門檻</span><strong>{snapshot.required_score:.0f}</strong></div>
              <div class="data-point"><span>最新作答</span><strong>{escape(latest_time)}</strong></div>
              <div class="data-point"><span>手冊章節</span><strong>{len(snapshot.manual_sections)}</strong></div>
              <div class="data-point"><span>題目數</span><strong>{len(snapshot.questions)}</strong></div>
            </div>
            <ul class="clean">{action_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Manual</div>
            <h2>教師手冊章節</h2>
          </div>
          <p class="section-subtitle">先把真人老師要遵守的平台流程看完，再進入下方驗證題。</p>
        </div>
        <div class="grid two">{section_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Quiz</div>
            <h2>開課驗證測驗</h2>
          </div>
          <p class="section-subtitle">測驗達到 85 分以上，系統就會回寫教師驗證結果。</p>
        </div>
        <form class="stack" method="post" action="/school-platform/teacher/verification/submit">
          <input type="hidden" name="teacher_name" value="{escape(teacher_name)}" />
          <input type="hidden" name="return_to" value="/school-platform/teacher/verification?{urlencode({'teacher_name': teacher_name})}" />
          <div class="grid two">{question_cards}</div>
          <button class="btn" type="submit">提交開課驗證</button>
        </form>
      </section>
    """
    return _page_shell(f"{teacher_name} 教師驗證", body)


@router.get("/admin/teacher-verification", response_class=HTMLResponse)
def school_platform_admin_teacher_verification_page() -> str:
    snapshots = teacher_verification_service.directory()
    passed_count = sum(1 for item in snapshots if item.pass_status == "passed")
    unlocked_count = sum(1 for item in snapshots if item.unlocked_permission)
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.teacher_name)}</div>"
        f"<h3>{escape('已通過' if item.pass_status == 'passed' else '待補強')}</h3>"
        f"<p>最新分數：{escape(f'{item.latest_attempt.score:.1f}' if item.latest_attempt else '未作答')}</p>"
        f"<p>權限：{escape('已解鎖開課權限' if item.unlocked_permission else '尚未解鎖')}</p>"
        f"<p>建議：{escape(item.recommended_actions[0] if item.recommended_actions else '目前沒有提醒')}</p>"
        f"<div class='actions'><a class='btn' href='/school-platform/teacher/verification?{urlencode({'teacher_name': item.teacher_name})}'>查看詳情</a><a class='btn alt' href='/school-platform/teacher-portal?{urlencode({'teacher_name': item.teacher_name})}'>打開教師工作台</a></div>"
        "</article>"
        for item in snapshots
    ) or "<article class='card'><h3>目前沒有教師驗證資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Teacher Verification Admin</div>
        <h1>教師開課驗證總覽</h1>
        <p>管理端可以在這裡查看每位教師是否已完成手冊閱讀、是否通過驗證，以及開課權限是否已回寫。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/teachers">回教師管理</a>
          <a class="btn alt" href="/school-platform/admin">回營運總覽</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">教師數</div><div class="value">{len(snapshots)}</div></div>
          <div class="stat"><div class="label">已通過</div><div class="value">{passed_count}</div></div>
          <div class="stat"><div class="label">已解鎖</div><div class="value">{unlocked_count}</div></div>
          <div class="stat"><div class="label">待補強</div><div class="value">{max(len(snapshots) - passed_count, 0)}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("教師開課驗證總覽", body)


@router.get("/teacher/classes/{class_id}", response_class=HTMLResponse)
def school_platform_teacher_class_detail_page(class_id: UUID, teacher_name: str = Query(...)) -> str:
    try:
        snapshot = teacher_workspace_service.class_snapshot(teacher_name, class_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Teacher class not found") from exc

    class_item = snapshot.class_item
    summary = snapshot.summary
    class_detail_return_to = f"/school-platform/teacher/classes/{class_item.id}?{urlencode({'teacher_name': teacher_name})}"
    teacher_materials = catalog_service.teaching_materials(course_slug=class_item.course_slug, class_id=class_item.id, owner_type="teacher")
    student_map = {item.student_id: item for item in snapshot.roster}
    assignment_map = {item.id: item for item in snapshot.assignments}
    exam_map = {item.id: item for item in snapshot.exams}
    high_risk_students = [item.chinese_name for item in snapshot.roster if item.risk_level == "high"][:3]
    class_nav = _render_portal_nav_cards(
        [
            {
                "kicker": "Roster",
                "title": "學員名單",
                "note": "先看風險高低、出席率、作業與測驗完成度。",
                "href": "#class-roster",
            },
            {
                "kicker": "Attendance",
                "title": "快速點名",
                "note": "授課後可以立刻補齊出席狀態與備註。",
                "href": "#attendance-form",
            },
            {
                "kicker": "Session Record",
                "title": "課後紀錄",
                "note": "整理教材、作業、下次焦點與高風險學員備註。",
                "href": "#session-record-form",
            },
            {
                "kicker": "Materials",
                "title": "補充教材",
                "note": "班級型講義、補充連結與老師自己的延伸資源放這裡。",
                "href": "#teacher-materials",
            },
            {
                "kicker": "Reviews",
                "title": "待批改作業",
                "note": "集中處理這個班的作業評分與回饋。",
                "href": "#class-assignment-reviews",
            },
            {
                "kicker": "Reviews",
                "title": "待批改測驗",
                "note": "把測驗答案、分數與評語一次整理完成。",
                "href": "#class-exam-reviews",
            },
        ]
    )
    class_tasks = [
        {
            "index": "01",
            "title": f"先看 {summary.high_risk_students} 位高風險學員",
            "note": f"目前需要優先關注：{', '.join(high_risk_students) if high_risk_students else '暫無高風險學員'}。",
        },
        {
            "index": "02",
            "title": f"補齊 {summary.pending_assignments} 筆待補作業",
            "note": "先確認是哪些學員還沒交，再決定要不要在課後紀錄裡標成風險提醒。",
        },
        {
            "index": "03",
            "title": f"完成 {summary.pending_exams} 筆待補測驗",
            "note": "如果這些測驗會影響分班或後續課程，建議本週內把狀態更新乾淨。",
        },
    ]
    class_pulse = "".join(
        f"<div class='data-point'><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in [
            ("班級", class_item.name),
            ("時間", f"{class_item.weekday} {class_item.start_time.strftime('%H:%M')}-{class_item.end_time.strftime('%H:%M')}"),
            ("學員數", str(summary.total_students)),
            ("高風險", str(summary.high_risk_students)),
            ("待審核紀錄", str(summary.pending_session_reviews)),
        ]
    )
    class_focus_cards = "".join(
        [
            (
                "<article class='focus-card'>"
                "<div class='eyebrow'>Risk Watch</div>"
                "<h3>班級風險分布</h3>"
                f"<p>高風險 {summary.high_risk_students} 位，中風險 {summary.medium_risk_students} 位。先把需要追蹤的學員從名單區拉出來看。</p>"
                f"<div class='meta'>{_risk_pill('high' if summary.high_risk_students else 'low', '風險提醒')}<span class='chip'>總學員 {summary.total_students}</span></div>"
                "</article>"
            ),
            (
                "<article class='focus-card'>"
                "<div class='eyebrow'>Learning Ops</div>"
                "<h3>作業與測驗節奏</h3>"
                f"<p>目前待補作業 {summary.pending_assignments} 筆、待補測驗 {summary.pending_exams} 筆，適合先清掉積壓再寫課後紀錄。</p>"
                f"<div class='meta'><span class='chip'>待補作業 {summary.pending_assignments}</span><span class='chip'>待補測驗 {summary.pending_exams}</span></div>"
                "</article>"
            ),
            (
                "<article class='focus-card'>"
                "<div class='eyebrow'>Review Flow</div>"
                "<h3>課後紀錄與主管審核</h3>"
                f"<p>這個班目前共有 {summary.session_records} 筆課後紀錄，其中 {summary.pending_session_reviews} 筆還在等主管確認。</p>"
                f"<div class='meta'><span class='chip'>課後紀錄 {summary.session_records}</span><span class='chip'>待審核 {summary.pending_session_reviews}</span></div>"
                "</article>"
            ),
        ]
    )
    student_options = "".join(
        f"<option value='{escape(item.email)}'>{escape(item.chinese_name)} / {escape(item.email)}</option>"
        for item in snapshot.roster
    )
    roster_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.risk_level)} / {escape(item.payment_status)}</div>"
            f"<h3>{escape(item.chinese_name)}</h3>"
            f"<p>{escape(item.email)}</p>"
            f"<div class='meta'>{_risk_pill(item.risk_level)}<span class='chip'>付款 {escape(item.payment_status)}</span></div>"
            f"<div class='meta'><span class='chip'>作業 {item.assignment_submitted}/{item.assignment_total}</span><span class='chip'>測驗 {item.exam_submitted}/{item.exam_total}</span></div>"
            f"<div class='meta'><span class='chip'>出席率 {item.attendance_rate:g}%</span><span class='chip'>最近出缺勤 {escape(item.latest_attendance_status or '尚無紀錄')}</span></div>"
            "</article>"
        )
        for item in snapshot.roster
    ) or "<article class='card'><h3>目前沒有學員資料</h3></article>"
    assignment_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.created_by)}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.due_at.isoformat())}</span></div>"
            "</article>"
        )
        for item in snapshot.assignments[:6]
    ) or "<article class='card'><h3>目前沒有作業</h3></article>"
    exam_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.exam_type)}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.instructions)}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.due_at.isoformat())}</span><span class='chip'>總分 {item.total_score:g}</span></div>"
            "</article>"
        )
        for item in snapshot.exams[:6]
    ) or "<article class='card'><h3>目前沒有測驗</h3></article>"
    attendance_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)}</div>"
            f"<h3>{escape(item.class_date.isoformat())}</h3>"
            f"<p>{escape(item.marked_by)}</p>"
            f"<p>{escape(item.note or '無備註')}</p>"
            "</article>"
        )
        for item in snapshot.attendance_records[:8]
    ) or "<article class='card'><h3>目前沒有出缺勤紀錄</h3></article>"
    session_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.class_date.isoformat())} / {escape(item.approval_status)}</div>"
            f"<h3>{escape(item.next_class_focus or '尚未設定下次課堂焦點')}</h3>"
            f"<p>{escape(item.summary)}</p>"
            f"<p>教材：{escape(item.materials_link or '尚未提供')}</p>"
            f"<p>作業：{escape(item.homework_summary or '尚未填寫')}</p>"
            f"<p>高風險學員：{escape(' / '.join(item.student_risk_notes) or '無')}</p>"
            f"<p>主管回覆：{escape(item.review_note or '尚未回覆')}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.reviewed_by or '待主管審核')}</span></div>"
            "</article>"
        )
        for item in snapshot.session_records[:6]
    ) or "<article class='card'><h3>目前還沒有課後紀錄</h3></article>"
    teacher_material_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>教師補充內容 / {escape(item.visibility)}</div>"
            f"<h3>{escape(item.title)}</h3>"
            f"<p>{escape(item.description)}</p>"
            f"{_material_asset_html(item, teacher_name=teacher_name, label='查看教材')}"
            f"{_material_source_html(item)}"
            f"<div class='meta'><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_by)}</span></div>"
            "</article>"
        )
        for item in teacher_materials
    ) or "<article class='card'><h3>目前沒有教師補充教材</h3><p>這個班尚未建立老師補充內容。</p></article>"
    pending_assignment_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(student_map[item.student_id].chinese_name) if item.student_id in student_map else '未知學員'} / 作業待批改</div>"
            f"<h3>{escape(assignment_map[item.assignment_id].title) if item.assignment_id in assignment_map else '未知作業'}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<div class='meta'><span class='chip'>{escape(student_map[item.student_id].email) if item.student_id in student_map else '未知 Email'}</span><span class='chip'>{escape(item.submitted_at.isoformat())}</span></div>"
            f"<form class='stack' method='post' action='/school-platform/teacher/assignment-submissions/{item.id}/grade'>"
            f"<input type='hidden' name='teacher_name' value='{escape(teacher_name)}' />"
            f"<input type='hidden' name='graded_by' value='{escape(teacher_name)}' />"
            f"<input type='hidden' name='return_to' value='{escape(class_detail_return_to)}' />"
            "<label class='field'>分數<input type='number' name='score' min='0' max='100' step='1' value='85' /></label>"
            "<label class='field'>回饋<textarea name='feedback' placeholder='輸入這位學員的作業評語'></textarea></label>"
            "<button class='btn' type='submit'>送出作業評分</button>"
            "</form>"
            "</article>"
        )
        for item in sorted(snapshot.assignment_submissions, key=lambda record: record.submitted_at, reverse=True)
        if item.status != "graded"
    ) or "<article class='card'><h3>目前沒有待批改作業</h3></article>"
    pending_exam_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(student_map[item.student_id].chinese_name) if item.student_id in student_map else '未知學員'} / 測驗待批改</div>"
            f"<h3>{escape(exam_map[item.exam_id].title) if item.exam_id in exam_map else '未知測驗'}</h3>"
            f"<p>{escape(item.content)}</p>"
            f"<div class='meta'><span class='chip'>{escape(student_map[item.student_id].email) if item.student_id in student_map else '未知 Email'}</span><span class='chip'>{escape(item.submitted_at.isoformat())}</span></div>"
            f"<form class='stack' method='post' action='/school-platform/teacher/exam-submissions/{item.id}/grade'>"
            f"<input type='hidden' name='teacher_name' value='{escape(teacher_name)}' />"
            f"<input type='hidden' name='graded_by' value='{escape(teacher_name)}' />"
            f"<input type='hidden' name='return_to' value='{escape(class_detail_return_to)}' />"
            "<label class='field'>分數<input type='number' name='score' min='0' max='100' step='1' value='88' /></label>"
            "<label class='field'>回饋<textarea name='feedback' placeholder='輸入這位學員的測驗評語'></textarea></label>"
            "<button class='btn' type='submit'>送出測驗評分</button>"
            "</form>"
            "</article>"
        )
        for item in sorted(snapshot.exam_submissions, key=lambda record: record.submitted_at, reverse=True)
        if item.status != "graded"
    ) or "<article class='card'><h3>目前沒有待批改測驗</h3></article>"
    body = f"""
      <section class="hero">
        <div class="workspace-hero-grid">
          <div class="workspace-copy">
            <div class="eyebrow">Teacher Class Detail</div>
            <h1>班級教學詳情</h1>
            <p>{escape(class_item.name)} / {escape(class_item.course_slug)} / {escape(class_item.weekday)} {escape(class_item.start_time.strftime('%H:%M'))}-{escape(class_item.end_time.strftime('%H:%M'))}</p>
            <div class="meta">
              <span class="chip">{escape(class_item.location_label)}</span>
              <span class="chip">{class_item.enrolled_count}/{class_item.capacity}</span>
              {_risk_pill("high" if summary.high_risk_students else "low", "班級風險")}
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/teacher-portal?teacher_name={escape(teacher_name)}">回教師工作台</a>
              <a class="btn alt" href="/school-platform/api/teacher/classes/{class_item.id}?teacher_name={escape(teacher_name)}">查看班級 JSON</a>
            </div>
          </div>
          <article class="workspace-panel">
            <div class="eyebrow">Class Pulse</div>
            <h2>先處理這個班最容易卡住的地方</h2>
            <div class="data-points">{class_pulse}</div>
            <div class="task-list">{_render_task_items(class_tasks)}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Class Workflow</div>
            <h2>班級工作捷徑</h2>
          </div>
          <p class="section-subtitle">點名、課後紀錄、名單與批改都在同一頁，先從你現在要處理的區塊進去即可。</p>
        </div>
        <div class="portal-nav-grid">{class_nav}</div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">學員數</div><div class="value">{summary.total_students}</div></div>
          <div class="stat"><div class="label">高風險</div><div class="value">{summary.high_risk_students}</div></div>
          <div class="stat"><div class="label">中風險</div><div class="value">{summary.medium_risk_students}</div></div>
          <div class="stat"><div class="label">待補作業</div><div class="value">{summary.pending_assignments}</div></div>
          <div class="stat"><div class="label">待補測驗</div><div class="value">{summary.pending_exams}</div></div>
          <div class="stat"><div class="label">出缺勤紀錄</div><div class="value">{summary.attendance_records}</div></div>
          <div class="stat"><div class="label">課後紀錄</div><div class="value">{summary.session_records}</div></div>
          <div class="stat"><div class="label">待審核</div><div class="value">{summary.pending_session_reviews}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Class Health</div>
            <h2>班級健康摘要</h2>
          </div>
          <p class="section-subtitle">先用這一區快速判斷這個班現在卡在風險學員、批改進度，還是課後紀錄審核。</p>
        </div>
        <div class="focus-grid">{class_focus_cards}</div>
      </section>
      <section id="class-roster" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Roster</div>
            <h2>學員名單</h2>
          </div>
          <p class="section-subtitle">每位學員的風險、付款、作業、測驗與出席率都壓在同一張卡上，方便老師先做教學判斷。</p>
        </div>
        <div class="grid two">{roster_cards}</div>
      </section>
      <section id="attendance-form" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Attendance</div>
            <h2>快速點名</h2>
          </div>
          <p class="section-subtitle">授課結束後先補出缺勤，再決定要不要把異常狀況寫進課後紀錄與風險備註。</p>
        </div>
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Attendance Form</div>
            <h3>送出本堂點名</h3>
            <form class="stack" method="post" action="/school-platform/teacher/classes/{class_item.id}/attendance">
              <input type="hidden" name="teacher_name" value="{escape(teacher_name)}" />
              <label class="field">學員
                <select name="student_email">{student_options}</select>
              </label>
              <label class="field">上課日期
                <input type="date" name="class_date_value" value="{date.today().isoformat()}" />
              </label>
              <label class="field">出席狀態
                <select name="status_value">
                  <option value="present">present</option>
                  <option value="late">late</option>
                  <option value="leave">leave</option>
                  <option value="absent">absent</option>
                </select>
              </label>
              <label class="field">備註
                <textarea name="note" placeholder="例如：遲到 10 分鐘、請假已提前通知"></textarea>
              </label>
              <button class="btn" type="submit">送出點名</button>
            </form>
          </article>
          <article class="card">
            <div class="eyebrow">Execution Snapshot</div>
            <h3>班級執行摘要</h3>
            <p>目前學員數：<code>{summary.total_students}</code></p>
            <p>待補作業：<code>{summary.pending_assignments}</code></p>
            <p>待補測驗：<code>{summary.pending_exams}</code></p>
            <p>待審核課後紀錄：<code>{summary.pending_session_reviews}</code></p>
            <p>若班級內已經收到作業或測驗提交，可直接在下方完成批改，不需要回上一層工作台。</p>
          </article>
        </div>
      </section>
      <section id="session-record-form" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Session Records</div>
            <h2>新增 / 更新課後紀錄</h2>
          </div>
          <p class="section-subtitle">把教材連結、作業、下次課程焦點與高風險學員備註一次補齊，主管也能直接沿用這份紀錄審核。</p>
        </div>
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Record Form</div>
            <h3>填寫本堂課後紀錄</h3>
            <form class="stack" method="post" action="/school-platform/teacher/classes/{class_item.id}/session-records">
              <input type="hidden" name="teacher_name" value="{escape(teacher_name)}" />
              <input type="hidden" name="return_to" value="{escape(class_detail_return_to)}" />
              <label class="field">上課日期
                <input type="date" name="class_date_value" value="{date.today().isoformat()}" />
              </label>
              <label class="field">本堂摘要
                <textarea name="summary_text" placeholder="例如：完成租屋問答、藥局購藥句型、生活敬語練習"></textarea>
              </label>
              <label class="field">教材 / 講義連結
                <input type="url" name="materials_link" placeholder="https://..." />
              </label>
              <label class="field">課後作業
                <textarea name="homework_summary" placeholder="例如：錄一段 60 秒租屋自我介紹"></textarea>
              </label>
              <label class="field">下次課堂焦點
                <input type="text" name="next_class_focus" placeholder="例如：病院掛號與症狀描述" />
              </label>
              <label class="field">高風險學員備註
                <textarea name="student_risk_notes" placeholder="每行一位，例如：王小明：連續兩週未交作業"></textarea>
              </label>
              <label class="field">送出方式
                <select name="approval_status_value">
                  <option value="submitted">submitted</option>
                  <option value="draft">draft</option>
                </select>
              </label>
              <button class="btn" type="submit">儲存課後紀錄</button>
            </form>
          </article>
          <article class="card">
            <div class="eyebrow">Recent Records</div>
            <h3>最近課後紀錄</h3>
            <div class="list">{session_cards}</div>
          </article>
        </div>
      </section>
      <section id="teacher-materials" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Teacher Materials</div>
            <h2>教師補充教材</h2>
          </div>
          <p class="section-subtitle">這裡只放老師針對這個班補充的內容，平台核心課綱與標準教材不會被直接覆寫。</p>
        </div>
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Material Form</div>
            <h3>新增班級補充教材</h3>
            <form class="stack" method="post" enctype="multipart/form-data" action="/school-platform/teacher/classes/{class_item.id}/materials">
              <input type="hidden" name="teacher_name" value="{escape(teacher_name)}" />
              <label class="field">教材名稱
                <input type="text" name="title" placeholder="例如：藥局會話補充講義" />
              </label>
              <label class="field">教材說明
                <textarea name="description" placeholder="描述這份教材是補哪個情境、給哪一類學員用"></textarea>
              </label>
              <label class="field">教材連結
                <input type="url" name="material_url" placeholder="https://..." />
              </label>
              <label class="field">或上傳檔案
                <input type="file" name="uploaded_file" />
              </label>
              <label class="field">可見範圍
                <select name="visibility">
                  <option value="enrolled_only">enrolled_only</option>
                  <option value="internal">internal</option>
                  <option value="public">public</option>
                </select>
              </label>
              <button class="btn" type="submit">新增補充教材</button>
            </form>
          </article>
          <article class="card">
            <div class="eyebrow">Boundary</div>
            <h3>內容邊界</h3>
            <div class="helper-list">
              <div>平台核心課程：由平台課程團隊維護。</div>
              <div>教師補充教材：針對班級狀況額外補充，不等於正式課程標準。</div>
              <div>對外顯示時，系統會保留內容來源標示。</div>
            </div>
          </article>
        </div>
        <div class="grid two">{teacher_material_cards}</div>
      </section>
      <section id="class-assignment-reviews" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Assignment Reviews</div>
            <h2>待批改作業</h2>
          </div>
          <p class="section-subtitle">先把尚未評分的作業清掉，才能讓學員端與主管端看到最新的學習回饋。</p>
        </div>
        <div class="grid two">{pending_assignment_cards}</div>
      </section>
      <section id="class-exam-reviews" class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Exam Reviews</div>
            <h2>待批改測驗</h2>
          </div>
          <p class="section-subtitle">測驗分數與回饋會直接影響學員進度與風險判斷，這裡建議每週固定清一次。</p>
        </div>
        <div class="grid two">{pending_exam_cards}</div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Teaching Assets</div>
            <h2>作業與測驗總覽</h2>
          </div>
          <p class="section-subtitle">這裡保留這個班目前已建立的作業與測驗內容，方便老師在批改前快速回看題目與截止時間。</p>
        </div>
        <div class="grid two">
          <article class="card">
            <div class="eyebrow">Assignments</div>
            <h3>作業</h3>
            <div class="list">{assignment_cards}</div>
          </article>
          <article class="card">
            <div class="eyebrow">Exams</div>
            <h3>測驗</h3>
            <div class="list">{exam_cards}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="section-head">
          <div>
            <div class="eyebrow">Recent Attendance</div>
            <h2>最近出缺勤</h2>
          </div>
          <p class="section-subtitle">這裡會把最近的點名紀錄集中列出，方便老師快速確認異常出席模式是否持續發生。</p>
        </div>
        <div class="grid two">{attendance_cards}</div>
      </section>
    """
    return _page_shell(f"{class_item.name} 班級教學詳情", body)


@router.get("/admin/recruiting", response_class=HTMLResponse)
def school_platform_admin_recruiting_page() -> str:
    summary = recruiting_service.recruiting_summary()
    jobs = recruiting_service.list_jobs()
    applicants = recruiting_service.list_applicants()
    interviews = recruiting_service.list_interviews()
    job_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.department)} / {escape(item.employment_type)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.summary)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.salary_range)}</span><span class='chip'>{escape(item.status)}</span></div>"
        "</article>"
        for item in jobs
    ) or "<article class='card'><h3>目前沒有職缺</h3></article>"
    applicant_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(str(item.ai_match_score))}</div>"
        f"<h3>{escape(item.name)}</h3>"
        f"<p>{escape(item.email)}</p>"
        f"<p>狀態：{escape(item.interview_status)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/recruiting/applicants/{item.id}'>查看應徵者詳情</a></div>"
        "</article>"
        for item in applicants[:6]
    ) or "<article class='card'><h3>目前沒有應徵者</h3></article>"
    interview_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.status)}</div>"
        f"<h3>{escape(item.interviewer_name)}</h3>"
        f"<p>{escape(item.interview_at.isoformat())}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.format)}</span></div>"
        "</article>"
        for item in interviews[:6]
    ) or "<article class='card'><h3>目前沒有面試</h3></article>"
    applicant_options = "".join(
        f"<option value='{item.id}'>{escape(item.name)} / {escape(item.email)}</option>"
        for item in applicants
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Recruiting Admin</div>
        <h1>招聘管理</h1>
        <p>這裡把公開職缺、應徵者、面試排程接進同一個後台，開始形成完整營運平台的一部分。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/jobs">打開公開招聘頁</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">開放職缺</div><div class="value">{summary['open_jobs']}</div></div>
          <div class="stat"><div class="label">應徵者</div><div class="value">{summary['applicants']}</div></div>
          <div class="stat"><div class="label">已排面試</div><div class="value">{summary['scheduled_interviews']}</div></div>
          <div class="stat"><div class="label">進行中 onboarding</div><div class="value">{summary['active_onboarding']}</div></div>
          <div class="stat"><div class="label">試用期追蹤</div><div class="value">{summary['active_probation']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>新增職缺</h2>
            <form class="stack" method="post" action="/school-platform/admin/recruiting/jobs/create">
              <label class="field">職缺名稱<input type="text" name="title" /></label>
              <label class="field">部門<input type="text" name="department" value="Teaching" /></label>
              <label class="field">聘用形式<input type="text" name="employment_type" value="part_time" /></label>
              <label class="field">地點<input type="text" name="location_label" value="Taipei / Remote" /></label>
              <label class="field">薪資範圍<input type="text" name="salary_range" value="JPY 200,000 - 320,000 / month" /></label>
              <label class="field">摘要<textarea name="summary"></textarea></label>
              <label class="field">需求條件<textarea name="requirements"></textarea></label>
              <button class="btn" type="submit">建立職缺</button>
            </form>
          </article>
          <article class="card">
            <h2>安排面試</h2>
            <form class="stack" method="post" action="/school-platform/admin/recruiting/interviews/create">
              <label class="field">應徵者
                <select name="applicant_id">{applicant_options}</select>
              </label>
              <label class="field">面試時間
                <input type="datetime-local" name="interview_at" />
              </label>
              <label class="field">面試官<input type="text" name="interviewer_name" value="Yuki Wang" /></label>
              <label class="field">形式
                <select name="format">
                  <option value="google_meet">google_meet</option>
                  <option value="onsite">onsite</option>
                  <option value="phone">phone</option>
                </select>
              </label>
              <button class="btn" type="submit">安排面試</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>職缺</h2>
        <div class="grid two">{job_cards}</div>
      </section>
      <section class="section">
        <h2>應徵者</h2>
        <div class="grid two">{applicant_cards}</div>
      </section>
      <section class="section">
        <h2>面試排程</h2>
        <div class="grid two">{interview_cards}</div>
      </section>
    """
    return _page_shell("招聘管理", body)


@router.get("/admin/recruiting/applicants/{applicant_id}", response_class=HTMLResponse)
def school_platform_admin_applicant_detail_page(applicant_id: UUID) -> str:
    try:
        snapshot = recruiting_service.applicant_detail(applicant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc

    applicant = snapshot.applicant
    position = snapshot.position
    evaluation = snapshot.evaluation
    applicant_note = escape(applicant.note or "未填寫").replace("\n", "<br />")
    applicant_status_options = "".join(
        f"<option value='{value}' {'selected' if applicant.interview_status == value else ''}>{value}</option>"
        for value in ["reviewing", "scheduled", "interviewing", "shortlisted", "offer_sent", "hired", "rejected", "talent_pool"]
    )
    interview_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)} / {escape(item.format)}</div>"
            f"<h3>{escape(item.interviewer_name)}</h3>"
            f"<p>{escape(item.interview_at.isoformat())}</p>"
            f"<p>{escape(item.feedback or '尚未填寫回饋').replace(chr(10), '<br />')}</p>"
            f"<form class='stack' method='post' action='/school-platform/admin/recruiting/interviews/{item.id}/review'>"
            "<label class='field'>面試狀態"
            "<select name='interview_status_value'>"
            + "".join(
                f"<option value='{value}' {'selected' if item.status == value else ''}>{value}</option>"
                for value in ["scheduled", "completed", "shortlisted", "offer_sent", "hired", "rejected", "no_show", "cancelled"]
            )
            + "</select></label>"
            "<label class='field'>案件階段"
            f"<select name='applicant_status'>{applicant_status_options}</select>"
            "</label>"
            "<label class='field'>面試回饋"
            f"<textarea name='feedback' placeholder='輸入面試觀察與建議'>{escape(item.feedback or '')}</textarea>"
            "</label>"
            "<label class='field'>HR 備註"
            "<textarea name='note' placeholder='例如：可進第二輪試教，或先放人才庫觀察'></textarea>"
            "</label>"
            "<button class='btn' type='submit'>儲存面試結論</button>"
            "</form>"
            "</article>"
        )
        for item in snapshot.interviews
    ) or "<article class='card'><h3>目前沒有面試紀錄</h3></article>"
    strength_items = "".join(f"<li>{escape(item)}</li>" for item in evaluation.strengths)
    concern_items = "".join(f"<li>{escape(item)}</li>" for item in evaluation.concerns) or "<li>目前沒有明顯風險</li>"
    question_items = "".join(f"<li>{escape(item)}</li>" for item in evaluation.suggested_questions)
    onboarding = snapshot.onboarding
    onboarding_stage_options = "".join(
        f"<option value='{value}' {'selected' if onboarding and onboarding.stage == value else ''}>{value}</option>"
        for value in ["preboarding", "docs_pending", "orientation_scheduled", "active", "completed", "cancelled"]
    )
    probation_status_options = "".join(
        f"<option value='{value}' {'selected' if onboarding and onboarding.probation_status == value else ''}>{value}</option>"
        for value in ["not_started", "in_progress", "passed", "extended", "ended"]
    )
    onboarding_checklist_text = "\n".join(onboarding.checklist_items) if onboarding and onboarding.checklist_items else ""
    body = f"""
      <section class="hero">
        <div class="eyebrow">Applicant Detail</div>
        <h1>應徵者詳情</h1>
        <p>這裡把職缺資訊、AI 配對評估與面試排程集中在同一頁，讓 HR 可直接往下處理。</p>
        <div class="meta">
          <span class="chip">{escape(applicant.name)}</span>
          <span class="chip">{escape(position.title)}</span>
          <span class="chip">AI 配對 {evaluation.ai_match_score:g}</span>
          <span class="chip">{escape(applicant.interview_status)}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/recruiting">回招聘管理</a>
          <a class="btn alt" href="/school-platform/api/recruiting/applicants/{applicant.id}">查看案件 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>基本資料</h2>
            <p>Email：{escape(applicant.email)}</p>
            <p>電話：{escape(applicant.phone or '未填寫')}</p>
            <p>履歷：{escape(applicant.resume_link or '未附連結')}</p>
            <p>備註：{applicant_note}</p>
            <p>職缺：{escape(position.title)} / {escape(position.department)}</p>
          </article>
          <article class="card">
            <h2>AI 評估建議</h2>
            <p>Recommendation：<code>{escape(evaluation.recommendation)}</code></p>
            <p>下一步：{escape(evaluation.next_action)}</p>
            <ul class="clean">{strength_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>風險提醒</h2>
            <ul class="clean">{concern_items}</ul>
          </article>
          <article class="card">
            <h2>建議面試題</h2>
            <ul class="clean">{question_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>安排面試</h2>
            <form class="stack" method="post" action="/school-platform/admin/recruiting/interviews/create">
              <input type="hidden" name="applicant_id" value="{applicant.id}" />
              <input type="hidden" name="return_to" value="/school-platform/admin/recruiting/applicants/{applicant.id}" />
              <label class="field">面試時間
                <input type="datetime-local" name="interview_at" />
              </label>
              <label class="field">面試官
                <input type="text" name="interviewer_name" value="Yuki Wang" />
              </label>
              <label class="field">形式
                <select name="format">
                  <option value="google_meet">google_meet</option>
                  <option value="zoom">zoom</option>
                  <option value="onsite">onsite</option>
                </select>
              </label>
              <button class="btn" type="submit">安排面試</button>
            </form>
          </article>
          <article class="card">
            <h2>更新案件進度</h2>
            <form class="stack" method="post" action="/school-platform/admin/recruiting/applicants/{applicant.id}/status">
              <label class="field">案件階段
                <select name="interview_status">{applicant_status_options}</select>
              </label>
              <label class="field">HR 備註
                <textarea name="note" placeholder="例如：先安排試教、待主管 final review、或放入人才庫"></textarea>
              </label>
              <button class="btn" type="submit">儲存案件進度</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>案件摘要</h2>
            <p>建立時間：<code>{escape(applicant.created_at.isoformat())}</code></p>
            <p>職缺需求：{escape(position.summary)}</p>
            <p>需求條件：{escape(' / '.join(position.requirements) if position.requirements else '未填寫')}</p>
          </article>
          <article class="card">
            <h2>面試流程建議</h2>
            <p>目前階段：<code>{escape(applicant.interview_status)}</code></p>
            <p>建議下一步：{escape(evaluation.next_action)}</p>
            <p>若已完成面談，可直接在下方面試紀錄卡填寫評語、更新案件階段，並推進到錄取或婉拒。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>到職 / 試用追蹤</h2>
            <p>Onboarding：<code>{escape(onboarding.stage if onboarding else 'not_created')}</code></p>
            <p>Probation：<code>{escape(onboarding.probation_status if onboarding else 'not_started')}</code></p>
            <p>Owner：{escape(onboarding.owner_name if onboarding else 'Yuki Wang')}</p>
            <p>預計報到：{escape(onboarding.start_date.isoformat() if onboarding and onboarding.start_date else '未設定')}</p>
            <p>試用期結束：{escape(onboarding.probation_end_date.isoformat() if onboarding and onboarding.probation_end_date else '未設定')}</p>
            <p>備註：{escape(onboarding.notes or '尚未填寫').replace(chr(10), '<br />') if onboarding else '尚未建立 onboarding 紀錄，錄取後可直接在右側建立。'}</p>
          </article>
          <article class="card">
            <h2>更新 onboarding / probation</h2>
            <form class="stack" method="post" action="/school-platform/admin/recruiting/applicants/{applicant.id}/onboarding">
              <label class="field">Owner
                <input type="text" name="owner_name" value="{escape(onboarding.owner_name if onboarding else 'Yuki Wang')}" />
              </label>
              <label class="field">Onboarding 階段
                <select name="stage">{onboarding_stage_options}</select>
              </label>
              <label class="field">報到日
                <input type="date" name="start_date" value="{escape(onboarding.start_date.isoformat() if onboarding and onboarding.start_date else '')}" />
              </label>
              <label class="field">Probation 狀態
                <select name="probation_status">{probation_status_options}</select>
              </label>
              <label class="field">試用期結束日
                <input type="date" name="probation_end_date" value="{escape(onboarding.probation_end_date.isoformat() if onboarding and onboarding.probation_end_date else '')}" />
              </label>
              <label class="field">Checklist
                <textarea name="checklist_items" placeholder="一行一項">{escape(onboarding_checklist_text)}</textarea>
              </label>
              <label class="field">備註
                <textarea name="notes" placeholder="例如：報到第一週需完成系統權限與教學觀課">{escape(onboarding.notes or '') if onboarding else ''}</textarea>
              </label>
              <button class="btn" type="submit">儲存 onboarding / probation</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>面試紀錄與評分</h2>
        <div class="grid two">{interview_cards}</div>
      </section>
    """
    return _page_shell("應徵者詳情", body)


@router.get("/admin/executive", response_class=HTMLResponse)
def school_platform_admin_executive_page() -> str:
    snapshot = executive_dashboard_service.snapshot()
    summary = snapshot.summary
    learning_report = analytics_service.student_learning_report()
    franchise_report = analytics_service.franchise_group_report()
    alert_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(alert.severity)}</div>"
            f"<h3>{escape(alert.title)}</h3>"
            f"<p>{escape(alert.detail)}</p>"
            "</article>"
        )
        for alert in snapshot.alerts
    ) or "<article class='card'><h3>目前沒有營運警示</h3></article>"
    lead_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.status)} / {escape(item.interested_course_slug or 'general')}</div>"
            f"<h3>{escape(item.name)}</h3>"
            f"<p>{escape(item.latest_log_summary or '尚無最新跟進摘要')}</p>"
            f"<div class='meta'><span class='chip'>意向 {item.intent_score:g}</span><span class='chip'>成交率 {item.win_probability:g}%</span></div>"
            "</article>"
        )
        for item in snapshot.hot_leads
    ) or "<article class='card'><h3>目前沒有高熱度名單</h3></article>"
    risk_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.risk_level)} / {escape(item.weak_spot)}</div>"
            f"<h3>{escape(item.chinese_name)}</h3>"
            f"<p>{escape(item.email)}</p>"
            f"<div class='meta'><span class='chip'>待補作業 {item.pending_assignments}</span><span class='chip'>待補測驗 {item.pending_exams}</span><span class='chip'>出席率 {item.attendance_rate:g}%</span></div>"
            "</article>"
        )
        for item in snapshot.high_risk_students
    ) or "<article class='card'><h3>目前沒有高風險學員</h3></article>"
    class_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.course_slug)} / {escape(item.teacher_name)}</div>"
            f"<h3>{escape(item.class_name)}</h3>"
            f"<p>滿班率 {item.fill_rate:g}% / 剩餘名額 {item.seats_left}</p>"
            f"<div class='meta'><span class='chip'>{item.enrolled_count}/{item.capacity}</span></div>"
            "</article>"
        )
        for item in snapshot.class_watchlist
    ) or "<article class='card'><h3>目前沒有班級容量資料</h3></article>"
    ai_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.module_name)}</div>"
            f"<h3>最近 7 天使用 {item.action_count} 次</h3>"
            f"<p>最近動作：{escape(item.latest_action_name or 'unknown')}</p>"
            f"<div class='meta'><span class='chip'>{escape(item.latest_at.isoformat() if item.latest_at else 'n/a')}</span></div>"
            "</article>"
        )
        for item in snapshot.ai_module_usage
    ) or "<article class='card'><h3>最近 7 天尚無 AI 使用紀錄</h3></article>"
    recommendation_items = "".join(f"<li>{escape(item)}</li>" for item in snapshot.recommendations)
    body = f"""
      <section class="hero">
        <div class="eyebrow">Executive Dashboard</div>
        <h1>主管工作台</h1>
        <p>把招生、學員、財務、教務、客服、招聘與 AI 使用整合成單一營運決策頁，讓主管直接抓到現在最該處理的事情。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/admin/executive-dashboard">查看主管 JSON</a>
          <a class="btn alt" href="/school-platform/admin/reports">前往報表中心</a>
        </div>
      </section>
      <section class="section">
        <h2>核心摘要</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">進行中班級</div><div class="value">{summary.active_classes}</div></div>
          <div class="stat"><div class="label">進行中學員</div><div class="value">{summary.active_students}</div></div>
          <div class="stat"><div class="label">逾期跟進</div><div class="value">{summary.overdue_follow_ups}</div></div>
          <div class="stat"><div class="label">高風險學員</div><div class="value">{summary.high_risk_students}</div></div>
          <div class="stat"><div class="label">待評分</div><div class="value">{summary.pending_reviews}</div></div>
          <div class="stat"><div class="label">待處理客服</div><div class="value">{summary.queued_support_cases}</div></div>
          <div class="stat"><div class="label">已收營收</div><div class="value">{_format_jpy(summary.paid_revenue)}</div></div>
          <div class="stat"><div class="label">待收營收</div><div class="value">{_format_jpy(summary.pending_revenue)}</div></div>
          <div class="stat"><div class="label">開放職缺</div><div class="value">{summary.open_jobs}</div></div>
          <div class="stat"><div class="label">應徵者</div><div class="value">{summary.applicants}</div></div>
          <div class="stat"><div class="label">面試安排</div><div class="value">{summary.scheduled_interviews}</div></div>
          <div class="stat"><div class="label">AI 7 日使用</div><div class="value">{summary.ai_actions_last_7_days}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>營運警示</h2>
        <div class="grid two">{alert_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>線上學習追蹤</h2>
            <p>管理區可直接查看目前線上學習紀錄，持續追蹤作業、測驗、出缺勤與高風險學員變化。</p>
            <div class="meta">
              <span class="chip">活躍學員 {learning_report.summary.active_students}</span>
              <span class="chip">高風險 {learning_report.summary.high_risk_students}</span>
              <span class="chip">活動數 {learning_report.summary.recent_activity_count}</span>
              <span class="chip">平均出席率 {learning_report.summary.average_attendance_rate:g}%</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/reports/learning">打開線上學習報表</a>
              <a class="btn alt" href="/school-platform/api/reports/student-learning">查看學習 JSON</a>
            </div>
          </article>
          <article class="card">
            <h2>加盟組招商追蹤</h2>
            <p>三個加盟組的名單漏斗、已售區域、加盟收入與月費都已整理成管理區可直接查看的報表。</p>
            <div class="meta">
              <span class="chip">加盟組 {franchise_report.summary.total_groups}</span>
              <span class="chip">活躍夥伴 {franchise_report.summary.total_partner_count}</span>
              <span class="chip">已售區域 {franchise_report.summary.sold_regions}/{franchise_report.summary.total_regions}</span>
              <span class="chip">綜合轉換率 {franchise_report.summary.blended_conversion_rate:g}%</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/reports/franchise">打開加盟組報表</a>
              <a class="btn alt" href="/school-platform/api/reports/franchise-groups">查看加盟 JSON</a>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article>
            <h2>熱度最高名單</h2>
            <div class="list">{lead_cards}</div>
          </article>
          <article>
            <h2>高風險學員</h2>
            <div class="list">{risk_cards}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article>
            <h2>班級容量觀察</h2>
            <div class="list">{class_cards}</div>
          </article>
          <article>
            <h2>AI 模組使用</h2>
            <div class="list">{ai_cards}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>本週建議</h2>
        <ul class="clean">{recommendation_items}</ul>
      </section>
    """
    return _page_shell("主管工作台", body)


@router.get("/admin/reports", response_class=HTMLResponse)
def school_platform_admin_reports_page() -> str:
    report = analytics_service.report_overview()
    weekly = analytics_service.weekly_ai_summary()
    learning_report = analytics_service.student_learning_report()
    franchise_report = analytics_service.franchise_group_report()
    lead_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(status_value)}</h3>"
        f"<p>名單數：{count}</p>"
        "</article>"
        for status_value, count in report.lead_status_counts.items()
    ) or "<article class='card'><h3>尚無名單資料</h3></article>"
    fill_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(str(item['class_name']))}</h3>"
        f"<p>{escape(str(item['course_slug']))}</p>"
        f"<div class='meta'><span class='chip'>滿班率 {item['fill_rate']}%</span><span class='chip'>{item['enrolled_count']}/{item['capacity']}</span></div>"
        "</article>"
        for item in report.course_fill_rates[:6]
    ) or "<article class='card'><h3>尚無班級資料</h3></article>"
    learning_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.risk_level)} / {escape(item.weak_spot)}</div>"
        f"<h3>{escape(item.chinese_name)}</h3>"
        f"<p>{escape(item.email)}</p>"
        f"<div class='meta'><span class='chip'>活動 {item.activity_count}</span><span class='chip'>出席率 {item.attendance_rate:g}%</span><span class='chip'>整體 {(f'{item.overall_score:g}' if item.overall_score is not None else 'N/A')}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/my-progress?email={escape(item.email)}'>查看學員進度</a></div>"
        "</article>"
        for item in learning_report.items[:4]
    ) or "<article class='card'><h3>尚無學習紀錄</h3></article>"
    franchise_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.partner_type)}</div>"
        f"<h3>{escape(item.group_name)}</h3>"
        f"<p>加盟夥伴 {item.partner_count} / 區域 {item.sold_regions}/{item.total_regions or item.sold_regions}</p>"
        f"<div class='meta'><span class='chip'>名單 {item.total_leads}</span><span class='chip'>成交 {item.enrolled_leads}</span><span class='chip'>轉換 {item.conversion_rate:g}%</span></div>"
        f"<div class='meta'><span class='chip'>加盟收入 {_format_jpy(item.booked_join_fee_revenue_jpy)}</span><span class='chip'>月費 {_format_jpy(item.monthly_recurring_revenue_jpy)}</span></div>"
        "</article>"
        for item in franchise_report.groups
    ) or "<article class='card'><h3>尚無加盟組報表</h3></article>"
    insight_items = "".join(f"<li>{escape(str(item))}</li>" for item in weekly["insights"])
    action_items = "".join(f"<li>{escape(str(item))}</li>" for item in weekly["actions"])
    body = f"""
      <section class="hero">
        <div class="eyebrow">Reports Center</div>
        <h1>報表中心</h1>
        <p>這裡把招生、班級滿班率、營收、招聘與教務資料整理成主管可直接看的中文儀表板。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/admin/executive">打開主管工作台</a>
          <a class="btn alt" href="/school-platform/api/reports/overview">查看報表 JSON</a>
          <a class="btn alt" href="/school-platform/admin/reports/learning">線上學習紀錄</a>
          <a class="btn alt" href="/school-platform/admin/reports/franchise">加盟組招生報表</a>
          <a class="btn alt" href="/school-platform/admin/ai-center">查看 AI 助理中心</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">已收營收</div><div class="value">{_format_jpy(report.revenue_summary['paid'])}</div></div>
          <div class="stat"><div class="label">待收營收</div><div class="value">{_format_jpy(report.revenue_summary['pending'])}</div></div>
          <div class="stat"><div class="label">應徵者</div><div class="value">{report.recruiting_summary['applicants']}</div></div>
          <div class="stat"><div class="label">作業數</div><div class="value">{report.teaching_summary['assignments']}</div></div>
          <div class="stat"><div class="label">學習活動</div><div class="value">{learning_report.summary.recent_activity_count}</div></div>
          <div class="stat"><div class="label">活躍加盟夥伴</div><div class="value">{franchise_report.summary.total_partner_count}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>名單狀態分布</h2>
        <div class="grid two">{lead_cards}</div>
      </section>
      <section class="section">
        <h2>班級滿班率</h2>
        <div class="grid two">{fill_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article>
            <h2>線上學習紀錄摘要</h2>
            <p>目前線上學習紀錄以作業提交、測驗提交、出缺勤與整體評估作為主要來源。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/reports/learning">打開學習紀錄報表</a>
              <a class="btn alt" href="/school-platform/api/reports/student-learning">查看學習報表 JSON</a>
            </div>
            <div class="grid two">{learning_cards}</div>
          </article>
          <article>
            <h2>加盟組招生流程摘要</h2>
            <p>管理區可直接查看三個加盟組的招商漏斗、區域銷售狀態與加盟收入概況。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/admin/reports/franchise">打開加盟組報表</a>
              <a class="btn alt" href="/school-platform/api/reports/franchise-groups">查看加盟報表 JSON</a>
            </div>
            <div class="grid two">{franchise_cards}</div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>{escape(str(weekly['headline']))}</h2>
            <ul class="clean">{insight_items}</ul>
          </article>
          <article class="card">
            <h2>建議動作</h2>
            <ul class="clean">{action_items}</ul>
          </article>
        </div>
      </section>
    """
    return _page_shell("報表中心", body)


@router.get("/admin/reports/learning", response_class=HTMLResponse)
def school_platform_admin_learning_reports_page() -> str:
    snapshot = analytics_service.student_learning_report()
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.risk_level)} / {escape(item.weak_spot)}</div>"
            f"<h3>{escape(item.chinese_name)}</h3>"
            f"<p>{escape(item.email)}</p>"
            f"<div class='meta'><span class='chip'>進行中課程 {item.active_course_count}</span><span class='chip'>活動 {item.activity_count}</span><span class='chip'>最近活動 {escape(item.last_activity_at.isoformat() if item.last_activity_at else 'n/a')}</span></div>"
            f"<div class='meta'><span class='chip'>作業 {item.assignment_submitted}/{item.assignment_submitted + item.assignment_pending}</span><span class='chip'>測驗 {item.exam_submitted}/{item.exam_submitted + item.exam_pending}</span><span class='chip'>出席率 {item.attendance_rate:g}%</span></div>"
            f"<ul class='clean'>{''.join(f'<li>{escape(activity.title)} / {escape(activity.class_name)} / {escape(activity.status)}</li>' for activity in item.recent_activities) or '<li>尚無活動紀錄</li>'}</ul>"
            f"<div class='actions'><a class='btn' href='/school-platform/my-progress?email={escape(item.email)}'>查看學員進度</a></div>"
            "</article>"
        )
        for item in snapshot.items
    ) or "<article class='card'><h3>目前沒有線上學習紀錄</h3></article>"
    average_score = f"{snapshot.summary.average_overall_score:.1f}" if snapshot.summary.average_overall_score is not None else "N/A"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Online Learning Reports</div>
        <h1>線上學習紀錄報表</h1>
        <p>目前線上學習紀錄已經納入作業、測驗、出缺勤與最近活動，方便教務與管理區查看實際線上學習是否持續發生。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/reports">回報表中心</a>
          <a class="btn alt" href="/school-platform/api/reports/student-learning">查看學習報表 JSON</a>
          <a class="btn alt" href="/school-platform/admin/student-progress">回學習進度總覽</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">學員數</div><div class="value">{snapshot.summary.total_students}</div></div>
          <div class="stat"><div class="label">活躍學員</div><div class="value">{snapshot.summary.active_students}</div></div>
          <div class="stat"><div class="label">高風險</div><div class="value">{snapshot.summary.high_risk_students}</div></div>
          <div class="stat"><div class="label">學習活動</div><div class="value">{snapshot.summary.recent_activity_count}</div></div>
          <div class="stat"><div class="label">平均出席率</div><div class="value">{snapshot.summary.average_attendance_rate:g}%</div></div>
          <div class="stat"><div class="label">平均整體評估</div><div class="value">{average_score}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="meta">
          <span class="chip">報表更新時間 {escape(snapshot.generated_at.isoformat())}</span>
          <span class="chip">管理用途 教務追蹤 / 主管監看 / 加盟營運佐證</span>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("線上學習紀錄報表", body)


@router.get("/admin/reports/franchise", response_class=HTMLResponse)
def school_platform_admin_franchise_reports_page() -> str:
    snapshot = analytics_service.franchise_group_report()
    cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(item.partner_type)}</div>"
            f"<h3>{escape(item.group_name)}</h3>"
            f"<p>加盟夥伴 {item.partner_count} / 已售區域 {item.sold_regions}/{item.total_regions or item.sold_regions}</p>"
            f"<div class='meta'><span class='chip'>名單 {item.total_leads}</span><span class='chip'>新名單 {item.new_leads}</span><span class='chip'>已聯繫 {item.contacted_leads}</span></div>"
            f"<div class='meta'><span class='chip'>試聽 {item.trial_booked_leads}</span><span class='chip'>考慮中 {item.considering_leads}</span><span class='chip'>成交 {item.enrolled_leads}</span><span class='chip'>流失 {item.lost_leads}</span></div>"
            f"<div class='meta'><span class='chip'>轉換率 {item.conversion_rate:g}%</span><span class='chip'>加盟收入 {_format_jpy(item.booked_join_fee_revenue_jpy)}</span><span class='chip'>月費 {_format_jpy(item.monthly_recurring_revenue_jpy)}</span></div>"
            f"<p>目前重點：{escape(item.next_focus)}</p>"
            "</article>"
        )
        for item in snapshot.groups
    ) or "<article class='card'><h3>目前沒有加盟組資料</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Franchise Recruitment Reports</div>
        <h1>加盟組招生流程報表</h1>
        <p>這裡集中顯示三個加盟組的招商漏斗、區域銷售、加盟收入與月費結構，方便管理區直接掌握加盟營運進度。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/reports">回報表中心</a>
          <a class="btn alt" href="/school-platform/api/reports/franchise-groups">查看加盟報表 JSON</a>
          <a class="btn alt" href="/school-platform/admin/executive">回主管工作台</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">加盟組</div><div class="value">{snapshot.summary.total_groups}</div></div>
          <div class="stat"><div class="label">活躍夥伴</div><div class="value">{snapshot.summary.total_partner_count}</div></div>
          <div class="stat"><div class="label">已售區域</div><div class="value">{snapshot.summary.sold_regions}/{snapshot.summary.total_regions}</div></div>
          <div class="stat"><div class="label">名單總數</div><div class="value">{snapshot.summary.total_leads}</div></div>
          <div class="stat"><div class="label">成交名單</div><div class="value">{snapshot.summary.enrolled_leads}</div></div>
          <div class="stat"><div class="label">綜合轉換率</div><div class="value">{snapshot.summary.blended_conversion_rate:g}%</div></div>
          <div class="stat"><div class="label">加盟收入</div><div class="value">{_format_jpy(snapshot.summary.booked_join_fee_revenue_jpy)}</div></div>
          <div class="stat"><div class="label">月費 MRR</div><div class="value">{_format_jpy(snapshot.summary.monthly_recurring_revenue_jpy)}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="meta">
          <span class="chip">報表更新時間 {escape(snapshot.generated_at.isoformat())}</span>
          <span class="chip">對象 三個加盟組 / 管理區 / 招商主管</span>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("加盟組招生流程報表", body)


@router.get("/admin/ai-center", response_class=HTMLResponse)
def school_platform_admin_ai_center_page() -> str:
    logs = analytics_service.ai_logs()[:12]
    weekly = analytics_service.weekly_ai_summary()
    provider_status = ai_assistant_service.provider_status()
    log_cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.module_name)} / {escape(item.action_name)}</div>"
        f"<h3>{escape(item.actor_email or 'system')}</h3>"
        f"<p>Input: {escape(item.input_summary)}</p>"
        f"<p>Output: {escape(item.output_summary)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        "</article>"
        for item in logs
    ) or "<article class='card'><h3>目前沒有 AI 紀錄</h3></article>"
    insight_items = "".join(f"<li>{escape(str(item))}</li>" for item in weekly["insights"])
    support_items = "".join(f"<li>{escape(item)}</li>" for item in provider_status.supported_features)
    last_error = escape(provider_status.last_error or "none")
    body = f"""
      <section class="hero">
        <div class="eyebrow">AI Operations Center</div>
        <h1>AI 助理中心</h1>
        <p>這裡集中顯示 AI 跟進草稿、營運摘要與系統內部 AI 操作紀錄，方便主管追蹤自動化使用狀況。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/admin/ai-teaching">打開 AI 教案中心</a>
          <a class="btn alt" href="/school-platform/api/ai/logs">查看 AI logs JSON</a>
          <a class="btn alt" href="/school-platform/api/ai/status">查看 AI status JSON</a>
          <a class="btn alt" href="/school-platform/api/reports/weekly-summary">查看週摘要 JSON</a>
        </div>
      </section>
      <section class="section">
        <h2>AI Provider 狀態</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">服務可用</div><div class="value">{'yes' if provider_status.service_ready else 'no'}</div></div>
          <div class="stat"><div class="label">外部模型就緒</div><div class="value">{'yes' if provider_status.external_model_ready else 'no'}</div></div>
          <div class="stat"><div class="label">目前供應商</div><div class="value">{escape(provider_status.active_provider)}</div></div>
          <div class="stat"><div class="label">runtime 模式</div><div class="value">{escape(provider_status.runtime_mode)}</div></div>
          <div class="stat"><div class="label">模型</div><div class="value">{escape(provider_status.model_name or 'n/a')}</div></div>
          <div class="stat"><div class="label">最近 provider 錯誤</div><div class="value">{last_error}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>本週 AI 營運摘要</h2>
            <ul class="clean">{insight_items}</ul>
          </article>
          <article class="card">
            <h2>AI 目前支援</h2>
            <ul class="clean">{support_items}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>AI 操作紀錄</h2>
        <div class="grid two">{log_cards}</div>
      </section>
    """
    return _page_shell("AI 助理中心", body)


@router.get("/admin/ai-teaching", response_class=HTMLResponse)
def school_platform_admin_ai_teaching_page(
    class_id: str | None = Query(default=None),
    lesson_focus: str = Query(default="藥局與租屋生活會話"),
    duration_minutes: int = Query(default=90),
) -> str:
    classes = catalog_service.open_classes()
    class_options = "".join(
        f"<option value='{item.id}' {'selected' if class_id == str(item.id) else ''}>{escape(item.name)} / {escape(item.teacher_name)} / {escape(item.weekday)}</option>"
        for item in classes
    )
    draft = None
    selected_class_id = class_id or (str(classes[0].id) if classes else None)
    if selected_class_id:
        try:
            draft = ai_assistant_service.lesson_plan_draft(
                LessonPlanDraftRequest(
                    class_id=UUID(selected_class_id),
                    lesson_focus=lesson_focus,
                    duration_minutes=duration_minutes,
                )
            )
        except KeyError:
            draft = None
    step_cards = (
        "".join(
            (
                "<article class='card'>"
                f"<div class='eyebrow'>{item.minutes} 分鐘</div>"
                f"<h3>{escape(item.title)}</h3>"
                f"<p>{escape(item.details)}</p>"
                "</article>"
            )
            for item in draft.teaching_steps
        )
        if draft
        else "<article class='card'><h3>目前沒有教案草稿</h3></article>"
    )
    review_items = "".join(f"<li>{escape(item)}</li>" for item in draft.review_points) if draft else "<li>請先選班級產生草稿</li>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">AI Teaching Drafts</div>
        <h1>AI 教案草稿中心</h1>
        <p>這裡可以依照班級、課堂主題與時長，快速生成可給老師修改的教案草稿與課後作業建議。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/ai-center">回 AI 助理中心</a>
          <a class="btn alt" href="/school-platform/api/ai/logs?module_name=teaching">查看 teaching AI logs</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>產生教案草稿</h2>
            <form class="stack" method="get" action="/school-platform/admin/ai-teaching">
              <label class="field">班級
                <select name="class_id">{class_options}</select>
              </label>
              <label class="field">課堂焦點
                <input type="text" name="lesson_focus" value="{escape(lesson_focus)}" />
              </label>
              <label class="field">課程時長（分鐘）
                <input type="number" name="duration_minutes" min="30" step="10" value="{duration_minutes}" />
              </label>
              <button class="btn" type="submit">生成草稿</button>
            </form>
          </article>
          <article class="card">
            <h2>草稿摘要</h2>
            {f"<p>班級：{escape(draft.class_name)}</p><p>老師：{escape(draft.teacher_name)}</p><p>焦點：{escape(draft.lesson_focus)}</p><p>教學目標：{escape(draft.objective)}</p><p>暖身：{escape(draft.warmup)}</p><p>課後作業：{escape(draft.homework)}</p>" if draft else "<p>選擇班級後即可生成教案草稿。</p>"}
          </article>
        </div>
      </section>
      <section class="section">
        <h2>教學步驟</h2>
        <div class="grid two">{step_cards}</div>
      </section>
      <section class="section">
        <h2>教師提醒</h2>
        <article class="card"><ul class="clean">{review_items}</ul></article>
      </section>
    """
    return _page_shell("AI 教案草稿中心", body)


@router.post("/admin/recruiting/jobs/create")
def school_platform_admin_job_create_submit(
    title: str = Form(...),
    department: str = Form(...),
    employment_type: str = Form(...),
    location_label: str = Form(...),
    salary_range: str = Form(...),
    summary: str = Form(...),
    requirements: str = Form(default=""),
):
    recruiting_service.create_job(
        JobPositionCreateRequest(
            title=title,
            department=department,
            employment_type=employment_type,
            location_label=location_label,
            salary_range=salary_range,
            summary=summary,
            requirements=[item.strip() for item in requirements.splitlines() if item.strip()],
        )
    )
    return RedirectResponse(url="/school-platform/admin/recruiting", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/recruiting/interviews/create")
def school_platform_admin_interview_create_submit(
    applicant_id: str = Form(...),
    interview_at: str = Form(...),
    interviewer_name: str = Form(...),
    format: str = Form(default="google_meet"),
    return_to: str = Form(default=""),
):
    try:
        recruiting_service.schedule_interview(
            InterviewCreateRequest(
                applicant_id=UUID(applicant_id),
                interview_at=datetime.fromisoformat(interview_at),
                interviewer_name=interviewer_name,
                format=format,
            )
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc
    redirect_to = return_to or "/school-platform/admin/recruiting"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/recruiting/applicants/{applicant_id}/status")
def school_platform_admin_applicant_status_submit(
    applicant_id: UUID,
    interview_status: str = Form(...),
    note: str = Form(default=""),
):
    try:
        recruiting_service.update_applicant_status(
            applicant_id,
            ApplicantStatusUpdateRequest(interview_status=interview_status, note=note or None),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc
    return RedirectResponse(
        url=f"/school-platform/admin/recruiting/applicants/{applicant_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/recruiting/applicants/{applicant_id}/onboarding")
def school_platform_admin_applicant_onboarding_submit(
    applicant_id: UUID,
    owner_name: str = Form(default="Yuki Wang"),
    stage: str = Form(default="preboarding"),
    start_date: str = Form(default=""),
    probation_status: str = Form(default="not_started"),
    probation_end_date: str = Form(default=""),
    checklist_items: str = Form(default=""),
    notes: str = Form(default=""),
):
    try:
        recruiting_service.upsert_onboarding_record(
            applicant_id,
            OnboardingUpsertRequest(
                owner_name=owner_name or None,
                stage=stage,
                start_date=date.fromisoformat(start_date) if start_date else None,
                probation_status=probation_status,
                probation_end_date=date.fromisoformat(probation_end_date) if probation_end_date else None,
                checklist_items=[item.strip() for item in checklist_items.splitlines() if item.strip()],
                notes=notes or None,
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc
    return RedirectResponse(
        url=f"/school-platform/admin/recruiting/applicants/{applicant_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/recruiting/interviews/{interview_id}/review")
def school_platform_admin_interview_review_submit(
    interview_id: UUID,
    interview_status_value: str = Form(...),
    applicant_status: str = Form(...),
    feedback: str = Form(default=""),
    note: str = Form(default=""),
):
    try:
        interview = recruiting_service.update_interview(
            interview_id,
            InterviewUpdateRequest(status=interview_status_value, feedback=feedback or None),
        )
        recruiting_service.update_applicant_status(
            interview.applicant_id,
            ApplicantStatusUpdateRequest(interview_status=applicant_status, note=note or None),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc
    return RedirectResponse(
        url=f"/school-platform/admin/recruiting/applicants/{interview.applicant_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/admin/support-inbox", response_class=HTMLResponse)
def school_platform_admin_support_inbox_page() -> str:
    summary = admissions_service.support_inbox_summary()
    items = admissions_service.support_inbox()
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item.type)}</div>"
        f"<h3>{escape(item.title)}</h3>"
        f"<p>{escape(item.content)}</p>"
        f"<div class='meta'><span class='chip'>{escape(item.channel)}</span><span class='chip'>{escape(item.status)}</span><span class='chip'>{escape(item.created_at.isoformat())}</span></div>"
        f"<div class='actions'><a class='btn' href='/school-platform/admin/support-inbox/{item.id}'>查看案件</a></div>"
        "</article>"
        for item in items
    ) or "<article class='card'><h3>目前沒有客服需求</h3></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">Support Inbox</div>
        <h1>客服收件箱</h1>
        <p>這裡集中顯示從學員端送進來的客服需求，方便管理端追蹤與後續處理。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/admin">回營運總覽</a>
          <a class="btn alt" href="/school-platform/api/notifications?user_email=admin@jls.local">查看通知 JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">總需求數</div><div class="value">{summary['total']}</div></div>
          <div class="stat"><div class="label">待處理</div><div class="value">{summary['queued']}</div></div>
          <div class="stat"><div class="label">處理中</div><div class="value">{summary['processing']}</div></div>
          <div class="stat"><div class="label">已解決</div><div class="value">{summary['resolved']}</div></div>
          <div class="stat"><div class="label">In-app 通知</div><div class="value">{summary['in_app']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("客服收件箱", body)


@router.post("/teacher/verification/submit")
async def school_platform_teacher_verification_submit(
    request: Request,
    teacher_name: str = Form(...),
    return_to: str = Form(default=""),
):
    form = await request.form()
    answers = {
        key.removeprefix("answer_"): str(value)
        for key, value in form.multi_items()
        if key.startswith("answer_")
    }
    try:
        teacher_verification_service.submit(
            payload=TeacherVerificationSubmitRequest(
                teacher_name=teacher_name,
                answers=answers,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    redirect_to = return_to or f"/school-platform/teacher/verification?{urlencode({'teacher_name': teacher_name})}"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/teacher/assignment-submissions/{submission_id}/grade")
def school_platform_teacher_assignment_grade_submit(
    submission_id: UUID,
    teacher_name: str = Form(...),
    score: float = Form(...),
    feedback: str = Form(default=""),
    graded_by: str = Form(default="Aki Mori"),
    return_to: str = Form(default=""),
):
    try:
        teaching_ops_service.grade_assignment_submission(
            submission_id,
            SubmissionGradeRequest(score=score, feedback=feedback or None, graded_by=graded_by or teacher_name),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assignment submission not found") from exc
    redirect_to = return_to or f"/school-platform/teacher-portal?{urlencode({'teacher_name': teacher_name})}"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/teacher/exam-submissions/{submission_id}/grade")
def school_platform_teacher_exam_grade_submit(
    submission_id: UUID,
    teacher_name: str = Form(...),
    score: float = Form(...),
    feedback: str = Form(default=""),
    graded_by: str = Form(default="Aki Mori"),
    return_to: str = Form(default=""),
):
    try:
        teaching_ops_service.grade_exam_submission(
            submission_id,
            SubmissionGradeRequest(score=score, feedback=feedback or None, graded_by=graded_by or teacher_name),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exam submission not found") from exc
    redirect_to = return_to or f"/school-platform/teacher-portal?{urlencode({'teacher_name': teacher_name})}"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/teacher/classes/{class_id}/attendance")
def school_platform_teacher_class_attendance_submit(
    class_id: UUID,
    teacher_name: str = Form(...),
    student_email: str = Form(...),
    class_date_value: str = Form(...),
    status_value: str = Form(...),
    note: str = Form(default=""),
):
    try:
        teaching_ops_service.mark_attendance(
            AttendanceMarkRequest(
                class_id=class_id,
                student_email=student_email,
                class_date=date.fromisoformat(class_date_value),
                status=status_value,
                note=note or None,
                marked_by=teacher_name,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid attendance payload") from exc
    query = urlencode({"teacher_name": teacher_name})
    return RedirectResponse(
        url=f"/school-platform/teacher/classes/{class_id}?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/teacher/classes/{class_id}/session-records")
def school_platform_teacher_session_record_submit(
    class_id: UUID,
    teacher_name: str = Form(...),
    class_date_value: str = Form(...),
    summary_text: str = Form(...),
    materials_link: str = Form(default=""),
    homework_summary: str = Form(default=""),
    next_class_focus: str = Form(default=""),
    student_risk_notes: str = Form(default=""),
    approval_status_value: str = Form(default="submitted"),
    return_to: str = Form(default=""),
):
    try:
        teaching_ops_service.upsert_teaching_session_record(
            TeachingSessionUpsertRequest(
                class_id=class_id,
                teacher_name=teacher_name,
                class_date=date.fromisoformat(class_date_value),
                summary=summary_text,
                materials_link=materials_link or None,
                homework_summary=homework_summary or None,
                next_class_focus=next_class_focus or None,
                student_risk_notes=[item.strip() for item in student_risk_notes.splitlines() if item.strip()],
                approval_status=approval_status_value,
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class not found") from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid teaching session payload") from exc
    redirect_to = return_to or f"/school-platform/teacher/classes/{class_id}?{urlencode({'teacher_name': teacher_name})}"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/teacher/classes/{class_id}/materials")
def school_platform_teacher_material_submit(
    class_id: UUID,
    teacher_name: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    material_url: str = Form(default=""),
    visibility: str = Form(default="enrolled_only"),
    uploaded_file: UploadFile | None = File(default=None),
):
    class_item = next((item for item in catalog_service.open_classes() if item.id == class_id), None)
    if class_item is None:
        raise HTTPException(status_code=404, detail="Class not found")
    try:
        _create_material_from_form(
            course_slug=class_item.course_slug,
            class_id=class_id,
            title=title,
            description=description,
            material_url=material_url,
            owner_type="teacher",
            visibility=visibility,
            created_by=teacher_name,
            uploaded_file=uploaded_file,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class or course not found") from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid teaching material payload") from exc
    return RedirectResponse(
        url=f"/school-platform/teacher/classes/{class_id}?{urlencode({'teacher_name': teacher_name})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/admin/support-inbox/{notification_id}", response_class=HTMLResponse)
def school_platform_admin_support_detail_page(notification_id: UUID) -> str:
    try:
        notification = notification_service.get_notification(notification_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Support request not found") from exc
    body = f"""
      <section class="hero">
        <div class="eyebrow">Support Detail</div>
        <h1>客服案件詳情</h1>
        <p>這裡可以更新案件狀態並直接回覆學生。</p>
        <div class="meta">
          <span class="chip">{escape(notification.type)}</span>
          <span class="chip">{escape(notification.status)}</span>
          <span class="chip">{escape(notification.created_at.isoformat())}</span>
        </div>
        <div class="actions">
          <a class="btn" href="/school-platform/admin/support-inbox">回客服收件箱</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>案件內容</h2>
            <p>{escape(notification.title)}</p>
            <p>{escape(notification.content)}</p>
          </article>
          <article class="card">
            <h2>更新狀態</h2>
            <form class="stack" method="post" action="/school-platform/admin/support-inbox/{notification.id}/status">
              <label class="field">狀態
                <select name="status_value">
                  <option value="processing">processing</option>
                  <option value="resolved">resolved</option>
                </select>
              </label>
              <button class="btn" type="submit">更新案件狀態</button>
            </form>
          </article>
        </div>
      </section>
      <section class="section">
        <article class="card">
          <h2>回覆學生</h2>
          <form class="stack" method="post" action="/school-platform/admin/support-inbox/{notification.id}/reply">
            <label class="field">回覆狀態
              <select name="status_value">
                <option value="processing">processing</option>
                <option value="resolved">resolved</option>
              </select>
            </label>
            <label class="field">回覆管道
              <select name="response_channel">
                <option value="email">email</option>
                <option value="line">line</option>
                <option value="in_app">in_app</option>
              </select>
            </label>
            <label class="field">回覆內容
              <textarea name="response_message" placeholder="輸入要回給學生的內容"></textarea>
            </label>
            <button class="btn" type="submit">送出回覆並更新狀態</button>
          </form>
        </article>
      </section>
    """
    return _page_shell("客服案件詳情", body)


@router.post("/admin/support-inbox/{notification_id}/status")
def school_platform_admin_support_status_submit(
    notification_id: UUID,
    status_value: str = Form(...),
):
    try:
        notification_service.update_status(notification_id, status_value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Support request not found") from exc
    return RedirectResponse(url=f"/school-platform/admin/support-inbox/{notification_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/support-inbox/{notification_id}/reply")
def school_platform_admin_support_reply_submit(
    notification_id: UUID,
    status_value: str = Form(...),
    response_channel: str = Form(...),
    response_message: str = Form(...),
):
    try:
        student_support_service.process_support_request(notification_id, status_value, response_message, response_channel)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Support request not found") from exc
    return RedirectResponse(url=f"/school-platform/admin/support-inbox/{notification_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/progress", response_class=HTMLResponse)
def school_platform_progress_page() -> str:
    snapshot = platform_status_service.progress_snapshot()
    cards = "".join(
        "<article class='card status-card "
        f"{escape(module.status)}'>"
        f"<div class='status {module.status}'>{escape(module.status.replace('_', ' '))}</div>"
        f"<h3>{escape(module.name)}</h3>"
        f"<p>{escape(module.summary)}</p>"
        "</article>"
        for module in snapshot.modules
    )
    next_actions = "".join(f"<li>{escape(item)}</li>" for item in snapshot.next_actions)
    route_cards = "".join(
        [
            "<article class='route-card'>"
            "<div class='route-label'>前台課程 API</div>"
            "<code>/school-platform/api/public/courses</code>"
            "<p>查看目前公開課程清單。</p>"
            "</article>",
            "<article class='route-card'>"
            "<div class='route-label'>管理儀表板 API</div>"
            "<code>/school-platform/api/admin/dashboard</code>"
            "<p>查看招生、報名、營收與待跟進摘要。</p>"
            "</article>",
            "<article class='route-card'>"
            "<div class='route-label'>開發進度 JSON</div>"
            "<code>/school-platform/api/progress</code>"
            "<p>查看目前完成模組、測試數與下一步。</p>"
            "</article>",
            "<article class='route-card'>"
            "<div class='route-label'>學員儀表板 API</div>"
            "<code>/school-platform/api/student/dashboard?email=...</code>"
            "<p>查看學員課程、付款狀態與通知數量。</p>"
            "</article>",
        ]
    )
    legend = "".join(
        [
            "<div class='legend-item'><span class='dot completed'></span><span>已完成：目前已可用或已通過測試</span></div>",
            "<div class='legend-item'><span class='dot in_progress'></span><span>開發中：已有骨架，正在持續補功能</span></div>",
            "<div class='legend-item'><span class='dot planned'></span><span>已規劃：下一階段會接上的模組</span></div>",
        ]
    )
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">AI 日語補習班營運平台 / 即時進度</div>
            <h1>平台開發進度總覽</h1>
            <p>這頁就是你的中文進度 dashboard。你不用再追問我有沒有繼續寫，這裡會直接顯示目前完成到哪、哪些模組已能操作、接下來會往哪裡收斂。</p>
            <div class="meta">
              <span class="chip">目前模式：持續開發中</span>
              <span class="chip">可查看 API 進度</span>
              <span class="chip">可追蹤模組狀態</span>
            </div>
            <div class="actions">
              <a class="btn" href="/school-platform/activity">最近開發紀錄</a>
              <a class="btn alt" href="/school-platform/api/progress">開發進度 JSON</a>
            </div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">開發快照</div>
            <h2>目前開發脈搏</h2>
            <p>更新時間：<code>{escape(snapshot.updated_at.isoformat())}</code></p>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>完成模組</span><strong>{snapshot.completed_modules}/{snapshot.total_modules}</strong></div>
              <div class="mini-kpi"><span>測試通過</span><strong>{snapshot.tests_passing}</strong></div>
              <div class="mini-kpi"><span>追蹤檔案</span><strong>{snapshot.tracked_files}</strong></div>
              <div class="mini-kpi"><span>資料行數</span><strong>{snapshot.lines_of_code}</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>開發概覽</h2>
        <div class="stat-grid">
          <div class="stat"><div class="label">完成模組</div><div class="value">{snapshot.completed_modules}/{snapshot.total_modules}</div></div>
          <div class="stat"><div class="label">測試通過</div><div class="value">{snapshot.tests_passing}</div></div>
          <div class="stat"><div class="label">追蹤檔案</div><div class="value">{snapshot.tracked_files}</div></div>
        </div>
      </section>
      <section class="section">
        <h2>狀態說明</h2>
        <p>下面的模組卡片會標出目前是已完成、開發中，還是已規劃但尚未開工。</p>
        <div class="legend">{legend}</div>
      </section>
      <section class="section">
        <h2>模組完成度</h2>
        <div class="grid two">{cards}</div>
      </section>
      <section class="section">
        <h2>目前可直接打開的功能入口</h2>
        <p>如果你想快速驗證我是不是有持續在做，可以直接點下面這些 API / 頁面入口。</p>
        <div class="route-grid">{route_cards}</div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>下一步正在接什麼</h2>
            <ul class="clean">{next_actions}</ul>
          </article>
          <article class="card">
            <h2>怎麼看我有沒有繼續做</h2>
            <div class="helper-list">
              <div>說明 1：這些清單不是空白規劃，而是我接著往前補的項目。</div>
              <div>說明 2：這頁如果有變化，就代表我有持續往前寫。</div>
              <div>說明 3：原始 JSON 可從 <a href="/school-platform/api/progress">/school-platform/api/progress</a> 查看。</div>
            </div>
          </article>
        </div>
      </section>
    """
    return _page_shell("平台開發進度", body)


@router.get("/activity", response_class=HTMLResponse)
def school_platform_activity_page() -> str:
    items = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{escape(item['time'])}</div>"
        f"<h3>{escape(item['title'])}</h3>"
        f"<p>{escape(item['summary'])}</p>"
        "</article>"
        for item in platform_status_service.activity_feed()
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Activity Feed</div>
        <h1>最近開發紀錄</h1>
        <p>如果你想知道我是不是有真的往前寫，直接看這頁。這裡會用中文列出最近補上的區塊。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/progress">回進度總覽</a>
          <a class="btn alt" href="/school-platform/api/activity">查看 activity JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{items}</div>
      </section>
    """
    return _page_shell("最近開發紀錄", body)


@router.get("/architecture", response_class=HTMLResponse)
def school_platform_architecture_page() -> str:
    domain_cards = "".join(
        [
            "<article class='card'><div class='eyebrow'>Public Growth</div><h3>前台招生域</h3><p>首頁、課程、試聽、報名、AI 推薦與名單收集。</p></article>",
            "<article class='card'><div class='eyebrow'>CRM</div><h3>招生與顧問域</h3><p>lead、指派、跟進、試聽、轉換率與招生漏斗。</p></article>",
            "<article class='card'><div class='eyebrow'>Teaching Ops</div><h3>教務與學員域</h3><p>課程、班級、教師、作業、測驗、學員中心。</p></article>",
            "<article class='card'><div class='eyebrow'>People Ops</div><h3>員工與招聘域</h3><p>staff、KPI、招聘職缺、面試流程與到職追蹤。</p></article>",
            "<article class='card'><div class='eyebrow'>Finance</div><h3>付款與報表域</h3><p>報名、付款、對帳、營收與主管報表。</p></article>",
            "<article class='card'><div class='eyebrow'>AI Layer</div><h3>AI 助理域</h3><p>招生話術、教案草稿、通知輔助與營運分析。</p></article>",
        ]
    )
    layer_cards = "".join(
        [
            "<article class='card'><h3>Presentation Layer</h3><p>公開站、學員中心、顧問後台、教務後台、主管儀表板。</p></article>",
            "<article class='card'><h3>Application API Layer</h3><p>auth、public、student、leads、courses、classes、payments、notifications、admin、ai。</p></article>",
            "<article class='card'><h3>Domain Service Layer</h3><p>LeadService、CourseService、ClassService、EnrollmentService、PaymentService、AIOrchestrator。</p></article>",
            "<article class='card'><h3>Persistence Layer</h3><p>目前 JSON repository，下一步切 PostgreSQL repository + migration。</p></article>",
            "<article class='card'><h3>Async Layer</h3><p>通知、AI worker、webhook reconciliation、週報月報、aggregation jobs。</p></article>",
            "<article class='card'><h3>Observability</h3><p>request logs、AI logs、payment logs、admin audit trail、job retry logs。</p></article>",
        ]
    )
    flow_items = "".join(
        [
            "<li>訪客進站 → 建立 lead → 指派顧問 → 試聽 → enrollment → payment → 學員中心開通</li>",
            "<li>manager 建立課程 → 建立班級 → teacher 授課 → student 學習與提交 → dashboard 聚合</li>",
            "<li>AI 只先產出草稿與建議，外部發送與最終決策保留人工確認</li>",
        ]
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">Platform Architecture</div>
        <h1>完整營運平台架構</h1>
        <p>這頁把 AI 日語補習班平台拆成 domain、系統分層、事件流與部署拓樸，給產品、工程與營運一起看同一張藍圖。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/progress">回進度總覽</a>
          <a class="btn alt" href="/school-platform/activity">回開發紀錄</a>
        </div>
      </section>
      <section class="section">
        <h2>Domain 架構</h2>
        <div class="grid two">{domain_cards}</div>
      </section>
      <section class="section">
        <h2>系統分層</h2>
        <div class="grid two">{layer_cards}</div>
      </section>
      <section class="section">
        <h2>主事件流</h2>
        <article class="card">
          <ul class="clean">{flow_items}</ul>
        </article>
      </section>
      <section class="section">
        <h2>工程現況</h2>
        <div class="grid two">
          <article class="card">
            <h3>已落地</h3>
            <p>公開站、學員中心、招生後台、課程 / 班級 / 教師管理、付款流程、auth / RBAC、進度與 activity 頁。</p>
          </article>
          <article class="card">
            <h3>下一段</h3>
            <p>PostgreSQL repository、通知 sender、AI worker、教務深化、招聘與 HR 模組。</p>
          </article>
        </div>
      </section>
    """
    return _page_shell("完整營運平台架構", body)


@router.get("/system", response_class=HTMLResponse)
def school_platform_system_page() -> str:
    summary = platform_status_service.storage_summary()
    operational_readiness = platform_status_service.operational_readiness()
    launch_readiness = platform_status_service.launch_readiness()
    capabilities = summary["capabilities"]
    readiness = summary["readiness"]
    materials_storage = summary["materials_storage"]
    teacher_verification_storage = summary["teacher_verification_storage"]
    artifacts = summary["migration_artifacts"]
    snapshot_integrity = summary["snapshot_integrity"]
    payment_provider = summary["payment_provider"]
    notification_providers = summary["notification_providers"]
    mutation_tables = "".join(f"<li><code>{escape(item)}</code></li>" for item in summary["mutation_tables"]) or "<li>尚未啟用 row-level mutation tables</li>"
    duplicate_cards = "".join(
        "<article class='card'>"
        f"<h3>{escape(str(item['state_key']))}.{escape(str(item['field']))}</h3>"
        f"<p>duplicate groups：{item['duplicate_count']}</p>"
        f"<p>{escape(str(item['samples'][:3]))}</p>"
        "</article>"
        for item in snapshot_integrity.get("duplicate_groups", [])
    ) or "<article class='card'><h3>Snapshot Integrity 正常</h3><p>目前沒有偵測到會阻擋 PostgreSQL cutover 的 unique-key 衝突。</p></article>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">System Status</div>
        <h1>系統與資料層狀態</h1>
        <p>這頁用來看目前平台實際跑在哪種 storage backend，以及下一步資料層要往哪裡切。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/operational-readiness">查看今日可營運</a>
          <a class="btn" href="/school-platform/launch-readiness">查看正式上線 readiness</a>
          <a class="btn alt" href="/school-platform/api/system/launch-readiness">查看 readiness JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h3>目前 backend</h3>
            <p><code>{escape(str(summary['backend']))}</code></p>
            <p>repository_mode：<code>{escape(str(summary['repository_mode']))}</code></p>
            <p>query_supported：<code>{escape(str(capabilities['query_supported']).lower())}</code></p>
            <p>partial_write_supported：<code>{escape(str(capabilities['partial_write_supported']).lower())}</code></p>
            <p>row_level_write_supported：<code>{escape(str(capabilities['row_level_write_supported']).lower())}</code></p>
            <p>mutation_table_count：<code>{summary['mutation_table_count']}</code></p>
            <p>現在已支援 JSON snapshot file 與 PostgreSQL domain tables 兩種模式。</p>
          </article>
          <article class="card">
            <h3>下一步</h3>
            <p>已經完成 repository abstraction 與 domain tables migration，並開始把高頻 mutation 改成 row-level write。接下來只要提供 PostgreSQL DSN，就能進行真實 cutover 驗證。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Storage Readiness</h2>
        <div class="grid two">
          <article class="card">
            <h3>狀態摘要</h3>
            <p>ready：<code>{escape(str(readiness['ready']).lower())}</code></p>
            <p>driver_installed：<code>{escape(str(readiness['driver_installed']).lower())}</code></p>
            <p>dsn_present：<code>{escape(str(readiness['dsn_present']).lower())}</code></p>
            <p>connectable：<code>{escape(str(readiness['connectable']).lower())}</code></p>
            <p>initialized：<code>{escape(str(readiness['initialized']).lower())}</code></p>
            <p>tables_ready：<code>{escape(str(readiness['tables_ready']).lower())}</code></p>
          </article>
          <article class="card">
            <h3>說明</h3>
            <p>{escape(str(readiness['message']))}</p>
            <p><code>POST /school-platform/api/system/storage/init</code></p>
            <p>當 backend 為 postgres 且 driver / DSN 都齊全時，可用這個入口初始化 domain tables。</p>
            <p><code>POST /school-platform/api/system/storage/cutover</code></p>
            <p>切到 postgres 後，可用這個入口把目前 JSON snapshot 正式搬進 active PostgreSQL。</p>
          </article>
          <article class="card">
            <h3>Materials Storage</h3>
            <p>path：<code>{escape(str(materials_storage['path']))}</code></p>
            <p>exists：<code>{escape(str(materials_storage['exists']).lower())}</code></p>
            <p>ready：<code>{escape(str(materials_storage['ready']).lower())}</code></p>
            <p>uploaded_file_count：<code>{escape(str(materials_storage['uploaded_file_count']))}</code></p>
          </article>
          <article class="card">
            <h3>Teacher Verification Storage</h3>
            <p>section_count：<code>{teacher_verification_storage['section_count']}</code></p>
            <p>question_count：<code>{teacher_verification_storage['question_count']}</code></p>
            <p>attempt_count：<code>{teacher_verification_storage['attempt_count']}</code></p>
            <p>verified_teacher_count：<code>{teacher_verification_storage['verified_teacher_count']}</code></p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Migration Readiness</h2>
        <div class="grid two">
          <article class="card">
            <h3>Artifacts</h3>
            <p>domain_sql_present：<code>{escape(str(artifacts['domain_sql_present']).lower())}</code></p>
            <p>snapshot_sql_present：<code>{escape(str(artifacts['snapshot_sql_present']).lower())}</code></p>
            <p>init_script_present：<code>{escape(str(artifacts['init_script_present']).lower())}</code></p>
            <p>migrate_script_present：<code>{escape(str(artifacts['migrate_script_present']).lower())}</code></p>
            <p>smoke_test_script_present：<code>{escape(str(artifacts['smoke_test_script_present']).lower())}</code></p>
            <p>cutover_script_present：<code>{escape(str(artifacts['cutover_script_present']).lower())}</code></p>
            <p>deployment_smoke_script_present：<code>{escape(str(artifacts['deployment_smoke_script_present']).lower())}</code></p>
            <p>row_write_probe_script_present：<code>{escape(str(artifacts['row_write_probe_script_present']).lower())}</code></p>
          </article>
          <article class="card">
            <h3>Paths</h3>
            <p><code>{escape(str(artifacts['sql_domain_tables']))}</code></p>
            <p><code>{escape(str(artifacts['init_script']))}</code></p>
            <p><code>{escape(str(artifacts['migrate_script']))}</code></p>
            <p><code>{escape(str(artifacts['smoke_test_script']))}</code></p>
            <p><code>{escape(str(artifacts['cutover_script']))}</code></p>
            <p><code>{escape(str(artifacts['deployment_smoke_script']))}</code></p>
            <p><code>{escape(str(artifacts['row_write_probe_script']))}</code></p>
            <p><a href="/school-platform/db-migration">打開 DB 切換與資料搬遷說明頁</a></p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Snapshot Integrity</h2>
        <div class="grid two">
          <article class="card">
            <h3>JSON Source</h3>
            <p>source_json_path：<code>{escape(str(snapshot_integrity['source_json_path']))}</code></p>
            <p>present：<code>{escape(str(snapshot_integrity['present']).lower())}</code></p>
            <p>ready：<code>{escape(str(snapshot_integrity['ready']).lower())}</code></p>
            <p>duplicate_group_count：<code>{escape(str(snapshot_integrity['duplicate_group_count']))}</code></p>
          </article>
          <article class="card">
            <h3>Cutover Note</h3>
            <p>若這裡有 duplicate groups，cutover script 會先做 normalization，再把乾淨資料寫入 PostgreSQL domain tables。</p>
          </article>
        </div>
        <div class="grid two">{duplicate_cards}</div>
      </section>
      <section class="section">
        <h2>External Integrations</h2>
        <div class="grid two">
          <article class="card">
            <h3>Payments</h3>
            <p>provider：<code>{escape(str(payment_provider['provider']))}</code></p>
            <p>ready：<code>{escape(str(payment_provider['ready']).lower())}</code></p>
            <p>currency：<code>{escape(str(payment_provider['currency']))}</code></p>
            <p>provider_mode：<code>{escape(str(payment_provider['provider_mode']))}</code></p>
            <p>reconciliation_supported：<code>{escape(str(payment_provider['reconciliation_supported']).lower())}</code></p>
            <p>{escape(str(payment_provider['message']))}</p>
          </article>
          <article class="card">
            <h3>Notifications</h3>
            <p>email_provider：<code>{escape(str(notification_providers['email_provider']))}</code></p>
            <p>email_ready：<code>{escape(str(notification_providers['email_ready']).lower())}</code></p>
            <p>line_ready：<code>{escape(str(notification_providers['line_ready']).lower())}</code></p>
            <p>{escape(str(notification_providers['message']))}</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Operational Readiness Summary</h2>
        <div class="grid two">
          <article class="card">
            <h3>今日可否直接營運</h3>
            <p>ready_for_operations：<code>{escape(str(operational_readiness['ready_for_operations']).lower())}</code></p>
            <p>mode：<code>{escape(str(operational_readiness['current_mode']))}</code></p>
            <p>blockers：<code>{operational_readiness['blocker_count']}</code></p>
            <p>warnings：<code>{operational_readiness['warning_count']}</code></p>
            <p>ready：<code>{operational_readiness['ready_count']}</code></p>
          </article>
          <article class="card">
            <h3>說明</h3>
            <p>這份狀態是看今天能不能直接進站操作，不把 PostgreSQL、Stripe、真實 Email 憑證混成同一件事。</p>
            <p><a href="/school-platform/operational-readiness">打開今日可營運頁</a></p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Launch Readiness Summary</h2>
        <div class="grid two">
          <article class="card">
            <h3>正式上線判定</h3>
            <p>ready_for_launch：<code>{escape(str(launch_readiness['ready_for_launch']).lower())}</code></p>
            <p>blockers：<code>{launch_readiness['blocker_count']}</code></p>
            <p>warnings：<code>{launch_readiness['warning_count']}</code></p>
            <p>ready：<code>{launch_readiness['ready_count']}</code></p>
          </article>
          <article class="card">
            <h3>說明</h3>
            <p>這份 readiness 會把 storage、金流、通知、測試與部署前手動任務一起列出，方便最後 cutover 前逐項收斂。</p>
            <p><a href="/school-platform/launch-readiness">打開正式上線檢查頁</a></p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Recommended Commands</h2>
        <div class="grid two">
          <article class="card">
            <h3>PostgreSQL 一鍵 rehearsal</h3>
            <p><code>python3 scripts/cutover_school_platform_postgres.py</code></p>
            <p>會依序跑 initialize、JSON 搬遷、row counts 比對與 PostgreSQL smoke checks。</p>
          </article>
          <article class="card">
            <h3>部署 smoke test</h3>
            <p><code>python3 scripts/smoke_test_school_platform_deployment.py --base-url https://crewai1-api.onrender.com</code></p>
            <p>會檢查 progress、storage、public routes、auth、reports、AI status 與 recruiting API。</p>
          </article>
          <article class="card">
            <h3>PostgreSQL row-level write probe</h3>
            <p><code>python3 scripts/verify_school_platform_postgres_row_writes.py</code></p>
            <p>會對 notifications、ai_logs、assignment_submissions 做 upsert 驗證並自動 cleanup。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Row-level Mutation Coverage</h2>
        <article class="card">
          <p>以下是目前 PostgreSQL repository 已納入 row-level write 能力的 domain tables：</p>
          <ul class="clean">{mutation_tables}</ul>
        </article>
      </section>
    """
    return _page_shell("系統與資料層狀態", body)


@router.get("/operational-readiness", response_class=HTMLResponse)
def school_platform_operational_readiness_page() -> str:
    readiness = platform_status_service.operational_readiness()
    check_cards = "".join(
        (
            "<article class='card status-card "
            f"{escape(str(item['status']))}'>"
            f"<div class='status {escape(str(item['status']))}'>{escape(str(item['status']).upper())}</div>"
            f"<h3>{escape(str(item['name']))}</h3>"
            f"<p>{escape(str(item['detail']))}</p>"
            "</article>"
        )
        for item in readiness["checks"]
    )
    entry_cards = "".join(
        (
            "<a class='route-card' "
            f"href='{escape(str(item['path']))}'>"
            f"<span class='route-label'>工作入口</span>"
            f"<h3>{escape(str(item['label']))}</h3>"
            f"<p>{escape(str(item['note']))}</p>"
            "</a>"
        )
        for item in readiness["entry_links"]
    )
    account_cards = "".join(
        (
            "<article class='card'>"
            f"<div class='eyebrow'>{escape(str(item['role']))}</div>"
            f"<h3>{escape(str(item['email']))}</h3>"
            f"<p>密碼：<code>{escape(str(item['password']))}</code></p>"
            f"<p><a href='{escape(str(item['entry']))}'>打開對應入口</a></p>"
            "</article>"
        )
        for item in readiness["demo_accounts"]
    ) or "<article class='card'><h3>示範帳號已隱藏</h3><p>非本機模式下不直接顯示內部示範帳號。</p></article>"
    external_gaps = "".join(f"<li>{escape(str(item))}</li>" for item in readiness["external_gaps"])
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Operational Readiness</div>
            <h1>今天可直接營運的狀態</h1>
            <p>這頁不是在看 production 憑證有沒有補齊，而是專門看今天這個平台能不能讓你、顧問、老師、行政與學員直接進去操作。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/system">回系統狀態</a>
              <a class="btn alt" href="/school-platform/api/system/operational-readiness">查看營運狀態 JSON</a>
              <a class="btn alt" href="/school-platform/launch-readiness">查看正式上線判定</a>
            </div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">Today Signal</div>
            <h2>今天可不可以直接操作</h2>
            <p>{'可以，核心模組已可在目前模式下直接操作。' if readiness['ready_for_operations'] else '目前仍有核心 blocker，要先補到可操作。'}</p>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>今日可營運</span><strong>{'可' if readiness['ready_for_operations'] else '否'}</strong></div>
              <div class="mini-kpi"><span>Mode</span><strong>{escape(str(readiness['current_mode']))}</strong></div>
              <div class="mini-kpi"><span>Blockers</span><strong>{readiness['blocker_count']}</strong></div>
              <div class="mini-kpi"><span>Warnings</span><strong>{readiness['warning_count']}</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">今日可營運</div><div class="value">{'可' if readiness['ready_for_operations'] else '否'}</div></div>
          <div class="stat"><div class="label">Blockers</div><div class="value">{readiness['blocker_count']}</div></div>
          <div class="stat"><div class="label">Warnings</div><div class="value">{readiness['warning_count']}</div></div>
          <div class="stat"><div class="label">Ready</div><div class="value">{readiness['ready_count']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>判定原則</h2>
            <p>{escape(str(readiness['note']))}</p>
          </article>
          <article class="card">
            <h2>正式對外前還差</h2>
            <ul class="clean">{external_gaps}</ul>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>核心模組狀態</h2>
        <div class="grid two">{check_cards}</div>
      </section>
      <section class="section">
        <h2>直接操作入口</h2>
        <div class="route-grid">{entry_cards}</div>
      </section>
      <section class="section">
        <h2>本機示範帳號</h2>
        <div class="grid two">{account_cards}</div>
      </section>
    """
    return _page_shell("今日可營運", body)


@router.get("/launch-readiness", response_class=HTMLResponse)
def school_platform_launch_readiness_page() -> str:
    readiness = platform_status_service.launch_readiness()
    check_cards = "".join(
        (
            "<article class='card status-card "
            f"{escape(str(item['status']))}'>"
            f"<div class='status {escape(str(item['status']))}'>{escape(str(item['status']).upper())}</div>"
            f"<h3>{escape(str(item['name']))}</h3>"
            f"<p>{escape(str(item['detail']))}</p>"
            "</article>"
        )
        for item in readiness["checks"]
    )
    manual_tasks = "".join(f"<li>{escape(str(item))}</li>" for item in readiness["manual_tasks"])
    body = f"""
      <section class="hero">
        <div class="hero-grid">
          <div>
            <div class="eyebrow">Launch Readiness</div>
            <h1>正式上線檢查清單</h1>
            <p>這頁把 PostgreSQL、真實金流、通知外發、部署 smoke test 與上線前人工收尾事項整成同一份中文儀表板，方便你直接看哪裡還卡著。</p>
            <div class="actions">
              <a class="btn" href="/school-platform/system">回 system 頁</a>
              <a class="btn alt" href="/school-platform/api/system/launch-readiness">查看 readiness JSON</a>
            </div>
          </div>
          <article class="hero-panel">
            <div class="eyebrow">Decision Signal</div>
            <h2>是否可正式上線</h2>
            <p>{'目前已具備上線條件，可進入最後驗收。' if readiness['ready_for_launch'] else '目前仍有 blocker，還不能直接視為 production ready。'}</p>
            <div class="mini-kpi-list">
              <div class="mini-kpi"><span>正式上線</span><strong>{'可' if readiness['ready_for_launch'] else '否'}</strong></div>
              <div class="mini-kpi"><span>Blockers</span><strong>{readiness['blocker_count']}</strong></div>
              <div class="mini-kpi"><span>Warnings</span><strong>{readiness['warning_count']}</strong></div>
              <div class="mini-kpi"><span>Ready</span><strong>{readiness['ready_count']}</strong></div>
            </div>
          </article>
        </div>
      </section>
      <section class="section">
        <div class="stat-grid">
          <div class="stat"><div class="label">正式上線</div><div class="value">{'可' if readiness['ready_for_launch'] else '否'}</div></div>
          <div class="stat"><div class="label">Blockers</div><div class="value">{readiness['blocker_count']}</div></div>
          <div class="stat"><div class="label">Warnings</div><div class="value">{readiness['warning_count']}</div></div>
        </div>
      </section>
      <section class="section">
        <div class="grid two">
          <article class="card">
            <h2>自動檢查</h2>
            <p>這裡顯示目前系統對正式上線前條件的自動判定，包含 storage、payment、notifications 與部署驗證。</p>
          </article>
          <article class="card">
            <h2>人工收尾提醒</h2>
            <p>正式 cutover 前，還需要把憑證、外部 webhook、金流帳號與通知 sender 做最後確認。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>自動檢查項目</h2>
        <div class="grid two">{check_cards}</div>
      </section>
      <section class="section">
        <h2>人工收尾</h2>
        <article class="card">
          <ul class="clean">{manual_tasks}</ul>
        </article>
      </section>
    """
    return _page_shell("正式上線檢查清單", body)


@router.get("/db-migration", response_class=HTMLResponse)
def school_platform_db_migration_page() -> str:
    summary = platform_status_service.storage_summary()
    artifacts = summary["migration_artifacts"]
    mutation_tables = "".join(f"<li><code>{escape(item)}</code></li>" for item in summary["mutation_tables"]) or "<li>尚未啟用 row-level mutation tables</li>"
    body = f"""
      <section class="hero">
        <div class="eyebrow">DB Cutover Runbook</div>
        <h1>DB 切換與資料搬遷說明</h1>
        <p>這頁把 JSON store 切到 PostgreSQL domain tables 的步驟整理成一份正式 runbook，方便工程與營運一起對齊。</p>
      </section>
      <section class="section">
        <h2>切換前檢查</h2>
        <article class="card">
          <ul class="clean">
            <li>確認 <code>SCHOOL_PLATFORM_STORAGE_BACKEND=postgres</code></li>
            <li>確認 <code>SCHOOL_PLATFORM_POSTGRES_DSN</code> 已提供</li>
            <li>確認 <code>psycopg</code> 與 <code>python-multipart</code> 已安裝</li>
            <li>確認 system readiness 中 <code>driver_installed</code>、<code>dsn_present</code>、<code>connectable</code> 狀態</li>
          </ul>
        </article>
      </section>
      <section class="section">
        <h2>執行步驟</h2>
        <div class="grid two">
          <article class="card">
            <h3>1. 初始化 domain tables</h3>
            <p><code>{escape(str(artifacts['init_script']))}</code></p>
            <p>或呼叫 <code>POST /school-platform/api/system/storage/init</code></p>
          </article>
          <article class="card">
            <h3>2. 搬遷 JSON 資料</h3>
            <p><code>{escape(str(artifacts['migrate_script']))}</code></p>
            <p>把目前 JSON store 的資料搬進 PostgreSQL 細表。</p>
          </article>
          <article class="card">
            <h3>3. 一鍵 rehearsal</h3>
            <p><code>{escape(str(artifacts['cutover_script']))}</code></p>
            <p>把 initialize、搬遷、row counts 比對與 PostgreSQL smoke checks 串成單一命令。</p>
          </article>
          <article class="card">
            <h3>4. 驗證 readiness</h3>
            <p>回到 <code>/school-platform/system</code> 查看 <code>tables_ready</code> 與 <code>ready</code>。</p>
          </article>
          <article class="card">
            <h3>5. 切換 backend</h3>
            <p>部署環境把 backend 改成 <code>postgres</code>，再跑 smoke test。</p>
          </article>
          <article class="card">
            <h3>6. 跑 smoke test</h3>
            <p><code>{escape(str(artifacts['smoke_test_script']))}</code></p>
            <p>驗證 courses / leads / student portal 等核心查詢與 readiness 指標。</p>
          </article>
          <article class="card">
            <h3>7. 驗證部署 smoke test</h3>
            <p><code>{escape(str(artifacts['deployment_smoke_script']))}</code></p>
            <p>對 live 或 staging base URL 跑 public / auth / reports / AI / recruiting API smoke checks。</p>
          </article>
          <article class="card">
            <h3>8. 驗證 row-level writes</h3>
            <p><code>{escape(str(artifacts['row_write_probe_script']))}</code></p>
            <p>對 notifications、ai_logs、assignment_submissions 做 upsert probe，確認不需要整包 snapshot rewrite。</p>
          </article>
        </div>
      </section>
      <section class="section">
        <h2>Artifacts</h2>
        <article class="card">
          <p><code>{escape(str(artifacts['sql_domain_tables']))}</code></p>
          <p><code>{escape(str(artifacts['init_script']))}</code></p>
          <p><code>{escape(str(artifacts['migrate_script']))}</code></p>
          <p><code>{escape(str(artifacts['smoke_test_script']))}</code></p>
          <p><code>{escape(str(artifacts['cutover_script']))}</code></p>
          <p><code>{escape(str(artifacts['deployment_smoke_script']))}</code></p>
          <p><code>{escape(str(artifacts['row_write_probe_script']))}</code></p>
        </article>
      </section>
      <section class="section">
        <h2>目前 row-level 覆蓋表</h2>
        <article class="card">
          <ul class="clean">{mutation_tables}</ul>
        </article>
      </section>
    """
    return _page_shell("DB 切換與資料搬遷說明", body)


@router.get("/db-smoke-test", response_class=HTMLResponse)
def school_platform_db_smoke_test_page() -> str:
    checks = platform_status_service.db_smoke_test_checks()
    cards = "".join(
        "<article class='card'>"
        f"<div class='eyebrow'>{'PASS' if item['ok'] else 'CHECK'}</div>"
        f"<h3>{escape(str(item['name']))}</h3>"
        f"<p>{escape(str(item['detail']))}</p>"
        f"<div class='meta'><span class='chip'>{'ok' if item['ok'] else 'pending'}</span></div>"
        "</article>"
        for item in checks
    )
    body = f"""
      <section class="hero">
        <div class="eyebrow">DB Smoke Test</div>
        <h1>DB 切換後 smoke test</h1>
        <p>這頁用來檢查 PostgreSQL domain tables 切換後，平台是否通過最基本的資料層與流程驗證。</p>
        <div class="actions">
          <a class="btn" href="/school-platform/system">回 system 頁</a>
          <a class="btn alt" href="/school-platform/api/system/smoke-test">查看 smoke test JSON</a>
        </div>
      </section>
      <section class="section">
        <div class="grid two">{cards}</div>
      </section>
    """
    return _page_shell("DB 切換後 smoke test", body)


@api_router.get("/health")
def school_platform_health() -> dict[str, str]:
    return platform_status_service.health_payload()


@api_router.get("/progress")
def school_platform_progress() -> dict[str, object]:
    return {"data": platform_status_service.progress_snapshot().model_dump(mode="json"), "error": None}


@api_router.get("/activity")
def school_platform_activity() -> dict[str, object]:
    return {"data": platform_status_service.activity_feed(), "error": None}


@api_router.get("/system/storage")
def school_platform_storage_info() -> dict[str, object]:
    return {"data": platform_status_service.storage_summary(), "error": None}


@api_router.get("/system/launch-readiness")
def school_platform_launch_readiness_info() -> dict[str, object]:
    return {"data": platform_status_service.launch_readiness(), "error": None}


@api_router.get("/system/operational-readiness")
def school_platform_operational_readiness_info() -> dict[str, object]:
    return {"data": platform_status_service.operational_readiness(), "error": None}


@api_router.post("/system/storage/init")
def school_platform_storage_init() -> dict[str, object]:
    return {"data": platform_status_service.initialize_storage(), "error": None}


@api_router.post("/system/storage/cutover")
def school_platform_storage_cutover() -> dict[str, object]:
    return {"data": platform_status_service.cutover_storage(), "error": None}


@api_router.get("/system/smoke-test")
def school_platform_storage_smoke_test() -> dict[str, object]:
    return {"data": platform_status_service.db_smoke_test_checks(), "error": None}


@api_router.post("/auth/login")
def auth_login(payload: AuthLoginRequest) -> dict[str, object]:
    return {"data": auth_service.authenticate(payload.email, payload.password).model_dump(mode="json"), "error": None}


@api_router.post("/auth/logout")
def auth_logout(token: str = Depends(current_token)) -> dict[str, object]:
    auth_service.logout(token)
    return {"data": {"success": True}, "error": None}


@api_router.get("/auth/me")
def auth_me(user=Depends(get_current_user)) -> dict[str, object]:
    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "permissions": user.permissions,
            "staff_id": str(user.staff_id) if user.staff_id else None,
            "parent_user_id": str(user.parent_user_id) if user.parent_user_id else None,
            "account_type": user.account_type,
            "scope_label": user.scope_label,
        },
        "error": None,
    }


@api_router.get("/subaccounts")
def list_subaccounts(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": account_admin_service.directory(user).model_dump(mode="json"), "error": None}


@api_router.post("/subaccounts")
def create_subaccount(payload: SubAccountCreateRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        result = account_admin_service.create_sub_account(payload, actor=user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Owner account not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": result.model_dump(mode="json"), "error": None}


@api_router.get("/public/home")
def public_home() -> dict[str, object]:
    return {"data": catalog_service.home_payload().model_dump(mode="json"), "error": None}


@api_router.get("/public/courses")
def public_courses() -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in catalog_service.list_courses()], "error": None}


@api_router.get("/public/courses/{slug}")
def public_course_detail(slug: str) -> dict[str, object]:
    try:
        return {"data": catalog_service.get_course(slug).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Course not found: {slug}") from exc


@api_router.get("/public/courses/{slug}/content")
def public_course_content(slug: str) -> dict[str, object]:
    try:
        return {"data": course_content_service.snapshot(slug).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Course not found: {slug}") from exc


@api_router.get("/public/courses/{slug}/classes")
def public_course_classes(slug: str) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in catalog_service.classes_for_course(slug)], "error": None}


@api_router.get("/public/trial-slots")
def public_trial_slots(course_slug: str | None = Query(default=None)) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in public_admissions_service.trial_slots(course_slug)], "error": None}


@api_router.post("/public/trial-bookings")
def public_trial_booking(payload: TrialBookingCreate) -> dict[str, object]:
    return {"data": public_admissions_service.create_trial_booking(payload).model_dump(mode="json"), "error": None}


@api_router.get("/public/classes/open")
def public_open_classes() -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in catalog_service.open_classes()], "error": None}


@api_router.get("/public/jobs")
def public_jobs() -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in recruiting_service.list_jobs(status="open")], "error": None}


@api_router.post("/public/applicants")
def public_create_applicant(payload: ApplicantCreateRequest) -> dict[str, object]:
    try:
        return {"data": recruiting_service.create_applicant(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@api_router.post("/public/enrollments")
def public_create_enrollment(payload: EnrollmentCreate) -> dict[str, object]:
    try:
        return {"data": finance_service.create_enrollment(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class not found") from exc


@api_router.post("/public/payments/create-intent")
def public_create_payment_intent(payload: PaymentIntentCreate) -> dict[str, object]:
    try:
        return {"data": finance_service.create_payment_intent(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Enrollment not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@api_router.get("/admin/dashboard")
def admin_dashboard(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": admissions_service.dashboard_metrics().model_dump(mode="json"), "error": None}


@api_router.get("/reports/overview")
def reports_overview(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": analytics_service.report_overview().model_dump(mode="json"), "error": None}


@api_router.get("/reports/student-learning")
def reports_student_learning(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": analytics_service.student_learning_report().model_dump(mode="json"), "error": None}


@api_router.get("/reports/franchise-groups")
def reports_franchise_groups(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": analytics_service.franchise_group_report().model_dump(mode="json"), "error": None}


@api_router.get("/reports/operations")
def reports_operations(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {
        "data": {
            "student_learning": analytics_service.student_learning_report().model_dump(mode="json"),
            "franchise_groups": analytics_service.franchise_group_report().model_dump(mode="json"),
            "generated_at": datetime.now().astimezone().isoformat(),
        },
        "error": None,
    }


@api_router.get("/reports/weekly-summary")
def reports_weekly_summary(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    summary = analytics_service.weekly_ai_summary()
    return {
        "data": {
            **summary,
            "generated_at": summary["generated_at"].isoformat() if hasattr(summary["generated_at"], "isoformat") else summary["generated_at"],
        },
        "error": None,
    }


@api_router.get("/leads")
def list_leads(status: str | None = Query(default=None), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in admissions_service.list_leads(status)], "error": None}


@api_router.get("/leads/{lead_id}")
def lead_detail(lead_id: UUID, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": admissions_service.get_lead(lead_id).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc


@api_router.get("/leads/{lead_id}/logs")
def lead_logs(lead_id: UUID, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in admissions_service.logs_for_lead(lead_id)], "error": None}


@api_router.post("/leads/{lead_id}/logs")
def create_lead_log(lead_id: UUID, payload: LeadLogCreate, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        log = lead_workflow_service.add_log(lead_id, payload.staff_name, payload.contact_method, payload.content, payload.next_action)
        return {"data": log.model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc


@api_router.post("/leads/{lead_id}/assign")
def assign_lead(lead_id: UUID, payload: LeadAssignmentRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": lead_workflow_service.assign_lead(lead_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead or staff not found") from exc


@api_router.post("/leads/{lead_id}/change-status")
def change_lead_status(lead_id: UUID, payload: LeadStatusChangeRequest, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": lead_workflow_service.change_status(lead_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc


@api_router.get("/courses")
def admin_courses(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in catalog_service.list_courses()], "error": None}


@api_router.post("/courses")
def create_course(payload: CourseUpsertRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": curriculum_admin_service.create_course(payload).model_dump(mode="json"), "error": None}


@api_router.patch("/courses/{slug}")
def update_course(slug: str, payload: CourseUpsertRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": curriculum_admin_service.update_course(slug, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc


@api_router.get("/course-content/{slug}")
def admin_course_content_snapshot(slug: str, user=Depends(require_roles("super_admin", "manager", "teacher", "consultant"))) -> dict[str, object]:
    try:
        return {"data": course_content_service.snapshot(slug).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc


@api_router.get("/course-modules")
def admin_course_modules(course_slug: str = Query(...), user=Depends(require_roles("super_admin", "manager", "teacher", "consultant"))) -> dict[str, object]:
    try:
        snapshot = course_content_service.snapshot(course_slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    return {"data": [item.model_dump(mode="json") for item in snapshot.core_modules], "error": None}


@api_router.post("/course-modules")
def create_course_module(payload: CourseModuleUpsertRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": course_content_service.create_platform_module(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc


@api_router.get("/teaching-materials")
def admin_teaching_materials(
    course_slug: str | None = Query(default=None),
    class_id: UUID | None = Query(default=None),
    owner_type: str | None = Query(default=None),
    user=Depends(require_roles("super_admin", "manager", "teacher", "consultant")),
) -> dict[str, object]:
    return {
        "data": [
            item.model_dump(mode="json")
            for item in catalog_service.teaching_materials(course_slug=course_slug, class_id=class_id, owner_type=owner_type)
        ],
        "error": None,
    }


@api_router.post("/teaching-materials")
def create_teaching_material(payload: TeachingMaterialUpsertRequest, user=Depends(require_roles("super_admin", "manager", "teacher"))) -> dict[str, object]:
    if user.role == "teacher":
        if payload.owner_type != "teacher":
            raise HTTPException(status_code=403, detail="Teacher can only create teacher-owned supplemental content")
        if payload.created_by != user.name:
            raise HTTPException(status_code=403, detail="Teacher can only create materials under current teacher profile")
    try:
        return {"data": course_content_service.create_material(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course or class not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api_router.get("/classes")
def admin_classes(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in catalog_service.open_classes()], "error": None}


@api_router.post("/classes")
def create_class(payload: ClassUpsertRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": curriculum_admin_service.create_class(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc


@api_router.patch("/classes/{class_id}")
def update_class(class_id: UUID, payload: ClassUpsertRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": curriculum_admin_service.update_class(class_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class or course not found") from exc


@api_router.get("/assignments")
def admin_assignments(class_id: UUID | None = Query(default=None), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.list_assignments(class_id)], "error": None}


@api_router.post("/assignments")
def create_assignment(payload: AssignmentCreateRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": teaching_ops_service.create_assignment(payload).model_dump(mode="json"), "error": None}


@api_router.post("/assignments/submissions/{submission_id}/grade")
def grade_assignment_submission(
    submission_id: UUID,
    payload: SubmissionGradeRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.grade_assignment_submission(submission_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assignment submission not found") from exc


@api_router.get("/attendance")
def admin_attendance(
    student_email: str | None = Query(default=None),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    if student_email:
        try:
            return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.student_attendance(student_email)], "error": None}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Student not found") from exc
    return {"data": [], "error": None}


@api_router.post("/attendance")
def create_attendance(payload: AttendanceMarkRequest, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.mark_attendance(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/exams")
def admin_exams(class_id: UUID | None = Query(default=None), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.list_exams(class_id)], "error": None}


@api_router.post("/exams")
def create_exam(payload: ExamCreateRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": teaching_ops_service.create_exam(payload).model_dump(mode="json"), "error": None}


@api_router.post("/exams/submissions/{submission_id}/grade")
def grade_exam_submission(
    submission_id: UUID,
    payload: SubmissionGradeRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.grade_exam_submission(submission_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exam submission not found") from exc


@api_router.get("/enrollments")
def admin_enrollments(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in finance_service.list_enrollments()], "error": None}


@api_router.get("/payments")
def admin_payments(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in finance_service.list_payments()], "error": None}


@api_router.get("/finance/overview")
def finance_overview(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    snapshot = finance_service.overview()
    return {
        "data": {
            "summary": snapshot.summary.model_dump(mode="json"),
            "recent_enrollments": [item.model_dump(mode="json") for item in snapshot.recent_enrollments],
            "recent_payments": [item.model_dump(mode="json") for item in snapshot.recent_payments],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/messages/overview")
def messages_overview(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    summary = notification_service.summary()
    notifications = admissions_service.list_notifications()[:20]
    return {
        "data": {
            "summary": summary.model_dump(mode="json"),
            "notifications": [item.model_dump(mode="json") for item in notifications],
            "providers": notification_service.provider_status(),
        },
        "error": None,
    }


@api_router.post("/messages/broadcast")
def messages_broadcast(
    payload: BroadcastMessageRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        result = notification_service.broadcast(payload)
        return {"data": result.model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Target email required for single student") from exc


@api_router.get("/admin/executive-dashboard")
def admin_executive_dashboard(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    snapshot = executive_dashboard_service.snapshot()
    return {
        "data": {
            "summary": snapshot.summary.model_dump(mode="json"),
            "alerts": [item.model_dump(mode="json") for item in snapshot.alerts],
            "hot_leads": [item.model_dump(mode="json") for item in snapshot.hot_leads],
            "high_risk_students": [item.model_dump(mode="json") for item in snapshot.high_risk_students],
            "class_watchlist": [item.model_dump(mode="json") for item in snapshot.class_watchlist],
            "ai_module_usage": [item.model_dump(mode="json") for item in snapshot.ai_module_usage],
            "recommendations": snapshot.recommendations,
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/admin/schedule")
def admin_schedule_overview(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    snapshot = scheduling_service.overview()
    return {
        "data": {
            "summary": snapshot.summary.model_dump(mode="json"),
            "teacher_loads": [item.model_dump(mode="json") for item in snapshot.teacher_loads],
            "classes": [item.model_dump(mode="json") for item in snapshot.classes],
            "conflicts": [item.model_dump(mode="json") for item in snapshot.conflicts],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/recruiting/jobs")
def admin_jobs(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in recruiting_service.list_jobs()], "error": None}


@api_router.post("/recruiting/jobs")
def create_job(payload: JobPositionCreateRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": recruiting_service.create_job(payload).model_dump(mode="json"), "error": None}


@api_router.get("/recruiting/applicants")
def admin_applicants(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in recruiting_service.list_applicants()], "error": None}


@api_router.get("/recruiting/onboarding")
def admin_onboarding_records(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in recruiting_service.list_onboarding_records()], "error": None}


@api_router.get("/recruiting/applicants/{applicant_id}")
def admin_applicant_detail(applicant_id: UUID, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        snapshot = recruiting_service.applicant_detail(applicant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc
    return {
        "data": {
            "applicant": snapshot.applicant.model_dump(mode="json"),
            "position": snapshot.position.model_dump(mode="json"),
            "interviews": [item.model_dump(mode="json") for item in snapshot.interviews],
            "evaluation": snapshot.evaluation.model_dump(mode="json"),
            "onboarding": snapshot.onboarding.model_dump(mode="json") if snapshot.onboarding else None,
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.patch("/recruiting/applicants/{applicant_id}/status")
def update_applicant_status(
    applicant_id: UUID,
    payload: ApplicantStatusUpdateRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": recruiting_service.update_applicant_status(applicant_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc


@api_router.put("/recruiting/applicants/{applicant_id}/onboarding")
def upsert_onboarding_record(
    applicant_id: UUID,
    payload: OnboardingUpsertRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": recruiting_service.upsert_onboarding_record(applicant_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc


@api_router.post("/recruiting/interviews")
def create_interview(payload: InterviewCreateRequest, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        return {"data": recruiting_service.schedule_interview(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Applicant not found") from exc


@api_router.patch("/recruiting/interviews/{interview_id}")
def update_interview(
    interview_id: UUID,
    payload: InterviewUpdateRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": recruiting_service.update_interview(interview_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc


@api_router.post("/payments/webhook")
def payments_webhook(payload: PaymentWebhookPayload) -> dict[str, object]:
    try:
        return {"data": finance_service.apply_payment_webhook(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Payment not found") from exc


@api_router.post("/payments/{payment_id}/reconcile")
def payment_reconcile(payment_id: UUID, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    try:
        result = finance_service.reconcile_payment(payment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Payment not found") from exc
    if isinstance(result.get("payment"), BaseModel):
        result = {**result, "payment": result["payment"].model_dump(mode="json")}
    return {"data": result, "error": None}


@api_router.post("/payments/stripe/webhook")
async def payments_stripe_webhook(request: Request) -> dict[str, object]:
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature")
    try:
        result = finance_service.apply_stripe_webhook(payload, signature_header)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Payment not found for webhook") from exc
    if isinstance(result.get("payment"), BaseModel):
        result = {**result, "payment": result["payment"].model_dump(mode="json")}
    return {"data": result, "error": None}


@api_router.get("/staff")
def admin_staff(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in admissions_service.list_staff()], "error": None}


@api_router.get("/notifications")
def admin_notifications(user_email: str | None = Query(default=None), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in admissions_service.list_notifications(user_email)], "error": None}


@api_router.post("/notifications")
def create_notification(payload: NotificationCreate, user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": notification_service.create_notification(payload).model_dump(mode="json"), "error": None}


@api_router.post("/messages/drain")
def api_messages_drain(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in notification_service.drain_queued_notifications()], "error": None}


@api_router.post("/notifications/{notification_id}/retry")
def retry_notification(
    notification_id: UUID,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": notification_service.retry_notification(notification_id).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc


@api_router.post("/notifications/{notification_id}/status")
def update_notification_status(
    notification_id: UUID,
    payload: NotificationStatusUpdateRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": notification_service.update_status(notification_id, payload.status).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc


@api_router.get("/support-inbox")
def api_support_inbox(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {
        "data": {
            "summary": admissions_service.support_inbox_summary(),
            "items": [item.model_dump(mode="json") for item in admissions_service.support_inbox()],
        },
        "error": None,
    }


@api_router.post("/support-inbox/{notification_id}/reply")
def api_support_reply(
    notification_id: UUID,
    payload: SupportReplyRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        result = student_support_service.process_support_request(
            notification_id,
            payload.status,
            payload.response_message,
            payload.response_channel,
        )
        return {
            "data": {key: value.model_dump(mode="json") for key, value in result.items()},
            "error": None,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Support request not found") from exc


@api_router.get("/student/dashboard")
def student_dashboard(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": student_portal_service.student_dashboard(email).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/courses")
def student_courses(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in student_portal_service.student_classes(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/materials")
def student_materials(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in student_portal_service.student_materials(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/assignments")
def student_assignments(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.student_assignments(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.post("/student/assignments/{assignment_id}/submit")
def submit_student_assignment(
    assignment_id: UUID,
    payload: AssignmentSubmissionCreateRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.submit_assignment(assignment_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Assignment or student not found") from exc


@api_router.get("/student/attendance")
def student_attendance(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.student_attendance(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/progress")
def student_progress(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.student_progress(email).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/exams")
def student_exams(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.student_exams(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/ai-practice")
def student_ai_practice(
    email: str = Query(...),
    theme: str = Query(default="藥局與購物生活會話"),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": ai_assistant_service.practice_conversation(email, theme).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.post("/student/exams/{exam_id}/submit")
def submit_student_exam(
    exam_id: UUID,
    payload: ExamSubmissionCreateRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.submit_exam(exam_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exam or student not found") from exc


@api_router.get("/student/payments")
def student_payments(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in student_portal_service.student_payments(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/student/notifications")
def student_notifications(email: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": [item.model_dump(mode="json") for item in student_portal_service.student_notifications(email)], "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc


@api_router.get("/admin/student-progress")
def admin_student_progress(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in teaching_ops_service.student_progress_overview()], "error": None}


@api_router.get("/admin/students")
def admin_students(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    snapshot = student_admin_service.overview()
    return {
        "data": {
            "summary": snapshot.summary.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in snapshot.items],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/admin/students/detail")
def admin_student_detail(
    email: str = Query(...),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        snapshot = student_admin_service.detail(email)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
    return {
        "data": {
            "item": snapshot.item.model_dump(mode="json"),
            "classes": [item.model_dump(mode="json") for item in snapshot.classes],
            "enrollments": [item.model_dump(mode="json") for item in snapshot.enrollments],
            "payments": [item.model_dump(mode="json") for item in snapshot.payments],
            "notifications": [item.model_dump(mode="json") for item in snapshot.notifications],
            "history": [item.model_dump(mode="json") for item in snapshot.history],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/admin/staff-performance")
def admin_staff_performance(user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    overview = staff_ops_service.performance_overview()
    return {
        "data": {
            "summary": overview["summary"].model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in overview["items"]],
        },
        "error": None,
    }


@api_router.get("/consultant/dashboard")
def consultant_dashboard(
    staff_name: str = Query(...),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    snapshot = consultant_workspace_service.dashboard(staff_name)
    return {
        "data": {
            "summary": snapshot.summary.model_dump(mode="json"),
            "hot_leads": [item.model_dump(mode="json") for item in snapshot.hot_leads],
            "follow_up_queue": [item.model_dump(mode="json") for item in snapshot.follow_up_queue],
            "recently_updated": [item.model_dump(mode="json") for item in snapshot.recently_updated],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.get("/consultant/leads/{lead_id}")
def consultant_lead_detail(
    lead_id: UUID,
    staff_name: str = Query(...),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        snapshot = consultant_workspace_service.lead_detail(staff_name, lead_id)
        snapshot = snapshot.model_copy(update={"followup_draft": ai_assistant_service.followup_draft(lead_id)})
        return {"data": snapshot.model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Consultant lead not found") from exc


@api_router.post("/ai/leads/{lead_id}/followup-draft")
def ai_followup_draft(lead_id: UUID, user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    try:
        return {"data": ai_assistant_service.followup_draft(lead_id).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc


@api_router.post("/ai/lesson-plan-draft")
def ai_lesson_plan_draft(
    payload: LessonPlanDraftRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": ai_assistant_service.lesson_plan_draft(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class not found") from exc


@api_router.get("/ai/logs")
def ai_logs(module_name: str | None = Query(default=None), user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": [item.model_dump(mode="json") for item in analytics_service.ai_logs(module_name)], "error": None}


@api_router.get("/ai/status")
def ai_status(user=Depends(require_roles("super_admin", "manager"))) -> dict[str, object]:
    return {"data": ai_assistant_service.provider_status().model_dump(mode="json"), "error": None}


@api_router.get("/teaching/session-records")
def teaching_session_records(
    class_id: UUID | None = Query(default=None),
    teacher_name: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    items = teaching_ops_service.list_teaching_session_records(class_id, teacher_name, approval_status)
    return {"data": [item.model_dump(mode="json") for item in items], "error": None}


@api_router.post("/teaching/session-records")
def create_teaching_session_record(
    payload: TeachingSessionUpsertRequest,
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.upsert_teaching_session_record(payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Class not found") from exc


@api_router.patch("/teaching/session-records/{record_id}/review")
def review_teaching_session_record(
    record_id: UUID,
    payload: TeachingSessionReviewRequest,
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    try:
        return {"data": teaching_ops_service.review_teaching_session_record(record_id, payload).model_dump(mode="json"), "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Teaching session record not found") from exc


@api_router.get("/teacher/verification")
def teacher_verification_snapshot_api(
    teacher_name: str = Query(...),
    user=Depends(require_roles("super_admin", "manager", "teacher")),
) -> dict[str, object]:
    snapshot = teacher_verification_service.snapshot(teacher_name)
    return {
        "data": {
            "teacher_name": snapshot.teacher_name,
            "teacher_email": snapshot.teacher_email,
            "required_score": snapshot.required_score,
            "manual_sections": [item.model_dump(mode="json") for item in snapshot.manual_sections],
            "questions": [
                {
                    "id": str(item.id),
                    "section_slug": item.section_slug,
                    "prompt": item.prompt,
                    "options": item.options,
                    "sort_order": item.sort_order,
                    "explanation": item.explanation,
                }
                for item in snapshot.questions
            ],
            "latest_attempt": snapshot.latest_attempt.model_dump(mode="json") if snapshot.latest_attempt else None,
            "unlocked_permission": snapshot.unlocked_permission,
            "pass_status": snapshot.pass_status,
            "recommended_actions": snapshot.recommended_actions,
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


@api_router.post("/teacher/verification")
def teacher_verification_submit_api(
    payload: TeacherVerificationSubmitRequest,
    user=Depends(require_roles("super_admin", "manager", "teacher")),
) -> dict[str, object]:
    try:
        return {"data": teacher_verification_service.submit(payload).model_dump(mode="json"), "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api_router.get("/admin/teacher-verification")
def teacher_verification_directory_api(
    user=Depends(require_roles("super_admin", "manager")),
) -> dict[str, object]:
    snapshots = teacher_verification_service.directory()
    return {
        "data": [
            {
                "teacher_name": item.teacher_name,
                "teacher_email": item.teacher_email,
                "required_score": item.required_score,
                "pass_status": item.pass_status,
                "unlocked_permission": item.unlocked_permission,
                "recommended_actions": item.recommended_actions,
                "latest_attempt": item.latest_attempt.model_dump(mode="json") if item.latest_attempt else None,
                "generated_at": item.generated_at.isoformat(),
            }
            for item in snapshots
        ],
        "error": None,
    }


@api_router.get("/teacher/dashboard")
def teacher_dashboard(teacher_name: str = Query(...), user=Depends(require_roles("super_admin", "manager", "consultant"))) -> dict[str, object]:
    dashboard = teacher_workspace_service.dashboard(teacher_name)
    return {
        "data": {
            "teacher_name": dashboard["teacher_name"],
            "summary": dashboard["summary"],
            "classes": [item.model_dump(mode="json") for item in dashboard["classes"]],
            "assignments": [item.model_dump(mode="json") for item in dashboard["assignments"]],
            "exams": [item.model_dump(mode="json") for item in dashboard["exams"]],
            "session_records": [item.model_dump(mode="json") for item in dashboard["session_records"]],
            "pending_assignment_reviews": [item.model_dump(mode="json") for item in dashboard["pending_assignment_reviews"]],
            "pending_exam_reviews": [item.model_dump(mode="json") for item in dashboard["pending_exam_reviews"]],
        },
        "error": None,
    }


@api_router.get("/teacher/classes/{class_id}")
def teacher_class_detail(
    class_id: UUID,
    teacher_name: str = Query(...),
    user=Depends(require_roles("super_admin", "manager", "consultant")),
) -> dict[str, object]:
    try:
        snapshot = teacher_workspace_service.class_snapshot(teacher_name, class_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Teacher class not found") from exc
    return {
        "data": {
            "class_item": snapshot.class_item.model_dump(mode="json"),
            "summary": snapshot.summary.model_dump(mode="json"),
            "roster": [item.model_dump(mode="json") for item in snapshot.roster],
            "assignments": [item.model_dump(mode="json") for item in snapshot.assignments],
            "exams": [item.model_dump(mode="json") for item in snapshot.exams],
            "attendance_records": [item.model_dump(mode="json") for item in snapshot.attendance_records],
            "assignment_submissions": [item.model_dump(mode="json") for item in snapshot.assignment_submissions],
            "exam_submissions": [item.model_dump(mode="json") for item in snapshot.exam_submissions],
            "session_records": [item.model_dump(mode="json") for item in snapshot.session_records],
            "generated_at": snapshot.generated_at.isoformat(),
        },
        "error": None,
    }


router.include_router(api_router)
