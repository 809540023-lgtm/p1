from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


LeadStatus = Literal[
    "new",
    "contacted",
    "replied",
    "trial_booked",
    "trial_completed",
    "considering",
    "enrolled",
    "waitlisted",
    "lost",
    "blacklisted",
]


class CourseSummary(BaseModel):
    id: UUID
    slug: str
    name: str
    course_type: str
    level: str
    delivery_mode: str
    price: float
    short_description: str


class CourseDetail(CourseSummary):
    objectives: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    teacher_names: list[str] = Field(default_factory=list)


class ClassSummary(BaseModel):
    id: UUID
    course_id: UUID
    course_slug: str
    name: str
    teacher_name: str
    start_date: date
    end_date: date
    weekday: str
    start_time: time
    end_time: time
    capacity: int
    enrolled_count: int
    location_label: str
    status: str


class CourseUpsertRequest(BaseModel):
    slug: str
    name: str
    course_type: str
    level: str
    delivery_mode: str
    price: float
    short_description: str
    objectives: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    teacher_names: list[str] = Field(default_factory=list)


class ClassUpsertRequest(BaseModel):
    course_slug: str
    name: str
    teacher_name: str
    start_date: date
    end_date: date
    weekday: str
    start_time: time
    end_time: time
    capacity: int
    location_label: str
    status: str = "open"


class Lead(BaseModel):
    id: UUID
    name: str
    phone: str | None = None
    email: str | None = None
    line_id: str | None = None
    source_channel: str
    campaign_name: str | None = None
    interested_course_slug: str | None = None
    budget_range: str | None = None
    japanese_level: str | None = None
    study_goal: str | None = None
    departure_plan_date: date | None = None
    intent_score: float = 0
    win_probability: float = 0
    status: LeadStatus = "new"
    assigned_staff_name: str | None = None
    last_contact_at: datetime | None = None
    next_follow_up_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadLog(BaseModel):
    id: UUID
    lead_id: UUID
    staff_name: str
    contact_method: str
    content: str
    next_action: str | None = None
    created_at: datetime


class TrialSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    course_slug: str
    label: str


class TrialBookingCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    line_id: str | None = None
    course_slug: str
    slot_start_at: datetime
    japanese_level: str | None = None
    study_goal: str | None = None
    departure_plan_date: date | None = None


class TrialBookingResponse(BaseModel):
    booking_id: UUID
    lead_id: UUID
    status: str
    assigned_staff_name: str
    next_follow_up_at: datetime


class LeadAssignmentRequest(BaseModel):
    staff_id: UUID


class LeadStatusChangeRequest(BaseModel):
    status: LeadStatus
    next_follow_up_at: datetime | None = None
    note: str | None = None


class EnrollmentCreate(BaseModel):
    chinese_name: str
    email: str
    phone: str | None = None
    class_id: UUID
    japanese_level: str | None = None
    study_goal: str | None = None
    coupon_code: str | None = None
    payment_method: Literal["card", "transfer", "cash"] = "card"


class EnrollmentResponse(BaseModel):
    enrollment_id: UUID
    student_id: UUID
    payment_id: UUID
    order_no: str
    status: str
    payment_status: str


class PaymentRecord(BaseModel):
    id: UUID
    enrollment_id: UUID
    order_no: str
    amount: float
    payment_method: str
    status: str
    provider: str | None = "mock"
    provider_payment_id: str | None = None
    checkout_url: str | None = None
    client_token: str | None = None
    currency: str | None = "JPY"
    provider_status: str | None = None
    checkout_expires_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    provider_last_error: str | None = None
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class PaymentIntentCreate(BaseModel):
    enrollment_id: UUID
    payment_method: Literal["card", "transfer", "cash"] = "card"


class PaymentIntentResponse(BaseModel):
    payment_id: UUID
    order_no: str
    amount: float
    payment_method: str
    status: str
    client_token: str
    provider: str = "mock"
    provider_payment_id: str | None = None
    checkout_url: str | None = None
    currency: str = "JPY"
    provider_status: str | None = None
    checkout_expires_at: datetime | None = None


