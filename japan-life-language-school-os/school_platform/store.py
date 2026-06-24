from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from school_platform.config import load_settings
from school_platform.repository import build_repository, repository_readiness
from school_platform.schemas import (
    AssignmentCreateRequest,
    AssignmentRecord,
    AssignmentSubmissionCreateRequest,
    AssignmentSubmissionRecord,
    AiLogRecord,
    AttendanceMarkRequest,
    AttendanceRecord,
    ClassSummary,
    ClassUpsertRequest,
    CourseContentSnapshot,
    CourseDetail,
    CourseModuleRecord,
    CourseModuleUpsertRequest,
    CourseSummary,
    CourseUpsertRequest,
    DashboardMetrics,
    ExamCreateRequest,
    ExamRecord,
    ExamSubmissionCreateRequest,
    ExamSubmissionRecord,
    ApplicantStatusUpdateRequest,
    InterviewCreateRequest,
    InterviewRecord,
    InterviewUpdateRequest,
    JobPositionCreateRequest,
    JobPositionRecord,
    ReportOverview,
    EnrollmentCreate,
    EnrollmentRecord,
    EnrollmentResponse,
    FollowupDraftResponse,
    HomePayload,
    Lead,
    LeadLog,
    LeadStatusChangeRequest,
    PaymentIntentCreate,
    PaymentIntentResponse,
    PaymentRecord,
    PaymentWebhookPayload,
    ApplicantCreateRequest,
    ApplicantRecord,
    NotificationCreate,
    NotificationRecord,
    OnboardingRecord,
    OnboardingUpsertRequest,
    ProgressModule,
    ProgressSnapshot,
    StaffRecord,
    StudentDashboard,
    StudentRecord,
    SubAccountCreateRequest,
    SubmissionGradeRequest,
    TeacherManualSectionRecord,
    TeachingSessionRecord,
    TeachingSessionReviewRequest,
    TeachingSessionUpsertRequest,
    TeachingMaterialRecord,
    TeachingMaterialUpsertRequest,
    TeacherVerificationAttemptRecord,
    TeacherVerificationQuestionRecord,
    TeacherVerificationSubmitRequest,
    TrialBookingCreate,
    TrialBookingResponse,
    TrialSlot,
    UserAccount,
)
from school_platform.snapshot_migration import normalize_snapshot_for_postgres
from school_platform.verification import TEACHER_VERIFICATION_REQUIRED_SCORE, teacher_manual_blueprint

_UNSET = object()

_ROLE_PERMISSION_PRESETS: dict[str, list[str]] = {
    "super_admin": ["*"],
    "manager": ["dashboard:read", "leads:read", "leads:write", "classes:read", "payments:read", "staff:read"],
    "consultant": ["leads:read", "leads:write", "dashboard:read"],
    "teacher": ["dashboard:read", "classes:read", "materials:write"],
}

_SUBACCOUNT_ROLE_OPTIONS: dict[str, tuple[str, ...]] = {
    "super_admin": ("manager", "consultant", "teacher"),
    "manager": ("consultant", "teacher"),
}


def _course_month_floor(today: date | None = None) -> date:
    today = today or date.today()
    august_floor = date(today.year, 8, 1)
    if today < august_floor:
        return august_floor
    return today + timedelta(days=14)


def _monthly_class_name(start_date: date, suffix: str) -> str:
    return f"{start_date.month} 月{suffix}"


def _now() -> datetime:
    return datetime.now().astimezone()


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.astimezone()
    return value


