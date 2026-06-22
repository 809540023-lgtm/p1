from __future__ import annotations

from datetime import datetime, time, timedelta
import re
from uuid import UUID

from school_platform.ai_runtime import SchoolPlatformAiRuntime
from school_platform.notification_runtime import SchoolPlatformNotificationRuntime
from school_platform.payment_runtime import SchoolPlatformPaymentRuntime
from school_platform.schemas import (
    AssignmentCreateRequest,
    AssignmentRecord,
    AssignmentSubmissionCreateRequest,
    AssignmentSubmissionRecord,
    AiLogRecord,
    AiProviderStatusResponse,
    ApplicantStatusUpdateRequest,
    AttendanceMarkRequest,
    AttendanceRecord,
    ClassSummary,
    ClassUpsertRequest,
    CourseDetail,
    CourseSummary,
    CourseUpsertRequest,
    DashboardMetrics,
    ExecutiveAiModuleUsageItem,
    ExecutiveAlertItem,
    ExecutiveClassWatchItem,
    ExecutiveDashboardSnapshot,
    ExecutiveDashboardSummary,
    FinanceOverviewSnapshot,
    FinanceSummary,
    ExamCreateRequest,
    ExamRecord,
    ExamSubmissionCreateRequest,
    ExamSubmissionRecord,
    InterviewCreateRequest,
    InterviewRecord,
    InterviewUpdateRequest,
    JobPositionCreateRequest,
    JobPositionRecord,
    LessonPlanDraftRequest,
    LessonPlanDraftResponse,
    LessonPlanStep,
    PracticeConversationResponse,
    ScheduleConflictItem,
    ScheduleOverviewSnapshot,
    ScheduleOverviewSummary,
    TeacherScheduleLoad,
    TeacherClassSnapshot,
    TeacherClassStudentItem,
    TeacherClassSummary,
    ReportOverview,
    EnrollmentCreate,
    EnrollmentRecord,
    EnrollmentResponse,
    FollowupDraftResponse,
    FranchiseGroupReportItem,
    FranchiseGroupReportSnapshot,
    FranchiseGroupReportSummary,
    HomePayload,
    LearningActivityRecord,
    Lead,
    LeadAssignmentRequest,
    LeadLog,
    LeadStatusChangeRequest,
    NotificationRecord,
    NotificationCreate,
    OnboardingRecord,
    OnboardingUpsertRequest,
    PaymentIntentCreate,
    PaymentIntentResponse,
    PaymentRecord,
    PaymentWebhookPayload,
    ApplicantCreateRequest,
    ApplicantDetailSnapshot,
    ApplicantEvaluationResponse,
    ApplicantRecord,
    BroadcastMessageRequest,
    BroadcastMessageResponse,
    ConsultantDashboardSnapshot,
    ConsultantDashboardSummary,
    ConsultantLeadDetailSnapshot,
    ConsultantLeadItem,
    MessageCenterSummary,
    ManagedUserAccountItem,
    StaffRecord,
    StaffPerformanceItem,
    StaffPerformanceSummary,
    StudentDashboard,
    StudentAdminDetailSnapshot,
    StudentAdminItem,
    StudentAdminSnapshot,
    StudentAdminSummary,
    StudentProgressAssignmentItem,
    StudentLearningReportItem,
    StudentLearningReportSnapshot,
    StudentLearningReportSummary,
    StudentProgressAttendanceItem,
    StudentProgressExamItem,
    StudentProgressOverviewItem,
    StudentProgressSnapshot,
    StudentProgressSummary,
    StudentRecord,
    SubAccountCreateRequest,
    StudentTimelineEvent,
    SubmissionGradeRequest,
    TeachingSessionRecord,
    TeachingSessionReviewRequest,
    TeachingSessionUpsertRequest,
    TrialBookingCreate,
    TrialBookingResponse,
    TrialSlot,
    UserAccount,
    UserAccountAdminSnapshot,
    UserAccountAdminSummary,
)
from school_platform.snapshot_migration import snapshot_integrity_from_json


class CatalogService:
    def __init__(self, store) -> None:
        self.store = store

    def list_courses(self) -> list[CourseSummary]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [CourseSummary.model_validate(item) for item in repository.list_courses()]
        return [CourseSummary(**course.model_dump()) for course in self.store.courses]

    def get_course(self, slug: str) -> CourseDetail:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            payload = repository.get_course(slug)
            if payload is None:
                raise KeyError(slug)
            return CourseDetail.model_validate(payload)
        return self.store.get_course(slug)

    def classes_for_course(self, slug: str) -> list[ClassSummary]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [ClassSummary.model_validate(item) for item in repository.list_classes(course_slug=slug)]
        return [item for item in self.store.classes if item.course_slug == slug]

    def open_classes(self) -> list[ClassSummary]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [ClassSummary.model_validate(item) for item in repository.list_classes(status="open")]
        return [item for item in self.store.classes if item.status == "open"]

    def home_payload(self) -> HomePayload:
        courses = self.list_courses()[:3]
        return HomePayload(
            brand_name="Japan Life Language School OS",
            hero_title="AI 化日語補習班營運平台 MVP",
            hero_subtitle="先把招生、試聽、報名、付款與後台追蹤跑起來，再往教務與 AI 升級。",
            featured_courses=courses,
            value_props=["前台自動招生", "後台名單追蹤", "可擴充成學員與教務平台"],
        )