class PaymentWebhookPayload(BaseModel):
    order_no: str
    status: Literal["paid", "failed", "refunded"]
    paid_at: datetime | None = None
    provider: str | None = None
    provider_payment_id: str | None = None
    provider_status: str | None = None


class StudentRecord(BaseModel):
    id: UUID
    chinese_name: str
    email: str
    phone: str | None = None
    japanese_level: str | None = None
    study_goal: str | None = None
    status: str
    created_at: datetime


class StudentDashboard(BaseModel):
    student: StudentRecord
    active_courses: list[ClassSummary] = Field(default_factory=list)
    payment_statuses: list[str] = Field(default_factory=list)
    notification_count: int = 0


class StudentTimelineEvent(BaseModel):
    kind: str
    title: str
    detail: str
    at: datetime


class StudentAdminItem(BaseModel):
    student: StudentRecord
    enrollment_count: int = 0
    active_course_count: int = 0
    payment_count: int = 0
    pending_payment_count: int = 0
    notification_count: int = 0
    queued_notification_count: int = 0
    last_activity_at: datetime | None = None


class StudentAdminSummary(BaseModel):
    total_students: int = 0
    active_students: int = 0
    pending_payment_students: int = 0
    queued_notification_students: int = 0


class StudentAdminSnapshot(BaseModel):
    summary: StudentAdminSummary
    items: list[StudentAdminItem] = Field(default_factory=list)
    generated_at: datetime


class StudentAdminDetailSnapshot(BaseModel):
    item: StudentAdminItem
    classes: list[ClassSummary] = Field(default_factory=list)
    enrollments: list["EnrollmentRecord"] = Field(default_factory=list)
    payments: list[PaymentRecord] = Field(default_factory=list)
    notifications: list[NotificationRecord] = Field(default_factory=list)
    history: list[StudentTimelineEvent] = Field(default_factory=list)
    generated_at: datetime


class StudentProgressSummary(BaseModel):
    assignment_total: int = 0
    assignment_submitted: int = 0
    assignment_graded: int = 0
    assignment_average: float | None = None
    exam_total: int = 0
    exam_submitted: int = 0
    exam_graded: int = 0
    exam_average: float | None = None
    attendance_total: int = 0
    attendance_present: int = 0
    attendance_rate: float = 0
    overall_score: float | None = None
    risk_level: Literal["low", "medium", "high"] = "low"
    weak_spot: str = "尚無明顯風險"
    recommended_action: str = "維持目前學習節奏。"


class StudentProgressAssignmentItem(BaseModel):
    assignment_id: UUID
    title: str
    class_name: str
    due_at: datetime
    status: str
    submitted_at: datetime | None = None
    score: float | None = None
    feedback: str | None = None


class StudentProgressExamItem(BaseModel):
    exam_id: UUID
    title: str
    class_name: str
    exam_type: str
    due_at: datetime
    total_score: float
    status: str
    submitted_at: datetime | None = None
    score: float | None = None
    feedback: str | None = None
    graded_by: str | None = None


class StudentProgressAttendanceItem(BaseModel):
    attendance_id: UUID
    class_name: str
    class_date: date
    status: str
    note: str | None = None
    marked_by: str


class StudentProgressSnapshot(BaseModel):
    student: StudentRecord
    summary: StudentProgressSummary
    assignments: list[StudentProgressAssignmentItem] = Field(default_factory=list)
    exams: list[StudentProgressExamItem] = Field(default_factory=list)
    attendance: list[StudentProgressAttendanceItem] = Field(default_factory=list)
    generated_at: datetime


class StudentProgressOverviewItem(BaseModel):
    student_id: UUID
    chinese_name: str
    email: str
    active_course_count: int = 0
    attendance_rate: float = 0
    overall_score: float | None = None
    pending_assignments: int = 0
    pending_exams: int = 0
    risk_level: Literal["low", "medium", "high"] = "low"
    weak_spot: str = "尚無明顯風險"


class LearningActivityRecord(BaseModel):
    student_id: UUID
    chinese_name: str
    email: str
    activity_kind: Literal["assignment_submission", "exam_submission", "attendance"]
    title: str
    class_name: str
    status: str
    occurred_at: datetime
    score: float | None = None
    detail: str | None = None