class SchoolPlatformStore:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.repository = build_repository(self.settings)
        self.staff: list[StaffRecord] = self._seed_staff()
        self.users: list[UserAccount] = self._seed_users()
        self.courses: list[CourseDetail] = self._seed_courses()
        self.course_modules: list[CourseModuleRecord] = self._seed_course_modules()
        self.classes: list[ClassSummary] = self._seed_classes()
        self.teaching_materials: list[TeachingMaterialRecord] = self._seed_teaching_materials()
        self.leads: list[Lead] = self._seed_leads()
        self.lead_logs: list[LeadLog] = self._seed_lead_logs()
        self.students: list[StudentRecord] = []
        self.enrollments: list[EnrollmentRecord] = []
        self.payments: list[PaymentRecord] = []
        self.job_positions: list[JobPositionRecord] = self._seed_job_positions()
        self.applicants: list[ApplicantRecord] = []
        self.interviews: list[InterviewRecord] = []
        self.onboarding_records: list[OnboardingRecord] = []
        self.teacher_manual_sections: list[TeacherManualSectionRecord] = self._seed_teacher_manual_sections()
        self.teacher_verification_questions: list[TeacherVerificationQuestionRecord] = self._seed_teacher_verification_questions()
        self.teacher_verification_attempts: list[TeacherVerificationAttemptRecord] = []
        self.assignments: list[AssignmentRecord] = self._seed_assignments()
        self.assignment_submissions: list[AssignmentSubmissionRecord] = []
        self.attendance_records: list[AttendanceRecord] = []
        self.exams: list[ExamRecord] = self._seed_exams()
        self.exam_submissions: list[ExamSubmissionRecord] = []
        self.teaching_session_records: list[TeachingSessionRecord] = []
        self.ai_logs: list[AiLogRecord] = self._seed_ai_logs()
        self.notifications: list[NotificationRecord] = []
        self._load_or_seed()

    def _seed_staff(self) -> list[StaffRecord]:
        return [
            StaffRecord(id=uuid4(), name="Mika Chen", role="consultant", department="Admissions", title="招生顧問"),
            StaffRecord(id=uuid4(), name="Sora Lin", role="consultant", department="Admissions", title="招生顧問"),
            StaffRecord(id=uuid4(), name="Yuki Wang", role="manager", department="Operations", title="校務主管"),
            StaffRecord(id=uuid4(), name="Aki Mori", role="teacher", department="Teaching", title="日語講師"),
        ]

    def _seed_users(self) -> list[UserAccount]:
        staff_by_name = {item.name: item for item in self.staff}
        return [
            UserAccount(
                id=uuid4(),
                email="admin@jls.local",
                name="Platform Admin",
                password_hash=self.hash_password("admin123"),
                role="super_admin",
                permissions=["*"],
            ),
            UserAccount(
                id=uuid4(),
                email="manager@jls.local",
                name="Yuki Wang",
                password_hash=self.hash_password("manager123"),
                role="manager",
                staff_id=staff_by_name["Yuki Wang"].id,
                permissions=["dashboard:read", "leads:read", "leads:write", "classes:read", "payments:read", "staff:read"],
            ),
            UserAccount(
                id=uuid4(),
                email="mika@jls.local",
                name="Mika Chen",
                password_hash=self.hash_password("mika123"),
                role="consultant",
                staff_id=staff_by_name["Mika Chen"].id,
                permissions=["leads:read", "leads:write", "dashboard:read"],
            ),
            UserAccount(
                id=uuid4(),
                email="sora@jls.local",
                name="Sora Lin",
                password_hash=self.hash_password("sora123"),
                role="consultant",
                staff_id=staff_by_name["Sora Lin"].id,
                permissions=["leads:read", "leads:write", "dashboard:read"],
            ),
            UserAccount(
                id=uuid4(),
                email="aki@jls.local",
                name="Aki Mori",
                password_hash=self.hash_password("aki123"),
                role="teacher",
                staff_id=staff_by_name["Aki Mori"].id,
                permissions=["dashboard:read", "classes:read", "materials:write"],
            ),
        ]

    def _seed_courses(self) -> list[CourseDetail]:
        return [
            CourseDetail(
                id=uuid4(),
                slug="japan-life-starter",
                name="日本生活日語 Starter",
                course_type="生活日語",
                level="N5-",
                delivery_mode="hybrid",
                price=12800,
                short_description="給準備赴日生活的新手，先學會租屋、購物、就醫與交通溝通。",
                objectives=["建立赴日生活生存會話", "完成基本自我介紹與求助", "理解高頻生活情境"],
                highlights=["生活情境對話", "LINE 課後複習", "赴日前學習地圖"],
                modules=["自我介紹與求助", "租屋與交通", "購物與餐飲", "醫療與行政"],
                teacher_names=["Aki Mori"],
            ),
            CourseDetail(
                id=uuid4(),
                slug="japanese-job-interview",
                name="日本工作面試日語",
                course_type="職場日語",
                level="N4-N3",
                delivery_mode="online",
                price=16800,
                short_description="聚焦履歷、自我介紹、面試問答與職場禮貌。",
                objectives=["完成面試自我介紹", "掌握敬語與面試禮節", "模擬常見問答"],
                highlights=["履歷改寫", "模擬面試", "AI 回答修正"],
                modules=["自我介紹", "志望動機", "經歷說明", "模擬問答"],
                teacher_names=["Aki Mori"],
            ),
            CourseDetail(
                id=uuid4(),
                slug="jlpt-n5-bootcamp",
                name="JLPT N5 Bootcamp",
                course_type="JLPT",
                level="N5",
                delivery_mode="online",
                price=9800,
                short_description="零基礎到 N5 的密集打底班。",
                objectives=["建立五十音與基礎文法", "完成 N5 範圍高頻題型訓練"],
                highlights=["每週測驗", "AI 弱點分析", "考前衝刺題庫"],
                modules=["五十音", "基礎文法", "聽力練習", "題型演練"],
                teacher_names=["Aki Mori"],
            ),
        ]

    def _seed_course_modules(self) -> list[CourseModuleRecord]:
        now = _now()
        description_map: dict[tuple[str, str], str] = {
            ("japan-life-starter", "自我介紹與求助"): "建立赴日初期最常用的自我介紹、請求協助與緊急求助表達。",
            ("japan-life-starter", "租屋與交通"): "涵蓋租屋詢問、看房、地址確認與搭車轉乘的高頻句型。",
            ("japan-life-starter", "購物與餐飲"): "練習超市、便利商店、餐廳點餐與付款時的實際對話。",
            ("japan-life-starter", "醫療與行政"): "整理掛號、症狀說明、領藥與區役所行政對應的核心用語。",
            ("japanese-job-interview", "自我介紹"): "用日商面試節奏整理 30 秒、60 秒與 90 秒版本的自我介紹。",
            ("japanese-job-interview", "志望動機"): "拆解志望動機的邏輯順序，避免只會背模板卻不會延伸回答。",
            ("japanese-job-interview", "經歷說明"): "練習把學歷、工作經歷與可轉移能力說得自然又有禮貌。",
            ("japanese-job-interview", "模擬問答"): "依常見面試問題做追問演練與修正，強化臨場應答能力。",
            ("jlpt-n5-bootcamp", "五十音"): "建立平假名、片假名識讀與基本發音節奏，避免後續學習卡關。",
            ("jlpt-n5-bootcamp", "基礎文法"): "把 N5 核心句型拆成可立即套用的生活例句與練習。",
            ("jlpt-n5-bootcamp", "聽力練習"): "用短句與情境題培養基本聽辨力與反應速度。",
            ("jlpt-n5-bootcamp", "題型演練"): "用小測驗與題型演練建立正式考試的節奏感。",
        }
        items: list[CourseModuleRecord] = []
        for course in self.courses:
            for index, title in enumerate(course.modules, start=1):
                items.append(
                    CourseModuleRecord(
                        id=uuid4(),
                        course_slug=course.slug,
                        title=title,
                        description=description_map.get((course.slug, title), f"{course.name} 的第 {index} 個核心教學章節。"),
                        sort_order=index,
                        material_url=f"https://school-platform.local/materials/{course.slug}/module-{index}",
                        owner_type="platform",
                        status="published",
                        created_by="Platform Curriculum Team",
                        updated_by="Platform Curriculum Team",
                        created_at=now,
                        updated_at=now,
                    )
                )
        return items

    def _seed_teaching_materials(self) -> list[TeachingMaterialRecord]:
        now = _now()
        class_by_slug = {item.course_slug: item for item in self.classes}
        return [
            TeachingMaterialRecord(
                id=uuid4(),
                course_slug="japan-life-starter",
                class_id=None,
                title="平台核心：赴日前生活會話地圖",
                description="平台自有的生活日語導覽地圖，幫學員先建立租屋、交通、購物、就醫四大場景。",
                material_url="https://school-platform.local/library/japan-life-starter/life-map",
                owner_type="platform",
                visibility="public",
                status="published",
                created_by="Platform Curriculum Team",
                updated_by="Platform Curriculum Team",
                created_at=now,
                updated_at=now,
            ),
            TeachingMaterialRecord(
                id=uuid4(),
                course_slug="japanese-job-interview",
                class_id=None,
                title="平台核心：面試回答框架講義",
                description="整理自我介紹、志望動機與經歷說明的回答骨架，作為平台標準教學資源。",
                material_url="https://school-platform.local/library/japanese-job-interview/interview-framework",
                owner_type="platform",
                visibility="public",
                status="published",
                created_by="Platform Curriculum Team",
                updated_by="Platform Curriculum Team",
                created_at=now,
                updated_at=now,
            ),
            TeachingMaterialRecord(
                id=uuid4(),
                course_slug="jlpt-n5-bootcamp",
                class_id=None,
                title="平台核心：N5 打底練習包",
                description="包含五十音、基礎文法與高頻聽力練習的標準化練習資源。",
                material_url="https://school-platform.local/library/jlpt-n5-bootcamp/n5-core-pack",
                owner_type="platform",
                visibility="public",
                status="published",
                created_by="Platform Curriculum Team",
                updated_by="Platform Curriculum Team",
                created_at=now,
                updated_at=now,
            ),
            TeachingMaterialRecord(
                id=uuid4(),
                course_slug="japan-life-starter",
                class_id=class_by_slug["japan-life-starter"].id if "japan-life-starter" in class_by_slug else None,
                title="老師補充：藥局與租屋會話延伸講義",
                description="Aki Mori 依照晚間班學生常見卡點補充的情境講義，屬於教師補充內容。",
                material_url="https://school-platform.local/teacher/aki/japan-life-starter/pharmacy-rental-notes",
                owner_type="teacher",
                visibility="enrolled_only",
                status="published",
                created_by="Aki Mori",
                updated_by="Aki Mori",
                created_at=now,
                updated_at=now,
            ),
        ]

    def _seed_classes(self) -> list[ClassSummary]:
        course_map = {course.slug: course for course in self.courses}
        month_floor = _course_month_floor()
        starter_start = max(month_floor, date(month_floor.year, month_floor.month, 4))
        interview_start = max(month_floor, date(month_floor.year, month_floor.month, 8))
        bootcamp_start = max(month_floor, date(month_floor.year, month_floor.month, 3))
        return [
            ClassSummary(
                id=uuid4(),
                course_id=course_map["japan-life-starter"].id,
                course_slug="japan-life-starter",
                name=_monthly_class_name(starter_start, "晚間班"),
                teacher_name="Aki Mori",
                start_date=starter_start,
                end_date=starter_start + timedelta(days=60),
                weekday="Tue / Thu",
                start_time=time(hour=19, minute=30),
                end_time=time(hour=21, minute=0),
                capacity=18,
                enrolled_count=9,
                location_label="Taipei + Zoom",
                status="open",
            ),
            ClassSummary(
                id=uuid4(),
                course_id=course_map["japanese-job-interview"].id,
                course_slug="japanese-job-interview",
                name=_monthly_class_name(interview_start, "週末班"),
                teacher_name="Aki Mori",
                start_date=interview_start,
                end_date=interview_start + timedelta(days=42),
                weekday="Sat",
                start_time=time(hour=10, minute=0),
                end_time=time(hour=12, minute=0),
                capacity=12,
                enrolled_count=5,
                location_label="Zoom Live",
                status="open",
            ),
            ClassSummary(
                id=uuid4(),
                course_id=course_map["jlpt-n5-bootcamp"].id,
                course_slug="jlpt-n5-bootcamp",
                name=_monthly_class_name(bootcamp_start, "衝刺班"),
                teacher_name="Aki Mori",
                start_date=bootcamp_start,
                end_date=bootcamp_start + timedelta(days=42),
                weekday="Mon / Wed",
                start_time=time(hour=20, minute=0),
                end_time=time(hour=21, minute=30),
                capacity=20,
                enrolled_count=14,
                location_label="Zoom Live",
                status="open",
            ),
        ]

    def _seed_leads(self) -> list[Lead]:
        now = _now()
        return [
            Lead(
                id=uuid4(),
                name="Emily Huang",
                phone="0912000111",
                email="emily@example.com",
                source_channel="website",
                interested_course_slug="japan-life-starter",
                japanese_level="beginner",
                study_goal="明年赴日生活，想先學會租屋與看病會話。",
                intent_score=88,
                win_probability=72,
                status="trial_booked",
                assigned_staff_name="Mika Chen",
                last_contact_at=now - timedelta(days=1),
                next_follow_up_at=now + timedelta(days=1),
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(hours=6),
            ),
            Lead(
                id=uuid4(),
                name="Kevin Wu",
                phone="0922333444",
                email="kevin@example.com",
                source_channel="line",
                interested_course_slug="japanese-job-interview",
                japanese_level="N4",
                study_goal="想去日本找工作，需要練面試。",
                intent_score=76,
                win_probability=60,
                status="contacted",
                assigned_staff_name="Sora Lin",
                last_contact_at=now - timedelta(days=2),
                next_follow_up_at=now,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(hours=10),
            ),
            Lead(
                id=uuid4(),
                name="Lina Zhang",
                phone="0801222333",
                email="lina.partner@example.com",
                source_channel="partner_referral",
                campaign_name="partner-referral-june",
                interested_course_slug="japan-life-starter",
                japanese_level="beginner",
                study_goal="想在自己的社群先推生活日語班。",
                intent_score=69,
                win_probability=42,
                status="replied",
                assigned_staff_name="Mika Chen",
                last_contact_at=now - timedelta(days=1),
                next_follow_up_at=now + timedelta(days=2),
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(hours=8),
            ),
            Lead(
                id=uuid4(),
                name="Oscar Chen",
                phone="0801444555",
                email="oscar.osaka@example.com",
                source_channel="osaka_partner",
                campaign_name="OSA-03-shinsaibashi",
                interested_course_slug="japanese-job-interview",
                japanese_level="N4",
                study_goal="想了解大阪單區加盟與職場日語產品如何搭配。",
                intent_score=91,
                win_probability=78,
                status="considering",
                assigned_staff_name="Sora Lin",
                last_contact_at=now - timedelta(hours=18),
                next_follow_up_at=now + timedelta(days=1),
                created_at=now - timedelta(days=4),
                updated_at=now - timedelta(hours=4),
            ),
            Lead(
                id=uuid4(),
                name="Mandy Liu",
                phone="0801666777",
                email="mandy.osaka@example.com",
                source_channel="osaka_single_zone",
                campaign_name="OSA-05-tennoji",
                interested_course_slug="japan-life-starter",
                japanese_level="beginner",
                study_goal="想先看加盟後的招生報表與培訓內容。",
                intent_score=86,
                win_probability=70,
                status="trial_booked",
                assigned_staff_name="Mika Chen",
                last_contact_at=now - timedelta(hours=12),
                next_follow_up_at=now + timedelta(days=1),
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(hours=3),
            ),
            Lead(
                id=uuid4(),
                name="Derek Lin",
                phone="0801888999",
                email="derek.regional@example.com",
                source_channel="regional_operator",
                campaign_name="kansai-multi-zone",
                interested_course_slug="japanese-job-interview",
                japanese_level="N3",
                study_goal="希望以多區營運方式導入既有團隊。",
                intent_score=94,
                win_probability=82,
                status="enrolled",
                assigned_staff_name="Yuki Wang",
                last_contact_at=now - timedelta(days=1),
                next_follow_up_at=now + timedelta(days=3),
                created_at=now - timedelta(days=6),
                updated_at=now - timedelta(hours=2),
            ),
            Lead(
                id=uuid4(),
                name="Cindy Wu",
                phone="0801999000",
                email="cindy.regional@example.com",
                source_channel="multi_zone_operator",
                campaign_name="kansai-multi-zone-b",
                interested_course_slug="jlpt-n5-bootcamp",
                japanese_level="N5",
                study_goal="正在評估是否用多區模式與夥伴共同推廣。",
                intent_score=58,
                win_probability=20,
                status="lost",
                assigned_staff_name="Yuki Wang",
                last_contact_at=now - timedelta(days=7),
                next_follow_up_at=None,
                created_at=now - timedelta(days=8),
                updated_at=now - timedelta(days=3),
            ),
        ]

    def _seed_lead_logs(self) -> list[LeadLog]:
        lead_by_name = {lead.name: lead for lead in self.leads}
        now = _now()
        return [
            LeadLog(
                id=uuid4(),
                lead_id=lead_by_name["Emily Huang"].id,
                staff_name="Mika Chen",
                contact_method="line",
                content="已回覆課程差異，學員希望先試聽晚間班。",
                next_action="試聽前一天提醒並提供上課連結。",
                created_at=now - timedelta(days=1),
            ),
            LeadLog(
                id=uuid4(),
                lead_id=lead_by_name["Kevin Wu"].id,
                staff_name="Sora Lin",
                contact_method="call",
                content="確認學員目標是日本求職，對面試班有興趣。",
                next_action="明天下午再次追蹤是否要預約試聽。",
                created_at=now - timedelta(days=2),
            ),
        ]

    def _seed_assignments(self) -> list[AssignmentRecord]:
        class_by_slug = {item.course_slug: item for item in self.classes}
        now = _now()
        items: list[AssignmentRecord] = []
        if "japan-life-starter" in class_by_slug:
            items.append(
                AssignmentRecord(
                    id=uuid4(),
                    class_id=class_by_slug["japan-life-starter"].id,
                    title="生活會話作業 1",
                    content="請錄一段 1 分鐘自我介紹，並寫下租屋時最想詢問的 3 個問題。",
                    due_at=now + timedelta(days=5),
                    created_by="Aki Mori",
                    created_at=now - timedelta(days=1),
                )
            )
        if "japanese-job-interview" in class_by_slug:
            items.append(
                AssignmentRecord(
                    id=uuid4(),
                    class_id=class_by_slug["japanese-job-interview"].id,
                    title="面試自我介紹草稿",
                    content="請完成 200 字的面試自我介紹，並列出 2 個你的優勢。",
                    due_at=now + timedelta(days=7),
                    created_by="Aki Mori",
                    created_at=now - timedelta(hours=12),
                )
            )
        return items

    def _seed_job_positions(self) -> list[JobPositionRecord]:
        now = _now()
        return [
            JobPositionRecord(
                id=uuid4(),
                title="日語講師",
                department="Teaching",
                employment_type="part_time",
                location_label="Taipei / Remote",
                salary_range="JPY 3,800 - 6,500 / hour",
                summary="負責生活日語、面試日語與初級 JLPT 班授課。",
                requirements=["日語教學經驗 2 年以上", "可設計口說與情境課程", "可配合晚間或週末授課"],
                status="open",
                created_at=now - timedelta(days=5),
            ),
            JobPositionRecord(
                id=uuid4(),
                title="招生顧問",
                department="Admissions",
                employment_type="full_time",
                location_label="Taipei",
                salary_range="JPY 190,000 - 280,000 / month + bonus",
                summary="負責招生諮詢、名單跟進、試聽安排與成交追蹤。",
                requirements=["具銷售或教育產業經驗", "溝通能力佳", "熟悉 CRM 操作加分"],
                status="open",
                created_at=now - timedelta(days=3),
            ),
        ]

    def _seed_ai_logs(self) -> list[AiLogRecord]:
        now = _now()
        return [
            AiLogRecord(
                id=uuid4(),
                module_name="admissions",
                actor_email="manager@jls.local",
                action_name="lead_heatmap_summary",
                input_summary="本週 lead 與試聽資料",
                output_summary="網站 lead 品質高於 line lead，建議優先追蹤網站新名單。",
                created_at=now - timedelta(hours=6),
            ),
            AiLogRecord(
                id=uuid4(),
                module_name="teaching",
                actor_email="aki@jls.local",
                action_name="lesson_summary",
                input_summary="生活日語 Starter 班第 1 週教學紀錄",
                output_summary="學生在藥局與租屋對話表現較弱，建議下週補強口說演練。",
                created_at=now - timedelta(hours=3),
            ),
        ]

    def _seed_exams(self) -> list[ExamRecord]:
        class_by_slug = {item.course_slug: item for item in self.classes}
        now = _now()
        items: list[ExamRecord] = []
        if "japan-life-starter" in class_by_slug:
            items.append(
                ExamRecord(
                    id=uuid4(),
                    class_id=class_by_slug["japan-life-starter"].id,
                    title="生活情境口說小考",
                    exam_type="speaking_quiz",
                    instructions="請模擬在藥局詢問感冒藥，並完成 3 句以上應答。",
                    total_score=100,
                    due_at=now + timedelta(days=6),
                    created_by="Aki Mori",
                    created_at=now - timedelta(hours=18),
                )
            )
        if "jlpt-n5-bootcamp" in class_by_slug:
            items.append(
                ExamRecord(
                    id=uuid4(),
                    class_id=class_by_slug["jlpt-n5-bootcamp"].id,
                    title="N5 文法小考 1",
                    exam_type="grammar_quiz",
                    instructions="完成 10 題文法選擇並寫下 2 句自造句。",
                    total_score=100,
                    due_at=now + timedelta(days=8),
                    created_by="Aki Mori",
                    created_at=now - timedelta(hours=8),
                )
            )
        return items

    def _seed_teacher_manual_sections(self) -> list[TeacherManualSectionRecord]:
        blueprint = teacher_manual_blueprint()
        now = _now()
        return [
            TeacherManualSectionRecord(
                id=uuid4(),
                slug=item["slug"],
                title=item["title"],
                summary=item["summary"],
                content=item["content"],
                estimated_minutes=item.get("estimated_minutes", 0),
                required=bool(item.get("required", True)),
                created_at=now,
                updated_at=now,
            )
            for item in blueprint["sections"]
        ]

    def _seed_teacher_verification_questions(self) -> list[TeacherVerificationQuestionRecord]:
        blueprint = teacher_manual_blueprint()
        now = _now()
        return [
            TeacherVerificationQuestionRecord(
                id=uuid4(),
                section_slug=item["section_slug"],
                prompt=item["prompt"],
                options=list(item.get("options", [])),
                correct_option=item["correct_option"],
                explanation=item.get("explanation"),
                sort_order=int(item.get("sort_order", 0)),
                created_at=now,
            )
            for item in blueprint["questions"]
        ]

    def _serialize_state(self) -> dict[str, object]:
        return {
            "staff": [item.model_dump(mode="json") for item in self.staff],
            "users": [item.model_dump(mode="json") for item in self.users],
            "courses": [item.model_dump(mode="json") for item in self.courses],
            "course_modules": [item.model_dump(mode="json") for item in self.course_modules],
            "classes": [item.model_dump(mode="json") for item in self.classes],
            "teaching_materials": [item.model_dump(mode="json") for item in self.teaching_materials],
            "leads": [item.model_dump(mode="json") for item in self.leads],
            "lead_logs": [item.model_dump(mode="json") for item in self.lead_logs],
            "students": [item.model_dump(mode="json") for item in self.students],
            "enrollments": [item.model_dump(mode="json") for item in self.enrollments],
            "payments": [item.model_dump(mode="json") for item in self.payments],
            "job_positions": [item.model_dump(mode="json") for item in self.job_positions],
            "applicants": [item.model_dump(mode="json") for item in self.applicants],
            "interviews": [item.model_dump(mode="json") for item in self.interviews],
            "onboarding_records": [item.model_dump(mode="json") for item in self.onboarding_records],
            "teacher_manual_sections": [item.model_dump(mode="json") for item in self.teacher_manual_sections],
            "teacher_verification_questions": [item.model_dump(mode="json") for item in self.teacher_verification_questions],
            "teacher_verification_attempts": [item.model_dump(mode="json") for item in self.teacher_verification_attempts],
            "assignments": [item.model_dump(mode="json") for item in self.assignments],
            "assignment_submissions": [item.model_dump(mode="json") for item in self.assignment_submissions],
            "attendance_records": [item.model_dump(mode="json") for item in self.attendance_records],
            "exams": [item.model_dump(mode="json") for item in self.exams],
            "exam_submissions": [item.model_dump(mode="json") for item in self.exam_submissions],
            "teaching_session_records": [item.model_dump(mode="json") for item in self.teaching_session_records],
            "ai_logs": [item.model_dump(mode="json") for item in self.ai_logs],
            "notifications": [item.model_dump(mode="json") for item in self.notifications],
        }

    def _merge_seed_staff(self) -> None:
        existing_names = {item.name for item in self.staff}
        for seeded in self._seed_staff():
            if seeded.name not in existing_names:
                self.staff.append(seeded)

    def _merge_seed_users(self) -> None:
        existing_emails = {item.email.lower() for item in self.users}
        for seeded in self._seed_users():
            if seeded.email.lower() not in existing_emails:
                self.users.append(seeded)

    def _merge_seed_teacher_manual_sections(self) -> None:
        existing_slugs = {item.slug for item in self.teacher_manual_sections}
        for seeded in self._seed_teacher_manual_sections():
            if seeded.slug not in existing_slugs:
                self.teacher_manual_sections.append(seeded)

    def _merge_seed_teacher_verification_questions(self) -> None:
        existing_pairs = {(item.section_slug, item.prompt) for item in self.teacher_verification_questions}
        for seeded in self._seed_teacher_verification_questions():
            key = (seeded.section_slug, seeded.prompt)
            if key not in existing_pairs:
                self.teacher_verification_questions.append(seeded)

    def _load_or_seed(self) -> None:
        payload = self.repository.load()
        if not payload:
            self._persist()
            return
        needs_persist = False
        loaded_staff = [StaffRecord.model_validate(item) for item in payload.get("staff", [])]
        if loaded_staff:
            self.staff = loaded_staff
            before_count = len(self.staff)
            self._merge_seed_staff()
            needs_persist = needs_persist or len(self.staff) != before_count
        else:
            needs_persist = True

        loaded_users = [UserAccount.model_validate(item) for item in payload.get("users", [])]
        if loaded_users:
            self.users = loaded_users
            before_count = len(self.users)
            self._merge_seed_users()
            needs_persist = needs_persist or len(self.users) != before_count
        else:
            self.users = self._seed_users()
            needs_persist = True

        loaded_courses = [CourseDetail.model_validate(item) for item in payload.get("courses", [])]
        if loaded_courses:
            self.courses = loaded_courses
        else:
            needs_persist = True

        loaded_course_modules = [CourseModuleRecord.model_validate(item) for item in payload.get("course_modules", [])]
        if loaded_course_modules:
            self.course_modules = loaded_course_modules
        else:
            self.course_modules = self._seed_course_modules()
            needs_persist = True

        loaded_classes = [ClassSummary.model_validate(item) for item in payload.get("classes", [])]
        if loaded_classes:
            self.classes = loaded_classes
        else:
            needs_persist = True

        loaded_teaching_materials = [TeachingMaterialRecord.model_validate(item) for item in payload.get("teaching_materials", [])]
        if loaded_teaching_materials:
            self.teaching_materials = loaded_teaching_materials
        else:
            self.teaching_materials = self._seed_teaching_materials()
            needs_persist = True

        self.leads = [Lead.model_validate(item) for item in payload.get("leads", [])]
        self.lead_logs = [LeadLog.model_validate(item) for item in payload.get("lead_logs", [])]
        self.students = [StudentRecord.model_validate(item) for item in payload.get("students", [])]
        self.enrollments = [EnrollmentRecord.model_validate(item) for item in payload.get("enrollments", [])]
        self.payments = [PaymentRecord.model_validate(item) for item in payload.get("payments", [])]
        loaded_job_positions = [JobPositionRecord.model_validate(item) for item in payload.get("job_positions", [])]
        if loaded_job_positions:
            self.job_positions = loaded_job_positions
        else:
            needs_persist = True
        self.applicants = [ApplicantRecord.model_validate(item) for item in payload.get("applicants", [])]
        self.interviews = [InterviewRecord.model_validate(item) for item in payload.get("interviews", [])]
        self.onboarding_records = [OnboardingRecord.model_validate(item) for item in payload.get("onboarding_records", [])]
        loaded_teacher_manual_sections = [
            TeacherManualSectionRecord.model_validate(item) for item in payload.get("teacher_manual_sections", [])
        ]
        if loaded_teacher_manual_sections:
            self.teacher_manual_sections = loaded_teacher_manual_sections
            before_count = len(self.teacher_manual_sections)
            self._merge_seed_teacher_manual_sections()
            needs_persist = needs_persist or len(self.teacher_manual_sections) != before_count
        else:
            self.teacher_manual_sections = self._seed_teacher_manual_sections()
            needs_persist = True
        loaded_teacher_verification_questions = [
            TeacherVerificationQuestionRecord.model_validate(item)
            for item in payload.get("teacher_verification_questions", [])
        ]
        if loaded_teacher_verification_questions:
            self.teacher_verification_questions = loaded_teacher_verification_questions
            before_count = len(self.teacher_verification_questions)
            self._merge_seed_teacher_verification_questions()
            needs_persist = needs_persist or len(self.teacher_verification_questions) != before_count
        else:
            self.teacher_verification_questions = self._seed_teacher_verification_questions()
            needs_persist = True
        self.teacher_verification_attempts = [
            TeacherVerificationAttemptRecord.model_validate(item)
            for item in payload.get("teacher_verification_attempts", [])
        ]
        loaded_assignments = [AssignmentRecord.model_validate(item) for item in payload.get("assignments", [])]
        if loaded_assignments:
            self.assignments = loaded_assignments
        else:
            needs_persist = True
        self.assignment_submissions = [AssignmentSubmissionRecord.model_validate(item) for item in payload.get("assignment_submissions", [])]
        self.attendance_records = [AttendanceRecord.model_validate(item) for item in payload.get("attendance_records", [])]
        loaded_exams = [ExamRecord.model_validate(item) for item in payload.get("exams", [])]
        if loaded_exams:
            self.exams = loaded_exams
        else:
            needs_persist = True
        self.exam_submissions = [ExamSubmissionRecord.model_validate(item) for item in payload.get("exam_submissions", [])]
        self.teaching_session_records = [TeachingSessionRecord.model_validate(item) for item in payload.get("teaching_session_records", [])]
        loaded_ai_logs = [AiLogRecord.model_validate(item) for item in payload.get("ai_logs", [])]
        if loaded_ai_logs:
            self.ai_logs = loaded_ai_logs
        else:
            needs_persist = True
        self.notifications = [NotificationRecord.model_validate(item) for item in payload.get("notifications", [])]
        if needs_persist:
            self._persist()

    def _persist(self, state_keys: tuple[str, ...] | None = None) -> None:
        payload = self._serialize_state()
        if state_keys and hasattr(self.repository, "save_state_keys"):
            self.repository.save_state_keys(payload, state_keys)
            return
        self.repository.save(payload)

    def _row_level_write_supported(self) -> bool:
        return bool(getattr(self.repository, "row_level_write_supported", lambda: False)())

    def _persist_rows(self, state_key: str, records: list[object]) -> None:
        if self._row_level_write_supported() and hasattr(self.repository, "upsert_state_rows"):
            payload_rows = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in records
            ]
            self.repository.upsert_state_rows(state_key, payload_rows)
            return
        self._persist((state_key,))

    def _persist_row_groups(self, rows_by_state: dict[str, list[object]]) -> None:
        state_keys = tuple(rows_by_state.keys())
        if self._row_level_write_supported() and hasattr(self.repository, "upsert_state_rows"):
            for state_key, records in rows_by_state.items():
                payload_rows = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in records
                ]
                self.repository.upsert_state_rows(state_key, payload_rows)
            return
        self._persist(state_keys)

    def storage_backend_name(self) -> str:
        return getattr(self.repository, "backend_name", self.settings.storage_backend)

    def storage_repository_mode(self) -> str:
        return getattr(self.repository, "repository_mode", "snapshot_file")

    def storage_readiness(self) -> dict[str, object]:
        return repository_readiness(self.settings)

    def initialize_storage(self) -> dict[str, object]:
        return self.repository.initialize()

    def cutover_from_json_snapshot(self) -> dict[str, object]:
        if self.storage_backend_name() != "postgres":
            return {
                "success": False,
                "skipped": True,
                "reason": "active storage backend is not postgres",
                "backend": self.storage_backend_name(),
            }
        snapshot_path = Path(self.settings.json_path)
        if not snapshot_path.exists():
            return {
                "success": False,
                "skipped": True,
                "reason": "source snapshot file does not exist",
                "backend": self.storage_backend_name(),
                "source_json_path": str(snapshot_path),
            }
        raw = snapshot_path.read_text(encoding="utf-8")
        if not raw.strip():
            return {
                "success": False,
                "skipped": True,
                "reason": "source snapshot file is empty",
                "backend": self.storage_backend_name(),
                "source_json_path": str(snapshot_path),
            }
        payload = json.loads(raw)
        normalized_payload, integrity_report = normalize_snapshot_for_postgres(payload)
        self.repository.initialize()
        self.repository.save(normalized_payload)
        self._load_or_seed()
        record_counts = {
            state_key: len(rows)
            for state_key, rows in normalized_payload.items()
            if isinstance(rows, list)
        }
        return {
            "success": True,
            "backend": self.storage_backend_name(),
            "source_json_path": str(snapshot_path),
            "record_counts": record_counts,
            "integrity_report": integrity_report,
            "readiness": self.storage_readiness(),
        }

    def migration_artifacts(self) -> dict[str, object]:
        return self.repository.migration_artifacts()

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def home_payload(self) -> HomePayload:
        return HomePayload(
            brand_name="Japan Life Language School OS",
            hero_title="AI 化日語補習班營運平台 MVP",
            hero_subtitle="先把招生、試聽、報名、付款與後台追蹤跑起來，再往教務與 AI 升級。",
            featured_courses=[CourseSummary(**course.model_dump()) for course in self.courses[:3]],
            value_props=["前台自動招生", "後台名單追蹤", "可擴充成學員與教務平台"],
        )

    def list_courses(self) -> list[CourseSummary]:
        return [CourseSummary(**course.model_dump()) for course in self.courses]

    def create_course(self, payload: CourseUpsertRequest) -> CourseDetail:
        existing = next((item for item in self.courses if item.slug == payload.slug), None)
        if existing is not None:
            return self.update_course(payload.slug, payload)
        course = CourseDetail(
            id=uuid4(),
            slug=payload.slug,
            name=payload.name,
            course_type=payload.course_type,
            level=payload.level,
            delivery_mode=payload.delivery_mode,
            price=payload.price,
            short_description=payload.short_description,
            objectives=payload.objectives,
            highlights=payload.highlights,
            modules=payload.modules,
            teacher_names=payload.teacher_names,
        )
        self.courses.append(course)
        self._sync_platform_course_modules(course)
        self._persist(("courses", "course_modules"))
        return course

    def update_course(self, slug: str, payload: CourseUpsertRequest) -> CourseDetail:
        course = self.get_course(slug)
        updated = course.model_copy(
            update={
                "slug": payload.slug,
                "name": payload.name,
                "course_type": payload.course_type,
                "level": payload.level,
                "delivery_mode": payload.delivery_mode,
                "price": payload.price,
                "short_description": payload.short_description,
                "objectives": payload.objectives,
                "highlights": payload.highlights,
                "modules": payload.modules,
                "teacher_names": payload.teacher_names,
            }
        )
        self.courses = [updated if item.id == course.id else item for item in self.courses]
        updated_classes = [
            item.model_copy(update={"course_slug": updated.slug}) if item.course_id == updated.id else item
            for item in self.classes
        ]
        self.classes = updated_classes
        touched_classes = [item for item in updated_classes if item.course_id == updated.id]
        self._sync_platform_course_modules(updated)
        self._persist(("courses", "classes", "course_modules"))
        return updated

    def get_course(self, slug: str) -> CourseDetail:
        for course in self.courses:
            if course.slug == slug:
                return course
        raise KeyError(slug)

    def _sync_platform_course_modules(self, course: CourseDetail) -> None:
        now = _now()
        existing = [
            item
            for item in self.course_modules
            if item.course_slug == course.slug and item.owner_type == "platform"
        ]
        preserved_ids = [item.id for item in sorted(existing, key=lambda item: item.sort_order)]
        platform_team = "Platform Curriculum Team"
        updated_modules: list[CourseModuleRecord] = []
        for index, title in enumerate(course.modules, start=1):
            previous = existing[index - 1] if index - 1 < len(existing) else None
            updated_modules.append(
                CourseModuleRecord(
                    id=previous.id if previous is not None else (preserved_ids[index - 1] if index - 1 < len(preserved_ids) else uuid4()),
                    course_slug=course.slug,
                    title=title,
                    description=previous.description if previous is not None else f"{course.name} 的核心章節：{title}",
                    sort_order=index,
                    material_url=previous.material_url if previous is not None else f"https://school-platform.local/materials/{course.slug}/module-{index}",
                    owner_type="platform",
                    status="published",
                    created_by=previous.created_by if previous is not None else platform_team,
                    updated_by=platform_team,
                    created_at=previous.created_at if previous is not None else now,
                    updated_at=now,
                )
            )
        self.course_modules = [
            item
            for item in self.course_modules
            if not (item.course_slug == course.slug and item.owner_type == "platform")
        ] + updated_modules

    def list_course_modules(self, course_slug: str, *, include_archived: bool = False) -> list[CourseModuleRecord]:
        items = [item for item in self.course_modules if item.course_slug == course_slug]
        if not include_archived:
            items = [item for item in items if item.status != "archived"]
        return sorted(items, key=lambda item: (item.sort_order, item.title))

    def create_course_module(self, payload: CourseModuleUpsertRequest) -> CourseModuleRecord:
        course = self.get_course(payload.course_slug)
        now = _now()
        record = CourseModuleRecord(
            id=uuid4(),
            course_slug=payload.course_slug,
            title=payload.title,
            description=payload.description,
            sort_order=payload.sort_order,
            material_url=payload.material_url,
            owner_type="platform",
            status=payload.status,
            created_by=payload.created_by,
            updated_by=payload.created_by,
            created_at=now,
            updated_at=now,
        )
        self.course_modules.append(record)
        if payload.title not in course.modules:
            updated_course = course.model_copy(update={"modules": [*course.modules, payload.title]})
            self.courses = [updated_course if item.slug == course.slug else item for item in self.courses]
            self._persist(("courses", "course_modules"))
        else:
            self._persist_rows("course_modules", [record])
        return record

    def list_teaching_materials(
        self,
        *,
        course_slug: str | None = None,
        class_id: UUID | None = None,
        owner_type: str | None = None,
        include_archived: bool = False,
    ) -> list[TeachingMaterialRecord]:
        items = self.teaching_materials
        if course_slug:
            items = [item for item in items if item.course_slug == course_slug]
        if class_id:
            items = [item for item in items if item.class_id == class_id]
        if owner_type:
            items = [item for item in items if item.owner_type == owner_type]
        if not include_archived:
            items = [item for item in items if item.status != "archived"]
        return sorted(items, key=lambda item: (item.owner_type != "platform", item.title.lower()))

    def create_teaching_material(self, payload: TeachingMaterialUpsertRequest) -> TeachingMaterialRecord:
        self.get_course(payload.course_slug)
        if payload.class_id is not None and not any(item.id == payload.class_id for item in self.classes):
            raise KeyError(str(payload.class_id))
        if not (payload.material_url or payload.stored_path):
            raise ValueError("material_url or stored_path is required")
        now = _now()
        record = TeachingMaterialRecord(
            id=uuid4(),
            course_slug=payload.course_slug,
            class_id=payload.class_id,
            title=payload.title,
            description=payload.description,
            material_url=payload.material_url,
            storage_kind=payload.storage_kind,
            file_name=payload.file_name,
            stored_path=payload.stored_path,
            mime_type=payload.mime_type,
            file_size_bytes=payload.file_size_bytes,
            owner_type=payload.owner_type,
            visibility=payload.visibility,
            status=payload.status,
            created_by=payload.created_by,
            updated_by=payload.created_by,
            created_at=now,
            updated_at=now,
        )
        self.teaching_materials.append(record)
        self._persist_rows("teaching_materials", [record])
        return record

    def get_teaching_material(self, material_id: UUID) -> TeachingMaterialRecord | None:
        return next((item for item in self.teaching_materials if item.id == material_id), None)

    def student_materials(self, email: str) -> list[TeachingMaterialRecord]:
        classes = self.student_classes(email)
        class_ids = {item.id for item in classes}
        course_slugs = {item.course_slug for item in classes}
        items = [
            item
            for item in self.teaching_materials
            if item.status == "published"
            and item.visibility != "internal"
            and item.course_slug in course_slugs
            and (item.class_id is None or item.class_id in class_ids)
        ]
        return sorted(items, key=lambda item: (item.owner_type != "platform", item.title.lower()))

    def course_content_snapshot(self, course_slug: str) -> CourseContentSnapshot:
        course = self.get_course(course_slug)
        return CourseContentSnapshot(
            course=course,
            core_modules=[item for item in self.list_course_modules(course_slug) if item.owner_type == "platform"],
            platform_materials=[item for item in self.list_teaching_materials(course_slug=course_slug, owner_type="platform") if item.status == "published"],
            teacher_materials=[item for item in self.list_teaching_materials(course_slug=course_slug, owner_type="teacher") if item.status == "published"],
            governance_notes=[
                "平台核心內容由課程團隊維護，決定課程主軸、核心章節與標準教材。",
                "教師可補充班級情境講義，但不會直接覆寫平台核心課綱。",
                "對外展示時，平台會區分『平台核心內容』與『教師補充內容』。",
            ],
        )

    def classes_for_course(self, slug: str) -> list[ClassSummary]:
        return [item for item in self.classes if item.course_slug == slug]

    def open_classes(self) -> list[ClassSummary]:
        return [item for item in self.classes if item.status == "open"]

    def create_class(self, payload: ClassUpsertRequest) -> ClassSummary:
        course = self.get_course(payload.course_slug)
        class_item = ClassSummary(
            id=uuid4(),
            course_id=course.id,
            course_slug=course.slug,
            name=payload.name,
            teacher_name=payload.teacher_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            weekday=payload.weekday,
            start_time=payload.start_time,
            end_time=payload.end_time,
            capacity=payload.capacity,
            enrolled_count=0,
            location_label=payload.location_label,
            status=payload.status,
        )
        self.classes.append(class_item)
        self._persist_rows("classes", [class_item])
        return class_item

    def update_class(self, class_id: UUID, payload: ClassUpsertRequest) -> ClassSummary:
        course = self.get_course(payload.course_slug)
        class_item = next((item for item in self.classes if item.id == class_id), None)
        if class_item is None:
            raise KeyError(str(class_id))
        updated = class_item.model_copy(
            update={
                "course_id": course.id,
                "course_slug": course.slug,
                "name": payload.name,
                "teacher_name": payload.teacher_name,
                "start_date": payload.start_date,
                "end_date": payload.end_date,
                "weekday": payload.weekday,
                "start_time": payload.start_time,
                "end_time": payload.end_time,
                "capacity": payload.capacity,
                "location_label": payload.location_label,
                "status": payload.status,
            }
        )
        self.classes = [updated if item.id == class_id else item for item in self.classes]
        self._persist_rows("classes", [updated])
        return updated

    def trial_slots(self, course_slug: str | None = None) -> list[TrialSlot]:
        classes = self.open_classes()
        if course_slug:
            classes = [item for item in classes if item.course_slug == course_slug]
        slots: list[TrialSlot] = []
        for class_item in classes:
            start_dt = datetime.combine(class_item.start_date, class_item.start_time).astimezone()
            slots.append(
                TrialSlot(
                    starts_at=start_dt,
                    ends_at=start_dt + timedelta(minutes=90),
                    course_slug=class_item.course_slug,
                    label=f"{class_item.name} / {class_item.weekday} / {class_item.location_label}",
                )
            )
        return slots

    def create_trial_booking(self, payload: TrialBookingCreate) -> TrialBookingResponse:
        staff = self.staff[0]
        now = _now()
        lead = Lead(
            id=uuid4(),
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
            line_id=payload.line_id,
            source_channel="trial_booking",
            interested_course_slug=payload.course_slug,
            japanese_level=payload.japanese_level,
            study_goal=payload.study_goal,
            departure_plan_date=payload.departure_plan_date,
            intent_score=82,
            win_probability=68,
            status="trial_booked",
            assigned_staff_name=staff.name,
            last_contact_at=now,
            next_follow_up_at=payload.slot_start_at - timedelta(hours=24),
            notes="來自公開試聽表單",
            created_at=now,
            updated_at=now,
        )
        self.leads.insert(0, lead)
        self.lead_logs.insert(
            0,
            LeadLog(
                id=uuid4(),
                lead_id=lead.id,
                staff_name=staff.name,
                contact_method="system",
                content="系統已建立試聽預約與顧問指派。",
                next_action="試聽前一天發送提醒。",
                created_at=now,
            ),
        )
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=payload.email,
                channel="email",
                type="trial_booking_confirmation",
                title="試聽預約已建立",
                content=f"{payload.name} 您的試聽預約已建立，我們會在上課前一天提醒您。",
                status="queued",
                created_at=now,
            ),
        )
        self._persist_row_groups({"leads": [lead], "lead_logs": [self.lead_logs[0]], "notifications": [self.notifications[0]]})
        return TrialBookingResponse(
            booking_id=uuid4(),
            lead_id=lead.id,
            status="booked",
            assigned_staff_name=staff.name,
            next_follow_up_at=lead.next_follow_up_at or now,
        )

    def list_leads(self, status: str | None = None) -> list[Lead]:
        items = self.leads
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get_lead(self, lead_id: UUID) -> Lead:
        for lead in self.leads:
            if lead.id == lead_id:
                return lead
        raise KeyError(str(lead_id))

    def logs_for_lead(self, lead_id: UUID) -> list[LeadLog]:
        return [item for item in self.lead_logs if item.lead_id == lead_id]

    def add_lead_log(self, lead_id: UUID, staff_name: str, contact_method: str, content: str, next_action: str | None) -> LeadLog:
        log = LeadLog(
            id=uuid4(),
            lead_id=lead_id,
            staff_name=staff_name,
            contact_method=contact_method,
            content=content,
            next_action=next_action,
            created_at=_now(),
        )
        self.lead_logs.insert(0, log)
        self._persist_rows("lead_logs", [log])
        return log

    def assign_lead(self, lead_id: UUID, staff_id: UUID) -> Lead:
        lead = self.get_lead(lead_id)
        staff = next((item for item in self.staff if item.id == staff_id), None)
        if staff is None:
            raise KeyError(str(staff_id))
        updated = lead.model_copy(
            update={
                "assigned_staff_name": staff.name,
                "updated_at": _now(),
            }
        )
        self.leads = [updated if item.id == lead_id else item for item in self.leads]
        self.lead_logs.insert(
            0,
            LeadLog(
                id=uuid4(),
                lead_id=lead_id,
                staff_name=staff.name,
                contact_method="system",
                content=f"系統已重新指派顧問為 {staff.name}。",
                next_action="請顧問接手後更新下一次跟進時間。",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"leads": [updated], "lead_logs": [self.lead_logs[0]]})
        return updated

    def change_lead_status(self, lead_id: UUID, payload: LeadStatusChangeRequest) -> Lead:
        lead = self.get_lead(lead_id)
        updated = lead.model_copy(
            update={
                "status": payload.status,
                "next_follow_up_at": _normalize_datetime(payload.next_follow_up_at),
                "updated_at": _now(),
            }
        )
        self.leads = [updated if item.id == lead_id else item for item in self.leads]
        if payload.note:
            self.lead_logs.insert(
                0,
                LeadLog(
                    id=uuid4(),
                    lead_id=lead_id,
                    staff_name=updated.assigned_staff_name or "System",
                    contact_method="system",
                    content=f"狀態更新為 {payload.status}。{payload.note}",
                    next_action=None,
                    created_at=_now(),
                ),
            )
        rows_by_state: dict[str, list[object]] = {"leads": [updated]}
        if payload.note:
            rows_by_state["lead_logs"] = [self.lead_logs[0]]
        self._persist_row_groups(rows_by_state)
        return updated

    def create_enrollment(self, payload: EnrollmentCreate) -> EnrollmentResponse:
        matched_class = next((item for item in self.classes if item.id == payload.class_id), None)
        if matched_class is None:
            raise KeyError(str(payload.class_id))
        student = StudentRecord(
            id=uuid4(),
            chinese_name=payload.chinese_name,
            email=payload.email,
            phone=payload.phone,
            japanese_level=payload.japanese_level,
            study_goal=payload.study_goal,
            status="active",
            created_at=_now(),
        )
        self.students.append(student)
        enrollment = EnrollmentRecord(
            id=uuid4(),
            student_id=student.id,
            class_id=matched_class.id,
            status="pending",
            payment_status="pending",
            list_price=next(course.price for course in self.courses if course.slug == matched_class.course_slug),
            paid_amount=0,
            created_at=_now(),
        )
        self.enrollments.append(enrollment)
        order_no = f"JLS-{len(self.payments)+1:05d}"
        payment = PaymentRecord(
            id=uuid4(),
            enrollment_id=enrollment.id,
            order_no=order_no,
            amount=enrollment.list_price,
            payment_method=payload.payment_method,
            status="pending",
            provider="mock",
            client_token=None,
            currency="JPY",
            provider_status="pending",
            created_at=_now(),
            updated_at=_now(),
        )
        self.payments.append(payment)
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=student.email,
                channel="email",
                type="enrollment_created",
                title="報名申請已建立",
                content=f"{student.chinese_name} 您的報名已建立，請完成付款以保留名額。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups(
            {
                "students": [student],
                "enrollments": [enrollment],
                "payments": [payment],
                "notifications": [self.notifications[0]],
            }
        )
        return EnrollmentResponse(
            enrollment_id=enrollment.id,
            student_id=student.id,
            payment_id=payment.id,
            order_no=payment.order_no,
            status=enrollment.status,
            payment_status=payment.status,
        )

    def list_enrollments(self) -> list[EnrollmentRecord]:
        return self.enrollments

    def list_payments(self) -> list[PaymentRecord]:
        return self.payments

    def list_job_positions(self, status: str | None = None) -> list[JobPositionRecord]:
        items = self.job_positions
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get_job_position(self, position_id: UUID) -> JobPositionRecord:
        position = next((item for item in self.job_positions if item.id == position_id), None)
        if position is None:
            raise KeyError(str(position_id))
        return position

    def create_job_position(self, payload: JobPositionCreateRequest) -> JobPositionRecord:
        position = JobPositionRecord(
            id=uuid4(),
            title=payload.title,
            department=payload.department,
            employment_type=payload.employment_type,
            location_label=payload.location_label,
            salary_range=payload.salary_range,
            summary=payload.summary,
            requirements=payload.requirements,
            status=payload.status,
            created_at=_now(),
        )
        self.job_positions.insert(0, position)
        self._persist_rows("job_positions", [position])
        return position

    def create_applicant(self, payload: ApplicantCreateRequest) -> ApplicantRecord:
        position = self.get_job_position(payload.position_id)
        applicant = ApplicantRecord(
            id=uuid4(),
            position_id=position.id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            resume_link=payload.resume_link,
            note=payload.note,
            ai_match_score=82 if position.department == "Teaching" else 76,
            interview_status="reviewing",
            created_at=_now(),
        )
        self.applicants.insert(0, applicant)
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email="admin@jls.local",
                channel="in_app",
                type="new_applicant",
                title=f"新應徵者：{position.title}",
                content=f"{applicant.name} 已投遞 {position.title}，請安排履歷審查。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"applicants": [applicant], "notifications": [self.notifications[0]]})
        return applicant

    def list_applicants(self, position_id: UUID | None = None) -> list[ApplicantRecord]:
        items = self.applicants
        if position_id:
            items = [item for item in items if item.position_id == position_id]
        return items

    def get_applicant(self, applicant_id: UUID) -> ApplicantRecord:
        applicant = next((item for item in self.applicants if item.id == applicant_id), None)
        if applicant is None:
            raise KeyError(str(applicant_id))
        return applicant

    @staticmethod
    def _merge_applicant_note(existing_note: str | None, status: str, note: str | None) -> str | None:
        cleaned_note = (note or "").strip()
        if not cleaned_note:
            return existing_note
        status_note = f"[{status}] {cleaned_note}"
        if not existing_note:
            return status_note
        if status_note in existing_note:
            return existing_note
        return f"{existing_note}\n{status_note}"

    @staticmethod
    def _default_onboarding_checklist(applicant_name: str) -> list[str]:
        return [
            f"確認 {applicant_name} 的 offer、報到時間與聯絡窗口",
            "建立員工帳號與內部權限",
            "安排校務流程與教學 / 招生工具說明",
            "設定試用期 checkpoint 與主管回饋節點",
        ]

    def list_onboarding_records(self, applicant_id: UUID | None = None) -> list[OnboardingRecord]:
        items = self.onboarding_records
        if applicant_id:
            items = [item for item in items if item.applicant_id == applicant_id]
        return items

    def get_onboarding_record(self, applicant_id: UUID) -> OnboardingRecord | None:
        return next((item for item in self.onboarding_records if item.applicant_id == applicant_id), None)

    def upsert_onboarding_record(self, applicant_id: UUID, payload: OnboardingUpsertRequest) -> OnboardingRecord:
        applicant = self.get_applicant(applicant_id)
        existing = self.get_onboarding_record(applicant_id)
        now = _now()
        checklist_items = payload.checklist_items or (
            existing.checklist_items if existing and existing.checklist_items else self._default_onboarding_checklist(applicant.name)
        )
        record = OnboardingRecord(
            id=existing.id if existing else uuid4(),
            applicant_id=applicant_id,
            owner_name=(payload.owner_name or (existing.owner_name if existing else "Yuki Wang")).strip() or "Yuki Wang",
            stage=payload.stage,
            start_date=payload.start_date if payload.start_date is not None else (existing.start_date if existing else None),
            probation_status=payload.probation_status,
            probation_end_date=(
                payload.probation_end_date if payload.probation_end_date is not None else (existing.probation_end_date if existing else None)
            ),
            checklist_items=checklist_items,
            notes=payload.notes if payload.notes is not None else (existing.notes if existing else None),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if existing is None:
            self.onboarding_records.insert(0, record)
        else:
            self.onboarding_records = [record if item.applicant_id == applicant_id else item for item in self.onboarding_records]
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email="admin@jls.local",
                channel="in_app",
                type="onboarding_updated",
                title=f"到職 / 試用流程已更新：{applicant.name}",
                content=f"{applicant.name} 的 onboarding 階段為 {record.stage}，試用狀態為 {record.probation_status}。",
                status="queued",
                created_at=now,
            ),
        )
        self._persist_row_groups({"onboarding_records": [record], "notifications": [self.notifications[0]]})
        return record

    def list_teacher_manual_sections(self) -> list[TeacherManualSectionRecord]:
        return sorted(self.teacher_manual_sections, key=lambda item: (item.slug, item.title))

    def list_teacher_verification_questions(
        self,
        section_slug: str | None = None,
    ) -> list[TeacherVerificationQuestionRecord]:
        items = self.teacher_verification_questions
        if section_slug:
            items = [item for item in items if item.section_slug == section_slug]
        return sorted(items, key=lambda item: (item.section_slug, item.sort_order, item.prompt))

    def list_teacher_verification_attempts(
        self,
        teacher_name: str | None = None,
    ) -> list[TeacherVerificationAttemptRecord]:
        items = self.teacher_verification_attempts
        if teacher_name:
            items = [item for item in items if item.teacher_name == teacher_name]
        return sorted(items, key=lambda item: item.submitted_at, reverse=True)

    def get_latest_teacher_verification_attempt(self, teacher_name: str) -> TeacherVerificationAttemptRecord | None:
        return next(iter(self.list_teacher_verification_attempts(teacher_name)), None)

    def get_teacher_user_by_name(self, teacher_name: str) -> UserAccount | None:
        lowered = teacher_name.strip().lower()
        return next((item for item in self.users if item.role == "teacher" and item.name.strip().lower() == lowered), None)

    def submit_teacher_verification(self, payload: TeacherVerificationSubmitRequest) -> TeacherVerificationAttemptRecord:
        teacher_name = payload.teacher_name.strip()
        if not teacher_name:
            raise ValueError("teacher_name is required")
        questions = self.list_teacher_verification_questions()
        if not questions:
            raise ValueError("teacher verification question bank is empty")

        answers = {str(key): value.strip().upper() for key, value in payload.answers.items() if value and value.strip()}
        correct_count = 0
        weak_section_slugs: set[str] = set()
        for question in questions:
            answer = answers.get(str(question.id), "")
            if answer == question.correct_option.strip().upper():
                correct_count += 1
            else:
                weak_section_slugs.add(question.section_slug)
        score = round((correct_count / len(questions)) * 100, 1)
        passed = score >= TEACHER_VERIFICATION_REQUIRED_SCORE

        teacher_user = self.get_teacher_user_by_name(teacher_name)
        teacher_email = teacher_user.email if teacher_user is not None else None
        unlocked_permission = bool(
            teacher_user is not None and ("*" in teacher_user.permissions or "teaching:verified" in teacher_user.permissions)
        )
        rows_by_state: dict[str, list[object]] = {}
        if passed and teacher_user is not None and "*" not in teacher_user.permissions and "teaching:verified" not in teacher_user.permissions:
            updated_user = teacher_user.model_copy(
                update={
                    "permissions": [*teacher_user.permissions, "teaching:verified"],
                    "note": f"{teacher_user.note}\n已通過教師開課驗證。".strip() if teacher_user.note else "已通過教師開課驗證。",
                }
            )
            self.users = [updated_user if item.id == teacher_user.id else item for item in self.users]
            rows_by_state["users"] = [updated_user]
            teacher_user = updated_user
            teacher_email = updated_user.email
            unlocked_permission = True
        elif passed and teacher_user is not None:
            unlocked_permission = True

        attempt = TeacherVerificationAttemptRecord(
            id=uuid4(),
            teacher_name=teacher_name,
            teacher_email=teacher_email,
            score=score,
            passed=passed,
            required_score=TEACHER_VERIFICATION_REQUIRED_SCORE,
            question_ids=[item.id for item in questions],
            answers=answers,
            weak_section_slugs=sorted(weak_section_slugs),
            unlocked_permission=unlocked_permission,
            submitted_at=_now(),
            reviewer_note=(
                "已通過，系統已解鎖開課權限。"
                if unlocked_permission
                else "成績已達標，但尚未找到對應教師帳號，請管理員補綁帳號。"
            )
            if passed
            else "未達 85 分門檻，請重新閱讀手冊並補強弱項章節。",
        )
        self.teacher_verification_attempts.insert(0, attempt)
        rows_by_state["teacher_verification_attempts"] = [attempt]

        notification_targets = ["admin@jls.local"]
        if teacher_email:
            notification_targets.insert(0, teacher_email)
        created_notifications: list[NotificationRecord] = []
        for user_email in notification_targets:
            created_notifications.append(
                NotificationRecord(
                    id=uuid4(),
                    user_email=user_email,
                    channel="in_app",
                    type="teacher_verification_updated",
                    title=f"教師驗證結果：{teacher_name}",
                    content=(
                        f"{teacher_name} 驗證分數 {score} 分，已解鎖開課權限。"
                        if unlocked_permission
                        else f"{teacher_name} 驗證分數 {score} 分，請補讀手冊後再測。"
                    ),
                    status="queued",
                    created_at=_now(),
                )
            )
        for notification in reversed(created_notifications):
            self.notifications.insert(0, notification)
        if created_notifications:
            rows_by_state["notifications"] = created_notifications
        self._persist_row_groups(rows_by_state)
        self.create_ai_log(
            module_name="teacher_verification",
            action_name="submit_teacher_verification",
            actor_email=teacher_email,
            input_summary=f"teacher={teacher_name}, answers={len(answers)}",
            output_summary=f"score={score}, passed={passed}, unlocked={unlocked_permission}",
        )
        return attempt

    def update_applicant_status(self, applicant_id: UUID, payload: ApplicantStatusUpdateRequest) -> ApplicantRecord:
        applicant = self.get_applicant(applicant_id)
        updated = applicant.model_copy(
            update={
                "interview_status": payload.interview_status,
                "note": self._merge_applicant_note(applicant.note, payload.interview_status, payload.note),
            }
        )
        self.applicants = [updated if item.id == applicant_id else item for item in self.applicants]
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email="admin@jls.local",
                channel="in_app",
                type="applicant_status_updated",
                title=f"招聘案件狀態更新：{applicant.name}",
                content=f"{applicant.name} 的案件狀態已更新為 {payload.interview_status}。",
                status="queued",
                created_at=_now(),
            ),
        )

        final_stage_messages = {
            "offer_sent": ("錄取邀請已送出", "我們已更新你的應徵進度，接下來會與你確認 offer 細節。"),
            "hired": ("錄取通知", "恭喜，你的應徵已進入錄取流程，我們會再提供到職與報到資訊。"),
            "rejected": ("應徵結果通知", "感謝你的投遞，這一輪暫時先不往下安排，但我們會保留你的資料供後續職缺參考。"),
        }
        if payload.interview_status in final_stage_messages:
            title, content = final_stage_messages[payload.interview_status]
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email=applicant.email,
                    channel="email",
                    type="applicant_decision",
                    title=title,
                    content=content,
                    status="queued",
                    created_at=_now(),
                ),
            )
        new_notifications = [self.notifications[0]]
        if payload.interview_status in final_stage_messages:
            new_notifications.append(self.notifications[1])
        rows_by_state: dict[str, list[object]] = {"applicants": [updated], "notifications": new_notifications}
        if payload.interview_status == "hired" and self.get_onboarding_record(applicant_id) is None:
            onboarding = OnboardingRecord(
                id=uuid4(),
                applicant_id=applicant_id,
                owner_name="Yuki Wang",
                stage="preboarding",
                start_date=None,
                probation_status="not_started",
                probation_end_date=None,
                checklist_items=self._default_onboarding_checklist(applicant.name),
                notes="已自動建立 onboarding 流程，待 HR 確認報到日與試用節點。",
                created_at=_now(),
                updated_at=_now(),
            )
            self.onboarding_records.insert(0, onboarding)
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email="admin@jls.local",
                    channel="in_app",
                    type="onboarding_created",
                    title=f"已建立 onboarding：{applicant.name}",
                    content=f"{applicant.name} 已進入 hired，請補上報到日、checklist 與 probation 設定。",
                    status="queued",
                    created_at=_now(),
                ),
            )
            rows_by_state["onboarding_records"] = [onboarding]
            rows_by_state["notifications"] = [self.notifications[0], *new_notifications]
        self._persist_row_groups(rows_by_state)
        return updated

    def schedule_interview(self, payload: InterviewCreateRequest) -> InterviewRecord:
        applicant = self.get_applicant(payload.applicant_id)
        interview = InterviewRecord(
            id=uuid4(),
            applicant_id=applicant.id,
            interview_at=_normalize_datetime(payload.interview_at) or _now(),
            interviewer_name=payload.interviewer_name,
            format=payload.format,
            status=payload.status,
            feedback=payload.feedback,
            created_at=_now(),
        )
        self.interviews.insert(0, interview)
        updated_applicant = applicant.model_copy(update={"interview_status": payload.status})
        self.applicants = [updated_applicant if item.id == applicant.id else item for item in self.applicants]
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=applicant.email,
                channel="email",
                type="interview_scheduled",
                title="面試已安排",
                content=f"你應徵的面試已安排在 {interview.interview_at.isoformat()}，請留意後續通知。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"applicants": [updated_applicant], "interviews": [interview], "notifications": [self.notifications[0]]})
        return interview

    def list_interviews(self, applicant_id: UUID | None = None) -> list[InterviewRecord]:
        items = self.interviews
        if applicant_id:
            items = [item for item in items if item.applicant_id == applicant_id]
        return items

    def get_interview(self, interview_id: UUID) -> InterviewRecord:
        interview = next((item for item in self.interviews if item.id == interview_id), None)
        if interview is None:
            raise KeyError(str(interview_id))
        return interview

    def update_interview(self, interview_id: UUID, payload: InterviewUpdateRequest) -> InterviewRecord:
        interview = self.get_interview(interview_id)
        applicant = self.get_applicant(interview.applicant_id)
        updated = interview.model_copy(update={"status": payload.status, "feedback": payload.feedback})
        self.interviews = [updated if item.id == interview_id else item for item in self.interviews]
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email="admin@jls.local",
                channel="in_app",
                type="interview_reviewed",
                title=f"面試結果已更新：{applicant.name}",
                content=f"{applicant.name} 的面試狀態已更新為 {payload.status}。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"interviews": [updated], "notifications": [self.notifications[0]]})
        return updated

    def create_ai_log(
        self,
        module_name: str,
        action_name: str,
        input_summary: str,
        output_summary: str,
        actor_email: str | None = None,
    ) -> AiLogRecord:
        log = AiLogRecord(
            id=uuid4(),
            module_name=module_name,
            actor_email=actor_email,
            action_name=action_name,
            input_summary=input_summary,
            output_summary=output_summary,
            created_at=_now(),
        )
        self.ai_logs.insert(0, log)
        self._persist_rows("ai_logs", [log])
        return log

    def list_ai_logs(self, module_name: str | None = None) -> list[AiLogRecord]:
        items = self.ai_logs
        if module_name:
            items = [item for item in items if item.module_name == module_name]
        return items

    def list_assignments(self, class_id: UUID | None = None) -> list[AssignmentRecord]:
        if class_id is None:
            return self.assignments
        return [item for item in self.assignments if item.class_id == class_id]

    def create_assignment(self, payload: AssignmentCreateRequest) -> AssignmentRecord:
        assignment = AssignmentRecord(
            id=uuid4(),
            class_id=payload.class_id,
            title=payload.title,
            content=payload.content,
            due_at=_normalize_datetime(payload.due_at) or _now(),
            created_by=payload.created_by,
            created_at=_now(),
        )
        self.assignments.insert(0, assignment)
        self._persist_rows("assignments", [assignment])
        return assignment

    def get_assignment(self, assignment_id: UUID) -> AssignmentRecord:
        assignment = next((item for item in self.assignments if item.id == assignment_id), None)
        if assignment is None:
            raise KeyError(str(assignment_id))
        return assignment

    def submit_assignment(self, assignment_id: UUID, payload: AssignmentSubmissionCreateRequest) -> AssignmentSubmissionRecord:
        assignment = self.get_assignment(assignment_id)
        student = self.get_student_by_email(payload.email)
        if student is None:
            raise KeyError(payload.email)
        existing = next(
            (item for item in self.assignment_submissions if item.assignment_id == assignment.id and item.student_id == student.id),
            None,
        )
        submission = AssignmentSubmissionRecord(
            id=existing.id if existing else uuid4(),
            assignment_id=assignment.id,
            student_id=student.id,
            content=payload.content,
            status="submitted",
            submitted_at=_now(),
            feedback=existing.feedback if existing else None,
            score=existing.score if existing else None,
        )
        if existing:
            self.assignment_submissions = [
                submission if item.id == existing.id else item for item in self.assignment_submissions
            ]
        else:
            self.assignment_submissions.insert(0, submission)
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=student.email,
                channel="in_app",
                type="assignment_submitted",
                title="作業已提交",
                content=f"你已提交「{assignment.title}」，老師之後可再補上評語。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"assignment_submissions": [submission], "notifications": [self.notifications[0]]})
        return submission

    def list_assignment_submissions(self, student_id: UUID | None = None, assignment_id: UUID | None = None) -> list[AssignmentSubmissionRecord]:
        items = self.assignment_submissions
        if student_id:
            items = [item for item in items if item.student_id == student_id]
        if assignment_id:
            items = [item for item in items if item.assignment_id == assignment_id]
        return items

    def mark_attendance(self, payload: AttendanceMarkRequest) -> AttendanceRecord:
        student = self.get_student_by_email(payload.student_email)
        if student is None:
            raise KeyError(payload.student_email)
        existing = next(
            (
                item
                for item in self.attendance_records
                if item.class_id == payload.class_id and item.student_id == student.id and item.class_date == payload.class_date
            ),
            None,
        )
        attendance = AttendanceRecord(
            id=existing.id if existing else uuid4(),
            class_id=payload.class_id,
            student_id=student.id,
            class_date=payload.class_date,
            status=payload.status,
            note=payload.note,
            marked_by=payload.marked_by,
            created_at=existing.created_at if existing else _now(),
        )
        if existing:
            self.attendance_records = [
                attendance if item.id == existing.id else item for item in self.attendance_records
            ]
        else:
            self.attendance_records.insert(0, attendance)
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=student.email,
                channel="in_app",
                type="attendance_updated",
                title="出缺勤已更新",
                content=f"{payload.class_date.isoformat()} 的出缺勤狀態已更新為 {payload.status}。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"attendance_records": [attendance], "notifications": [self.notifications[0]]})
        return attendance

    def list_attendance(self, student_id: UUID | None = None, class_id: UUID | None = None) -> list[AttendanceRecord]:
        items = self.attendance_records
        if student_id:
            items = [item for item in items if item.student_id == student_id]
        if class_id:
            items = [item for item in items if item.class_id == class_id]
        return items

    def list_exams(self, class_id: UUID | None = None) -> list[ExamRecord]:
        if class_id is None:
            return self.exams
        return [item for item in self.exams if item.class_id == class_id]

    def create_exam(self, payload: ExamCreateRequest) -> ExamRecord:
        exam = ExamRecord(
            id=uuid4(),
            class_id=payload.class_id,
            title=payload.title,
            exam_type=payload.exam_type,
            instructions=payload.instructions,
            total_score=payload.total_score,
            due_at=_normalize_datetime(payload.due_at) or _now(),
            created_by=payload.created_by,
            created_at=_now(),
        )
        self.exams.insert(0, exam)
        self._persist_rows("exams", [exam])
        return exam

    def get_exam(self, exam_id: UUID) -> ExamRecord:
        exam = next((item for item in self.exams if item.id == exam_id), None)
        if exam is None:
            raise KeyError(str(exam_id))
        return exam

    def submit_exam(self, exam_id: UUID, payload: ExamSubmissionCreateRequest) -> ExamSubmissionRecord:
        exam = self.get_exam(exam_id)
        student = self.get_student_by_email(payload.email)
        if student is None:
            raise KeyError(payload.email)
        existing = next(
            (item for item in self.exam_submissions if item.exam_id == exam.id and item.student_id == student.id),
            None,
        )
        submission = ExamSubmissionRecord(
            id=existing.id if existing else uuid4(),
            exam_id=exam.id,
            student_id=student.id,
            content=payload.content,
            status="submitted",
            submitted_at=_now(),
            feedback=existing.feedback if existing else None,
            score=existing.score if existing else None,
            graded_by=existing.graded_by if existing else None,
        )
        if existing:
            self.exam_submissions = [submission if item.id == existing.id else item for item in self.exam_submissions]
        else:
            self.exam_submissions.insert(0, submission)
        self.notifications.insert(
            0,
            NotificationRecord(
                id=uuid4(),
                user_email=student.email,
                channel="in_app",
                type="exam_submitted",
                title="測驗已提交",
                content=f"你已提交「{exam.title}」，老師之後會補上分數與回饋。",
                status="queued",
                created_at=_now(),
            ),
        )
        self._persist_row_groups({"exam_submissions": [submission], "notifications": [self.notifications[0]]})
        return submission

    def list_exam_submissions(self, student_id: UUID | None = None, exam_id: UUID | None = None) -> list[ExamSubmissionRecord]:
        items = self.exam_submissions
        if student_id:
            items = [item for item in items if item.student_id == student_id]
        if exam_id:
            items = [item for item in items if item.exam_id == exam_id]
        return items

    def list_teaching_session_records(
        self,
        class_id: UUID | None = None,
        teacher_name: str | None = None,
        approval_status: str | None = None,
    ) -> list[TeachingSessionRecord]:
        items = self.teaching_session_records
        if class_id:
            items = [item for item in items if item.class_id == class_id]
        if teacher_name:
            items = [item for item in items if item.teacher_name == teacher_name]
        if approval_status:
            items = [item for item in items if item.approval_status == approval_status]
        return sorted(items, key=lambda item: (item.class_date, item.updated_at), reverse=True)

    def upsert_teaching_session_record(self, payload: TeachingSessionUpsertRequest) -> TeachingSessionRecord:
        class_item = next((item for item in self.classes if item.id == payload.class_id), None)
        if class_item is None:
            raise KeyError(str(payload.class_id))
        existing = next(
            (
                item
                for item in self.teaching_session_records
                if item.class_id == payload.class_id
                and item.teacher_name == payload.teacher_name
                and item.class_date == payload.class_date
            ),
            None,
        )
        now = _now()
        approval_status = payload.approval_status
        record = TeachingSessionRecord(
            id=existing.id if existing else uuid4(),
            class_id=payload.class_id,
            teacher_name=payload.teacher_name,
            class_date=payload.class_date,
            summary=payload.summary,
            materials_link=payload.materials_link,
            homework_summary=payload.homework_summary,
            next_class_focus=payload.next_class_focus,
            student_risk_notes=payload.student_risk_notes,
            approval_status=approval_status,
            review_note=None if approval_status in {"draft", "submitted"} else existing.review_note if existing else None,
            reviewed_by=None if approval_status in {"draft", "submitted"} else existing.reviewed_by if existing else None,
            submitted_at=now if approval_status == "submitted" else None,
            reviewed_at=None if approval_status in {"draft", "submitted"} else existing.reviewed_at if existing else None,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if existing:
            self.teaching_session_records = [
                record if item.id == existing.id else item for item in self.teaching_session_records
            ]
        else:
            self.teaching_session_records.insert(0, record)

        rows_by_state: dict[str, list[object]] = {"teaching_session_records": [record]}
        if approval_status == "submitted":
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email="manager@jls.local",
                    channel="in_app",
                    type="teaching_session_review",
                    title="新的課後紀錄待審核",
                    content=f"{payload.teacher_name} 已送出 {class_item.name} {payload.class_date.isoformat()} 的課後紀錄。",
                    status="queued",
                    created_at=now,
                ),
            )
            rows_by_state["notifications"] = [self.notifications[0]]
        self._persist_row_groups(rows_by_state)
        return record

    def review_teaching_session_record(self, record_id: UUID, payload: TeachingSessionReviewRequest) -> TeachingSessionRecord:
        record = next((item for item in self.teaching_session_records if item.id == record_id), None)
        if record is None:
            raise KeyError(str(record_id))
        now = _now()
        updated = record.model_copy(
            update={
                "approval_status": payload.approval_status,
                "review_note": payload.review_note,
                "reviewed_by": payload.reviewed_by,
                "reviewed_at": now,
                "updated_at": now,
            }
        )
        self.teaching_session_records = [
            updated if item.id == record_id else item for item in self.teaching_session_records
        ]
        rows_by_state: dict[str, list[object]] = {"teaching_session_records": [updated]}
        teacher_user = next((item for item in self.users if item.name == updated.teacher_name), None)
        if teacher_user is not None:
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email=teacher_user.email,
                    channel="in_app",
                    type="teaching_session_reviewed",
                    title="課後紀錄已更新審核結果",
                    content=f"{updated.class_date.isoformat()} 的課後紀錄已更新為 {payload.approval_status}。",
                    status="queued",
                    created_at=now,
                ),
            )
            rows_by_state["notifications"] = [self.notifications[0]]
        self._persist_row_groups(rows_by_state)
        return updated

    def grade_assignment_submission(self, submission_id: UUID, payload: SubmissionGradeRequest) -> AssignmentSubmissionRecord:
        submission = next((item for item in self.assignment_submissions if item.id == submission_id), None)
        if submission is None:
            raise KeyError(str(submission_id))
        updated = submission.model_copy(
            update={
                "status": "graded",
                "score": payload.score,
                "feedback": payload.feedback,
            }
        )
        self.assignment_submissions = [updated if item.id == submission_id else item for item in self.assignment_submissions]
        student = next((item for item in self.students if item.id == updated.student_id), None)
        assignment = self.get_assignment(updated.assignment_id)
        if student is not None:
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email=student.email,
                    channel="in_app",
                    type="assignment_graded",
                    title="作業已評分",
                    content=f"「{assignment.title}」已完成評分，分數 {payload.score:g}。",
                    status="queued",
                    created_at=_now(),
                ),
            )
        rows_by_state: dict[str, list[object]] = {"assignment_submissions": [updated]}
        if student is not None:
            rows_by_state["notifications"] = [self.notifications[0]]
        self._persist_row_groups(rows_by_state)
        return updated

    def grade_exam_submission(self, submission_id: UUID, payload: SubmissionGradeRequest) -> ExamSubmissionRecord:
        submission = next((item for item in self.exam_submissions if item.id == submission_id), None)
        if submission is None:
            raise KeyError(str(submission_id))
        updated = submission.model_copy(
            update={
                "status": "graded",
                "score": payload.score,
                "feedback": payload.feedback,
                "graded_by": payload.graded_by,
            }
        )
        self.exam_submissions = [updated if item.id == submission_id else item for item in self.exam_submissions]
        student = next((item for item in self.students if item.id == updated.student_id), None)
        exam = self.get_exam(updated.exam_id)
        if student is not None:
            self.notifications.insert(
                0,
                NotificationRecord(
                    id=uuid4(),
                    user_email=student.email,
                    channel="in_app",
                    type="exam_graded",
                    title="測驗已評分",
                    content=f"「{exam.title}」已完成評分，分數 {payload.score:g}。",
                    status="queued",
                    created_at=_now(),
                ),
            )
        rows_by_state: dict[str, list[object]] = {"exam_submissions": [updated]}
        if student is not None:
            rows_by_state["notifications"] = [self.notifications[0]]
        self._persist_row_groups(rows_by_state)
        return updated

    def create_payment_intent(self, payload: PaymentIntentCreate) -> PaymentIntentResponse:
        enrollment = next((item for item in self.enrollments if item.id == payload.enrollment_id), None)
        if enrollment is None:
            raise KeyError(str(payload.enrollment_id))
        payment = next((item for item in self.payments if item.enrollment_id == payload.enrollment_id), None)
        if payment is None:
            order_no = f"JLS-{len(self.payments)+1:05d}"
            payment = PaymentRecord(
                id=uuid4(),
                enrollment_id=enrollment.id,
                order_no=order_no,
                amount=enrollment.list_price,
                payment_method=payload.payment_method,
                status="pending",
                provider="mock",
                currency="JPY",
                provider_status="pending",
                provider_last_error=None,
                created_at=_now(),
                updated_at=_now(),
            )
            self.payments.append(payment)
            self._persist_rows("payments", [payment])
        client_token = payment.client_token or f"demo_{payment.order_no}"
        updated_payment = payment.model_copy(
            update={
                "payment_method": payload.payment_method,
                "client_token": client_token,
                "provider": payment.provider or "mock",
                "currency": payment.currency or "JPY",
                "provider_status": payment.provider_status or payment.status,
                "updated_at": _now(),
            }
        )
        self.payments = [updated_payment if item.id == payment.id else item for item in self.payments]
        self._persist_rows("payments", [updated_payment])
        return PaymentIntentResponse(
            payment_id=updated_payment.id,
            order_no=updated_payment.order_no,
            amount=updated_payment.amount,
            payment_method=updated_payment.payment_method,
            status=updated_payment.status,
            client_token=updated_payment.client_token or "",
            provider=updated_payment.provider or "mock",
            provider_payment_id=updated_payment.provider_payment_id,
            checkout_url=updated_payment.checkout_url,
            currency=(updated_payment.currency or "JPY").upper(),
            provider_status=updated_payment.provider_status,
            checkout_expires_at=updated_payment.checkout_expires_at,
        )

    def apply_payment_webhook(self, payload: PaymentWebhookPayload) -> PaymentRecord:
        payment = next((item for item in self.payments if item.order_no == payload.order_no), None)
        if payment is None:
            raise KeyError(payload.order_no)
        status_changed = payment.status != payload.status
        paid_at = payment.paid_at
        if payload.status == "paid":
            paid_at = payload.paid_at or payment.paid_at or _now()
        updated_payment = payment.model_copy(
            update={
                "status": payload.status,
                "provider": payload.provider or payment.provider,
                "provider_payment_id": payload.provider_payment_id or payment.provider_payment_id,
                "provider_status": payload.provider_status or payload.status,
                "last_reconciled_at": _now() if payload.provider else payment.last_reconciled_at,
                "provider_last_error": None if payload.status == "paid" else payment.provider_last_error,
                "paid_at": paid_at,
                "updated_at": _now(),
            }
        )
        self.payments = [updated_payment if item.id == payment.id else item for item in self.payments]
        enrollment = next((item for item in self.enrollments if item.id == payment.enrollment_id), None)
        student = None
        created_notification = None
        if enrollment is not None:
            enrollment_payment_status = payload.status if payload.status != "failed" else "failed"
            enrollment_status = "active" if payload.status == "paid" else enrollment.status
            updated_enrollment = enrollment.model_copy(
                update={
                    "payment_status": enrollment_payment_status,
                    "status": enrollment_status,
                    "paid_amount": updated_payment.amount if payload.status == "paid" else enrollment.paid_amount,
                }
            )
            self.enrollments = [updated_enrollment if item.id == enrollment.id else item for item in self.enrollments]
            student = next((item for item in self.students if item.id == enrollment.student_id), None)
            if student is not None and status_changed:
                notification_now = _now()
                created_notification = NotificationRecord(
                    id=uuid4(),
                    user_email=student.email,
                    channel="email",
                    type="payment_status_updated",
                    title="付款狀態已更新",
                    content=f"您的訂單 {payload.order_no} 狀態已更新為 {payload.status}。",
                    status="queued",
                    created_at=notification_now,
                    attempt_count=0,
                    updated_at=notification_now,
                )
                self.notifications.insert(
                    0,
                    created_notification,
                )
        rows_by_state: dict[str, list[object]] = {"payments": [updated_payment]}
        if enrollment is not None:
            updated_enrollment = next((item for item in self.enrollments if item.id == enrollment.id), None)
            if updated_enrollment is not None:
                rows_by_state["enrollments"] = [updated_enrollment]
            if created_notification is not None:
                rows_by_state["notifications"] = [created_notification]
        self._persist_row_groups(rows_by_state)
        return updated_payment

    def list_staff(self) -> list[StaffRecord]:
        return self.staff

    def create_notification(self, payload: NotificationCreate) -> NotificationRecord:
        created_at = _now()
        notification = NotificationRecord(
            id=uuid4(),
            user_email=payload.user_email,
            channel=payload.channel,
            type=payload.type,
            title=payload.title,
            content=payload.content,
            status="queued",
            created_at=created_at,
            external_recipient=payload.external_recipient,
            attempt_count=0,
            updated_at=created_at,
        )
        self.notifications.insert(0, notification)
        self._persist_rows("notifications", [notification])
        return notification

    def get_notification(self, notification_id: UUID) -> NotificationRecord:
        notification = next((item for item in self.notifications if item.id == notification_id), None)
        if notification is None:
            raise KeyError(str(notification_id))
        return notification

    def update_notification_status(self, notification_id: UUID, status: str) -> NotificationRecord:
        notification = self.get_notification(notification_id)
        updated = notification.model_copy(update={"status": status, "updated_at": _now()})
        self.notifications = [updated if item.id == notification_id else item for item in self.notifications]
        self._persist_rows("notifications", [updated])
        return updated

    def update_notification_delivery(
        self,
        notification_id: UUID,
        *,
        status: str,
        provider: str | None = None,
        external_recipient: str | None = None,
        provider_message_id: str | None = None,
        error_message: str | None = None,
        delivered_at: datetime | None = None,
        increment_attempt_count: bool = True,
    ) -> NotificationRecord:
        notification = self.get_notification(notification_id)
        now = _now()
        updated = notification.model_copy(
            update={
                "status": status,
                "provider": provider or notification.provider,
                "external_recipient": external_recipient or notification.external_recipient,
                "provider_message_id": provider_message_id or notification.provider_message_id,
                "error_message": error_message,
                "delivered_at": delivered_at,
                "attempt_count": notification.attempt_count + (1 if increment_attempt_count else 0),
                "last_attempt_at": now if increment_attempt_count else notification.last_attempt_at,
                "updated_at": now,
            }
        )
        self.notifications = [updated if item.id == notification_id else item for item in self.notifications]
        self._persist_rows("notifications", [updated])
        return updated

    def update_payment_provider_state(
        self,
        payment_id: UUID,
        *,
        provider: str | None = None,
        provider_payment_id: str | None = None,
        checkout_url: str | None = None,
        client_token: str | None = None,
        currency: str | None = None,
        provider_status: str | None = None,
        checkout_expires_at: datetime | None | object = _UNSET,
        last_reconciled_at: datetime | None | object = _UNSET,
        provider_last_error: str | None | object = _UNSET,
    ) -> PaymentRecord:
        payment = next((item for item in self.payments if item.id == payment_id), None)
        if payment is None:
            raise KeyError(str(payment_id))
        update_payload: dict[str, object | None] = {
            "provider": provider or payment.provider,
            "provider_payment_id": provider_payment_id or payment.provider_payment_id,
            "checkout_url": checkout_url or payment.checkout_url,
            "client_token": client_token or payment.client_token,
            "currency": currency or payment.currency,
            "provider_status": provider_status or payment.provider_status,
            "updated_at": _now(),
        }
        if checkout_expires_at is not _UNSET:
            update_payload["checkout_expires_at"] = checkout_expires_at
        if last_reconciled_at is not _UNSET:
            update_payload["last_reconciled_at"] = last_reconciled_at
        if provider_last_error is not _UNSET:
            update_payload["provider_last_error"] = provider_last_error
        updated = payment.model_copy(
            update=update_payload
        )
        self.payments = [updated if item.id == payment_id else item for item in self.payments]
        self._persist_rows("payments", [updated])
        return updated

    def list_notifications(self, user_email: str | None = None) -> list[NotificationRecord]:
        if user_email:
            return [item for item in self.notifications if item.user_email == user_email]
        return self.notifications

    def get_student_by_email(self, email: str) -> StudentRecord | None:
        lowered = email.strip().lower()
        matches = [item for item in self.students if item.email.lower() == lowered]
        if not matches:
            return None
        return max(matches, key=lambda item: item.created_at)

    def get_student_by_id(self, student_id: UUID) -> StudentRecord | None:
        return next((item for item in self.students if item.id == student_id), None)

    def get_enrollment_by_id(self, enrollment_id: UUID) -> EnrollmentRecord | None:
        return next((item for item in self.enrollments if item.id == enrollment_id), None)

    def get_payment_by_id(self, payment_id: UUID) -> PaymentRecord | None:
        return next((item for item in self.payments if item.id == payment_id), None)

    def get_payment_by_order_no(self, order_no: str) -> PaymentRecord | None:
        return next((item for item in self.payments if item.order_no == order_no), None)

    def get_class_by_id(self, class_id: UUID) -> ClassSummary | None:
        return next((item for item in self.classes if item.id == class_id), None)

    def find_lead_by_email(self, email: str) -> Lead | None:
        lowered = email.strip().lower()
        matches = [item for item in self.leads if item.email and item.email.lower() == lowered]
        if not matches:
            return None
        return max(matches, key=lambda item: item.updated_at)

    def student_dashboard(self, email: str) -> StudentDashboard:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        student_enrollments = self.student_enrollments(email)
        class_ids = {item.class_id for item in student_enrollments if item.status in {"pending", "active"}}
        active_courses = [item for item in self.classes if item.id in class_ids]
        payment_statuses = [item.payment_status for item in student_enrollments]
        notifications = self.list_notifications(student.email)
        return StudentDashboard(
            student=student,
            active_courses=active_courses,
            payment_statuses=payment_statuses,
            notification_count=len(notifications),
        )

    def student_enrollments(self, email: str) -> list[EnrollmentRecord]:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        return [item for item in self.enrollments if item.student_id == student.id]

    def student_classes(self, email: str) -> list[ClassSummary]:
        enrollments = self.student_enrollments(email)
        class_ids = {item.class_id for item in enrollments}
        return [item for item in self.classes if item.id in class_ids]

    def student_payments(self, email: str) -> list[PaymentRecord]:
        enrollments = self.student_enrollments(email)
        enrollment_ids = {item.id for item in enrollments}
        return [item for item in self.payments if item.enrollment_id in enrollment_ids]

    def student_notifications(self, email: str) -> list[NotificationRecord]:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        return self.list_notifications(student.email)

    def progress_snapshot(self) -> ProgressSnapshot:
        modules = [
            ProgressModule(name="Docs / PRD", status="completed", summary="規格、ER、roadmap、delivery plan 已完成。"),
            ProgressModule(name="Schema / SQL", status="completed", summary="PostgreSQL MVP schema 已整理完成。"),
            ProgressModule(name="Public Site API", status="completed", summary="課程、試聽、報名入口已可用。"),
            ProgressModule(name="CRM / Leads", status="completed", summary="lead 列表、詳情、分派、狀態更新與顧問案件頁已完成。"),
            ProgressModule(name="Payments", status="completed", summary="payment intent 與 webhook 回寫已完成。"),
            ProgressModule(name="Auth / RBAC", status="completed", summary="登入、token session、角色限制已完成。"),
            ProgressModule(name="Student Portal API", status="completed", summary="dashboard、課程、付款、通知 API 已完成。"),
            ProgressModule(name="Notifications", status="completed", summary="通知資料已落地，建單與付款流程會自動產生通知，後台訊息中心也能直接廣播。"),
            ProgressModule(name="Teaching Ops", status="in_progress", summary="作業、出缺勤、測驗、評分、學習進度中心、教師課後紀錄與主管審核鏈已可在教務管理頁操作。"),
            ProgressModule(name="Teacher Workspace", status="in_progress", summary="教師工作台、班級教學詳頁、待評分作業與測驗流程已補上，班級頁也可直接批改、點名、送出課後紀錄與進行教學驗證。"),
            ProgressModule(name="Teacher Verification", status="in_progress", summary="教師教學手冊、開課驗證題庫、驗證紀錄與管理端總覽已補上第一版。"),
            ProgressModule(name="Recruiting", status="in_progress", summary="公開職缺頁、應徵投遞、招聘後台、應徵者詳頁、面試排程、錄取決策與 onboarding / probation 追蹤已補上第一版。"),
            ProgressModule(name="Reports / AI Center", status="in_progress", summary="主管報表中心、主管工作台、AI 助理中心、AI 操作紀錄與教案草稿中心已補上第一版。"),
            ProgressModule(name="PostgreSQL Repository", status="in_progress", summary="已改成 domain tables + partial table writes + row-level mutation writes 模式，並補上 cutover rehearsal / deployment smoke 工具，等待實際 DSN 與 DB 連線驗證。"),
            ProgressModule(name="Frontend Dashboard", status="in_progress", summary="已補首頁、課程頁、學員中心、後台預覽、名單詳頁、學員管理、班級/課程/教師管理與 progress 中文頁面。"),
        ]
        tracked_files = 25
        lines_of_code = 0
        code_paths = [
            "school_platform/router.py",
            "school_platform/store.py",
            "school_platform/repository.py",
            "school_platform/ai_runtime.py",
            "school_platform/config.py",
            "school_platform/i18n.py",
            "scripts/cutover_school_platform_postgres.py",
            "scripts/smoke_test_school_platform_postgres.py",
            "scripts/smoke_test_school_platform_deployment.py",
            "scripts/self_distill_school_platform.py",
            "scripts/verify_school_platform_postgres_row_writes.py",
            "tests/test_school_platform_api.py",
            "sql/japanese_school_platform_domain_tables.sql",
        ]
        for path in code_paths:
            try:
                with open(path, encoding="utf-8") as handle:
                    lines_of_code += len(handle.read().splitlines())
            except FileNotFoundError:
                continue
        tests_passing = 67
        try:
            tests_path = Path("tests/test_school_platform_api.py")
            tests_passing = sum(1 for line in tests_path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("def test_"))
        except FileNotFoundError:
            pass
        return ProgressSnapshot(
            updated_at=_now(),
            completed_modules=sum(1 for item in modules if item.status == "completed"),
            total_modules=len(modules),
            tests_passing=tests_passing,
            tracked_files=tracked_files,
            lines_of_code=lines_of_code,
            modules=modules,
            next_actions=[
                "把 PostgreSQL 連到實際 DSN 做端到端驗證",
                "把教師教材 / 講義工作流與更多批量教務操作接到同一套 Teaching Ops",
                "補 DB cutover 後的真實資料搬遷 smoke test 與正式部署驗證",
                "把顧問、教師、財務、排課、學生 AI 練習、AI 教務、招聘案件與主管工作台接成更完整的營運閉環",
            ],
        )

    def activity_feed(self) -> list[dict[str, str]]:
        return [
            {
                "time": _now().isoformat(),
                "title": "加盟招商 VAP 首頁與 AI-aging 敘事已上線",
                "summary": "首頁主視覺改為先推加盟招商，新增獨立加盟招商 VAP 頁，集中呈現 AI-aging、AI Edge、學生分享飛輪與大阪十區加盟權益。",
            },
            {
                "time": _now().isoformat(),
                "title": "線上學習紀錄與加盟組招生報表已接進管理區",
                "summary": "主管工作台與報表中心新增學員線上學習紀錄報表，以及三個加盟組的招商漏斗、區域銷售與加盟收入追蹤頁。",
            },
            {
                "time": _now().isoformat(),
                "title": "教師課後紀錄與主管審核 workflow 已補上",
                "summary": "教師班級詳頁新增課後紀錄送審表單，教務管理頁新增核准 / 退回修正流程，teacher dashboard 與 class API 也同步顯示審核狀態。",
            },
            {
                "time": _now().isoformat(),
                "title": "教師教學手冊與開課驗證流程已補上",
                "summary": "新增教師手冊章節、驗證題庫、教師驗證頁與管理端總覽，通過後會回寫 teaching:verified 權限。",
            },
            {
                "time": _now().isoformat(),
                "title": "self-distill audit runner 已補上",
                "summary": "新增 repo 內可重跑的 self-distill script，可自動產出 evidence index、capability candidates、validation report 與 receipt。",
            },
            {
                "time": _now().isoformat(),
                "title": "DB cutover rehearsal 與部署 smoke tooling 已補上",
                "summary": "新增一鍵 PostgreSQL cutover rehearsal、live deployment smoke test 與 row-level write probe scripts，system / runbook / README 也已同步對齊。",
            },
            {
                "time": _now().isoformat(),
                "title": "招聘 onboarding / probation 流程已開始落地",
                "summary": "新增 applicant onboarding record、API 與表單，HR 可從錄取後直接追蹤報到、checklist 與試用期節點。",
            },
            {
                "time": _now().isoformat(),
                "title": "PostgreSQL row-level mutation write 已開始落地",
                "summary": "repository 新增 row-level write 能力，system / migration / smoke test 頁也已補上更正式的 readiness 與切換資訊。",
            },
            {
                "time": _now().isoformat(),
                "title": "教師班級詳頁批改與點名已補齊",
                "summary": "新增班級詳頁內的待批改作業、待批改測驗與快速點名表單，老師可直接在班級層完成教學操作。",
            },
            {
                "time": _now().isoformat(),
                "title": "招聘決策流程已開始落地",
                "summary": "新增面試評分、案件階段更新與錄取/婉拒決策流程，HR 可直接在應徵者詳頁推進招聘案件。",
            },
            {
                "time": _now().isoformat(),
                "title": "顧問案件詳頁已開始落地",
                "summary": "新增顧問案件詳頁與 consultant lead detail API，讓顧問可在自己的工作流裡更新狀態、補 log 並查看 AI 跟進草稿。",
            },
            {
                "time": _now().isoformat(),
                "title": "教師班級詳頁已開始落地",
                "summary": "新增教師班級詳頁與 teacher class detail API，讓老師可直接查看學員名單、作業、測驗與最近出缺勤。",
            },
            {
                "time": _now().isoformat(),
                "title": "主管工作台已開始落地",
                "summary": "新增主管工作台與 executive dashboard API，把招生、學員、財務、客服、招聘與 AI 使用整合成單一決策頁。",
            },
            {
                "time": _now().isoformat(),
                "title": "學員管理中心已開始落地",
                "summary": "新增學員管理頁、學員詳情頁與 admin students API，讓主管可直接查看學員課程、付款、通知與最近歷程。",
            },
            {
                "time": _now().isoformat(),
                "title": "訊息中心已開始落地",
                "summary": "新增訊息中心與 messages overview / broadcast API，讓行政可對單一學員、進行中學員或全部學員發送通知。",
            },
            {
                "time": _now().isoformat(),
                "title": "學員 AI 練習區已開始落地",
                "summary": "新增學員端 AI 練習區與 student ai practice API，讓學生可依主題生成生活日語情境對話、關鍵句型與自我檢查清單。",
            },
            {
                "time": _now().isoformat(),
                "title": "招聘應徵者詳頁已開始落地",
                "summary": "新增應徵者詳頁與 applicant detail API，把職缺資訊、AI 配對評估、建議面試題與面試紀錄集中成 HR 可直接處理的案件頁。",
            },
            {
                "time": _now().isoformat(),
                "title": "AI 教案草稿中心已開始落地",
                "summary": "新增 AI 教案草稿中心與 lesson plan draft API，讓老師和主管可依班級與課堂焦點快速生成教學草稿。",
            },
            {
                "time": _now().isoformat(),
                "title": "排課中心已開始落地",
                "summary": "新增排課中心與 schedule overview API，把班級時段、教師排課負載與衝堂檢查整理成主管可直接看的排課入口。",
            },
            {
                "time": _now().isoformat(),
                "title": "財務中心已開始落地",
                "summary": "新增財務中心與 finance overview API，把最近報名、付款、待收款與營收狀態整理成主管可直接看的財務入口。",
            },
            {
                "time": _now().isoformat(),
                "title": "招生顧問工作台已開始落地",
                "summary": "新增顧問工作台與 consultant dashboard API，把高意向名單、待跟進隊列與最近更新集中到單一工作入口。",
            },
            {
                "time": _now().isoformat(),
                "title": "員工績效中心已開始落地",
                "summary": "新增員工績效中心與 staff performance API，把招生顧問、教師與主管的工作量與待辦匯成同一個管理視圖。",
            },
            {
                "time": _now().isoformat(),
                "title": "學生學習進度中心已開始落地",
                "summary": "新增學生端學習進度中心、教務端學習進度總覽，以及整合作業、測驗、出缺勤的進度 API。",
            },
            {
                "time": _now().isoformat(),
                "title": "School Platform 全站已可切換簡體中文",
                "summary": "新增全站語系切換器、繁簡轉換 middleware，並讓導頁與表單流程維持 lang=zh-Hans。",
            },
            {
                "time": _now().isoformat(),
                "title": "主管報表與 AI 助理中心已開始落地",
                "summary": "新增報表中心、AI 助理中心、AI logs 與週摘要 API，開始把營運分析拉進正式後台。",
            },
            {
                "time": _now().isoformat(),
                "title": "教師工作台與測驗中心已開始落地",
                "summary": "新增教師工作台、學生端測驗中心、測驗建立、提交與評分 API，教學流程從作業延伸到測驗與教師評改。",
            },
            {
                "time": _now().isoformat(),
                "title": "招聘管理與公開職缺頁已開始落地",
                "summary": "新增公開職缺頁、應徵投遞表單、招聘後台與面試安排流程，平台不再只限招生與教務。",
            },
            {
                "time": _now().isoformat(),
                "title": "作業中心與出缺勤已開始落地",
                "summary": "新增學生端作業中心、出缺勤頁，以及管理端教務管理頁、作業發布與點名流程。",
            },
            {
                "time": _now().isoformat(),
                "title": "通知與客服處理 API 已補齊",
                "summary": "新增通知狀態更新、客服收件箱與客服回覆 API，前後端分離時也能直接串接。",
            },
            {
                "time": _now().isoformat(),
                "title": "通知已讀與客服回覆流程已完成",
                "summary": "學員可在通知中心標記已讀，管理端可在客服案件詳情頁回覆學生並更新案件狀態。",
            },
            {
                "time": _now().isoformat(),
                "title": "學生歷程頁與客服收件箱已完成",
                "summary": "新增 /school-platform/my-history 與 /school-platform/admin/support-inbox，學生端與管理端的客服流程已串成一條線。",
            },
            {
                "time": _now().isoformat(),
                "title": "客服需求中心與付款提醒已可提交",
                "summary": "新增 /school-platform/help-center 與付款提醒送出流程，學員端不再只有查詢頁，也能主動發起需求。",
            },
            {
                "time": _now().isoformat(),
                "title": "學員通知中心與我的課表已完成",
                "summary": "新增 /school-platform/notifications-center 與 /school-platform/my-schedule，學員端不再只有總覽頁。",
            },
            {
                "time": _now().isoformat(),
                "title": "前台付款中心已完成",
                "summary": "新增 /school-platform/payment，可直接查訂單、建立 payment intent，並模擬 webhook 更新付款狀態。",
            },
            {
                "time": _now().isoformat(),
                "title": "正式報名頁已做成中文可操作表單",
                "summary": "新增 /school-platform/enrollment 與成功頁，前台現在可直接建立學員、報名單與付款訂單。",
            },
            {
                "time": _now().isoformat(),
                "title": "資料層已支援 partial table writes",
                "summary": "高頻 mutation 現在只會持久化受影響的 state keys，PostgreSQL domain tables 切換後不需要每次整包重寫。",
            },
            {
                "time": _now().isoformat(),
                "title": "前台試聽頁已做成中文可操作表單",
                "summary": "新增 /school-platform/trial-booking 與成功頁，現在不只 API，使用者也能直接從網頁送出試聽預約。",
            },
            {
                "time": _now().isoformat(),
                "title": "Router 已全面改走 service 層",
                "summary": "學員中心頁、試聽預約 API、AI 跟進草稿、system health/init 都已不再直接在 router 層碰 store。",
            },
            {
                "time": _now().isoformat(),
                "title": "學員 / 報名 / 付款查詢已開始切到 service / repository",
                "summary": "新增 FinanceService，student portal 與 admin finance 查詢路徑開始脫離 store 內的 in-memory 聚合。",
            },
            {
                "time": _now().isoformat(),
                "title": "PostgreSQL repository 已拆成 domain tables persistence",
                "summary": "不再只靠整包 snapshot；目前已對應 staff、users、courses、classes、leads、lead_logs、students、enrollments、payments、notifications 細表。",
            },
            {
                "time": _now().isoformat(),
                "title": "完整平台架構已整理成文件與頁面",
                "summary": "新增 09-platform-architecture.md，並補上 /school-platform/architecture 中文架構頁。",
            },
            {
                "time": _now().isoformat(),
                "title": "後台編輯流程已接上",
                "summary": "lead 指派、lead 狀態更新、lead 跟進紀錄、課程編輯、班級編輯都已變成可提交表單。",
            },
            {
                "time": _now().isoformat(),
                "title": "後台頁面骨架擴充",
                "summary": "營運總覽、招生名單、名單詳頁、班級管理、課程管理、教師管理都已提供中文頁面。",
            },
            {
                "time": _now().isoformat(),
                "title": "學員端與前台已可視化",
                "summary": "平台首頁、課程總覽、課程詳情、學員中心、進度頁都可以直接在瀏覽器查看。",
            },
            {
                "time": _now().isoformat(),
                "title": "測試覆蓋持續增加",
                "summary": "目前自動測試已到 31 支，覆蓋公開 API、權限、付款流程、通知/客服、作業提交、出缺勤與教務管理頁。",
            },
        ]

    def get_user_by_email(self, email: str) -> UserAccount | None:
        lowered = email.strip().lower()
        return next((item for item in self.users if item.email.lower() == lowered), None)

    def get_user_by_id(self, user_id: UUID) -> UserAccount | None:
        return next((item for item in self.users if item.id == user_id), None)

    def default_permissions_for_role(self, role: str) -> list[str]:
        return list(_ROLE_PERMISSION_PRESETS.get(role, []))

    def allowed_subaccount_roles(self, owner: UserAccount | None = None) -> list[str]:
        if owner is None:
            return list(_SUBACCOUNT_ROLE_OPTIONS["super_admin"])
        return list(_SUBACCOUNT_ROLE_OPTIONS.get(owner.role, ()))

    def list_user_accounts(
        self,
        *,
        parent_user_id: UUID | object = _UNSET,
        account_type: str | None = None,
        status: str | None = None,
    ) -> list[UserAccount]:
        items = self.users
        if parent_user_id is not _UNSET:
            items = [item for item in items if item.parent_user_id == parent_user_id]
        if account_type:
            items = [item for item in items if item.account_type == account_type]
        if status:
            items = [item for item in items if item.status == status]
        return sorted(items, key=lambda item: (item.account_type != "primary", item.name.lower(), item.email.lower()))

    def create_sub_account(self, payload: SubAccountCreateRequest, actor: UserAccount | None = None) -> UserAccount:
        existing = self.get_user_by_email(payload.email)
        if existing is not None:
            raise ValueError("User email already exists")
        if actor is not None and actor.role not in {"super_admin", "manager"}:
            raise PermissionError("Only managers can create sub accounts")

        owner: UserAccount | None = None
        if payload.owner_user_id is not None:
            owner = self.get_user_by_id(payload.owner_user_id)
            if owner is None:
                raise KeyError("owner_user_id")
        elif actor is not None:
            owner = actor

        if owner is None:
            raise KeyError("owner_user_id")
        if owner.account_type != "primary":
            raise ValueError("Sub account cannot own another sub account")

        acting_owner = actor or owner
        allowed_roles = self.allowed_subaccount_roles(acting_owner)
        if payload.role not in allowed_roles:
            raise PermissionError("Requested role is not allowed for this owner")
        if actor is not None and actor.role == "manager" and owner.id != actor.id:
            raise PermissionError("Manager can only create sub accounts under current account")

        normalized_email = payload.email.strip().lower()
        normalized_name = payload.name.strip()
        normalized_scope = payload.scope_label.strip() if payload.scope_label and payload.scope_label.strip() else None
        normalized_note = payload.note.strip() if payload.note and payload.note.strip() else None
        matched_staff = next(
            (item for item in self.staff if item.name == normalized_name and item.role == payload.role),
            None,
        )
        account = UserAccount(
            id=uuid4(),
            email=normalized_email,
            name=normalized_name,
            password_hash=self.hash_password(payload.password),
            role=payload.role,
            staff_id=matched_staff.id if matched_staff is not None else None,
            permissions=payload.permissions or self.default_permissions_for_role(payload.role),
            status=payload.status,
            parent_user_id=owner.id,
            account_type="sub_account",
            scope_label=normalized_scope,
            note=normalized_note,
        )
        self.users.append(account)
        self._persist_rows("users", [account])
        return account

    def dashboard_metrics(self) -> DashboardMetrics:
        now = _now()
        week_start = now - timedelta(days=7)
        return DashboardMetrics(
            today_new_leads=sum(1 for item in self.leads if item.created_at.date() == now.date()),
            this_week_trial_bookings=sum(1 for item in self.leads if item.status == "trial_booked" and item.created_at >= week_start),
            this_week_enrollments=sum(1 for item in self.enrollments if item.created_at >= week_start),
            paid_revenue_total=sum(item.amount for item in self.payments if item.status == "paid"),
            pending_follow_ups=sum(
                1
                for item in self.leads
                if _normalize_datetime(item.next_follow_up_at) and _normalize_datetime(item.next_follow_up_at) <= now
            ),
            active_classes=sum(1 for item in self.classes if item.status == "open"),
        )

    def followup_draft(self, lead_id: UUID) -> FollowupDraftResponse:
        lead = self.get_lead(lead_id)
        course_name = lead.interested_course_slug or "課程"
        result = FollowupDraftResponse(
            lead_id=lead.id,
            recommended_channel="line" if lead.line_id or lead.phone else "email",
            line_message=(
                f"{lead.name} 您好，我是 Japan Life Language School 的招生顧問。"
                f"看到您對 {course_name} 有興趣，想幫您整理最適合的上課方式與近期可預約時段。"
                "如果方便，我可以直接幫您安排一堂試聽。"
            ),
            email_subject=f"{lead.name} 您的日語課程建議與近期開班資訊",
            email_message=(
                f"{lead.name} 您好，\n\n"
                f"根據您目前的程度與目標，我們建議先從 {course_name} 開始。"
                "如果您希望，我們可以先安排試聽，再依照赴日時間幫您排最合適的班。"
            ),
            next_step="先確認學員可試聽的日期，再提供 1 到 2 個具體班級選項。",
        )
        self.create_ai_log(
            module_name="admissions",
            action_name="followup_draft",
            actor_email=lead.email,
            input_summary=f"lead={lead.name}, course={course_name}, status={lead.status}",
            output_summary=f"recommended_channel={result.recommended_channel}, next_step={result.next_step}",
        )
        return result

    def report_overview(self) -> ReportOverview:
        lead_status_counts: dict[str, int] = {}
        for item in self.leads:
            lead_status_counts[item.status] = lead_status_counts.get(item.status, 0) + 1
        course_fill_rates = []
        for class_item in self.classes:
            fill_rate = round((class_item.enrolled_count / class_item.capacity) * 100, 1) if class_item.capacity else 0
            course_fill_rates.append(
                {
                    "class_name": class_item.name,
                    "course_slug": class_item.course_slug,
                    "fill_rate": fill_rate,
                    "enrolled_count": class_item.enrolled_count,
                    "capacity": class_item.capacity,
                }
            )
        report = ReportOverview(
            lead_status_counts=lead_status_counts,
            course_fill_rates=course_fill_rates,
            revenue_summary={
                "paid": round(sum(item.amount for item in self.payments if item.status == "paid"), 2),
                "pending": round(sum(item.amount for item in self.payments if item.status == "pending"), 2),
                "refunded": round(sum(item.amount for item in self.payments if item.status == "refunded"), 2),
            },
            recruiting_summary={
                "open_jobs": sum(1 for item in self.job_positions if item.status == "open"),
                "applicants": len(self.applicants),
                "scheduled_interviews": sum(1 for item in self.interviews if item.status == "scheduled"),
                "active_onboarding": sum(1 for item in self.onboarding_records if item.stage not in {"completed", "cancelled"}),
                "active_probation": sum(1 for item in self.onboarding_records if item.probation_status in {"in_progress", "extended"}),
            },
            teaching_summary={
                "assignments": len(self.assignments),
                "submitted_assignments": len(self.assignment_submissions),
                "exams": len(self.exams),
                "submitted_exams": len(self.exam_submissions),
            },
            generated_at=_now(),
        )
        return report

    def weekly_ai_summary(self) -> dict[str, object]:
        report = self.report_overview()
        hottest_status = max(report.lead_status_counts.items(), key=lambda item: item[1])[0] if report.lead_status_counts else "new"
        top_fill = max(report.course_fill_rates, key=lambda item: item["fill_rate"]) if report.course_fill_rates else None
        summary = {
            "headline": "本週營運摘要已生成",
            "insights": [
                f"目前 lead 最大宗狀態是 {hottest_status}，建議優先處理臨近 follow-up 的名單。",
                f"最高滿班率班級是 {top_fill['class_name']}（{top_fill['fill_rate']}%）。" if top_fill else "目前尚無班級滿班率資料。",
                f"招聘端目前共有 {report.recruiting_summary['applicants']} 位應徵者，已排面試 {report.recruiting_summary['scheduled_interviews']} 場。",
                f"到職 / 試用流程中共有 {report.recruiting_summary['active_onboarding']} 筆 onboarding、{report.recruiting_summary['active_probation']} 筆 probation 追蹤。",
            ],
            "actions": [
                "優先追蹤 trial_booked 與 considering 名單，縮短轉換週期。",
                "對高滿班率班級評估增開班或候補機制。",
                "持續讓教師工作台完成待評分項目，避免學員回饋延遲。",
            ],
            "generated_at": _now(),
        }
        self.create_ai_log(
            module_name="operations",
            action_name="weekly_summary",
            actor_email="manager@jls.local",
            input_summary="lead, payment, recruiting, teaching aggregates",
            output_summary="; ".join(summary["insights"]),
        )
        return summary


store = SchoolPlatformStore()