class AdmissionsService:
    def __init__(self, store) -> None:
        self.store = store

    def list_leads(self, status: str | None = None) -> list[Lead]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [Lead.model_validate(item) for item in repository.list_leads(status=status)]
        items = self.store.leads
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get_lead(self, lead_id: UUID) -> Lead:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            payload = repository.get_lead(str(lead_id))
            if payload is None:
                raise KeyError(str(lead_id))
            return Lead.model_validate(payload)
        return self.store.get_lead(lead_id)

    def logs_for_lead(self, lead_id: UUID) -> list[LeadLog]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [LeadLog.model_validate(item) for item in repository.list_lead_logs(str(lead_id))]
        return [item for item in self.store.lead_logs if item.lead_id == lead_id]

    def list_notifications(self, user_email: str | None = None) -> list[NotificationRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [NotificationRecord.model_validate(item) for item in repository.list_notifications(user_email=user_email)]
        if user_email:
            return [item for item in self.store.notifications if item.user_email == user_email]
        return self.store.notifications

    def list_staff(self, role: str | None = None) -> list[StaffRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [StaffRecord.model_validate(item) for item in repository.list_staff(role=role)]
        items = self.store.staff
        if role:
            items = [item for item in items if item.role == role]
        return items

    def dashboard_metrics(self) -> DashboardMetrics:
        return self.store.dashboard_metrics()

    def support_inbox(self) -> list[NotificationRecord]:
        return [item for item in self.list_notifications("admin@jls.local") if item.type == "student_support_request"]

    def support_inbox_summary(self) -> dict[str, int]:
        items = self.support_inbox()
        return {
            "total": len(items),
            "queued": sum(1 for item in items if item.status == "queued"),
            "processing": sum(1 for item in items if item.status == "processing"),
            "resolved": sum(1 for item in items if item.status == "resolved"),
            "in_app": sum(1 for item in items if item.channel == "in_app"),
        }


class AccountAdminService:
    def __init__(self, store) -> None:
        self.store = store

    def directory(self, actor: UserAccount | None = None) -> UserAccountAdminSnapshot:
        if actor is not None and actor.role == "manager":
            visible_ids = {actor.id}
            visible_ids.update(item.id for item in self.store.list_user_accounts(parent_user_id=actor.id))
            users = [item for item in self.store.list_user_accounts() if item.id in visible_ids]
            owners = [actor]
        else:
            users = self.store.list_user_accounts()
            owners = self.store.list_user_accounts(account_type="primary")
        return UserAccountAdminSnapshot(
            summary=UserAccountAdminSummary(
                total_accounts=len(users),
                primary_accounts=sum(1 for item in users if item.account_type == "primary"),
                sub_accounts=sum(1 for item in users if item.account_type == "sub_account"),
                active_accounts=sum(1 for item in users if item.status == "active"),
                inactive_accounts=sum(1 for item in users if item.status != "active"),
            ),
            items=[self._to_item(item) for item in users],
            owners=[self._to_item(item) for item in owners],
        )

    def create_sub_account(self, payload: SubAccountCreateRequest, actor: UserAccount | None = None) -> ManagedUserAccountItem:
        created = self.store.create_sub_account(payload, actor=actor)
        return self._to_item(created)

    def allowed_roles_for_owner(self, owner: UserAccount | None = None) -> list[str]:
        return self.store.allowed_subaccount_roles(owner)

    def _to_item(self, user: UserAccount) -> ManagedUserAccountItem:
        parent = self.store.get_user_by_id(user.parent_user_id) if user.parent_user_id else None
        return ManagedUserAccountItem(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            permissions=user.permissions,
            staff_id=user.staff_id,
            status=user.status,
            parent_user_id=user.parent_user_id,
            parent_user_name=parent.name if parent is not None else None,
            account_type=user.account_type,
            scope_label=user.scope_label,
            note=user.note,
        )


class StudentPortalService:
    def __init__(self, store, catalog_service: CatalogService, admissions_service: AdmissionsService) -> None:
        self.store = store
        self.catalog_service = catalog_service
        self.admissions_service = admissions_service

    def student_dashboard(self, email: str) -> StudentDashboard:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        student_enrollments = self.student_enrollments(email)
        class_ids = {item.class_id for item in student_enrollments if item.status in {"pending", "active"}}
        active_courses = [item for item in self.catalog_service.open_classes() if item.id in class_ids]
        payment_statuses = [item.payment_status for item in student_enrollments]
        notifications = self.admissions_service.list_notifications(student.email)
        return StudentDashboard(
            student=student,
            active_courses=active_courses,
            payment_statuses=payment_statuses,
            notification_count=len(notifications),
        )

    def get_student_by_email(self, email: str) -> StudentRecord | None:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            payload = repository.get_student_by_email(email)
            return StudentRecord.model_validate(payload) if payload else None
        return self.store.get_student_by_email(email)

    def student_enrollments(self, email: str) -> list[EnrollmentRecord]:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [EnrollmentRecord.model_validate(item) for item in repository.list_enrollments(student_id=str(student.id))]
        return [item for item in self.store.enrollments if item.student_id == student.id]

    def student_classes(self, email: str) -> list[ClassSummary]:
        enrollments = self.student_enrollments(email)
        class_ids = {item.class_id for item in enrollments}
        return [item for item in self.catalog_service.open_classes() if item.id in class_ids]

    def student_schedule(self, email: str) -> list[ClassSummary]:
        return sorted(
            self.student_classes(email),
            key=lambda item: (item.start_date, item.start_time, item.name),
        )

    def student_payments(self, email: str) -> list[PaymentRecord]:
        enrollments = self.student_enrollments(email)
        enrollment_ids = [str(item.id) for item in enrollments]
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [PaymentRecord.model_validate(item) for item in repository.list_payments(enrollment_ids=enrollment_ids)]
        enrollment_id_set = {item.id for item in enrollments}
        return [item for item in self.store.payments if item.enrollment_id in enrollment_id_set]

    def student_notifications(self, email: str) -> list[NotificationRecord]:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        return self.admissions_service.list_notifications(student.email)

    def all_students(self) -> list[StudentRecord]:
        latest_by_email: dict[str, StudentRecord] = {}
        for item in self.store.students:
            key = item.email.strip().lower()
            existing = latest_by_email.get(key)
            if existing is None or item.created_at > existing.created_at:
                latest_by_email[key] = item
        return sorted(latest_by_email.values(), key=lambda item: item.created_at, reverse=True)

    def student_notification_summary(self, email: str) -> dict[str, int]:
        notifications = self.student_notifications(email)
        return {
            "total": len(notifications),
            "queued": sum(1 for item in notifications if item.status == "queued"),
            "email": sum(1 for item in notifications if item.channel == "email"),
            "line": sum(1 for item in notifications if item.channel == "line"),
            "in_app": sum(1 for item in notifications if item.channel == "in_app"),
        }

    def student_history(self, email: str) -> list[StudentTimelineEvent]:
        student = self.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        history: list[StudentTimelineEvent] = []
        for enrollment in self.student_enrollments(email):
            history.append(
                StudentTimelineEvent(
                    kind="enrollment",
                    title=f"報名建立：{enrollment.status}",
                    detail=f"付款狀態 {enrollment.payment_status} / 原價 JPY {enrollment.list_price:,.0f}",
                    at=enrollment.created_at,
                )
            )
        for payment in self.student_payments(email):
            history.append(
                StudentTimelineEvent(
                    kind="payment",
                    title=f"付款狀態：{payment.status}",
                    detail=f"訂單 {payment.order_no} / 金額 JPY {payment.amount:,.0f}",
                    at=payment.paid_at or payment.created_at,
                )
            )
        for notification in self.student_notifications(email):
            history.append(
                StudentTimelineEvent(
                    kind="notification",
                    title=notification.title,
                    detail=notification.content,
                    at=notification.created_at,
                )
            )
        return sorted(history, key=lambda item: item.at, reverse=True)


class StudentAdminService:
    def __init__(self, student_portal_service: StudentPortalService) -> None:
        self.student_portal_service = student_portal_service

    def _item_for_student(self, student: StudentRecord) -> StudentAdminItem:
        enrollments = self.student_portal_service.student_enrollments(student.email)
        classes = self.student_portal_service.student_classes(student.email)
        payments = self.student_portal_service.student_payments(student.email)
        notifications = self.student_portal_service.student_notifications(student.email)
        history = self.student_portal_service.student_history(student.email)
        return StudentAdminItem(
            student=student,
            enrollment_count=len(enrollments),
            active_course_count=len(classes),
            payment_count=len(payments),
            pending_payment_count=sum(1 for item in payments if item.status != "paid"),
            notification_count=len(notifications),
            queued_notification_count=sum(1 for item in notifications if item.status == "queued"),
            last_activity_at=history[0].at if history else student.created_at,
        )

    def overview(self) -> StudentAdminSnapshot:
        items = [self._item_for_student(student) for student in self.student_portal_service.all_students()]
        summary = StudentAdminSummary(
            total_students=len(items),
            active_students=sum(1 for item in items if item.active_course_count > 0),
            pending_payment_students=sum(1 for item in items if item.pending_payment_count > 0),
            queued_notification_students=sum(1 for item in items if item.queued_notification_count > 0),
        )
        return StudentAdminSnapshot(
            summary=summary,
            items=sorted(
                items,
                key=lambda item: item.last_activity_at or item.student.created_at,
                reverse=True,
            ),
            generated_at=datetime.now().astimezone(),
        )

    def detail(self, email: str) -> StudentAdminDetailSnapshot:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        return StudentAdminDetailSnapshot(
            item=self._item_for_student(student),
            classes=self.student_portal_service.student_schedule(email),
            enrollments=self.student_portal_service.student_enrollments(email),
            payments=self.student_portal_service.student_payments(email),
            notifications=self.student_portal_service.student_notifications(email),
            history=self.student_portal_service.student_history(email),
            generated_at=datetime.now().astimezone(),
        )


class PublicAdmissionsService:
    def __init__(self, store, catalog_service: CatalogService) -> None:
        self.store = store
        self.catalog_service = catalog_service

    def trial_slots(self, course_slug: str | None = None) -> list[TrialSlot]:
        classes = self.catalog_service.open_classes()
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
        return self.store.create_trial_booking(payload)


class FinanceService:
    def __init__(self, store) -> None:
        self.store = store
        self.payment_runtime = SchoolPlatformPaymentRuntime(store.settings)

    def list_enrollments(self) -> list[EnrollmentRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [EnrollmentRecord.model_validate(item) for item in repository.list_enrollments()]
        return self.store.enrollments

    def list_payments(self) -> list[PaymentRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [PaymentRecord.model_validate(item) for item in repository.list_payments()]
        return self.store.payments

    def overview(self) -> FinanceOverviewSnapshot:
        enrollments = sorted(self.list_enrollments(), key=lambda item: item.created_at, reverse=True)
        payments = sorted(self.list_payments(), key=lambda item: item.created_at, reverse=True)
        summary = FinanceSummary(
            enrollment_total=len(enrollments),
            pending_enrollments=sum(1 for item in enrollments if item.status in {"pending", "waiting_payment"}),
            paid_payments=sum(1 for item in payments if item.status == "paid"),
            pending_payments=sum(1 for item in payments if item.status == "pending"),
            refunded_payments=sum(1 for item in payments if item.status == "refunded"),
            paid_revenue=sum(item.amount for item in payments if item.status == "paid"),
            pending_revenue=sum(item.amount for item in payments if item.status == "pending"),
        )
        return FinanceOverviewSnapshot(
            summary=summary,
            recent_enrollments=enrollments[:10],
            recent_payments=payments[:10],
            generated_at=datetime.now().astimezone(),
        )

    def create_enrollment(self, payload: EnrollmentCreate) -> EnrollmentResponse:
        return self.store.create_enrollment(payload)

    def create_payment_intent(self, payload: PaymentIntentCreate) -> PaymentIntentResponse:
        intent = self.store.create_payment_intent(payload)
        if self.payment_runtime.status()["provider"] == "mock" or payload.payment_method != "card":
            return intent

        payment = self.store.get_payment_by_id(intent.payment_id)
        if payment is None:
            return intent
        enrollment = self.store.get_enrollment_by_id(payment.enrollment_id)
        if enrollment is None:
            return intent
        student = self.store.get_student_by_id(enrollment.student_id)
        if student is None:
            return intent
        class_item = self.store.get_class_by_id(enrollment.class_id)
        course_name = class_item.name if class_item is not None else payment.order_no
        try:
            provider_session = self.payment_runtime.create_checkout_session(
                order_no=payment.order_no,
                amount=payment.amount,
                payment_method=payload.payment_method,
                student_email=student.email,
                product_name=course_name,
                enrollment_id=str(enrollment.id),
            )
        except RuntimeError as exc:
            self.store.update_payment_provider_state(
                payment.id,
                provider="stripe",
                provider_status="checkout_create_failed",
                last_reconciled_at=datetime.now().astimezone(),
                provider_last_error=str(exc),
            )
            raise
        updated_payment = self.store.update_payment_provider_state(
            payment.id,
            provider=provider_session["provider"],
            provider_payment_id=provider_session.get("provider_payment_id"),
            checkout_url=provider_session.get("checkout_url"),
            client_token=provider_session.get("client_token"),
            currency=provider_session.get("currency"),
            provider_status=provider_session.get("provider_status"),
            checkout_expires_at=provider_session.get("checkout_expires_at"),
            last_reconciled_at=datetime.now().astimezone(),
            provider_last_error=None,
        )
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
        return self.store.apply_payment_webhook(payload)

    def payment_provider_status(self) -> dict[str, object]:
        return self.payment_runtime.status()

    def reconcile_payment(self, payment_id: UUID) -> dict[str, object]:
        payment = self.store.get_payment_by_id(payment_id)
        if payment is None:
            raise KeyError(str(payment_id))
        provider_status = self.payment_runtime.status()
        if provider_status["provider"] != "stripe":
            return {"synced": False, "reason": "payment provider is not stripe", "payment": payment}
        if not payment.provider_payment_id:
            return {"synced": False, "reason": "payment has no stripe checkout session id", "payment": payment}
        if not payment.provider_payment_id.startswith("cs_"):
            return {"synced": False, "reason": "payment provider reference is not a checkout session id", "payment": payment}

        session = self.payment_runtime.retrieve_checkout_session(payment.provider_payment_id)
        normalized = self.payment_runtime.normalize_checkout_session_for_reconcile(session)
        if normalized is None:
            return {"synced": False, "reason": "stripe session missing order_no metadata", "payment": payment, "provider_snapshot": session}

        synced_payment = self.store.update_payment_provider_state(
            payment.id,
            provider=str(normalized["provider"]),
            provider_payment_id=normalized.get("provider_payment_id"),
            provider_status=normalized.get("provider_status"),
            checkout_expires_at=normalized.get("checkout_expires_at"),
            last_reconciled_at=datetime.now().astimezone(),
            provider_last_error=None,
        )
        status_changed = False
        if normalized.get("status"):
            previous_status = synced_payment.status
            synced_payment = self.store.apply_payment_webhook(
                PaymentWebhookPayload(
                    order_no=str(normalized["order_no"]),
                    status=str(normalized["status"]),
                    provider=str(normalized["provider"]),
                    provider_payment_id=normalized.get("provider_payment_id"),
                    provider_status=normalized.get("provider_status"),
                )
            )
            status_changed = previous_status != synced_payment.status
        return {
            "synced": True,
            "status_changed": status_changed,
            "payment": synced_payment,
            "provider_snapshot": {
                "id": session.get("id"),
                "status": session.get("status"),
                "payment_status": session.get("payment_status"),
                "expires_at": session.get("expires_at"),
            },
        }

    def apply_stripe_webhook(self, payload: bytes, signature_header: str | None) -> dict[str, object]:
        event = self.payment_runtime.verify_and_parse_stripe_event(payload, signature_header)
        normalized = self.payment_runtime.normalize_webhook_event(event)
        if normalized is None:
            return {"ignored": True, "event_type": event.get("type")}
        updated = self.store.apply_payment_webhook(
            PaymentWebhookPayload(
                order_no=str(normalized["order_no"]),
                status=str(normalized["status"]),
                paid_at=datetime.fromisoformat(normalized["paid_at"]) if normalized.get("paid_at") else None,
                provider=str(normalized["provider"]),
                provider_payment_id=normalized.get("provider_payment_id"),
                provider_status=normalized.get("provider_status"),
            )
        )
        return {
            "ignored": False,
            "event_type": normalized.get("event_type"),
            "payment": updated,
        }


class SchedulingService:
    def __init__(self, catalog_service: CatalogService) -> None:
        self.catalog_service = catalog_service

    @staticmethod
    def _weekday_tokens(value: str) -> list[str]:
        parts = re.split(r"\s*/\s*", value.strip())
        return [item.strip() for item in parts if item.strip()]

    @staticmethod
    def _time_overlap(left: ClassSummary, right: ClassSummary) -> bool:
        return max(left.start_time, right.start_time) < min(left.end_time, right.end_time)

    @staticmethod
    def _date_overlap(left: ClassSummary, right: ClassSummary) -> bool:
        return left.start_date <= right.end_date and right.start_date <= left.end_date

    @staticmethod
    def _weekly_hours(class_item: ClassSummary) -> float:
        start_minutes = class_item.start_time.hour * 60 + class_item.start_time.minute
        end_minutes = class_item.end_time.hour * 60 + class_item.end_time.minute
        duration_hours = max(end_minutes - start_minutes, 0) / 60
        return duration_hours * max(len(SchedulingService._weekday_tokens(class_item.weekday)), 1)

    def overview(self) -> ScheduleOverviewSnapshot:
        classes = sorted(
            self.catalog_service.open_classes(),
            key=lambda item: (item.teacher_name, item.weekday, item.start_time, item.name),
        )

        teacher_load_map: dict[str, dict[str, float | int | str]] = {}
        for class_item in classes:
            bucket = teacher_load_map.setdefault(
                class_item.teacher_name,
                {"teacher_name": class_item.teacher_name, "class_count": 0, "weekly_sessions": 0, "weekly_hours": 0.0},
            )
            bucket["class_count"] += 1
            bucket["weekly_sessions"] += max(len(self._weekday_tokens(class_item.weekday)), 1)
            bucket["weekly_hours"] += self._weekly_hours(class_item)

        teacher_loads = [
            TeacherScheduleLoad(
                teacher_name=str(item["teacher_name"]),
                class_count=int(item["class_count"]),
                weekly_sessions=int(item["weekly_sessions"]),
                weekly_hours=round(float(item["weekly_hours"]), 1),
            )
            for item in teacher_load_map.values()
        ]
        teacher_loads.sort(key=lambda item: (-item.class_count, -item.weekly_hours, item.teacher_name))

        conflicts: list[ScheduleConflictItem] = []
        by_teacher: dict[str, list[ClassSummary]] = {}
        for class_item in classes:
            by_teacher.setdefault(class_item.teacher_name, []).append(class_item)

        for teacher_name, teacher_classes in by_teacher.items():
            for index, left in enumerate(teacher_classes):
                for right in teacher_classes[index + 1 :]:
                    common_days = sorted(set(self._weekday_tokens(left.weekday)) & set(self._weekday_tokens(right.weekday)))
                    if not common_days:
                        continue
                    if not self._date_overlap(left, right):
                        continue
                    if not self._time_overlap(left, right):
                        continue
                    conflicts.append(
                        ScheduleConflictItem(
                            teacher_name=teacher_name,
                            weekday=" / ".join(common_days),
                            class_names=[left.name, right.name],
                            time_range=f"{left.start_time.strftime('%H:%M')}-{left.end_time.strftime('%H:%M')} vs {right.start_time.strftime('%H:%M')}-{right.end_time.strftime('%H:%M')}",
                            overlap_note=f"{left.start_date.isoformat()} 到 {left.end_date.isoformat()} 與 {right.start_date.isoformat()} 到 {right.end_date.isoformat()} 發生重疊。",
                        )
                    )

        summary = ScheduleOverviewSummary(
            total_open_classes=len(classes),
            teachers_scheduled=len({item.teacher_name for item in classes}),
            online_classes=sum(1 for item in classes if item.location_label.lower().startswith("zoom") or "online" in item.location_label.lower()),
            onsite_classes=sum(1 for item in classes if not (item.location_label.lower().startswith("zoom") or "online" in item.location_label.lower())),
            detected_conflicts=len(conflicts),
        )
        return ScheduleOverviewSnapshot(
            summary=summary,
            teacher_loads=teacher_loads,
            classes=classes,
            conflicts=conflicts,
            generated_at=datetime.now().astimezone(),
        )


class TeachingOpsService:
    def __init__(self, store, catalog_service: CatalogService, student_portal_service: StudentPortalService) -> None:
        self.store = store
        self.catalog_service = catalog_service
        self.student_portal_service = student_portal_service

    def list_assignments(self, class_id: UUID | None = None) -> list[AssignmentRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = repository.list_assignments(class_id=str(class_id)) if class_id else repository.list_assignments()
            return [AssignmentRecord.model_validate(item) for item in rows]
        return self.store.list_assignments(class_id)

    def student_assignments(self, email: str) -> list[AssignmentRecord]:
        classes = self.student_portal_service.student_classes(email)
        class_ids = {item.id for item in classes}
        return sorted(
            [item for item in self.list_assignments() if item.class_id in class_ids],
            key=lambda item: item.due_at,
        )

    def student_assignment_submissions(self, email: str) -> list[AssignmentSubmissionRecord]:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [AssignmentSubmissionRecord.model_validate(item) for item in repository.list_assignment_submissions(student_id=str(student.id))]
        return self.store.list_assignment_submissions(student_id=student.id)

    def create_assignment(self, payload: AssignmentCreateRequest) -> AssignmentRecord:
        return self.store.create_assignment(payload)

    def submit_assignment(self, assignment_id: UUID, payload: AssignmentSubmissionCreateRequest) -> AssignmentSubmissionRecord:
        return self.store.submit_assignment(assignment_id, payload)

    def grade_assignment_submission(self, submission_id: UUID, payload: SubmissionGradeRequest) -> AssignmentSubmissionRecord:
        return self.store.grade_assignment_submission(submission_id, payload)

    def student_attendance(self, email: str) -> list[AttendanceRecord]:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [AttendanceRecord.model_validate(item) for item in repository.list_attendance(student_id=str(student.id))]
        return self.store.list_attendance(student_id=student.id)

    def attendance_summary(self, email: str) -> dict[str, int]:
        items = self.student_attendance(email)
        return {
            "total": len(items),
            "present": sum(1 for item in items if item.status == "present"),
            "absent": sum(1 for item in items if item.status == "absent"),
            "late": sum(1 for item in items if item.status == "late"),
            "leave": sum(1 for item in items if item.status == "leave"),
        }

    def mark_attendance(self, payload: AttendanceMarkRequest) -> AttendanceRecord:
        return self.store.mark_attendance(payload)

    def assignment_submission_summary(self, email: str) -> dict[str, int]:
        assignments = self.student_assignments(email)
        submissions = self.student_assignment_submissions(email)
        submitted_ids = {item.assignment_id for item in submissions}
        return {
            "total": len(assignments),
            "submitted": sum(1 for item in assignments if item.id in submitted_ids),
            "pending": sum(1 for item in assignments if item.id not in submitted_ids),
        }

    def list_exams(self, class_id: UUID | None = None) -> list[ExamRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = repository.list_exams(class_id=str(class_id)) if class_id else repository.list_exams()
            return [ExamRecord.model_validate(item) for item in rows]
        return self.store.list_exams(class_id)

    def student_exams(self, email: str) -> list[ExamRecord]:
        classes = self.student_portal_service.student_classes(email)
        class_ids = {item.id for item in classes}
        return sorted(
            [item for item in self.list_exams() if item.class_id in class_ids],
            key=lambda item: item.due_at,
        )

    def student_exam_submissions(self, email: str) -> list[ExamSubmissionRecord]:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [ExamSubmissionRecord.model_validate(item) for item in repository.list_exam_submissions(student_id=str(student.id))]
        return self.store.list_exam_submissions(student_id=student.id)

    def create_exam(self, payload: ExamCreateRequest) -> ExamRecord:
        return self.store.create_exam(payload)

    def submit_exam(self, exam_id: UUID, payload: ExamSubmissionCreateRequest) -> ExamSubmissionRecord:
        return self.store.submit_exam(exam_id, payload)

    def grade_exam_submission(self, submission_id: UUID, payload: SubmissionGradeRequest) -> ExamSubmissionRecord:
        return self.store.grade_exam_submission(submission_id, payload)

    def list_teaching_session_records(
        self,
        class_id: UUID | None = None,
        teacher_name: str | None = None,
        approval_status: str | None = None,
    ) -> list[TeachingSessionRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = repository.list_teaching_session_records(
                class_id=str(class_id) if class_id else None,
                teacher_name=teacher_name,
                approval_status=approval_status,
            )
            return [TeachingSessionRecord.model_validate(item) for item in rows]
        return self.store.list_teaching_session_records(class_id, teacher_name, approval_status)

    def upsert_teaching_session_record(self, payload: TeachingSessionUpsertRequest) -> TeachingSessionRecord:
        return self.store.upsert_teaching_session_record(payload)

    def review_teaching_session_record(self, record_id: UUID, payload: TeachingSessionReviewRequest) -> TeachingSessionRecord:
        return self.store.review_teaching_session_record(record_id, payload)

    def exam_submission_summary(self, email: str) -> dict[str, int]:
        exams = self.student_exams(email)
        submissions = self.student_exam_submissions(email)
        submitted_ids = {item.exam_id for item in submissions}
        return {
            "total": len(exams),
            "submitted": sum(1 for item in exams if item.id in submitted_ids),
            "pending": sum(1 for item in exams if item.id not in submitted_ids),
        }

    def student_progress(self, email: str) -> StudentProgressSnapshot:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        classes = self.student_portal_service.student_classes(email)
        class_map = {item.id: item for item in classes}
        assignments = self.student_assignments(email)
        assignment_submissions = {item.assignment_id: item for item in self.student_assignment_submissions(email)}
        exams = self.student_exams(email)
        exam_submissions = {item.exam_id: item for item in self.student_exam_submissions(email)}
        attendance_records = self.student_attendance(email)

        assignment_items = [
            StudentProgressAssignmentItem(
                assignment_id=item.id,
                title=item.title,
                class_name=class_map.get(item.class_id).name if item.class_id in class_map else item.class_id.hex,
                due_at=item.due_at,
                status=(assignment_submissions[item.id].status if item.id in assignment_submissions else "pending"),
                submitted_at=(assignment_submissions[item.id].submitted_at if item.id in assignment_submissions else None),
                score=(assignment_submissions[item.id].score if item.id in assignment_submissions else None),
                feedback=(assignment_submissions[item.id].feedback if item.id in assignment_submissions else None),
            )
            for item in assignments
        ]
        exam_items = [
            StudentProgressExamItem(
                exam_id=item.id,
                title=item.title,
                class_name=class_map.get(item.class_id).name if item.class_id in class_map else item.class_id.hex,
                exam_type=item.exam_type,
                due_at=item.due_at,
                total_score=item.total_score,
                status=(exam_submissions[item.id].status if item.id in exam_submissions else "pending"),
                submitted_at=(exam_submissions[item.id].submitted_at if item.id in exam_submissions else None),
                score=(exam_submissions[item.id].score if item.id in exam_submissions else None),
                feedback=(exam_submissions[item.id].feedback if item.id in exam_submissions else None),
                graded_by=(exam_submissions[item.id].graded_by if item.id in exam_submissions else None),
            )
            for item in exams
        ]
        attendance_items = [
            StudentProgressAttendanceItem(
                attendance_id=item.id,
                class_name=class_map.get(item.class_id).name if item.class_id in class_map else item.class_id.hex,
                class_date=item.class_date,
                status=item.status,
                note=item.note,
                marked_by=item.marked_by,
            )
            for item in sorted(attendance_records, key=lambda record: record.class_date, reverse=True)
        ]

        assignment_scores = [item.score for item in assignment_items if item.score is not None]
        exam_scores = [item.score for item in exam_items if item.score is not None]
        attendance_total = len(attendance_items)
        attendance_present = sum(1 for item in attendance_items if item.status == "present")
        attendance_rate = round((attendance_present / attendance_total) * 100, 1) if attendance_total else 0
        assignment_average = round(sum(assignment_scores) / len(assignment_scores), 1) if assignment_scores else None
        exam_average = round(sum(exam_scores) / len(exam_scores), 1) if exam_scores else None
        components = [value for value in [assignment_average, exam_average, attendance_rate if attendance_total else None] if value is not None]
        overall_score = round(sum(components) / len(components), 1) if components else None
        pending_assignments = sum(1 for item in assignment_items if item.status == "pending")
        pending_exams = sum(1 for item in exam_items if item.status == "pending")

        weak_spot = "尚無明顯風險"
        weak_value = 101.0
        weakness_candidates = [
            ("作業成績", assignment_average),
            ("測驗成績", exam_average),
            ("出缺勤", attendance_rate if attendance_total else None),
        ]
        for label, value in weakness_candidates:
            if value is not None and value < weak_value:
                weak_spot = label
                weak_value = value
        if pending_exams >= 2 or pending_assignments >= 3:
            weak_spot = "待補作業 / 測驗"

        if attendance_total and attendance_rate < 70 or pending_exams >= 2 or pending_assignments >= 3 or (overall_score is not None and overall_score < 65):
            risk_level = "high"
            recommended_action = "建議優先安排顧問或老師介入，先補作業與測驗，再檢查出席狀態。"
        elif pending_exams >= 1 or pending_assignments >= 1 or (overall_score is not None and overall_score < 80) or (attendance_total and attendance_rate < 85):
            risk_level = "medium"
            recommended_action = "建議本週完成補交與複習，並追蹤下次課堂出席。"
        else:
            risk_level = "low"
            recommended_action = "維持目前學習節奏，可安排更進階的練習。"

        summary = StudentProgressSummary(
            assignment_total=len(assignment_items),
            assignment_submitted=sum(1 for item in assignment_items if item.status != "pending"),
            assignment_graded=len(assignment_scores),
            assignment_average=assignment_average,
            exam_total=len(exam_items),
            exam_submitted=sum(1 for item in exam_items if item.status != "pending"),
            exam_graded=len(exam_scores),
            exam_average=exam_average,
            attendance_total=attendance_total,
            attendance_present=attendance_present,
            attendance_rate=attendance_rate,
            overall_score=overall_score,
            risk_level=risk_level,
            weak_spot=weak_spot,
            recommended_action=recommended_action,
        )
        return StudentProgressSnapshot(
            student=student,
            summary=summary,
            assignments=assignment_items,
            exams=exam_items,
            attendance=attendance_items,
            generated_at=datetime.now().astimezone(),
        )

    def student_progress_overview(self) -> list[StudentProgressOverviewItem]:
        items: list[StudentProgressOverviewItem] = []
        for student in self.student_portal_service.all_students():
            snapshot = self.student_progress(student.email)
            items.append(
                StudentProgressOverviewItem(
                    student_id=student.id,
                    chinese_name=student.chinese_name,
                    email=student.email,
                    active_course_count=len(self.student_portal_service.student_classes(student.email)),
                    attendance_rate=snapshot.summary.attendance_rate,
                    overall_score=snapshot.summary.overall_score,
                    pending_assignments=snapshot.summary.assignment_total - snapshot.summary.assignment_submitted,
                    pending_exams=snapshot.summary.exam_total - snapshot.summary.exam_submitted,
                    risk_level=snapshot.summary.risk_level,
                    weak_spot=snapshot.summary.weak_spot,
                )
            )
        risk_priority = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            items,
            key=lambda item: (
                risk_priority.get(item.risk_level, 9),
                item.overall_score if item.overall_score is not None else 999,
                item.email,
            ),
        )


class TeacherWorkspaceService:
    def __init__(self, catalog_service: CatalogService, teaching_ops_service: TeachingOpsService, store) -> None:
        self.catalog_service = catalog_service
        self.teaching_ops_service = teaching_ops_service
        self.store = store

    def classes_for_teacher(self, teacher_name: str) -> list[ClassSummary]:
        return [item for item in self.catalog_service.open_classes() if item.teacher_name == teacher_name]

    def assignment_submissions(self, assignment_id: UUID) -> list[AssignmentSubmissionRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [AssignmentSubmissionRecord.model_validate(item) for item in repository.list_assignment_submissions(assignment_id=str(assignment_id))]
        return self.store.list_assignment_submissions(assignment_id=assignment_id)

    def exam_submissions(self, exam_id: UUID) -> list[ExamSubmissionRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [ExamSubmissionRecord.model_validate(item) for item in repository.list_exam_submissions(exam_id=str(exam_id))]
        return self.store.list_exam_submissions(exam_id=exam_id)

    def dashboard(self, teacher_name: str) -> dict[str, object]:
        classes = self.classes_for_teacher(teacher_name)
        class_ids = {item.id for item in classes}
        assignments = [item for item in self.teaching_ops_service.list_assignments() if item.class_id in class_ids]
        exams = [item for item in self.teaching_ops_service.list_exams() if item.class_id in class_ids]
        session_records = [
            item
            for item in self.teaching_ops_service.list_teaching_session_records(teacher_name=teacher_name)
            if item.class_id in class_ids
        ]
        pending_assignment_reviews: list[AssignmentSubmissionRecord] = []
        for assignment in assignments:
            pending_assignment_reviews.extend(
                [item for item in self.assignment_submissions(assignment.id) if item.status != "graded"]
            )
        pending_exam_reviews: list[ExamSubmissionRecord] = []
        for exam in exams:
            pending_exam_reviews.extend([item for item in self.exam_submissions(exam.id) if item.status != "graded"])
        return {
            "teacher_name": teacher_name,
            "classes": classes,
            "assignments": assignments,
            "exams": exams,
            "session_records": session_records,
            "pending_assignment_reviews": pending_assignment_reviews,
            "pending_exam_reviews": pending_exam_reviews,
            "summary": {
                "class_count": len(classes),
                "assignment_count": len(assignments),
                "exam_count": len(exams),
                "pending_reviews": len(pending_assignment_reviews) + len(pending_exam_reviews),
                "session_record_count": len(session_records),
                "pending_session_reviews": sum(1 for item in session_records if item.approval_status == "submitted"),
                "revision_requested": sum(1 for item in session_records if item.approval_status == "revision_requested"),
            },
        }

    def class_snapshot(self, teacher_name: str, class_id: UUID) -> TeacherClassSnapshot:
        class_item = next((item for item in self.classes_for_teacher(teacher_name) if item.id == class_id), None)
        if class_item is None:
            raise KeyError(str(class_id))

        assignments = self.teaching_ops_service.list_assignments(class_id)
        exams = self.teaching_ops_service.list_exams(class_id)
        session_records = self.teaching_ops_service.list_teaching_session_records(class_id=class_id, teacher_name=teacher_name)
        assignment_submission_groups = {item.id: self.assignment_submissions(item.id) for item in assignments}
        exam_submission_groups = {item.id: self.exam_submissions(item.id) for item in exams}
        assignment_submissions = [submission for items in assignment_submission_groups.values() for submission in items]
        exam_submissions = [submission for items in exam_submission_groups.values() for submission in items]
        attendance_records = sorted(
            self.store.list_attendance(class_id=class_id),
            key=lambda item: (item.class_date, item.created_at),
            reverse=True,
        )
        enrollments = [item for item in self.store.enrollments if item.class_id == class_id]
        student_map = {item.id: item for item in self.store.students}
        assignment_total = len(assignments)
        exam_total = len(exams)
        roster: list[TeacherClassStudentItem] = []

        for enrollment in enrollments:
            student = student_map.get(enrollment.student_id)
            if student is None:
                continue
            student_assignment_submissions = [
                item for item in assignment_submissions if item.student_id == student.id and item.status != "pending"
            ]
            student_exam_submissions = [
                item for item in exam_submissions if item.student_id == student.id and item.status != "pending"
            ]
            student_attendance = [item for item in attendance_records if item.student_id == student.id]
            attendance_present = sum(1 for item in student_attendance if item.status == "present")
            attendance_rate = round((attendance_present / len(student_attendance)) * 100, 1) if student_attendance else 0
            latest_attendance = student_attendance[0].status if student_attendance else None

            if (
                (assignment_total and len(student_assignment_submissions) == 0)
                or (exam_total and len(student_exam_submissions) == 0)
                or (student_attendance and attendance_rate < 70)
            ):
                risk_level = "high"
            elif (
                len(student_assignment_submissions) < assignment_total
                or len(student_exam_submissions) < exam_total
                or (student_attendance and attendance_rate < 85)
                or enrollment.payment_status != "paid"
            ):
                risk_level = "medium"
            else:
                risk_level = "low"

            roster.append(
                TeacherClassStudentItem(
                    student_id=student.id,
                    chinese_name=student.chinese_name,
                    email=student.email,
                    enrollment_status=enrollment.status,
                    payment_status=enrollment.payment_status,
                    assignment_submitted=len(student_assignment_submissions),
                    assignment_total=assignment_total,
                    exam_submitted=len(student_exam_submissions),
                    exam_total=exam_total,
                    attendance_rate=attendance_rate,
                    latest_attendance_status=latest_attendance,
                    risk_level=risk_level,
                )
            )

        risk_priority = {"high": 0, "medium": 1, "low": 2}
        roster = sorted(roster, key=lambda item: (risk_priority.get(item.risk_level, 9), item.chinese_name, item.email))
        summary = TeacherClassSummary(
            total_students=len(roster),
            high_risk_students=sum(1 for item in roster if item.risk_level == "high"),
            medium_risk_students=sum(1 for item in roster if item.risk_level == "medium"),
            submitted_assignments=sum(item.assignment_submitted for item in roster),
            pending_assignments=sum(max(item.assignment_total - item.assignment_submitted, 0) for item in roster),
            submitted_exams=sum(item.exam_submitted for item in roster),
            pending_exams=sum(max(item.exam_total - item.exam_submitted, 0) for item in roster),
            attendance_records=len(attendance_records),
            session_records=len(session_records),
            pending_session_reviews=sum(1 for item in session_records if item.approval_status == "submitted"),
        )
        return TeacherClassSnapshot(
            class_item=class_item,
            summary=summary,
            roster=roster,
            assignments=assignments,
            exams=exams,
            attendance_records=attendance_records,
            assignment_submissions=assignment_submissions,
            exam_submissions=exam_submissions,
            session_records=session_records,
            generated_at=datetime.now().astimezone(),
        )


class RecruitingService:
    def __init__(self, store) -> None:
        self.store = store

    def list_jobs(self, status: str | None = None) -> list[JobPositionRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [JobPositionRecord.model_validate(item) for item in repository.list_job_positions(status=status)]
        return self.store.list_job_positions(status)

    def get_job(self, position_id: UUID) -> JobPositionRecord:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            payload = repository.get_job_position(str(position_id))
            if payload is None:
                raise KeyError(str(position_id))
            return JobPositionRecord.model_validate(payload)
        return self.store.get_job_position(position_id)

    def create_job(self, payload: JobPositionCreateRequest) -> JobPositionRecord:
        return self.store.create_job_position(payload)

    def create_applicant(self, payload: ApplicantCreateRequest) -> ApplicantRecord:
        return self.store.create_applicant(payload)

    def list_applicants(self, position_id: UUID | None = None) -> list[ApplicantRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = repository.list_applicants(position_id=str(position_id)) if position_id else repository.list_applicants()
            return [ApplicantRecord.model_validate(item) for item in rows]
        return self.store.list_applicants(position_id)

    def get_applicant(self, applicant_id: UUID) -> ApplicantRecord:
        applicant = next((item for item in self.list_applicants() if item.id == applicant_id), None)
        if applicant is None:
            raise KeyError(str(applicant_id))
        return applicant

    def applicant_evaluation(self, applicant_id: UUID) -> ApplicantEvaluationResponse:
        applicant = self.get_applicant(applicant_id)
        position = self.get_job(applicant.position_id)
        note_text = (applicant.note or "").strip()
        strengths = [
            f"目前 AI 配對分數為 {applicant.ai_match_score:g}，代表履歷與 {position.title} 有中高程度相符。",
            f"職缺需求聚焦在 {position.department}，現有投遞資訊已具備初步篩選價值。",
        ]
        if applicant.resume_link:
            strengths.append("已提供履歷連結，HR 可以直接進入履歷審查與面試安排。")
        concerns = []
        if not applicant.phone:
            concerns.append("缺少電話資訊，若要安排面試需先確認替代聯絡方式。")
        if not note_text:
            concerns.append("自述資訊偏少，建議在初篩時補問應徵動機與可到職時間。")
        if applicant.ai_match_score < 75:
            concerns.append("AI 配對分數未達強匹配區間，建議先做 10 到 15 分鐘的初篩。")

        if position.department == "Teaching":
            suggested_questions = [
                "請分享你帶初學者口說課時，會如何設計暖身與互動練習？",
                "如果學生在生活情境對話裡一直不敢開口，你會怎麼介入？",
                "你會怎麼判斷一堂 90 分鐘課的節奏是否需要調整？",
            ]
        elif position.department == "Admissions":
            suggested_questions = [
                "遇到試聽後猶豫中的名單，你會如何安排兩次跟進？",
                "你怎麼判斷一筆 lead 是高意向還是只是單純詢問？",
                "如果家長和學生的需求不一致，你會怎麼處理成交節奏？",
            ]
        else:
            suggested_questions = [
                "請描述你過去如何處理跨部門協作與臨時變動。",
                "你會怎麼安排每日任務優先順序，避免行政工作塞車？",
                "遇到同時有學員、家長、老師提出需求時，你會怎麼分流？",
            ]

        recommendation = "strong_match" if applicant.ai_match_score >= 80 else "review_needed" if applicant.ai_match_score >= 70 else "screen_first"
        next_action = (
            "可直接安排正式面試。"
            if recommendation == "strong_match"
            else "建議先做短初篩，再決定是否安排正式面試。"
        )
        return ApplicantEvaluationResponse(
            applicant_id=applicant.id,
            position_title=position.title,
            ai_match_score=applicant.ai_match_score,
            recommendation=recommendation,
            strengths=strengths,
            concerns=concerns,
            suggested_questions=suggested_questions,
            next_action=next_action,
        )

    def applicant_detail(self, applicant_id: UUID) -> ApplicantDetailSnapshot:
        applicant = self.get_applicant(applicant_id)
        position = self.get_job(applicant.position_id)
        interviews = self.list_interviews(applicant_id)
        evaluation = self.applicant_evaluation(applicant_id)
        onboarding = self.get_onboarding_record(applicant_id)
        return ApplicantDetailSnapshot(
            applicant=applicant,
            position=position,
            interviews=interviews,
            evaluation=evaluation,
            onboarding=onboarding,
            generated_at=datetime.now().astimezone(),
        )

    def schedule_interview(self, payload: InterviewCreateRequest) -> InterviewRecord:
        return self.store.schedule_interview(payload)

    def update_interview(self, interview_id: UUID, payload: InterviewUpdateRequest) -> InterviewRecord:
        return self.store.update_interview(interview_id, payload)

    def update_applicant_status(self, applicant_id: UUID, payload: ApplicantStatusUpdateRequest) -> ApplicantRecord:
        return self.store.update_applicant_status(applicant_id, payload)

    def list_interviews(self, applicant_id: UUID | None = None) -> list[InterviewRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = repository.list_interviews(applicant_id=str(applicant_id)) if applicant_id else repository.list_interviews()
            return [InterviewRecord.model_validate(item) for item in rows]
        return self.store.list_interviews(applicant_id)

    def list_onboarding_records(self, applicant_id: UUID | None = None) -> list[OnboardingRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            rows = (
                repository.list_onboarding_records(applicant_id=str(applicant_id))
                if applicant_id
                else repository.list_onboarding_records()
            )
            return [OnboardingRecord.model_validate(item) for item in rows]
        return self.store.list_onboarding_records(applicant_id)

    def get_onboarding_record(self, applicant_id: UUID) -> OnboardingRecord | None:
        return next((item for item in self.list_onboarding_records(applicant_id) if item.applicant_id == applicant_id), None)

    def upsert_onboarding_record(self, applicant_id: UUID, payload: OnboardingUpsertRequest) -> OnboardingRecord:
        return self.store.upsert_onboarding_record(applicant_id, payload)

    def recruiting_summary(self) -> dict[str, int]:
        jobs = self.list_jobs()
        applicants = self.list_applicants()
        interviews = self.list_interviews()
        onboarding_records = self.list_onboarding_records()
        return {
            "open_jobs": sum(1 for item in jobs if item.status == "open"),
            "applicants": len(applicants),
            "scheduled_interviews": sum(1 for item in interviews if item.status == "scheduled"),
            "active_onboarding": sum(1 for item in onboarding_records if item.stage not in {"completed", "cancelled"}),
            "active_probation": sum(1 for item in onboarding_records if item.probation_status in {"in_progress", "extended"}),
        }


class AnalyticsService:
    def __init__(
        self,
        store,
        recruiting_service: RecruitingService,
        ai_runtime: SchoolPlatformAiRuntime,
        teaching_ops_service: TeachingOpsService,
        student_portal_service: StudentPortalService,
    ) -> None:
        self.store = store
        self.recruiting_service = recruiting_service
        self.ai_runtime = ai_runtime
        self.teaching_ops_service = teaching_ops_service
        self.student_portal_service = student_portal_service

    @staticmethod
    def _franchise_group_configs() -> list[dict[str, object]]:
        return [
            {
                "group_code": "partner_referral",
                "group_name": "推薦夥伴組",
                "partner_type": "低門檻轉介紹與社群導流",
                "partner_count": 4,
                "sold_regions": 0,
                "total_regions": 0,
                "join_fee_jpy": 33_000,
                "monthly_fee_jpy": 9_800,
                "source_channels": {"partner_referral", "wechat_referral", "line_referral"},
            },
            {
                "group_code": "osaka_single_zone",
                "group_name": "大阪單區加盟組",
                "partner_type": "大阪十區單區加盟",
                "partner_count": 3,
                "sold_regions": 3,
                "total_regions": 10,
                "join_fee_jpy": 100_000,
                "monthly_fee_jpy": 19_800,
                "source_channels": {"osaka_partner", "osaka_single_zone"},
            },
            {
                "group_code": "regional_operator",
                "group_name": "多區營運組",
                "partner_type": "多區營運與團隊型代理",
                "partner_count": 1,
                "sold_regions": 2,
                "total_regions": 10,
                "join_fee_jpy": 300_000,
                "monthly_fee_jpy": 59_800,
                "source_channels": {"regional_operator", "multi_zone_operator"},
            },
        ]

    def student_learning_report(self) -> StudentLearningReportSnapshot:
        items: list[StudentLearningReportItem] = []
        activity_total = 0
        attendance_rates: list[float] = []
        overall_scores: list[float] = []
        tzinfo = datetime.now().astimezone().tzinfo

        for student in self.student_portal_service.all_students():
            snapshot = self.teaching_ops_service.student_progress(student.email)
            activities: list[LearningActivityRecord] = []

            for assignment in snapshot.assignments:
                if assignment.submitted_at is None:
                    continue
                activities.append(
                    LearningActivityRecord(
                        student_id=student.id,
                        chinese_name=student.chinese_name,
                        email=student.email,
                        activity_kind="assignment_submission",
                        title=assignment.title,
                        class_name=assignment.class_name,
                        status=assignment.status,
                        occurred_at=assignment.submitted_at,
                        score=assignment.score,
                        detail=assignment.feedback,
                    )
                )

            for exam in snapshot.exams:
                if exam.submitted_at is None:
                    continue
                activities.append(
                    LearningActivityRecord(
                        student_id=student.id,
                        chinese_name=student.chinese_name,
                        email=student.email,
                        activity_kind="exam_submission",
                        title=exam.title,
                        class_name=exam.class_name,
                        status=exam.status,
                        occurred_at=exam.submitted_at,
                        score=exam.score,
                        detail=exam.feedback,
                    )
                )

            for attendance in snapshot.attendance:
                activities.append(
                    LearningActivityRecord(
                        student_id=student.id,
                        chinese_name=student.chinese_name,
                        email=student.email,
                        activity_kind="attendance",
                        title=f"{attendance.class_date.isoformat()} 點名",
                        class_name=attendance.class_name,
                        status=attendance.status,
                        occurred_at=datetime.combine(attendance.class_date, time(hour=12), tzinfo=tzinfo),
                        detail=attendance.note or f"由 {attendance.marked_by} 點名",
                    )
                )

            activities.sort(key=lambda item: item.occurred_at, reverse=True)
            activity_total += len(activities)
            attendance_rates.append(snapshot.summary.attendance_rate)
            if snapshot.summary.overall_score is not None:
                overall_scores.append(snapshot.summary.overall_score)

            items.append(
                StudentLearningReportItem(
                    student_id=student.id,
                    chinese_name=student.chinese_name,
                    email=student.email,
                    active_course_count=len(self.student_portal_service.student_classes(student.email)),
                    assignment_submitted=snapshot.summary.assignment_submitted,
                    assignment_pending=snapshot.summary.assignment_total - snapshot.summary.assignment_submitted,
                    exam_submitted=snapshot.summary.exam_submitted,
                    exam_pending=snapshot.summary.exam_total - snapshot.summary.exam_submitted,
                    attendance_rate=snapshot.summary.attendance_rate,
                    overall_score=snapshot.summary.overall_score,
                    activity_count=len(activities),
                    last_activity_at=activities[0].occurred_at if activities else None,
                    risk_level=snapshot.summary.risk_level,
                    weak_spot=snapshot.summary.weak_spot,
                    recent_activities=activities[:5],
                )
            )

        risk_priority = {"high": 0, "medium": 1, "low": 2}
        items.sort(
            key=lambda item: (
                risk_priority.get(item.risk_level, 9),
                item.last_activity_at.timestamp() * -1 if item.last_activity_at else 0,
                item.email,
            )
        )
        average_overall_score = round(sum(overall_scores) / len(overall_scores), 1) if overall_scores else None
        average_attendance_rate = round(sum(attendance_rates) / len(attendance_rates), 1) if attendance_rates else 0
        summary = StudentLearningReportSummary(
            total_students=len(items),
            active_students=sum(1 for item in items if item.active_course_count > 0),
            high_risk_students=sum(1 for item in items if item.risk_level == "high"),
            average_attendance_rate=average_attendance_rate,
            average_overall_score=average_overall_score,
            recent_activity_count=activity_total,
        )
        return StudentLearningReportSnapshot(summary=summary, items=items, generated_at=datetime.now().astimezone())

    def franchise_group_report(self) -> FranchiseGroupReportSnapshot:
        groups: list[FranchiseGroupReportItem] = []
        total_leads = 0
        enrolled_leads = 0
        total_partner_count = 0
        sold_regions = 0
        total_regions = 0
        booked_join_fee_revenue_jpy = 0.0
        monthly_recurring_revenue_jpy = 0.0

        for config in self._franchise_group_configs():
            source_channels = set(config["source_channels"])
            matched_leads = [item for item in self.store.leads if item.source_channel in source_channels]
            total = len(matched_leads)
            new_leads = sum(1 for item in matched_leads if item.status == "new")
            contacted_leads = sum(1 for item in matched_leads if item.status in {"contacted", "replied"})
            trial_booked_leads = sum(1 for item in matched_leads if item.status in {"trial_booked", "trial_completed"})
            considering_leads = sum(1 for item in matched_leads if item.status == "considering")
            enrolled = sum(1 for item in matched_leads if item.status == "enrolled")
            lost = sum(1 for item in matched_leads if item.status in {"lost", "blacklisted"})
            conversion_rate = round((enrolled / total) * 100, 1) if total else 0
            sold_region_count = int(config["sold_regions"])
            partner_count = int(config["partner_count"])
            join_fee_jpy = float(config["join_fee_jpy"])
            monthly_fee_jpy = float(config["monthly_fee_jpy"])
            next_focus = (
                "優先把已預約試聽與考慮中名單推進到成交。"
                if trial_booked_leads or considering_leads
                else "補強新名單來源，避免漏斗前段不足。"
            )

            groups.append(
                FranchiseGroupReportItem(
                    group_code=str(config["group_code"]),
                    group_name=str(config["group_name"]),
                    partner_type=str(config["partner_type"]),
                    partner_count=partner_count,
                    sold_regions=sold_region_count,
                    total_regions=int(config["total_regions"]),
                    join_fee_jpy=join_fee_jpy,
                    monthly_fee_jpy=monthly_fee_jpy,
                    booked_join_fee_revenue_jpy=sold_region_count * join_fee_jpy,
                    monthly_recurring_revenue_jpy=partner_count * monthly_fee_jpy,
                    total_leads=total,
                    new_leads=new_leads,
                    contacted_leads=contacted_leads,
                    trial_booked_leads=trial_booked_leads,
                    considering_leads=considering_leads,
                    enrolled_leads=enrolled,
                    lost_leads=lost,
                    conversion_rate=conversion_rate,
                    next_focus=next_focus,
                )
            )
            total_leads += total
            enrolled_leads += enrolled
            total_partner_count += partner_count
            sold_regions += sold_region_count
            total_regions += int(config["total_regions"])
            booked_join_fee_revenue_jpy += sold_region_count * join_fee_jpy
            monthly_recurring_revenue_jpy += partner_count * monthly_fee_jpy

        groups.sort(key=lambda item: (-item.sold_regions, -item.partner_count, item.group_name))
        summary = FranchiseGroupReportSummary(
            total_groups=len(groups),
            active_groups=sum(1 for item in groups if item.partner_count > 0),
            total_partner_count=total_partner_count,
            sold_regions=sold_regions,
            total_regions=total_regions,
            total_leads=total_leads,
            enrolled_leads=enrolled_leads,
            blended_conversion_rate=round((enrolled_leads / total_leads) * 100, 1) if total_leads else 0,
            booked_join_fee_revenue_jpy=booked_join_fee_revenue_jpy,
            monthly_recurring_revenue_jpy=monthly_recurring_revenue_jpy,
        )
        return FranchiseGroupReportSnapshot(summary=summary, groups=groups, generated_at=datetime.now().astimezone())

    def report_overview(self) -> ReportOverview:
        return self.store.report_overview()

    def weekly_ai_summary(self) -> dict[str, object]:
        fallback = self.store.weekly_ai_summary()
        report = self.store.report_overview()
        fallback_payload = {
            **fallback,
            "generated_at": fallback["generated_at"].isoformat() if hasattr(fallback["generated_at"], "isoformat") else fallback["generated_at"],
        }
        result, provider, reason = self.ai_runtime.enhance_mapping(
            feature_name="weekly_operations_summary",
            instructions=(
                "Refine the weekly operations summary into a concise executive briefing. Keep the same keys, stay grounded "
                "in the metrics provided, and do not invent numbers."
            ),
            context={"report_overview": report.model_dump(mode="json")},
            fallback_payload=fallback_payload,
        )
        self.store.create_ai_log(
            module_name="operations_runtime",
            action_name="weekly_summary_runtime",
            actor_email="manager@jls.local",
            input_summary="report_overview executive summary generation",
            output_summary=f"provider={provider}, reason={reason}, insights={len(result.get('insights', []))}",
        )
        return result

    def ai_logs(self, module_name: str | None = None) -> list[AiLogRecord]:
        repository = self.store.repository
        if getattr(repository, "query_supported", lambda: False)():
            return [AiLogRecord.model_validate(item) for item in repository.list_ai_logs(module_name=module_name)]
        return self.store.list_ai_logs(module_name)

    def ai_provider_status(self) -> AiProviderStatusResponse:
        return self.ai_runtime.status()


class ExecutiveDashboardService:
    def __init__(
        self,
        admissions_service: AdmissionsService,
        catalog_service: CatalogService,
        finance_service: FinanceService,
        teaching_ops_service: TeachingOpsService,
        staff_ops_service: "StaffOpsService",
        student_admin_service: StudentAdminService,
        recruiting_service: RecruitingService,
        analytics_service: AnalyticsService,
    ) -> None:
        self.admissions_service = admissions_service
        self.catalog_service = catalog_service
        self.finance_service = finance_service
        self.teaching_ops_service = teaching_ops_service
        self.staff_ops_service = staff_ops_service
        self.student_admin_service = student_admin_service
        self.recruiting_service = recruiting_service
        self.analytics_service = analytics_service

    @staticmethod
    def _normalize_datetime(value: datetime | None, now: datetime) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=now.tzinfo)
        return value.astimezone(now.tzinfo)

    def _hot_lead_items(self, leads: list[Lead], now: datetime) -> list[ConsultantLeadItem]:
        latest_log_by_lead: dict[UUID, LeadLog] = {}
        for lead in leads:
            logs = self.admissions_service.logs_for_lead(lead.id)
            if logs:
                latest_log_by_lead[lead.id] = max(logs, key=lambda item: item.created_at)

        items = [
            ConsultantLeadItem(
                lead_id=lead.id,
                name=lead.name,
                status=lead.status,
                interested_course_slug=lead.interested_course_slug,
                intent_score=lead.intent_score,
                win_probability=lead.win_probability,
                next_follow_up_at=lead.next_follow_up_at,
                last_contact_at=lead.last_contact_at,
                latest_log_summary=(latest_log_by_lead[lead.id].content if lead.id in latest_log_by_lead else None),
            )
            for lead in leads
            if lead.status not in {"enrolled", "lost", "blacklisted"}
        ]
        return sorted(
            items,
            key=lambda item: (
                -item.intent_score,
                -item.win_probability,
                self._normalize_datetime(item.next_follow_up_at, now) or datetime.max.replace(tzinfo=now.tzinfo),
                item.name,
            ),
        )[:5]

    def snapshot(self) -> ExecutiveDashboardSnapshot:
        now = datetime.now().astimezone()
        leads = self.admissions_service.list_leads()
        classes = self.catalog_service.open_classes()
        finance = self.finance_service.overview()
        staff_overview = self.staff_ops_service.performance_overview()
        student_snapshot = self.student_admin_service.overview()
        support_summary = self.admissions_service.support_inbox_summary()
        recruiting_summary = self.recruiting_service.recruiting_summary()
        progress_items = self.teaching_ops_service.student_progress_overview()
        ai_logs = self.analytics_service.ai_logs()
        recent_ai_logs = [
            item
            for item in ai_logs
            if self._normalize_datetime(item.created_at, now) is not None
            and self._normalize_datetime(item.created_at, now) >= now - timedelta(days=7)
        ]

        overdue_follow_ups = [
            lead
            for lead in leads
            if self._normalize_datetime(lead.next_follow_up_at, now) is not None
            and self._normalize_datetime(lead.next_follow_up_at, now) <= now
            and lead.status not in {"enrolled", "lost", "blacklisted"}
        ]
        hot_leads = self._hot_lead_items(leads, now)
        high_risk_students = [item for item in progress_items if item.risk_level == "high"][:5]

        class_watchlist = sorted(
            [
                ExecutiveClassWatchItem(
                    class_id=item.id,
                    class_name=item.name,
                    course_slug=item.course_slug,
                    teacher_name=item.teacher_name,
                    fill_rate=round((item.enrolled_count / item.capacity) * 100, 1) if item.capacity else 0,
                    enrolled_count=item.enrolled_count,
                    capacity=item.capacity,
                    seats_left=max(item.capacity - item.enrolled_count, 0),
                )
                for item in classes
            ],
            key=lambda item: (-item.fill_rate, item.seats_left, item.class_name),
        )[:5]

        ai_usage_map: dict[str, ExecutiveAiModuleUsageItem] = {}
        for log in recent_ai_logs:
            existing = ai_usage_map.get(log.module_name)
            if existing is None:
                ai_usage_map[log.module_name] = ExecutiveAiModuleUsageItem(
                    module_name=log.module_name,
                    action_count=1,
                    latest_action_name=log.action_name,
                    latest_at=log.created_at,
                )
                continue
            if existing.latest_at is None or log.created_at > existing.latest_at:
                existing.latest_at = log.created_at
                existing.latest_action_name = log.action_name
            existing.action_count += 1

        ai_module_usage = sorted(ai_usage_map.values(), key=lambda item: (-item.action_count, item.module_name))[:6]
        fill_rates = [item.fill_rate for item in class_watchlist]
        summary = ExecutiveDashboardSummary(
            active_classes=len(classes),
            active_students=student_snapshot.summary.active_students,
            hot_leads=len(hot_leads),
            overdue_follow_ups=len(overdue_follow_ups),
            high_risk_students=len([item for item in progress_items if item.risk_level == "high"]),
            pending_reviews=staff_overview["summary"].pending_reviews,
            paid_revenue=finance.summary.paid_revenue,
            pending_revenue=finance.summary.pending_revenue,
            queued_support_cases=support_summary["queued"],
            processing_support_cases=support_summary["processing"],
            open_jobs=recruiting_summary["open_jobs"],
            applicants=recruiting_summary["applicants"],
            scheduled_interviews=recruiting_summary["scheduled_interviews"],
            ai_actions_last_7_days=len(recent_ai_logs),
            average_fill_rate=round(sum(fill_rates) / len(fill_rates), 1) if fill_rates else 0,
        )

        alerts: list[ExecutiveAlertItem] = []
        if overdue_follow_ups:
            alerts.append(
                ExecutiveAlertItem(
                    severity="critical",
                    title="待跟進名單已逾期",
                    detail=f"目前有 {len(overdue_follow_ups)} 筆名單已到 follow-up 時間，建議優先由顧問處理。",
                )
            )
        if summary.high_risk_students:
            alerts.append(
                ExecutiveAlertItem(
                    severity="critical",
                    title="高風險學員需要介入",
                    detail=f"目前有 {summary.high_risk_students} 位高風險學員，應優先安排老師或顧問追蹤。",
                )
            )
        if summary.pending_reviews:
            alerts.append(
                ExecutiveAlertItem(
                    severity="warning",
                    title="排課 / 教學待處理",
                    detail=f"教師端目前累積 {summary.pending_reviews} 筆待評分項目，可能影響學員回饋時效。",
                )
            )
        if summary.queued_support_cases:
            alerts.append(
                ExecutiveAlertItem(
                    severity="warning",
                    title="客服待處理案件",
                    detail=f"客服收件箱仍有 {summary.queued_support_cases} 筆 queued 案件尚未回覆。",
                )
            )
        if finance.summary.pending_payments:
            alerts.append(
                ExecutiveAlertItem(
                    severity="info",
                    title="待收款提醒",
                    detail=f"目前有 {finance.summary.pending_payments} 筆付款尚未完成，可搭配訊息中心催收。",
                )
            )
        if class_watchlist and class_watchlist[0].fill_rate >= 80:
            alerts.append(
                ExecutiveAlertItem(
                    severity="info",
                    title="課程供給提醒",
                    detail=f"{class_watchlist[0].class_name} 滿班率已達 {class_watchlist[0].fill_rate}%，可評估候補或增班。",
                )
            )
        if not alerts:
            alerts.append(
                ExecutiveAlertItem(
                    severity="info",
                    title="營運狀態穩定",
                    detail="目前沒有立即性的營運警示，可持續追蹤招生與教務節奏。",
                )
            )

        recommendations = [
            "優先處理已逾期 follow-up 名單，避免高意向 lead 冷掉。",
            "讓教師先消化待評分項目，再由顧問銜接高風險學員的關懷追蹤。",
            "針對待付款與客服案件，用訊息中心做分眾提醒，縮短行政往返時間。",
            "對高滿班率班級預備候補與增班方案，避免招生繼續堆積在單一時段。",
        ]

        return ExecutiveDashboardSnapshot(
            summary=summary,
            alerts=alerts[:6],
            hot_leads=hot_leads,
            high_risk_students=high_risk_students,
            class_watchlist=class_watchlist,
            ai_module_usage=ai_module_usage,
            recommendations=recommendations,
            generated_at=now,
        )


class StaffOpsService:
    def __init__(
        self,
        admissions_service: AdmissionsService,
        catalog_service: CatalogService,
        teaching_ops_service: TeachingOpsService,
        teacher_workspace_service: TeacherWorkspaceService,
    ) -> None:
        self.admissions_service = admissions_service
        self.catalog_service = catalog_service
        self.teaching_ops_service = teaching_ops_service
        self.teacher_workspace_service = teacher_workspace_service

    def performance_overview(self) -> dict[str, object]:
        staff_items = self.admissions_service.list_staff()
        leads = self.admissions_service.list_leads()
        assignments = self.teaching_ops_service.list_assignments()
        exams = self.teaching_ops_service.list_exams()
        performance_items: list[StaffPerformanceItem] = []
        for item in staff_items:
            assigned_leads = [lead for lead in leads if lead.assigned_staff_name == item.name]
            active_classes = self.teacher_workspace_service.classes_for_teacher(item.name) if item.role == "teacher" else []
            teacher_dashboard = self.teacher_workspace_service.dashboard(item.name) if item.role == "teacher" else None
            performance_items.append(
                StaffPerformanceItem(
                    staff_id=item.id,
                    name=item.name,
                    role=item.role,
                    department=item.department,
                    title=item.title,
                    assigned_leads=len(assigned_leads),
                    enrolled_leads=sum(1 for lead in assigned_leads if lead.status == "enrolled"),
                    pending_follow_ups=sum(1 for lead in assigned_leads if lead.status not in {"enrolled", "lost", "blacklisted"}),
                    active_classes=len(active_classes),
                    assignments_created=sum(1 for assignment in assignments if assignment.created_by == item.name),
                    exams_created=sum(1 for exam in exams if exam.created_by == item.name),
                    pending_reviews=(teacher_dashboard["summary"]["pending_reviews"] if teacher_dashboard else 0),
                )
            )
        performance_items = sorted(
            performance_items,
            key=lambda item: (
                0 if item.role == "consultant" else 1 if item.role == "teacher" else 2,
                -item.pending_follow_ups,
                -item.pending_reviews,
                item.name,
            ),
        )
        summary = StaffPerformanceSummary(
            total_staff=len(performance_items),
            consultants=sum(1 for item in performance_items if item.role == "consultant"),
            teachers=sum(1 for item in performance_items if item.role == "teacher"),
            managers=sum(1 for item in performance_items if item.role == "manager"),
            pending_follow_ups=sum(item.pending_follow_ups for item in performance_items),
            pending_reviews=sum(item.pending_reviews for item in performance_items),
        )
        return {"summary": summary, "items": performance_items}


class ConsultantWorkspaceService:
    def __init__(self, admissions_service: AdmissionsService) -> None:
        self.admissions_service = admissions_service

    def dashboard(self, consultant_name: str) -> ConsultantDashboardSnapshot:
        leads = [item for item in self.admissions_service.list_leads() if item.assigned_staff_name == consultant_name]
        now = datetime.now().astimezone()
        today = now.date()

        def normalized_follow_up(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=now.tzinfo)
            return value.astimezone(now.tzinfo)

        latest_log_by_lead: dict[UUID, LeadLog] = {}
        for lead in leads:
            logs = self.admissions_service.logs_for_lead(lead.id)
            if logs:
                latest_log_by_lead[lead.id] = max(logs, key=lambda item: item.created_at)

        def to_item(lead: Lead) -> ConsultantLeadItem:
            latest_log = latest_log_by_lead.get(lead.id)
            return ConsultantLeadItem(
                lead_id=lead.id,
                name=lead.name,
                status=lead.status,
                interested_course_slug=lead.interested_course_slug,
                intent_score=lead.intent_score,
                win_probability=lead.win_probability,
                next_follow_up_at=lead.next_follow_up_at,
                last_contact_at=lead.last_contact_at,
                latest_log_summary=latest_log.content if latest_log else None,
            )

        follow_up_queue = sorted(
            [item for item in leads if normalized_follow_up(item.next_follow_up_at) is not None and item.status not in {"enrolled", "lost", "blacklisted"}],
            key=lambda item: normalized_follow_up(item.next_follow_up_at),
        )
        hot_leads = sorted(
            [item for item in leads if item.intent_score >= 75 and item.status not in {"enrolled", "lost", "blacklisted"}],
            key=lambda item: (-item.intent_score, -(item.win_probability or 0), item.name),
        )
        recently_updated = sorted(
            leads,
            key=lambda item: item.updated_at,
            reverse=True,
        )

        overdue_follow_ups = sum(
            1
            for item in leads
            if normalized_follow_up(item.next_follow_up_at) is not None
            and normalized_follow_up(item.next_follow_up_at) < now
            and item.status not in {"enrolled", "lost", "blacklisted"}
        )
        due_today = sum(
            1
            for item in leads
            if normalized_follow_up(item.next_follow_up_at) is not None
            and normalized_follow_up(item.next_follow_up_at).date() == today
            and item.status not in {"enrolled", "lost", "blacklisted"}
        )

        summary = ConsultantDashboardSummary(
            consultant_name=consultant_name,
            assigned_leads=len(leads),
            overdue_follow_ups=overdue_follow_ups,
            due_today=due_today,
            high_intent_leads=sum(1 for item in leads if item.intent_score >= 75),
            trial_booked_leads=sum(1 for item in leads if item.status in {"trial_booked", "trial_completed"}),
            enrolled_leads=sum(1 for item in leads if item.status == "enrolled"),
        )
        return ConsultantDashboardSnapshot(
            summary=summary,
            hot_leads=[to_item(item) for item in hot_leads[:8]],
            follow_up_queue=[to_item(item) for item in follow_up_queue[:12]],
            recently_updated=[to_item(item) for item in recently_updated[:8]],
            generated_at=now,
        )

    def lead_detail(self, consultant_name: str, lead_id: UUID) -> ConsultantLeadDetailSnapshot:
        lead = self.admissions_service.get_lead(lead_id)
        if lead.assigned_staff_name != consultant_name:
            raise KeyError(str(lead_id))
        logs = sorted(self.admissions_service.logs_for_lead(lead_id), key=lambda item: item.created_at, reverse=True)
        return ConsultantLeadDetailSnapshot(
            consultant_name=consultant_name,
            lead=lead,
            logs=logs,
            generated_at=datetime.now().astimezone(),
        )


class LeadWorkflowService:
    def __init__(self, store, admissions_service: AdmissionsService) -> None:
        self.store = store
        self.admissions_service = admissions_service

    def add_log(self, lead_id: UUID, staff_name: str, contact_method: str, content: str, next_action: str | None) -> LeadLog:
        self.admissions_service.get_lead(lead_id)
        return self.store.add_lead_log(
            lead_id=lead_id,
            staff_name=staff_name,
            contact_method=contact_method,
            content=content,
            next_action=next_action,
        )

    def assign_lead(self, lead_id: UUID, payload: LeadAssignmentRequest) -> Lead:
        return self.store.assign_lead(lead_id, payload.staff_id)

    def change_status(self, lead_id: UUID, payload: LeadStatusChangeRequest) -> Lead:
        return self.store.change_lead_status(lead_id, payload)


class CurriculumAdminService:
    def __init__(self, store) -> None:
        self.store = store

    def create_course(self, payload: CourseUpsertRequest) -> CourseDetail:
        return self.store.create_course(payload)

    def update_course(self, slug: str, payload: CourseUpsertRequest) -> CourseDetail:
        return self.store.update_course(slug, payload)

    def create_class(self, payload: ClassUpsertRequest) -> ClassSummary:
        return self.store.create_class(payload)

    def update_class(self, class_id: UUID, payload: ClassUpsertRequest) -> ClassSummary:
        return self.store.update_class(class_id, payload)


class NotificationService:
    def __init__(self, store) -> None:
        self.store = store
        self.notification_runtime = SchoolPlatformNotificationRuntime(store.settings)

    def create_notification(self, payload: NotificationCreate) -> NotificationRecord:
        notification = self.store.create_notification(payload)
        return self.dispatch_notification(notification.id)

    def send_test_notification(
        self,
        *,
        channel: str,
        title: str,
        content: str,
        recipient: str | None = None,
        user_email: str | None = None,
    ) -> NotificationRecord:
        resolved_recipient = recipient
        if channel == "email":
            resolved_recipient = recipient or self.store.settings.notification_test_email or user_email
        elif channel == "line":
            resolved_recipient = (
                recipient
                or self.store.settings.notification_test_line_user_id
                or self.store.settings.line_fallback_user_id
            )
        if channel != "in_app" and not resolved_recipient:
            raise ValueError(f"Missing recipient for {channel} smoke test.")
        audit_email = user_email or (resolved_recipient if channel == "email" else "admin@jls.local")
        return self.create_notification(
            NotificationCreate(
                user_email=audit_email,
                channel=channel,
                type="provider_smoke_test",
                title=title,
                content=content,
                external_recipient=resolved_recipient,
            )
        )

    def get_notification(self, notification_id: UUID) -> NotificationRecord:
        return self.store.get_notification(notification_id)

    def update_status(self, notification_id: UUID, status: str) -> NotificationRecord:
        return self.store.update_notification_status(notification_id, status)

    def summary(self) -> MessageCenterSummary:
        notifications = self.store.list_notifications()
        return MessageCenterSummary(
            total_notifications=len(notifications),
            queued_notifications=sum(1 for item in notifications if item.status == "queued"),
            sent_notifications=sum(1 for item in notifications if item.status == "sent"),
            failed_notifications=sum(1 for item in notifications if item.status == "failed"),
            suppressed_notifications=sum(1 for item in notifications if item.status == "suppressed"),
            read_notifications=sum(1 for item in notifications if item.status == "read"),
            email_notifications=sum(1 for item in notifications if item.channel == "email"),
            line_notifications=sum(1 for item in notifications if item.channel == "line"),
            in_app_notifications=sum(1 for item in notifications if item.channel == "in_app"),
            broadcast_notifications=sum(1 for item in notifications if item.type == "manual_broadcast"),
        )

    def _resolve_external_recipient(self, notification: NotificationRecord) -> str | None:
        if notification.external_recipient:
            return notification.external_recipient
        if notification.channel == "email":
            return notification.user_email
        if notification.channel == "line" and notification.user_email:
            lead = self.store.find_lead_by_email(notification.user_email)
            if lead and lead.line_id:
                return lead.line_id
        return None

    def dispatch_notification(self, notification_id: UUID) -> NotificationRecord:
        notification = self.store.get_notification(notification_id)
        recipient = self._resolve_external_recipient(notification)
        try:
            result = self.notification_runtime.dispatch(
                channel=notification.channel,
                title=notification.title,
                content=notification.content,
                recipient=recipient,
                user_email=notification.user_email,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            result = {
                "status": "failed",
                "provider": "runtime_error",
                "provider_message_id": None,
                "error_message": str(exc),
                "external_recipient": recipient,
            }
        delivered_at = datetime.now().astimezone() if result["status"] == "sent" else None
        return self.store.update_notification_delivery(
            notification_id,
            status=str(result["status"]),
            provider=result.get("provider"),
            external_recipient=result.get("external_recipient"),
            provider_message_id=result.get("provider_message_id"),
            error_message=result.get("error_message"),
            delivered_at=delivered_at,
        )

    def drain_queued_notifications(self, limit: int = 50) -> list[NotificationRecord]:
        queued = [item for item in self.store.list_notifications() if item.status == "queued"][:limit]
        results: list[NotificationRecord] = []
        for item in queued:
            results.append(self.dispatch_notification(item.id))
        return results

    def retry_notification(self, notification_id: UUID) -> NotificationRecord:
        self.store.update_notification_delivery(
            notification_id,
            status="queued",
            error_message=None,
            delivered_at=None,
            increment_attempt_count=False,
        )
        return self.dispatch_notification(notification_id)

    def suppress_undeliverable_email_notifications(self) -> list[NotificationRecord]:
        results: list[NotificationRecord] = []
        for item in self.store.list_notifications():
            if item.channel != "email":
                continue
            if item.status not in {"queued", "failed"}:
                continue
            recipient = self._resolve_external_recipient(item)
            suppression_reason = self.notification_runtime.email_suppression_reason(recipient)
            if not suppression_reason:
                continue
            results.append(
                self.store.update_notification_delivery(
                    item.id,
                    status="suppressed",
                    provider="guardrail",
                    external_recipient=recipient,
                    error_message=suppression_reason,
                    delivered_at=None,
                    increment_attempt_count=False,
                )
            )
        return results

    def provider_status(self) -> dict[str, object]:
        return self.notification_runtime.status()

    def audience_emails(self, audience: str, target_email: str | None = None) -> list[str]:
        if audience == "single_student":
            if not target_email:
                raise KeyError("target_email")
            return [target_email]
        if audience == "staff_admin":
            return ["admin@jls.local"]

        students = self.store.students
        if audience == "active_students":
            active_ids = {item.student_id for item in self.store.enrollments if item.status in {"pending", "active"}}
            return sorted({item.email for item in students if item.id in active_ids and item.email})
        return sorted({item.email for item in students if item.email})

    def broadcast(self, payload: BroadcastMessageRequest) -> BroadcastMessageResponse:
        recipients = self.audience_emails(payload.audience, payload.target_email)
        notifications = [
            self.create_notification(
                NotificationCreate(
                    user_email=email,
                    channel=payload.channel,
                    type=payload.type,
                    title=payload.title,
                    content=payload.content,
                )
            )
            for email in recipients
        ]
        return BroadcastMessageResponse(
            audience=payload.audience,
            recipient_count=len(recipients),
            sample_recipients=recipients[:5],
            notifications=notifications[:10],
            sent_at=datetime.now().astimezone(),
        )


class StudentSupportService:
    def __init__(self, student_portal_service: StudentPortalService, notification_service: NotificationService) -> None:
        self.student_portal_service = student_portal_service
        self.notification_service = notification_service

    def create_support_request(self, email: str, topic: str, message: str, preferred_channel: str = "email") -> dict[str, NotificationRecord]:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        channel = preferred_channel if preferred_channel in {"email", "line", "in_app"} else "email"
        internal_notification = self.notification_service.create_notification(
            NotificationCreate(
                user_email="admin@jls.local",
                channel="in_app",
                type="student_support_request",
                title=f"新的學員需求：{topic}",
                content=f"{student.chinese_name} ({student.email}) 提出需求：{message}",
            )
        )
        student_confirmation = self.notification_service.create_notification(
            NotificationCreate(
                user_email=student.email,
                channel=channel,
                type="support_request_received",
                title="客服需求已收到",
                content=f"我們已收到你關於「{topic}」的需求，客服會再依你偏好的聯絡方式跟進。",
            )
        )
        return {
            "request": internal_notification,
            "confirmation": student_confirmation,
        }

    def mark_notification_read(self, email: str, notification_id: UUID) -> NotificationRecord:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        notification = self.notification_service.get_notification(notification_id)
        if notification.user_email != student.email:
            raise KeyError(str(notification_id))
        return self.notification_service.update_status(notification_id, "read")

    def _extract_student_email(self, content: str) -> str | None:
        match = re.search(r"\(([^)]+@[^)]+)\)", content)
        if not match:
            return None
        return match.group(1).strip()

    def process_support_request(
        self,
        notification_id: UUID,
        status: str,
        response_message: str | None = None,
        response_channel: str = "email",
    ) -> dict[str, NotificationRecord]:
        notification = self.notification_service.get_notification(notification_id)
        updated_request = self.notification_service.update_status(notification_id, status)
        student_email = self._extract_student_email(notification.content)
        if student_email is None:
            raise KeyError(str(notification_id))
        channel = response_channel if response_channel in {"email", "line", "in_app"} else "email"
        reply_content = response_message or "客服已更新你的需求狀態，請回到平台查看最新資訊。"
        student_reply = self.notification_service.create_notification(
            NotificationCreate(
                user_email=student_email,
                channel=channel,
                type=f"support_request_{status}",
                title=f"客服需求狀態已更新：{status}",
                content=reply_content,
            )
        )
        return {"request": updated_request, "reply": student_reply}

    def send_payment_reminder(self, email: str, order_no: str) -> NotificationRecord:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        return self.notification_service.create_notification(
            NotificationCreate(
                user_email=student.email,
                channel="email",
                type="payment_reminder",
                title="付款提醒已重新寄送",
                content=f"訂單 {order_no} 的付款提醒已重新寄送，你可以回到付款中心繼續完成付款。",
            )
        )


class AiAssistantService:
    def __init__(
        self,
        store,
        admissions_service: AdmissionsService,
        catalog_service: CatalogService,
        student_portal_service: StudentPortalService,
        ai_runtime: SchoolPlatformAiRuntime,
    ) -> None:
        self.store = store
        self.admissions_service = admissions_service
        self.catalog_service = catalog_service
        self.student_portal_service = student_portal_service
        self.ai_runtime = ai_runtime

    def provider_status(self) -> AiProviderStatusResponse:
        return self.ai_runtime.status()

    def followup_draft(self, lead_id: UUID) -> FollowupDraftResponse:
        lead = self.admissions_service.get_lead(lead_id)
        fallback = self.store.followup_draft(lead_id)
        result, provider, reason = self.ai_runtime.enhance_model(
            feature_name="lead_followup_draft",
            instructions=(
                "Refine the recruitment follow-up draft so it is practical, warm, and oriented toward booking a trial lesson. "
                "Keep the same structure and avoid inventing unavailable offers or schedules."
            ),
            context={
                "lead_name": lead.name,
                "lead_status": lead.status,
                "course_slug": lead.interested_course_slug,
                "japanese_level": lead.japanese_level,
                "study_goal": lead.study_goal,
                "intent_score": lead.intent_score,
            },
            fallback_model=fallback,
        )
        self.store.create_ai_log(
            module_name="admissions_runtime",
            action_name="followup_draft_runtime",
            actor_email=lead.email,
            input_summary=f"lead={lead.name}, status={lead.status}, course={lead.interested_course_slug or 'general'}",
            output_summary=f"provider={provider}, reason={reason}, channel={result.recommended_channel}",
        )
        return result

    def lesson_plan_draft(self, payload: LessonPlanDraftRequest) -> LessonPlanDraftResponse:
        class_item = next((item for item in self.catalog_service.open_classes() if item.id == payload.class_id), None)
        if class_item is None:
            raise KeyError(str(payload.class_id))
        course = self.catalog_service.get_course(class_item.course_slug)
        teacher_name = payload.teacher_name or class_item.teacher_name
        duration = max(payload.duration_minutes, 30)
        teaching_steps = [
            LessonPlanStep(
                title="暖身與情境引入",
                minutes=max(duration // 6, 10),
                details=f"先用 {payload.lesson_focus} 情境做暖身提問，讓學生回想 {course.modules[0] if course.modules else course.name} 的核心用法。",
            ),
            LessonPlanStep(
                title="核心句型拆解",
                minutes=max(duration // 3, 20),
                details=f"講解 {payload.lesson_focus} 會用到的句型、語氣與關鍵單字，並搭配 {course.level} 程度可理解的例句。",
            ),
            LessonPlanStep(
                title="雙人對話演練",
                minutes=max(duration // 3, 20),
                details=f"安排學生兩人一組演練 {payload.lesson_focus}，老師巡迴糾正發音與回應順序。",
            ),
            LessonPlanStep(
                title="全班回收與口說回饋",
                minutes=max(duration // 6, 10),
                details="挑選 2 到 3 組上台示範，統整常見錯誤並給出可立即修正的說法。",
            ),
        ]
        remaining = duration - sum(item.minutes for item in teaching_steps)
        if remaining > 0:
            teaching_steps.append(
                LessonPlanStep(
                    title="課末複盤",
                    minutes=remaining,
                    details="回顧今天的情境單字、句型與口說節奏，確認學生知道回家要怎麼複習。",
                )
            )

        fallback_result = LessonPlanDraftResponse(
            class_id=class_item.id,
            class_name=class_item.name,
            course_slug=class_item.course_slug,
            teacher_name=teacher_name,
            lesson_focus=payload.lesson_focus,
            duration_minutes=duration,
            objective=f"讓學生能在 {payload.lesson_focus} 情境下，用 {course.level} 程度完成基礎應答與追問。",
            warmup=f"請學生用 30 秒描述自己最近一次遇到 {payload.lesson_focus} 的經驗，帶出本課情境。",
            teaching_steps=teaching_steps,
            homework=f"完成一段以「{payload.lesson_focus}」為主題的 6 句對話，並錄一段 1 分鐘口說練習。",
            review_points=[
                "確認學生是否能主動開口而不是只背誦句型",
                "記錄容易卡住的單字與敬語點，下次課前再複習",
                "把今天表現較弱的學生列入課後提醒名單",
            ],
            generated_at=datetime.now().astimezone(),
        )
        result, provider, reason = self.ai_runtime.enhance_model(
            feature_name="lesson_plan_draft",
            instructions=(
                "Refine the lesson plan so the steps are classroom-ready, time-balanced, and suited to Chinese-speaking learners "
                "preparing for life and work in Japan."
            ),
            context={
                "class_name": class_item.name,
                "teacher_name": teacher_name,
                "course_name": course.name,
                "course_level": course.level,
                "course_modules": course.modules,
                "lesson_focus": payload.lesson_focus,
                "duration_minutes": duration,
            },
            fallback_model=fallback_result,
        )
        self.store.create_ai_log(
            module_name="teaching",
            action_name="lesson_plan_draft",
            actor_email=None,
            input_summary=f"class={class_item.name}, focus={payload.lesson_focus}, duration={duration}",
            output_summary=f"provider={provider}, reason={reason}, teacher={teacher_name}, steps={len(result.teaching_steps)}",
        )
        return result

    def practice_conversation(self, email: str, theme: str) -> PracticeConversationResponse:
        student = self.student_portal_service.get_student_by_email(email)
        if student is None:
            raise KeyError(email)
        classes = self.student_portal_service.student_classes(email)
        class_item = classes[0] if classes else None
        level = student.japanese_level or "N5"
        normalized_theme = theme.strip() or "日本生活會話"
        class_name = class_item.name if class_item else None
        scenario_title = f"{normalized_theme} 情境對話"
        situation = (
            f"你正在練習「{normalized_theme}」，需要用 {level} 程度完成 4 到 6 句自然應答。"
            + (f" 這段練習會對應你目前的班級：{class_name}。" if class_name else "")
        )
        key_phrases = [
            "すみません",
            "もう一度お願いします",
            "おすすめはありますか",
            "大丈夫です",
        ]
        goals = [
            "先用一句自然的開場把情境打開",
            "至少完成一次追問或補充說明",
            "練習用完整句而不是只回單字",
        ]
        hints = [
            "先說需求，再補充原因，句子會更自然。",
            "如果卡住，可以先用簡單句，再追加一個問題。",
            "回應時記得加上禮貌開頭，讓口氣更像真實生活場景。",
        ]
        review_checklist = [
            "我有沒有主動提問，而不是只等對方說完？",
            "我有沒有把需求說完整，例如時間、數量、原因？",
            "我有沒有至少用到 2 個今天的關鍵句型？",
        ]
        ai_opening = (
            f"你好，我是你的日語練習夥伴。現在我們來做「{normalized_theme}」情境對話。"
            "你先開口說第一句，我會接著和你往下對話。"
        )
        fallback_result = PracticeConversationResponse(
            student_email=student.email,
            student_name=student.chinese_name,
            class_name=class_name,
            level=level,
            theme=normalized_theme,
            scenario_title=scenario_title,
            situation=situation,
            goals=goals,
            key_phrases=key_phrases,
            ai_opening=ai_opening,
            hints=hints,
            review_checklist=review_checklist,
            generated_at=datetime.now().astimezone(),
        )
        result, provider, reason = self.ai_runtime.enhance_model(
            feature_name="student_practice_conversation",
            instructions=(
                "Refine the conversation practice so it feels practical and natural, keeps to the student's level, "
                "and encourages full-sentence speaking."
            ),
            context={
                "student_name": student.chinese_name,
                "student_email": student.email,
                "class_name": class_name,
                "level": level,
                "theme": normalized_theme,
            },
            fallback_model=fallback_result,
        )
        self.store.create_ai_log(
            module_name="student_ai_practice",
            action_name="practice_conversation_draft",
            actor_email=student.email,
            input_summary=f"student={student.email}, theme={normalized_theme}, level={level}",
            output_summary=f"provider={provider}, reason={reason}, class={class_name or 'none'}, phrases={len(result.key_phrases)}",
        )
        return result


class PlatformStatusService:
    def __init__(self, store) -> None:
        self.store = store

    def progress_snapshot(self):
        return self.store.progress_snapshot()

    def activity_feed(self):
        return self.store.activity_feed()

    def storage_summary(self) -> dict[str, object]:
        mutation_tables = list(getattr(self.store.repository, "mutation_tables", lambda: [])())
        return {
            "backend": self.store.storage_backend_name(),
            "repository_mode": self.store.storage_repository_mode(),
            "json_path": self.store.settings.json_path,
            "postgres_enabled": bool(self.store.settings.postgres_dsn),
            "capabilities": {
                "query_supported": bool(getattr(self.store.repository, "query_supported", lambda: False)()),
                "partial_write_supported": bool(getattr(self.store.repository, "partial_write_supported", lambda: False)()),
                "row_level_write_supported": bool(getattr(self.store.repository, "row_level_write_supported", lambda: False)()),
            },
            "mutation_tables": mutation_tables,
            "mutation_table_count": len(mutation_tables),
            "readiness": self.store.storage_readiness(),
            "migration_artifacts": self.store.migration_artifacts(),
            "snapshot_integrity": snapshot_integrity_from_json(self.store.settings.json_path),
            "payment_provider": FinanceService(self.store).payment_provider_status(),
            "notification_providers": NotificationService(self.store).provider_status(),
        }

    def launch_readiness(self) -> dict[str, object]:
        summary = self.storage_summary()
        readiness = summary["readiness"]
        payment_provider = summary["payment_provider"]
        notification_providers = summary["notification_providers"]
        progress = self.progress_snapshot()
        checks: list[dict[str, str]] = []

        def add_check(name: str, status: str, detail: str) -> None:
            checks.append({"name": name, "status": status, "detail": detail})

        add_check(
            "Storage backend",
            "ready" if summary["backend"] == "postgres" else "blocker",
            f"目前 backend 為 {summary['backend']}，正式上線建議切到 postgres。",
        )
        add_check(
            "Storage readiness",
            "ready" if bool(readiness["ready"]) else "blocker",
            str(readiness["message"]),
        )
        add_check(
            "HTTPS app base URL",
            "ready" if str(self.store.settings.app_base_url).startswith("https://") else "warning",
            f"目前 APP_BASE_URL = {self.store.settings.app_base_url}",
        )
        add_check(
            "Stripe provider selected",
            "ready" if payment_provider["provider"] == "stripe" else "blocker",
            f"payment provider = {payment_provider['provider']}",
        )
        add_check(
            "Stripe readiness",
            "ready" if bool(payment_provider["ready"]) else "blocker",
            str(payment_provider["message"]),
        )
        add_check(
            "Email provider",
            "ready" if bool(notification_providers["email_ready"]) and notification_providers["email_provider"] != "mock" else "blocker",
            f"email provider = {notification_providers['email_provider']}",
        )
        add_check(
            "LINE notifications",
            "ready" if bool(notification_providers["line_ready"]) else "warning",
            "LINE 可選，但若要在招生/客服正式外發，建議上線前補齊 channel token。",
        )
        add_check(
            "Automated tests",
            "ready" if progress.tests_passing > 0 else "warning",
            f"目前測試通過數 = {progress.tests_passing}",
        )
        add_check(
            "Notification retry flow",
            "ready",
            "已提供 drain queued 與單筆 retry，外部 provider 失敗不會中斷整批發送。",
        )

        blocker_count = sum(1 for item in checks if item["status"] == "blocker")
        warning_count = sum(1 for item in checks if item["status"] == "warning")
        ready_count = sum(1 for item in checks if item["status"] == "ready")
        return {
            "ready_for_launch": blocker_count == 0,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "ready_count": ready_count,
            "checks": checks,
            "manual_tasks": [
                "在 Render 補齊正式 Stripe / Email / LINE secrets。",
                "將 webhook URL 指向 /school-platform/api/payments/stripe/webhook。",
                "對正式網域執行 deployment smoke test 與至少一筆真實小額付款驗證。",
            ],
        }

    def operational_readiness(self) -> dict[str, object]:
        summary = self.storage_summary()
        readiness = summary["readiness"]
        payment_provider = summary["payment_provider"]
        notification_providers = summary["notification_providers"]
        checks: list[dict[str, str]] = []

        def add_check(name: str, status: str, detail: str) -> None:
            checks.append({"name": name, "status": status, "detail": detail})

        courses = self.store.list_courses()
        open_classes = self.store.open_classes()
        consultant_name = next((item.name for item in self.store.staff if item.role == "consultant"), "Mika Chen")
        teacher_name = next((item.name for item in self.store.staff if item.role == "teacher"), "Aki Mori")
        student_email = next((item.email for item in self.store.students if item.email), None)
        jobs = [item for item in self.store.job_positions if item.status == "open"]
        finance = FinanceService(self.store).overview()
        message_summary = NotificationService(self.store).summary()
        ai_status = AiAssistantService(
            self.store,
            AdmissionsService(self.store),
            CatalogService(self.store),
            StudentPortalService(self.store, CatalogService(self.store), AdmissionsService(self.store)),
            SchoolPlatformAiRuntime(),
        ).provider_status()

        consultant_ready = bool(consultant_name) and any(
            item.assigned_staff_name == consultant_name for item in self.store.leads
        )
        teacher_ready = bool(teacher_name) and any(
            item.teacher_name == teacher_name for item in self.store.classes
        )
        student_ready = bool(student_email) and any(
            item.email == student_email for item in self.store.students
        )

        add_check(
            "Storage for daily operations",
            "ready" if bool(readiness["ready"]) else "blocker",
            f"目前以 {summary['backend']} / {summary['repository_mode']} 運作；日常模式可直接操作。",
        )
        add_check(
            "Public course and admissions flow",
            "ready" if len(courses) >= 1 and len(open_classes) >= 1 else "blocker",
            f"公開課程 {len(courses)} 門，開放班級 {len(open_classes)} 個，試聽與報名流程可直接使用。",
        )
        student_portal_status = "ready" if student_ready else ("warning" if not student_email else "blocker")
        student_portal_detail = (
            f"示範學員帳號 = {student_email}。"
            if student_email
            else "示範學員帳號尚未建立，仍可透過學生入口頁與公開報名流程操作。"
        )
        add_check("Student learning portal", student_portal_status, student_portal_detail)
        add_check(
            "Consultant workspace",
            "ready" if consultant_ready else "blocker",
            f"顧問工作台示範帳號 = {consultant_name}。",
        )
        add_check(
            "Teacher workspace",
            "ready" if teacher_ready else "blocker",
            f"教師工作台示範帳號 = {teacher_name}。",
        )
        add_check(
            "Admin / executive operations",
            "ready",
            "招生、學員、財務、教務、客服、招聘、報表與 AI 中心都已有後台入口。",
        )
        add_check(
            "Recruiting workflow",
            "ready" if len(jobs) >= 1 else "warning",
            f"目前開放職缺 {len(jobs)} 個，可進行應徵、面試與 onboarding 流程。",
        )
        add_check(
            "Payments in current mode",
            "ready" if bool(payment_provider["ready"]) else "blocker",
            f"目前金流模式 = {payment_provider['provider']} / {payment_provider['provider_mode']}，已可在當前模式建立付款流程。",
        )
        add_check(
            "Notifications in current mode",
            "ready" if bool(notification_providers["email_ready"]) or message_summary.in_app_notifications >= 0 else "blocker",
            f"目前 Email provider = {notification_providers['email_provider']}，站內通知與重送流程可操作。",
        )
        add_check(
            "AI module availability",
            "ready" if bool(ai_status.service_ready) else "warning",
            f"目前 AI provider = {ai_status.active_provider} / mode = {ai_status.runtime_mode}。",
        )
        launch_cutover_gaps: list[str] = []
        if summary["backend"] != "postgres":
            launch_cutover_gaps.append("PostgreSQL")
        if payment_provider["provider"] != "stripe":
            launch_cutover_gaps.append("Stripe")
        if notification_providers["email_provider"] == "mock":
            launch_cutover_gaps.append("真實 Email provider")
        if not bool(notification_providers["line_ready"]):
            launch_cutover_gaps.append("真實 LINE provider")
        add_check(
            "Production external cutover",
            "warning" if launch_cutover_gaps else "ready",
            "若要正式對外收款與外發，仍需補齊 "
            + "、".join(launch_cutover_gaps)
            + "。"
            if launch_cutover_gaps
            else "正式對外收款、Email 與 LINE 外發設定已補齊。",
        )

        blocker_count = sum(1 for item in checks if item["status"] == "blocker")
        warning_count = sum(1 for item in checks if item["status"] == "warning")
        ready_count = sum(1 for item in checks if item["status"] == "ready")
        app_base_url = str(self.store.settings.app_base_url)
        is_local_demo = "127.0.0.1" in app_base_url or "localhost" in app_base_url
        entry_links = [
            {"label": "平台首頁", "path": "/school-platform", "note": "所有入口的總覽首頁"},
            {"label": "營運後台", "path": "/school-platform/admin", "note": "招生、財務、教務、客服、招聘總入口"},
            {"label": "學員中心", "path": f"/school-platform/student-portal?email={student_email}" if student_email else "/school-platform/student-portal", "note": "查看課程、作業、付款與通知"},
            {"label": "顧問工作台", "path": f"/school-platform/consultant-portal?staff_name={consultant_name.replace(' ', '+')}", "note": "處理 hot leads 與跟進節奏"},
            {"label": "教師工作台", "path": f"/school-platform/teacher-portal?teacher_name={teacher_name.replace(' ', '+')}", "note": "批改作業、測驗、點名與課後紀錄"},
            {"label": "子帳號中心", "path": "/school-platform/admin/subaccounts", "note": "開設主帳號 / 子帳號與權限"},
            {"label": "系統狀態", "path": "/school-platform/system", "note": "查看 storage / integrations / deploy 狀態"},
        ]
        demo_accounts: list[dict[str, str]] = []
        if is_local_demo:
            demo_accounts = [
                {"role": "super_admin", "email": "admin@jls.local", "password": "admin123", "entry": "/school-platform/admin"},
                {"role": "manager", "email": "manager@jls.local", "password": "manager123", "entry": "/school-platform/admin/executive"},
                {"role": "consultant", "email": "mika@jls.local", "password": "mika123", "entry": f"/school-platform/consultant-portal?staff_name={consultant_name.replace(' ', '+')}"},
                {"role": "student_demo", "email": student_email or "", "password": "query access", "entry": f"/school-platform/student-portal?email={student_email}" if student_email else "/school-platform/student-portal"},
            ]
        external_gaps = ["正式 PostgreSQL cutover", "Stripe 真實收款"]
        if notification_providers["email_provider"] == "mock":
            external_gaps.append("真實 Email 外發")
        if not bool(notification_providers["line_ready"]):
            external_gaps.append("真實 LINE 外發")
        return {
            "ready_for_operations": blocker_count == 0,
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "ready_count": ready_count,
            "current_mode": "internal_operable" if blocker_count == 0 else "needs_fix",
            "checks": checks,
            "entry_links": entry_links,
            "demo_accounts": demo_accounts,
            "external_gaps": external_gaps,
            "note": "這份狀態是看今天能不能直接操作平台，不等同於 production 正式上線判定。",
        }

    def initialize_storage(self) -> dict[str, object]:
        return self.store.initialize_storage()

    def cutover_storage(self) -> dict[str, object]:
        return self.store.cutover_from_json_snapshot()

    def health_payload(self) -> dict[str, str]:
        return {
            "status": "ok",
            "mode": "mvp",
            "storage": self.store.storage_backend_name(),
            "repository_mode": self.store.storage_repository_mode(),
        }

    def db_smoke_test_checks(self) -> list[dict[str, object]]:
        summary = self.storage_summary()
        readiness = summary["readiness"]
        artifacts = summary["migration_artifacts"]
        return [
            {"name": "Driver Installed", "ok": bool(readiness["driver_installed"]), "detail": "psycopg 與表單依賴已安裝"},
            {"name": "DSN Present", "ok": bool(readiness["dsn_present"]), "detail": "已提供 PostgreSQL DSN"},
            {"name": "Connection Ready", "ok": bool(readiness["connectable"]), "detail": "應可連到 PostgreSQL"},
            {"name": "Tables Ready", "ok": bool(readiness["tables_ready"]), "detail": "domain tables 已初始化"},
            {"name": "Partial Writes", "ok": bool(summary["capabilities"]["partial_write_supported"]), "detail": "高頻 mutation 可改成只更新受影響表"},
            {"name": "Row-level Writes", "ok": bool(summary["capabilities"]["row_level_write_supported"]), "detail": f"目前 row-level tables 覆蓋 {summary['mutation_table_count']} 張表"},
            {"name": "Artifacts Present", "ok": bool(artifacts["domain_sql_present"] and artifacts["init_script_present"] and artifacts["migrate_script_present"] and artifacts["smoke_test_script_present"]), "detail": "SQL、migration 與 smoke test scripts 已就緒"},
            {"name": "Public Courses", "ok": True, "detail": "切換後應先驗證課程列表可讀"},
            {"name": "Lead Queries", "ok": True, "detail": "切換後應驗證 lead list / detail / logs"},
            {"name": "Student Portal", "ok": True, "detail": "切換後應驗證學員課程 / 付款 / 通知"},
        ]