class StudentLearningReportItem(BaseModel):
    student_id: UUID
    chinese_name: str
    email: str
    active_course_count: int = 0
    assignment_submitted: int = 0
    assignment_pending: int = 0
    exam_submitted: int = 0
    exam_pending: int = 0
    attendance_rate: float = 0
    overall_score: float | None = None
    activity_count: int = 0
    last_activity_at: datetime | None = None
    risk_level: Literal["low", "medium", "high"] = "low"
    weak_spot: str = "尚無明顯風險"
    recent_activities: list[LearningActivityRecord] = Field(default_factory=list)


class StudentLearningReportSummary(BaseModel):
    total_students: int = 0
    active_students: int = 0
    high_risk_students: int = 0
    average_attendance_rate: float = 0
    average_overall_score: float | None = None
    recent_activity_count: int = 0


class StudentLearningReportSnapshot(BaseModel):
    summary: StudentLearningReportSummary
    items: list[StudentLearningReportItem] = Field(default_factory=list)
    generated_at: datetime


class EnrollmentRecord(BaseModel):
    id: UUID
    student_id: UUID
    class_id: UUID
    status: str
    payment_status: str
    list_price: float
    paid_amount: float
    created_at: datetime


class AssignmentRecord(BaseModel):
    id: UUID
    class_id: UUID
    title: str
    content: str
    due_at: datetime
    created_by: str
    created_at: datetime


class AssignmentCreateRequest(BaseModel):
    class_id: UUID
    title: str
    content: str
    due_at: datetime
    created_by: str = "manager"


class AssignmentSubmissionRecord(BaseModel):
    id: UUID
    assignment_id: UUID
    student_id: UUID
    content: str
    status: str
    submitted_at: datetime
    feedback: str | None = None
    score: float | None = None


class AssignmentSubmissionCreateRequest(BaseModel):
    email: str
    content: str


class SubmissionGradeRequest(BaseModel):
    score: float
    feedback: str | None = None
    graded_by: str = "Aki Mori"


class AttendanceRecord(BaseModel):
    id: UUID
    class_id: UUID
    student_id: UUID
    class_date: date
    status: str
    note: str | None = None
    marked_by: str
    created_at: datetime


class AttendanceMarkRequest(BaseModel):
    class_id: UUID
    student_email: str
    class_date: date
    status: Literal["present", "absent", "late", "leave"]
    note: str | None = None
    marked_by: str = "manager"


class ExamRecord(BaseModel):
    id: UUID
    class_id: UUID
    title: str
    exam_type: str
    instructions: str
    total_score: float
    due_at: datetime
    created_by: str
    created_at: datetime


class ExamCreateRequest(BaseModel):
    class_id: UUID
    title: str
    exam_type: str = "quiz"
    instructions: str
    total_score: float = 100
    due_at: datetime
    created_by: str = "Aki Mori"


class ExamSubmissionRecord(BaseModel):
    id: UUID
    exam_id: UUID
    student_id: UUID
    content: str
    status: str
    submitted_at: datetime
    feedback: str | None = None
    score: float | None = None
    graded_by: str | None = None


class ExamSubmissionCreateRequest(BaseModel):
    email: str
    content: str


class TeachingSessionRecord(BaseModel):
    id: UUID
    class_id: UUID
    teacher_name: str
    class_date: date
    summary: str
    materials_link: str | None = None
    homework_summary: str | None = None
    next_class_focus: str | None = None
    student_risk_notes: list[str] = Field(default_factory=list)
    approval_status: Literal["draft", "submitted", "approved", "revision_requested"] = "draft"
    review_note: str | None = None
    reviewed_by: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TeachingSessionUpsertRequest(BaseModel):
    class_id: UUID
    teacher_name: str
    class_date: date
    summary: str
    materials_link: str | None = None
    homework_summary: str | None = None
    next_class_focus: str | None = None
    student_risk_notes: list[str] = Field(default_factory=list)
    approval_status: Literal["draft", "submitted"] = "submitted"


class TeachingSessionReviewRequest(BaseModel):
    approval_status: Literal["approved", "revision_requested"]
    review_note: str | None = None
    reviewed_by: str = "Yuki Wang"


class TeacherClassStudentItem(BaseModel):
    student_id: UUID
    chinese_name: str
    email: str
    enrollment_status: str
    payment_status: str
    assignment_submitted: int = 0
    assignment_total: int = 0
    exam_submitted: int = 0
    exam_total: int = 0
    attendance_rate: float = 0
    latest_attendance_status: str | None = None
    risk_level: Literal["low", "medium", "high"] = "low"


class TeacherClassSummary(BaseModel):
    total_students: int = 0
    high_risk_students: int = 0
    medium_risk_students: int = 0
    submitted_assignments: int = 0
    pending_assignments: int = 0
    submitted_exams: int = 0
    pending_exams: int = 0
    attendance_records: int = 0
    session_records: int = 0
    pending_session_reviews: int = 0


class TeacherClassSnapshot(BaseModel):
    class_item: ClassSummary
    summary: TeacherClassSummary
    roster: list[TeacherClassStudentItem] = Field(default_factory=list)
    assignments: list[AssignmentRecord] = Field(default_factory=list)
    exams: list[ExamRecord] = Field(default_factory=list)
    attendance_records: list[AttendanceRecord] = Field(default_factory=list)
    assignment_submissions: list[AssignmentSubmissionRecord] = Field(default_factory=list)
    exam_submissions: list[ExamSubmissionRecord] = Field(default_factory=list)
    session_records: list[TeachingSessionRecord] = Field(default_factory=list)
    generated_at: datetime


class StaffRecord(BaseModel):
    id: UUID
    name: str
    role: str
    department: str
    title: str


class StaffPerformanceItem(BaseModel):
    staff_id: UUID
    name: str
    role: str
    department: str
    title: str
    assigned_leads: int = 0
    enrolled_leads: int = 0
    pending_follow_ups: int = 0
    active_classes: int = 0
    assignments_created: int = 0
    exams_created: int = 0
    pending_reviews: int = 0


class StaffPerformanceSummary(BaseModel):
    total_staff: int = 0
    consultants: int = 0
    teachers: int = 0
    managers: int = 0
    pending_follow_ups: int = 0
    pending_reviews: int = 0


class ConsultantLeadItem(BaseModel):
    lead_id: UUID
    name: str
    status: LeadStatus
    interested_course_slug: str | None = None
    intent_score: float = 0
    win_probability: float = 0
    next_follow_up_at: datetime | None = None
    last_contact_at: datetime | None = None
    latest_log_summary: str | None = None


class ConsultantDashboardSummary(BaseModel):
    consultant_name: str
    assigned_leads: int = 0
    overdue_follow_ups: int = 0
    due_today: int = 0
    high_intent_leads: int = 0
    trial_booked_leads: int = 0
    enrolled_leads: int = 0


class ConsultantDashboardSnapshot(BaseModel):
    summary: ConsultantDashboardSummary
    hot_leads: list[ConsultantLeadItem] = Field(default_factory=list)
    follow_up_queue: list[ConsultantLeadItem] = Field(default_factory=list)
    recently_updated: list[ConsultantLeadItem] = Field(default_factory=list)
    generated_at: datetime


class ConsultantLeadDetailSnapshot(BaseModel):
    consultant_name: str
    lead: Lead
    logs: list[LeadLog] = Field(default_factory=list)
    followup_draft: FollowupDraftResponse | None = None
    generated_at: datetime


class FinanceSummary(BaseModel):
    enrollment_total: int = 0
    pending_enrollments: int = 0
    paid_payments: int = 0
    pending_payments: int = 0
    refunded_payments: int = 0
    paid_revenue: float = 0
    pending_revenue: float = 0


class FinanceOverviewSnapshot(BaseModel):
    summary: FinanceSummary
    recent_enrollments: list[EnrollmentRecord] = Field(default_factory=list)
    recent_payments: list[PaymentRecord] = Field(default_factory=list)
    generated_at: datetime


class TeacherScheduleLoad(BaseModel):
    teacher_name: str
    class_count: int = 0
    weekly_sessions: int = 0
    weekly_hours: float = 0


class ScheduleConflictItem(BaseModel):
    teacher_name: str
    weekday: str
    class_names: list[str] = Field(default_factory=list)
    time_range: str
    overlap_note: str


class ScheduleOverviewSummary(BaseModel):
    total_open_classes: int = 0
    teachers_scheduled: int = 0
    online_classes: int = 0
    onsite_classes: int = 0
    detected_conflicts: int = 0


class ScheduleOverviewSnapshot(BaseModel):
    summary: ScheduleOverviewSummary
    teacher_loads: list[TeacherScheduleLoad] = Field(default_factory=list)
    classes: list[ClassSummary] = Field(default_factory=list)
    conflicts: list[ScheduleConflictItem] = Field(default_factory=list)
    generated_at: datetime


class JobPositionRecord(BaseModel):
    id: UUID
    title: str
    department: str
    employment_type: str
    location_label: str
    salary_range: str
    summary: str
    requirements: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime


class JobPositionCreateRequest(BaseModel):
    title: str
    department: str
    employment_type: str
    location_label: str
    salary_range: str
    summary: str
    requirements: list[str] = Field(default_factory=list)
    status: str = "open"


class ApplicantRecord(BaseModel):
    id: UUID
    position_id: UUID
    name: str
    email: str
    phone: str | None = None
    resume_link: str | None = None
    note: str | None = None
    ai_match_score: float = 0
    interview_status: str
    created_at: datetime


class ApplicantCreateRequest(BaseModel):
    position_id: UUID
    name: str
    email: str
    phone: str | None = None
    resume_link: str | None = None
    note: str | None = None


class InterviewRecord(BaseModel):
    id: UUID
    applicant_id: UUID
    interview_at: datetime
    interviewer_name: str
    format: str
    status: str
    feedback: str | None = None
    created_at: datetime


class InterviewCreateRequest(BaseModel):
    applicant_id: UUID
    interview_at: datetime
    interviewer_name: str
    format: str = "google_meet"
    status: str = "scheduled"
    feedback: str | None = None


class InterviewUpdateRequest(BaseModel):
    status: str
    feedback: str | None = None


class ApplicantStatusUpdateRequest(BaseModel):
    interview_status: str
    note: str | None = None


class ApplicantEvaluationResponse(BaseModel):
    applicant_id: UUID
    position_title: str
    ai_match_score: float
    recommendation: str
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    next_action: str


class OnboardingRecord(BaseModel):
    id: UUID
    applicant_id: UUID
    owner_name: str
    stage: str
    start_date: date | None = None
    probation_status: str
    probation_end_date: date | None = None
    checklist_items: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class OnboardingUpsertRequest(BaseModel):
    owner_name: str | None = None
    stage: str = "preboarding"
    start_date: date | None = None
    probation_status: str = "not_started"
    probation_end_date: date | None = None
    checklist_items: list[str] = Field(default_factory=list)
    notes: str | None = None


class ApplicantDetailSnapshot(BaseModel):
    applicant: ApplicantRecord
    position: JobPositionRecord
    interviews: list[InterviewRecord] = Field(default_factory=list)
    evaluation: ApplicantEvaluationResponse
    onboarding: OnboardingRecord | None = None
    generated_at: datetime


class UserAccount(BaseModel):
    id: UUID
    email: str
    name: str
    password_hash: str
    role: str
    staff_id: UUID | None = None
    permissions: list[str] = Field(default_factory=list)
    status: str = "active"
    parent_user_id: UUID | None = None
    account_type: Literal["primary", "sub_account"] = "primary"
    scope_label: str | None = None
    note: str | None = None


class SubAccountCreateRequest(BaseModel):
    owner_user_id: UUID | None = None
    name: str
    email: str
    password: str
    role: Literal["manager", "consultant", "teacher"]
    permissions: list[str] = Field(default_factory=list)
    status: Literal["active", "inactive"] = "active"
    scope_label: str | None = None
    note: str | None = None


class ManagedUserAccountItem(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    staff_id: UUID | None = None
    status: str = "active"
    parent_user_id: UUID | None = None
    parent_user_name: str | None = None
    account_type: Literal["primary", "sub_account"] = "primary"
    scope_label: str | None = None
    note: str | None = None


class UserAccountAdminSummary(BaseModel):
    total_accounts: int = 0
    primary_accounts: int = 0
    sub_accounts: int = 0
    active_accounts: int = 0
    inactive_accounts: int = 0


class UserAccountAdminSnapshot(BaseModel):
    summary: UserAccountAdminSummary
    items: list[ManagedUserAccountItem] = Field(default_factory=list)
    owners: list[ManagedUserAccountItem] = Field(default_factory=list)


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthUserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    staff_id: UUID | None = None
    parent_user_id: UUID | None = None
    account_type: Literal["primary", "sub_account"] = "primary"
    scope_label: str | None = None


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse


class DashboardMetrics(BaseModel):
    today_new_leads: int
    this_week_trial_bookings: int
    this_week_enrollments: int
    paid_revenue_total: float
    pending_follow_ups: int
    active_classes: int


class HomePayload(BaseModel):
    brand_name: str
    hero_title: str
    hero_subtitle: str
    featured_courses: list[CourseSummary]
    value_props: list[str]


class FollowupDraftResponse(BaseModel):
    lead_id: UUID
    recommended_channel: str
    line_message: str
    email_subject: str
    email_message: str
    next_step: str


class LessonPlanDraftRequest(BaseModel):
    class_id: UUID
    lesson_focus: str
    duration_minutes: int = 90
    teacher_name: str | None = None


class LessonPlanStep(BaseModel):
    title: str
    minutes: int
    details: str


class LessonPlanDraftResponse(BaseModel):
    class_id: UUID
    class_name: str
    course_slug: str
    teacher_name: str
    lesson_focus: str
    duration_minutes: int
    objective: str
    warmup: str
    teaching_steps: list[LessonPlanStep] = Field(default_factory=list)
    homework: str
    review_points: list[str] = Field(default_factory=list)
    generated_at: datetime


class PracticeConversationResponse(BaseModel):
    student_email: str
    student_name: str
    class_name: str | None = None
    level: str
    theme: str
    scenario_title: str
    situation: str
    goals: list[str] = Field(default_factory=list)
    key_phrases: list[str] = Field(default_factory=list)
    ai_opening: str
    hints: list[str] = Field(default_factory=list)
    review_checklist: list[str] = Field(default_factory=list)
    generated_at: datetime


class AiProviderStatusResponse(BaseModel):
    requested_provider: str
    active_provider: str
    runtime_mode: str
    service_ready: bool = True
    external_model_ready: bool = False
    model_name: str | None = None
    api_key_present: bool = False
    sdk_available: bool = False
    last_error: str | None = None
    supported_features: list[str] = Field(default_factory=list)


class NotificationRecord(BaseModel):
    id: UUID
    user_email: str | None = None
    channel: str
    type: str
    title: str
    content: str
    status: str
    created_at: datetime
    external_recipient: str | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    updated_at: datetime | None = None


class NotificationCreate(BaseModel):
    user_email: str | None = None
    channel: Literal["email", "line", "in_app"] = "email"
    type: str
    title: str
    content: str
    external_recipient: str | None = None


class NotificationStatusUpdateRequest(BaseModel):
    status: str


class BroadcastMessageRequest(BaseModel):
    audience: Literal["single_student", "all_students", "active_students", "staff_admin"]
    channel: Literal["email", "line", "in_app"] = "email"
    title: str
    content: str
    target_email: str | None = None
    type: str = "manual_broadcast"


class BroadcastMessageResponse(BaseModel):
    audience: str
    recipient_count: int
    sample_recipients: list[str] = Field(default_factory=list)
    notifications: list[NotificationRecord] = Field(default_factory=list)
    sent_at: datetime


class MessageCenterSummary(BaseModel):
    total_notifications: int = 0
    queued_notifications: int = 0
    sent_notifications: int = 0
    failed_notifications: int = 0
    suppressed_notifications: int = 0
    read_notifications: int = 0
    email_notifications: int = 0
    line_notifications: int = 0
    in_app_notifications: int = 0
    broadcast_notifications: int = 0


class SupportReplyRequest(BaseModel):
    status: str
    response_channel: Literal["email", "line", "in_app"] = "email"
    response_message: str


class AiLogRecord(BaseModel):
    id: UUID
    module_name: str
    actor_email: str | None = None
    action_name: str
    input_summary: str
    output_summary: str
    created_at: datetime


class ReportOverview(BaseModel):
    lead_status_counts: dict[str, int] = Field(default_factory=dict)
    course_fill_rates: list[dict[str, object]] = Field(default_factory=list)
    revenue_summary: dict[str, float] = Field(default_factory=dict)
    recruiting_summary: dict[str, int] = Field(default_factory=dict)
    teaching_summary: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime


class FranchiseGroupReportItem(BaseModel):
    group_code: str
    group_name: str
    partner_type: str
    partner_count: int = 0
    sold_regions: int = 0
    total_regions: int = 0
    join_fee_jpy: float = 0
    monthly_fee_jpy: float = 0
    booked_join_fee_revenue_jpy: float = 0
    monthly_recurring_revenue_jpy: float = 0
    total_leads: int = 0
    new_leads: int = 0
    contacted_leads: int = 0
    trial_booked_leads: int = 0
    considering_leads: int = 0
    enrolled_leads: int = 0
    lost_leads: int = 0
    conversion_rate: float = 0
    next_focus: str = "持續追蹤高意向名單。"


class FranchiseGroupReportSummary(BaseModel):
    total_groups: int = 0
    active_groups: int = 0
    total_partner_count: int = 0
    sold_regions: int = 0
    total_regions: int = 0
    total_leads: int = 0
    enrolled_leads: int = 0
    blended_conversion_rate: float = 0
    booked_join_fee_revenue_jpy: float = 0
    monthly_recurring_revenue_jpy: float = 0


class FranchiseGroupReportSnapshot(BaseModel):
    summary: FranchiseGroupReportSummary
    groups: list[FranchiseGroupReportItem] = Field(default_factory=list)
    generated_at: datetime


class ExecutiveAlertItem(BaseModel):
    severity: Literal["info", "warning", "critical"] = "info"
    title: str
    detail: str


class ExecutiveClassWatchItem(BaseModel):
    class_id: UUID
    class_name: str
    course_slug: str
    teacher_name: str
    fill_rate: float = 0
    enrolled_count: int = 0
    capacity: int = 0
    seats_left: int = 0


class ExecutiveAiModuleUsageItem(BaseModel):
    module_name: str
    action_count: int = 0
    latest_action_name: str | None = None
    latest_at: datetime | None = None


class ExecutiveDashboardSummary(BaseModel):
    active_classes: int = 0
    active_students: int = 0
    hot_leads: int = 0
    overdue_follow_ups: int = 0
    high_risk_students: int = 0
    pending_reviews: int = 0
    paid_revenue: float = 0
    pending_revenue: float = 0
    queued_support_cases: int = 0
    processing_support_cases: int = 0
    open_jobs: int = 0
    applicants: int = 0
    scheduled_interviews: int = 0
    ai_actions_last_7_days: int = 0
    average_fill_rate: float = 0


class ExecutiveDashboardSnapshot(BaseModel):
    summary: ExecutiveDashboardSummary
    alerts: list[ExecutiveAlertItem] = Field(default_factory=list)
    hot_leads: list[ConsultantLeadItem] = Field(default_factory=list)
    high_risk_students: list[StudentProgressOverviewItem] = Field(default_factory=list)
    class_watchlist: list[ExecutiveClassWatchItem] = Field(default_factory=list)
    ai_module_usage: list[ExecutiveAiModuleUsageItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    generated_at: datetime


class ProgressModule(BaseModel):
    name: str
    status: Literal["completed", "in_progress", "planned"]
    summary: str


class ProgressSnapshot(BaseModel):
    updated_at: datetime
    completed_modules: int
    total_modules: int
    tests_passing: int
    tracked_files: int
    lines_of_code: int
    modules: list[ProgressModule] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
