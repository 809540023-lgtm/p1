from __future__ import annotations

from datetime import date
import uuid
import unittest

from fastapi.testclient import TestClient

from api import app


class SchoolPlatformApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def login_headers(self, email: str = "manager@jls.local", password: str = "manager123") -> dict[str, str]:
        response = self.client.post(
            "/school-platform/api/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_public_courses_and_dashboard(self) -> None:
        root_response = self.client.get("/", follow_redirects=False)
        self.assertEqual(root_response.status_code, 307)
        self.assertEqual(root_response.headers["location"], "/school-platform")

        marketplace_response = self.client.get("/marketplace")
        self.assertEqual(marketplace_response.status_code, 200)
        self.assertIn("二手生財餐飲器具", marketplace_response.text)

        home_page_response = self.client.get("/school-platform")
        self.assertEqual(home_page_response.status_code, 200)
        self.assertIn("平台入口總覽", home_page_response.text)
        self.assertIn("角色入口", home_page_response.text)
        self.assertIn("對外成長入口", home_page_response.text)
        self.assertIn("學習與教學入口", home_page_response.text)
        self.assertIn("營運與管理入口", home_page_response.text)
        self.assertIn("系統與開發入口", home_page_response.text)
        self.assertIn("/school-platform/franchise-vap", home_page_response.text)
        self.assertIn("/school-platform/admin", home_page_response.text)
        self.assertIn("/school-platform/system", home_page_response.text)
        self.assertIn("學員中心", home_page_response.text)
        self.assertIn("教師工作台", home_page_response.text)

        franchise_vap_response = self.client.get("/school-platform/franchise-vap")
        self.assertEqual(franchise_vap_response.status_code, 200)
        self.assertIn("加盟招商 VAP", franchise_vap_response.text)
        self.assertIn("10 到 100 個 AI agents", franchise_vap_response.text)
        self.assertIn("JPY 100,000 / 區", franchise_vap_response.text)
        self.assertIn("20 小時加盟主線上營運培訓", franchise_vap_response.text)

        courses_response = self.client.get("/school-platform/api/public/courses")
        self.assertEqual(courses_response.status_code, 200)
        courses = courses_response.json()["data"]
        self.assertGreaterEqual(len(courses), 3)

        august_floor = date(date.today().year, 8, 1)
        for course in courses[:3]:
            trial_slots_response = self.client.get(f"/school-platform/api/public/trial-slots?course_slug={course['slug']}")
            self.assertEqual(trial_slots_response.status_code, 200)
            trial_slots = trial_slots_response.json()["data"]
            self.assertGreaterEqual(len(trial_slots), 1)
            self.assertTrue(all(date.fromisoformat(item["starts_at"][:10]) >= august_floor for item in trial_slots))

        courses_page_response = self.client.get("/school-platform/courses")
        self.assertEqual(courses_page_response.status_code, 200)
        self.assertIn("課程總覽", courses_page_response.text)

        progress_response = self.client.get("/school-platform/api/progress")
        self.assertEqual(progress_response.status_code, 200)
        self.assertIn("application/json", progress_response.headers["content-type"])
        self.assertIn("charset=utf-8", progress_response.headers["content-type"].lower())
        progress = progress_response.json()["data"]
        self.assertGreaterEqual(progress["tests_passing"], 1)

        progress_page_response = self.client.get("/school-platform/progress")
        self.assertEqual(progress_page_response.status_code, 200)
        self.assertIn("平台開發進度總覽", progress_page_response.text)

        activity_response = self.client.get("/school-platform/api/activity")
        self.assertEqual(activity_response.status_code, 200)
        activity = activity_response.json()["data"]
        self.assertGreaterEqual(len(activity), 1)

        activity_page_response = self.client.get("/school-platform/activity")
        self.assertEqual(activity_page_response.status_code, 200)
        self.assertIn("最近開發紀錄", activity_page_response.text)

        architecture_page_response = self.client.get("/school-platform/architecture")
        self.assertEqual(architecture_page_response.status_code, 200)
        self.assertIn("完整營運平台架構", architecture_page_response.text)

        system_storage_response = self.client.get("/school-platform/api/system/storage")
        self.assertEqual(system_storage_response.status_code, 200)
        self.assertEqual(system_storage_response.json()["data"]["backend"], "json")
        self.assertEqual(system_storage_response.json()["data"]["repository_mode"], "snapshot_file")
        self.assertIn("capabilities", system_storage_response.json()["data"])
        self.assertFalse(system_storage_response.json()["data"]["capabilities"]["query_supported"])
        self.assertFalse(system_storage_response.json()["data"]["capabilities"]["partial_write_supported"])
        self.assertFalse(system_storage_response.json()["data"]["capabilities"]["row_level_write_supported"])
        self.assertEqual(system_storage_response.json()["data"]["mutation_table_count"], 0)
        self.assertIn("readiness", system_storage_response.json()["data"])
        self.assertIn("materials_storage", system_storage_response.json()["data"])
        self.assertTrue(system_storage_response.json()["data"]["readiness"]["ready"])
        self.assertIn("migration_artifacts", system_storage_response.json()["data"])
        self.assertIn("snapshot_integrity", system_storage_response.json()["data"])
        self.assertIn("payment_provider", system_storage_response.json()["data"])
        self.assertIn("notification_providers", system_storage_response.json()["data"])
        self.assertTrue(system_storage_response.json()["data"]["migration_artifacts"]["domain_sql_present"])
        self.assertTrue(system_storage_response.json()["data"]["migration_artifacts"]["smoke_test_script_present"])
        self.assertTrue(system_storage_response.json()["data"]["migration_artifacts"]["cutover_script_present"])
        self.assertTrue(system_storage_response.json()["data"]["migration_artifacts"]["deployment_smoke_script_present"])
        self.assertTrue(system_storage_response.json()["data"]["migration_artifacts"]["row_write_probe_script_present"])

        system_init_response = self.client.post("/school-platform/api/system/storage/init")
        self.assertEqual(system_init_response.status_code, 200)
        self.assertTrue(system_init_response.json()["data"]["ready"])

        system_cutover_response = self.client.post("/school-platform/api/system/storage/cutover")
        self.assertEqual(system_cutover_response.status_code, 200)
        self.assertTrue(system_cutover_response.json()["data"]["skipped"])
        self.assertEqual(system_cutover_response.json()["data"]["reason"], "active storage backend is not postgres")

        system_page_response = self.client.get("/school-platform/system")
        self.assertEqual(system_page_response.status_code, 200)
        self.assertIn("系統與資料層狀態", system_page_response.text)
        self.assertIn("Operational Readiness Summary", system_page_response.text)
        self.assertIn("Storage Readiness", system_page_response.text)
        self.assertIn("Materials Storage", system_page_response.text)
        self.assertIn("Migration Readiness", system_page_response.text)
        self.assertIn("Snapshot Integrity", system_page_response.text)
        self.assertIn("External Integrations", system_page_response.text)
        self.assertIn("Launch Readiness Summary", system_page_response.text)
        self.assertIn("partial_write_supported", system_page_response.text)
        self.assertIn("row_level_write_supported", system_page_response.text)
        self.assertIn("Row-level Mutation Coverage", system_page_response.text)
        self.assertIn("Recommended Commands", system_page_response.text)
        self.assertIn("PostgreSQL 一鍵 rehearsal", system_page_response.text)
        self.assertIn("部署 smoke test", system_page_response.text)
        self.assertIn("PostgreSQL row-level write probe", system_page_response.text)

        launch_readiness_response = self.client.get("/school-platform/api/system/launch-readiness")
        self.assertEqual(launch_readiness_response.status_code, 200)
        self.assertIn("blocker_count", launch_readiness_response.json()["data"])
        self.assertGreaterEqual(launch_readiness_response.json()["data"]["blocker_count"], 1)

        launch_readiness_page_response = self.client.get("/school-platform/launch-readiness")
        self.assertEqual(launch_readiness_page_response.status_code, 200)
        self.assertIn("正式上線檢查清單", launch_readiness_page_response.text)
        self.assertIn("Storage backend", launch_readiness_page_response.text)

        operational_readiness_response = self.client.get("/school-platform/api/system/operational-readiness")
        self.assertEqual(operational_readiness_response.status_code, 200)
        operational_readiness = operational_readiness_response.json()["data"]
        self.assertTrue(operational_readiness["ready_for_operations"])
        self.assertIn("entry_links", operational_readiness)
        self.assertIn("demo_accounts", operational_readiness)

        operational_readiness_page_response = self.client.get("/school-platform/operational-readiness")
        self.assertEqual(operational_readiness_page_response.status_code, 200)
        self.assertIn("今天可直接營運的狀態", operational_readiness_page_response.text)
        self.assertIn("本機示範帳號", operational_readiness_page_response.text)

        db_migration_page_response = self.client.get("/school-platform/db-migration")
        self.assertEqual(db_migration_page_response.status_code, 200)
        self.assertIn("DB 切換與資料搬遷說明", db_migration_page_response.text)
        self.assertIn("跑 smoke test", db_migration_page_response.text)
        self.assertIn("目前 row-level 覆蓋表", db_migration_page_response.text)
        self.assertIn("一鍵 rehearsal", db_migration_page_response.text)
        self.assertIn("驗證部署 smoke test", db_migration_page_response.text)
        self.assertIn("verify_school_platform_postgres_row_writes.py", db_migration_page_response.text)

        smoke_test_response = self.client.get("/school-platform/api/system/smoke-test")
        self.assertEqual(smoke_test_response.status_code, 200)
        self.assertGreaterEqual(len(smoke_test_response.json()["data"]), 1)

        smoke_test_page_response = self.client.get("/school-platform/db-smoke-test")
        self.assertEqual(smoke_test_page_response.status_code, 200)
        self.assertIn("DB 切換後 smoke test", smoke_test_page_response.text)

        admin_page_response = self.client.get("/school-platform/admin")
        self.assertEqual(admin_page_response.status_code, 200)
        self.assertIn("營運後台總覽", admin_page_response.text)
        self.assertIn("加盟招商 VAP", admin_page_response.text)

        dashboard_response = self.client.get("/school-platform/api/admin/dashboard", headers=self.login_headers())
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard = dashboard_response.json()["data"]
        self.assertIn("active_classes", dashboard)

    def test_simplified_chinese_page_switch(self) -> None:
        courses = self.client.get("/school-platform/api/public/courses").json()["data"]
        target_slug = courses[0]["slug"]

        response = self.client.get("/school-platform/courses?lang=zh-Hans")
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="zh-Hans"', response.text)
        self.assertIn("课程总览", response.text)
        self.assertIn("简体中文", response.text)
        self.assertIn(f"/school-platform/courses/{target_slug}?lang=zh-Hans", response.text)

    def test_simplified_chinese_redirect_is_preserved(self) -> None:
        course = self.client.get("/school-platform/api/public/courses").json()["data"][0]
        slot = self.client.get(f"/school-platform/api/public/trial-slots?course_slug={course['slug']}").json()["data"][0]

        response = self.client.post(
            "/school-platform/trial-booking/create?lang=zh-Hans",
            data={
                "name": "简体试听学员",
                "email": "simplified-trial@example.com",
                "phone": "0911000111",
                "line_id": "simplified-line",
                "course_slug": course["slug"],
                "slot_start_at": slot["starts_at"],
                "japanese_level": "beginner",
                "study_goal": "测试简体中文切换是否保留",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("lang=zh-Hans", response.headers["location"])

        success_response = self.client.get(response.headers["location"])
        self.assertEqual(success_response.status_code, 200)
        self.assertIn("试听预约成功", success_response.text)

    def test_admin_endpoints_require_auth(self) -> None:
        response = self.client.get("/school-platform/api/admin/dashboard")
        self.assertEqual(response.status_code, 401)

    def test_trial_booking_creates_lead(self) -> None:
        headers = self.login_headers()
        before = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]

        slot = self.client.get("/school-platform/api/public/trial-slots").json()["data"][0]
        booking_response = self.client.post(
            "/school-platform/api/public/trial-bookings",
            json={
                "name": "新試聽學員",
                "email": "trial@example.com",
                "phone": "0911222333",
                "course_slug": slot["course_slug"],
                "slot_start_at": slot["starts_at"],
                "japanese_level": "beginner",
                "study_goal": "赴日前生活會話",
            },
        )
        self.assertEqual(booking_response.status_code, 200)

        after = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]
        self.assertEqual(len(after), len(before) + 1)

    def test_trial_slots_filter_and_ai_followup_draft(self) -> None:
        headers = self.login_headers()
        courses = self.client.get("/school-platform/api/public/courses").json()["data"]
        target_slug = courses[0]["slug"]

        slots_response = self.client.get(f"/school-platform/api/public/trial-slots?course_slug={target_slug}")
        self.assertEqual(slots_response.status_code, 200)
        slots = slots_response.json()["data"]
        self.assertGreaterEqual(len(slots), 1)
        self.assertTrue(all(item["course_slug"] == target_slug for item in slots))

        leads = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]
        lead_id = leads[0]["id"]
        draft_response = self.client.post(
            f"/school-platform/api/ai/leads/{lead_id}/followup-draft",
            headers=headers,
        )
        self.assertEqual(draft_response.status_code, 200)
        draft = draft_response.json()["data"]
        self.assertEqual(draft["lead_id"], lead_id)
        self.assertIn("試聽", draft["line_message"])
        self.assertTrue(draft["recommended_channel"] in {"line", "email"})

    def test_trial_booking_page_and_form_submit(self) -> None:
        course = self.client.get("/school-platform/api/public/courses").json()["data"][0]
        page_response = self.client.get(f"/school-platform/trial-booking?course_slug={course['slug']}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("免費試聽預約", page_response.text)
        self.assertIn(course["slug"], page_response.text)

        slot = self.client.get(f"/school-platform/api/public/trial-slots?course_slug={course['slug']}").json()["data"][0]
        submit_response = self.client.post(
            "/school-platform/trial-booking/create",
            data={
                "name": "表單試聽學員",
                "email": "form-trial@example.com",
                "phone": "0911555666",
                "line_id": "form-trial-line",
                "course_slug": course["slug"],
                "slot_start_at": slot["starts_at"],
                "japanese_level": "beginner",
                "study_goal": "先測試前台試聽頁是否成功建 lead",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)
        self.assertIn("/school-platform/trial-booking/success?", submit_response.headers["location"])

    def test_enrollment_payment_flow(self) -> None:
        headers = self.login_headers()
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]

        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "付款學員",
                "email": "paying@example.com",
                "phone": "0900111222",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        enrollment = enrollment_response.json()["data"]

        intent_response = self.client.post(
            "/school-platform/api/public/payments/create-intent",
            json={
                "enrollment_id": enrollment["enrollment_id"],
                "payment_method": "card",
            },
        )
        self.assertEqual(intent_response.status_code, 200)
        intent = intent_response.json()["data"]
        self.assertEqual(intent["status"], "pending")

        webhook_response = self.client.post(
            "/school-platform/api/payments/webhook",
            json={
                "order_no": enrollment["order_no"],
                "status": "paid",
            },
        )
        self.assertEqual(webhook_response.status_code, 200)
        self.assertEqual(webhook_response.json()["data"]["status"], "paid")

        dashboard_response = self.client.get("/school-platform/api/admin/dashboard", headers=headers)
        self.assertEqual(dashboard_response.status_code, 200)

    def test_enrollment_page_and_form_submit(self) -> None:
        course = self.client.get("/school-platform/api/public/courses").json()["data"][0]
        page_response = self.client.get(f"/school-platform/enrollment?course_slug={course['slug']}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("正式報名", page_response.text)
        self.assertIn(course["slug"], page_response.text)

        class_item = self.client.get(f"/school-platform/api/public/courses/{course['slug']}/classes").json()["data"][0]
        submit_response = self.client.post(
            "/school-platform/enrollment/create",
            data={
                "chinese_name": "前台報名學員",
                "email": "web-enrollment@example.com",
                "phone": "0911666777",
                "class_id": class_item["id"],
                "japanese_level": "N5",
                "study_goal": "測試前台正式報名頁",
                "payment_method": "card",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)
        self.assertIn("/school-platform/enrollment/success?", submit_response.headers["location"])

    def test_payment_center_page_and_update_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "付款中心測試",
                "email": "payment-center@example.com",
                "phone": "0911777888",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        enrollment = enrollment_response.json()["data"]

        page_response = self.client.get(
            f"/school-platform/payment?email=payment-center@example.com&order_no={enrollment['order_no']}"
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("付款中心", page_response.text)
        self.assertIn(enrollment["order_no"], page_response.text)

        intent_response = self.client.post(
            "/school-platform/payment/intent",
            data={
                "email": "payment-center@example.com",
                "order_no": enrollment["order_no"],
                "enrollment_id": enrollment["enrollment_id"],
                "payment_method": "card",
            },
            follow_redirects=False,
        )
        self.assertEqual(intent_response.status_code, 303)
        self.assertIn("client_token=demo_", intent_response.headers["location"])

        reconcile_response = self.client.post(
            "/school-platform/payment/reconcile",
            data={
                "email": "payment-center@example.com",
                "order_no": enrollment["order_no"],
                "payment_id": enrollment["payment_id"],
            },
            follow_redirects=False,
        )
        self.assertEqual(reconcile_response.status_code, 303)
        self.assertIn("reconcile_result=success", reconcile_response.headers["location"])

        update_response = self.client.post(
            "/school-platform/payment/update",
            data={
                "email": "payment-center@example.com",
                "order_no": enrollment["order_no"],
                "payment_status": "paid",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 303)

        paid_page_response = self.client.get(
            f"/school-platform/payment?email=payment-center@example.com&order_no={enrollment['order_no']}"
        )
        self.assertEqual(paid_page_response.status_code, 200)
        self.assertIn("paid", paid_page_response.text)
        self.assertIn("重新同步 Stripe 狀態", paid_page_response.text)

    def test_student_schedule_and_notifications_center_pages(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "self-service@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "自助功能學員",
                "email": student_email,
                "phone": "0911888999",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        schedule_page_response = self.client.get(f"/school-platform/my-schedule?email={student_email}")
        self.assertEqual(schedule_page_response.status_code, 200)
        self.assertIn("我的課表", schedule_page_response.text)
        self.assertIn(student_email, schedule_page_response.text)

        notifications_page_response = self.client.get(f"/school-platform/notifications-center?email={student_email}")
        self.assertEqual(notifications_page_response.status_code, 200)
        self.assertIn("通知中心", notifications_page_response.text)
        self.assertIn("通知總數", notifications_page_response.text)

    def test_help_center_submit_and_payment_reminder(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "support-center@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "客服中心學員",
                "email": student_email,
                "phone": "0911999000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        order_no = enrollment_response.json()["data"]["order_no"]

        help_page_response = self.client.get(f"/school-platform/help-center?email={student_email}")
        self.assertEqual(help_page_response.status_code, 200)
        self.assertIn("客服需求中心", help_page_response.text)

        help_submit_response = self.client.post(
            "/school-platform/help-center/submit",
            data={
                "email": student_email,
                "topic": "付款問題",
                "preferred_channel": "email",
                "message": "想確認付款截止時間與轉帳資訊",
            },
            follow_redirects=False,
        )
        self.assertEqual(help_submit_response.status_code, 303)
        self.assertIn("/school-platform/help-center/success?", help_submit_response.headers["location"])

        remind_response = self.client.post(
            "/school-platform/payment/remind",
            data={
                "email": student_email,
                "order_no": order_no,
            },
            follow_redirects=False,
        )
        self.assertEqual(remind_response.status_code, 303)
        self.assertIn("reminder_sent=1", remind_response.headers["location"])

        history_page_response = self.client.get(f"/school-platform/my-history?email={student_email}")
        self.assertEqual(history_page_response.status_code, 200)
        self.assertIn("我的歷程", history_page_response.text)
        self.assertIn("payment", history_page_response.text)

        support_inbox_page_response = self.client.get("/school-platform/admin/support-inbox")
        self.assertEqual(support_inbox_page_response.status_code, 200)
        self.assertIn("客服收件箱", support_inbox_page_response.text)
        self.assertIn("付款問題", support_inbox_page_response.text)

    def test_notifications_mark_read_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "mark-read@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "通知已讀學員",
                "email": student_email,
                "phone": "0911222999",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        headers = self.login_headers()
        notifications = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        ).json()["data"]
        target_id = notifications[0]["id"]

        response = self.client.post(
            f"/school-platform/notifications-center/{target_id}/read",
            data={"email": student_email},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        updated = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        ).json()["data"]
        target = next(item for item in updated if item["id"] == target_id)
        self.assertEqual(target["status"], "read")

    def test_support_inbox_detail_and_reply_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "support-detail@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "客服案件詳情學員",
                "email": student_email,
                "phone": "0911333444",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        submit_response = self.client.post(
            "/school-platform/help-center/submit",
            data={
                "email": student_email,
                "topic": "教材需求",
                "preferred_channel": "email",
                "message": "想索取最近一堂課的講義",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)

        headers = self.login_headers()
        admin_notifications = self.client.get(
            "/school-platform/api/notifications?user_email=admin@jls.local",
            headers=headers,
        ).json()["data"]
        support_request = next(item for item in admin_notifications if item["type"] == "student_support_request")

        detail_response = self.client.get(f"/school-platform/admin/support-inbox/{support_request['id']}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("客服案件詳情", detail_response.text)

        reply_response = self.client.post(
            f"/school-platform/admin/support-inbox/{support_request['id']}/reply",
            data={
                "status_value": "resolved",
                "response_channel": "email",
                "response_message": "已將最新講義寄到你的信箱，也同步補到教材區。",
            },
            follow_redirects=False,
        )
        self.assertEqual(reply_response.status_code, 303)

        student_notifications = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        ).json()["data"]
        self.assertTrue(any(item["type"] == "support_request_resolved" for item in student_notifications))

    def test_notification_status_api_and_support_inbox_api(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "support-api@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "通知 API 學員",
                "email": student_email,
                "phone": "0911444555",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        headers = self.login_headers()
        student_notifications = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        ).json()["data"]
        notification_id = student_notifications[0]["id"]

        status_response = self.client.post(
            f"/school-platform/api/notifications/{notification_id}/status",
            headers=headers,
            json={"status": "read"},
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["data"]["status"], "read")

        self.client.post(
            "/school-platform/help-center/submit",
            data={
                "email": student_email,
                "topic": "排課問題",
                "preferred_channel": "email",
                "message": "想調整到週末班",
            },
            follow_redirects=False,
        )
        inbox_response = self.client.get("/school-platform/api/support-inbox", headers=headers)
        self.assertEqual(inbox_response.status_code, 200)
        self.assertIn("summary", inbox_response.json()["data"])
        self.assertGreaterEqual(len(inbox_response.json()["data"]["items"]), 1)

    def test_support_reply_api_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "support-reply-api@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "客服 API 學員",
                "email": student_email,
                "phone": "0911555000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        self.client.post(
            "/school-platform/help-center/submit",
            data={
                "email": student_email,
                "topic": "教材需求",
                "preferred_channel": "email",
                "message": "需要補發教材下載連結",
            },
            follow_redirects=False,
        )
        headers = self.login_headers()
        inbox_response = self.client.get("/school-platform/api/support-inbox", headers=headers).json()["data"]
        support_request = inbox_response["items"][0]

        reply_response = self.client.post(
            f"/school-platform/api/support-inbox/{support_request['id']}/reply",
            headers=headers,
            json={
                "status": "resolved",
                "response_channel": "email",
                "response_message": "教材下載連結已補寄到你的信箱。",
            },
        )
        self.assertEqual(reply_response.status_code, 200)
        self.assertEqual(reply_response.json()["data"]["request"]["status"], "resolved")
        self.assertEqual(reply_response.json()["data"]["reply"]["type"], "support_request_resolved")

    def test_admin_messages_page_and_overview_api(self) -> None:
        page_response = self.client.get("/school-platform/admin/messages")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("訊息中心", page_response.text)
        self.assertIn("發送訊息", page_response.text)
        self.assertIn("已抑制", page_response.text)
        self.assertIn("Gmail SMTP 最短設定", page_response.text)
        self.assertIn("LINE 外發需要什麼", page_response.text)
        self.assertIn("Provider Smoke Test", page_response.text)

    def test_admin_message_smoke_test_submit(self) -> None:
        response = self.client.post(
            "/school-platform/admin/messages/test",
            data={
                "channel": "email",
                "recipient": "smoke@example.com",
                "user_email": "admin@jls.local",
                "title": "Smoke Test",
                "content": "Testing provider smoke flow.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/school-platform/admin/messages")

        page_response = self.client.get("/school-platform/admin/messages")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("provider_smoke_test", page_response.text)
        self.assertIn("smoke@example.com", page_response.text)

    def test_notification_retry_api(self) -> None:
        headers = self.login_headers()
        create_response = self.client.post(
            "/school-platform/api/notifications",
            headers=headers,
            json={
                "user_email": "retry@example.com",
                "channel": "email",
                "type": "manual_retry_test",
                "title": "Retry Test",
                "content": "Please retry this notification.",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        notification = create_response.json()["data"]
        self.assertEqual(notification["status"], "suppressed")
        self.assertEqual(notification["provider"], "guardrail")
        self.assertEqual(notification["attempt_count"], 1)

        retry_response = self.client.post(
            f"/school-platform/api/notifications/{notification['id']}/retry",
            headers=headers,
        )
        self.assertEqual(retry_response.status_code, 200)
        retried = retry_response.json()["data"]
        self.assertEqual(retried["status"], "suppressed")
        self.assertEqual(retried["provider"], "guardrail")
        self.assertEqual(retried["attempt_count"], 2)
        page_response = self.client.get("/school-platform/admin/messages")
        self.assertIn("最近通知紀錄", page_response.text)
        self.assertIn("已送達", page_response.text)
        self.assertIn("送達失敗", page_response.text)
        self.assertIn("已抑制", page_response.text)
        self.assertIn("重送 queued 通知", page_response.text)

        overview_response = self.client.get("/school-platform/api/messages/overview", headers=self.login_headers())
        self.assertEqual(overview_response.status_code, 200)
        overview = overview_response.json()["data"]
        self.assertIn("summary", overview)
        self.assertIn("notifications", overview)
        self.assertIn("providers", overview)
        self.assertGreaterEqual(overview["summary"]["suppressed_notifications"], 1)

    def test_messages_broadcast_api_creates_student_notification(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "message-center@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "訊息中心學員",
                "email": student_email,
                "phone": "0911666111",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        headers = self.login_headers()

        broadcast_response = self.client.post(
            "/school-platform/api/messages/broadcast",
            headers=headers,
            json={
                "audience": "single_student",
                "target_email": student_email,
                "channel": "email",
                "title": "系統公告",
                "content": "請確認本週上課資訊與教材。",
            },
        )
        self.assertEqual(broadcast_response.status_code, 200)
        broadcast = broadcast_response.json()["data"]
        self.assertEqual(broadcast["audience"], "single_student")
        self.assertEqual(broadcast["recipient_count"], 1)
        self.assertEqual(broadcast["sample_recipients"], [student_email])

        notifications_response = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        )
        self.assertEqual(notifications_response.status_code, 200)
        notifications = notifications_response.json()["data"]
        self.assertTrue(any(item["title"] == "系統公告" and item["type"] == "manual_broadcast" for item in notifications))

    def test_student_assignments_page_and_submission_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "assignment-center@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "作業中心學員",
                "email": student_email,
                "phone": "0911666000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        headers = self.login_headers()
        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "會話練習作業",
                "content": "請完成一段購物情境對話。",
                "due_at": "2026-05-01T20:00:00+08:00",
                "created_by": "Yuki Wang",
            },
        )
        self.assertEqual(assignment_response.status_code, 200)
        assignment_id = assignment_response.json()["data"]["id"]

        page_response = self.client.get(f"/school-platform/my-assignments?email={student_email}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("作業中心", page_response.text)
        self.assertIn("會話練習作業", page_response.text)

        submit_response = self.client.post(
            f"/school-platform/my-assignments/{assignment_id}/submit",
            data={"email": student_email, "content": "這是我的購物對話作業。"},
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)

        student_assignments = self.client.get(
            f"/school-platform/api/student/assignments?email={student_email}",
            headers=headers,
        )
        self.assertEqual(student_assignments.status_code, 200)
        self.assertTrue(any(item["id"] == assignment_id for item in student_assignments.json()["data"]))

    def test_student_attendance_page_and_admin_mark_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "attendance-center@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "出缺勤學員",
                "email": student_email,
                "phone": "0911777000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        headers = self.login_headers()
        attendance_response = self.client.post(
            "/school-platform/api/attendance",
            headers=headers,
            json={
                "class_id": class_id,
                "student_email": student_email,
                "class_date": "2026-04-20",
                "status": "present",
                "note": "準時到課",
                "marked_by": "Yuki Wang",
            },
        )
        self.assertEqual(attendance_response.status_code, 200)

        page_response = self.client.get(f"/school-platform/my-attendance?email={student_email}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("出缺勤", page_response.text)
        self.assertIn("present", page_response.text)

        attendance_list = self.client.get(
            f"/school-platform/api/student/attendance?email={student_email}",
            headers=headers,
        )
        self.assertEqual(attendance_list.status_code, 200)
        self.assertGreaterEqual(len(attendance_list.json()["data"]), 1)

    def test_student_exams_page_and_submission_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "exam-center@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "測驗中心學員",
                "email": student_email,
                "phone": "0911888000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        headers = self.login_headers()
        exam_response = self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "生活日語情境小考",
                "exam_type": "speaking_quiz",
                "instructions": "請完成 3 句藥局問答。",
                "total_score": 100,
                "due_at": "2026-05-02T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(exam_response.status_code, 200)
        exam_id = exam_response.json()["data"]["id"]

        page_response = self.client.get(f"/school-platform/my-exams?email={student_email}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("測驗中心", page_response.text)
        self.assertIn("生活日語情境小考", page_response.text)

        submit_response = self.client.post(
            f"/school-platform/my-exams/{exam_id}/submit",
            data={"email": student_email, "content": "這是我的藥局問答答案。"},
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)

        student_exams = self.client.get(
            f"/school-platform/api/student/exams?email={student_email}",
            headers=headers,
        )
        self.assertEqual(student_exams.status_code, 200)
        self.assertTrue(any(item["id"] == exam_id for item in student_exams.json()["data"]))

    def test_student_progress_page_and_api(self) -> None:
        headers = self.login_headers()
        course_slug = f"progress-lab-{uuid.uuid4().hex[:8]}"
        course_response = self.client.post(
            "/school-platform/api/courses",
            headers=headers,
            json={
                "slug": course_slug,
                "name": "進度專用課程",
                "course_type": "生活日語",
                "level": "N5",
                "delivery_mode": "online",
                "price": 9800,
                "short_description": "專供進度測試使用。",
                "objectives": ["整合進度頁"],
                "highlights": ["測試專用班級"],
                "modules": ["租屋", "就醫"],
                "teacher_names": ["Aki Mori"],
            },
        )
        self.assertEqual(course_response.status_code, 200)
        class_response = self.client.post(
            "/school-platform/api/classes",
            headers=headers,
            json={
                "course_slug": course_slug,
                "name": "進度專用班",
                "teacher_name": "Aki Mori",
                "start_date": "2026-06-05",
                "end_date": "2026-07-05",
                "weekday": "Fri",
                "start_time": "19:00:00",
                "end_time": "20:30:00",
                "capacity": 12,
                "location_label": "Zoom",
                "status": "open",
            },
        )
        self.assertEqual(class_response.status_code, 200)
        class_id = class_response.json()["data"]["id"]
        student_email = "progress-center@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "進度中心學員",
                "email": student_email,
                "phone": "0911999777",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "進度作業",
                "content": "請完成一段租屋對話。",
                "due_at": "2026-05-08T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        assignment_id = assignment_response.json()["data"]["id"]
        exam_response = self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "進度測驗",
                "exam_type": "quiz",
                "instructions": "請完成 4 題情境題。",
                "total_score": 100,
                "due_at": "2026-05-09T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        exam_id = exam_response.json()["data"]["id"]
        self.client.post(
            "/school-platform/api/attendance",
            headers=headers,
            json={
                "class_id": class_id,
                "student_email": student_email,
                "class_date": "2026-04-21",
                "status": "present",
                "note": "正常到課",
                "marked_by": "Aki Mori",
            },
        )
        assignment_submit = self.client.post(
            f"/school-platform/api/student/assignments/{assignment_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是我的租屋對話。"},
        )
        assignment_submission_id = assignment_submit.json()["data"]["id"]
        exam_submit = self.client.post(
            f"/school-platform/api/student/exams/{exam_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是我的測驗答案。"},
        )
        exam_submission_id = exam_submit.json()["data"]["id"]
        self.client.post(
            f"/school-platform/api/assignments/submissions/{assignment_submission_id}/grade",
            headers=headers,
            json={"score": 90, "feedback": "作業完成度高", "graded_by": "Aki Mori"},
        )
        self.client.post(
            f"/school-platform/api/exams/submissions/{exam_submission_id}/grade",
            headers=headers,
            json={"score": 94, "feedback": "答題完整", "graded_by": "Aki Mori"},
        )

        progress_api = self.client.get(
            f"/school-platform/api/student/progress?email={student_email}",
            headers=headers,
        )
        self.assertEqual(progress_api.status_code, 200)
        progress_data = progress_api.json()["data"]
        self.assertEqual(progress_data["summary"]["assignment_graded"], 1)
        self.assertEqual(progress_data["summary"]["exam_graded"], 1)
        self.assertEqual(progress_data["summary"]["attendance_total"], 1)
        self.assertEqual(progress_data["summary"]["risk_level"], "low")

        progress_page = self.client.get(f"/school-platform/my-progress?email={student_email}")
        self.assertEqual(progress_page.status_code, 200)
        self.assertIn("學習進度中心", progress_page.text)
        self.assertIn("整體學習評估", progress_page.text)
        self.assertIn("進度作業", progress_page.text)
        self.assertIn("進度測驗", progress_page.text)

    def test_admin_student_progress_page_and_risk_flag(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "progress-risk@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "高風險學員",
                "email": student_email,
                "phone": "0911888666",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        headers = self.login_headers()
        self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "高風險作業",
                "content": "請完成醫院掛號會話。",
                "due_at": "2026-05-10T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "高風險測驗",
                "exam_type": "quiz",
                "instructions": "請完成 3 題口說題。",
                "total_score": 100,
                "due_at": "2026-05-11T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.client.post(
            "/school-platform/api/attendance",
            headers=headers,
            json={
                "class_id": class_id,
                "student_email": student_email,
                "class_date": "2026-04-22",
                "status": "absent",
                "note": "未出席",
                "marked_by": "Aki Mori",
            },
        )

        admin_api = self.client.get("/school-platform/api/admin/student-progress", headers=headers)
        self.assertEqual(admin_api.status_code, 200)
        target = next(item for item in admin_api.json()["data"] if item["email"] == student_email)
        self.assertEqual(target["risk_level"], "high")

        admin_page = self.client.get("/school-platform/admin/student-progress")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("學習進度總覽", admin_page.text)
        self.assertIn(student_email, admin_page.text)

    def test_admin_students_page(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "admin-students-page@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "學員管理頁測試",
                "email": student_email,
                "phone": "0911777111",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        page_response = self.client.get("/school-platform/admin/students")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("學員管理", page_response.text)
        self.assertIn("學員名單", page_response.text)
        self.assertIn(student_email, page_response.text)

        detail_page_response = self.client.get(f"/school-platform/admin/students/detail?email={student_email}")
        self.assertEqual(detail_page_response.status_code, 200)
        self.assertIn("學員檔案", detail_page_response.text)
        self.assertIn(student_email, detail_page_response.text)

    def test_admin_students_api_detail(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "admin-students-api@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "學員管理 API 測試",
                "email": student_email,
                "phone": "0911777222",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        headers = self.login_headers()

        list_response = self.client.get("/school-platform/api/admin/students", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        items = list_response.json()["data"]["items"]
        self.assertTrue(any(item["student"]["email"] == student_email for item in items))

        detail_response = self.client.get(
            f"/school-platform/api/admin/students/detail?email={student_email}",
            headers=headers,
        )
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()["data"]
        self.assertEqual(detail["item"]["student"]["email"], student_email)
        self.assertGreaterEqual(len(detail["enrollments"]), 1)
        self.assertGreaterEqual(len(detail["history"]), 1)

    def test_admin_staff_page(self) -> None:
        response = self.client.get("/school-platform/admin/staff")
        self.assertEqual(response.status_code, 200)
        self.assertIn("員工績效中心", response.text)
        self.assertIn("Mika Chen", response.text)
        self.assertIn("Aki Mori", response.text)
        self.assertIn("查看教師工作台", response.text)

    def test_admin_subaccounts_page_and_form_submit(self) -> None:
        page_response = self.client.get("/school-platform/admin/subaccounts")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("子帳號中心", page_response.text)
        self.assertIn("建立新子帳號", page_response.text)

        headers = self.login_headers()
        owners = self.client.get("/school-platform/api/subaccounts", headers=headers).json()["data"]["owners"]
        self.assertGreaterEqual(len(owners), 1)
        unique_email = f"subform-{uuid.uuid4().hex[:8]}@jls.local"

        response = self.client.post(
            "/school-platform/admin/subaccounts/create",
            data={
                "owner_user_id": owners[0]["id"],
                "name": "Form Subaccount",
                "email": unique_email,
                "password": "temp123456",
                "role": "consultant",
                "status": "active",
                "scope_label": "大阪第 1 區",
                "permissions": "dashboard:read\nleads:read",
                "note": "表單建立測試",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("created=", response.headers["location"])

        created_page = self.client.get(response.headers["location"])
        self.assertEqual(created_page.status_code, 200)
        self.assertIn(unique_email, created_page.text)

    def test_admin_staff_performance_api(self) -> None:
        headers = self.login_headers()
        response = self.client.get("/school-platform/api/admin/staff-performance", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("summary", payload)
        self.assertIn("items", payload)
        self.assertGreater(payload["summary"]["total_staff"], 0)
        self.assertGreaterEqual(payload["summary"]["consultants"], 1)
        self.assertGreaterEqual(payload["summary"]["teachers"], 1)
        self.assertTrue(any(item["role"] == "teacher" for item in payload["items"]))

    def test_subaccount_api_create_and_login(self) -> None:
        headers = self.login_headers()
        unique_email = f"subapi-{uuid.uuid4().hex[:8]}@jls.local"
        response = self.client.post(
            "/school-platform/api/subaccounts",
            headers=headers,
            json={
                "name": "API Subaccount",
                "email": unique_email,
                "password": "sub123456",
                "role": "consultant",
                "scope_label": "加盟招商助理",
                "note": "API 建立測試",
            },
        )
        self.assertEqual(response.status_code, 200)
        created = response.json()["data"]
        self.assertEqual(created["account_type"], "sub_account")
        self.assertEqual(created["email"], unique_email)
        self.assertIsNotNone(created["parent_user_id"])

        directory = self.client.get("/school-platform/api/subaccounts", headers=headers)
        self.assertEqual(directory.status_code, 200)
        items = directory.json()["data"]["items"]
        self.assertTrue(any(item["email"] == unique_email for item in items))

        login_response = self.client.post(
            "/school-platform/api/auth/login",
            json={"email": unique_email, "password": "sub123456"},
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["data"]["access_token"]
        me_response = self.client.get(
            "/school-platform/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me_response.status_code, 200)
        me = me_response.json()["data"]
        self.assertEqual(me["account_type"], "sub_account")
        self.assertEqual(me["email"], unique_email)
        self.assertIsNotNone(me["parent_user_id"])

    def test_consultant_portal_page(self) -> None:
        response = self.client.get("/school-platform/consultant-portal?staff_name=Mika%20Chen")
        self.assertEqual(response.status_code, 200)
        self.assertIn("招生顧問工作台", response.text)
        self.assertIn("Mika Chen", response.text)
        self.assertIn("高意向名單", response.text)

    def test_consultant_dashboard_api(self) -> None:
        headers = self.login_headers()
        response = self.client.get(
            "/school-platform/api/consultant/dashboard?staff_name=Mika%20Chen",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["summary"]["consultant_name"], "Mika Chen")
        self.assertGreaterEqual(payload["summary"]["assigned_leads"], 1)
        self.assertIn("follow_up_queue", payload)
        self.assertIn("recently_updated", payload)
        self.assertTrue(any(item["name"] for item in payload["recently_updated"]))

    def test_consultant_lead_detail_page_and_api(self) -> None:
        headers = self.login_headers()
        dashboard = self.client.get(
            "/school-platform/api/consultant/dashboard?staff_name=Mika%20Chen",
            headers=headers,
        ).json()["data"]
        lead_id = dashboard["hot_leads"][0]["lead_id"]

        page_response = self.client.get(
            f"/school-platform/consultant-portal/leads/{lead_id}?staff_name=Mika%20Chen"
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("顧問案件詳情", page_response.text)
        self.assertIn("AI 跟進草稿", page_response.text)
        self.assertIn("新增跟進", page_response.text)

        api_response = self.client.get(
            f"/school-platform/api/consultant/leads/{lead_id}?staff_name=Mika%20Chen",
            headers=headers,
        )
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertEqual(payload["consultant_name"], "Mika Chen")
        self.assertIn("lead", payload)
        self.assertIn("logs", payload)
        self.assertIn("followup_draft", payload)
        self.assertEqual(payload["lead"]["assigned_staff_name"], "Mika Chen")

    def test_consultant_lead_status_and_log_submit(self) -> None:
        headers = self.login_headers()
        dashboard = self.client.get(
            "/school-platform/api/consultant/dashboard?staff_name=Mika%20Chen",
            headers=headers,
        ).json()["data"]
        lead_id = dashboard["hot_leads"][0]["lead_id"]

        status_response = self.client.post(
            f"/school-platform/consultant-portal/leads/{lead_id}/status",
            data={
                "staff_name": "Mika Chen",
                "status_value": "considering",
                "next_follow_up_at": "2026-04-30T10:30:00",
                "note": "先發送 AI 建議話術，兩天後再確認。",
            },
            follow_redirects=False,
        )
        self.assertEqual(status_response.status_code, 303)

        log_response = self.client.post(
            f"/school-platform/consultant-portal/leads/{lead_id}/logs",
            data={
                "staff_name": "Mika Chen",
                "contact_method": "line",
                "content": "已先用 LINE 傳送試聽與班級建議。",
                "next_action": "後天下午再次確認是否預約試聽。",
            },
            follow_redirects=False,
        )
        self.assertEqual(log_response.status_code, 303)

        lead_response = self.client.get(f"/school-platform/api/leads/{lead_id}", headers=headers)
        self.assertEqual(lead_response.status_code, 200)
        self.assertEqual(lead_response.json()["data"]["status"], "considering")

        logs_response = self.client.get(f"/school-platform/api/leads/{lead_id}/logs", headers=headers)
        self.assertEqual(logs_response.status_code, 200)
        self.assertTrue(any("LINE" in item["content"] or "試聽" in item["content"] for item in logs_response.json()["data"]))

    def test_admin_finance_page(self) -> None:
        response = self.client.get("/school-platform/admin/finance")
        self.assertEqual(response.status_code, 200)
        self.assertIn("財務中心", response.text)
        self.assertIn("最近付款", response.text)
        self.assertIn("已收款", response.text)

    def test_finance_overview_api(self) -> None:
        headers = self.login_headers()
        response = self.client.get("/school-platform/api/finance/overview", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("summary", payload)
        self.assertIn("recent_payments", payload)
        self.assertGreaterEqual(payload["summary"]["enrollment_total"], 1)
        self.assertTrue(isinstance(payload["recent_enrollments"], list))

    def test_admin_schedule_page(self) -> None:
        response = self.client.get("/school-platform/admin/schedule")
        self.assertEqual(response.status_code, 200)
        self.assertIn("排課中心", response.text)
        self.assertIn("教師排課負載", response.text)
        self.assertIn("排課衝堂檢查", response.text)

    def test_admin_schedule_api_detects_conflicts(self) -> None:
        headers = self.login_headers()
        course_slug = f"schedule-lab-{uuid.uuid4().hex[:8]}"
        course_response = self.client.post(
            "/school-platform/api/courses",
            headers=headers,
            json={
                "slug": course_slug,
                "name": "排課衝堂測試課程",
                "course_type": "生活日語",
                "level": "N4",
                "delivery_mode": "online",
                "price": 12800,
                "short_description": "測試排課衝堂。",
                "objectives": ["驗證排課中心"],
                "highlights": ["排課測試"],
                "modules": ["租屋", "購物"],
                "teacher_names": ["Aki Mori"],
            },
        )
        self.assertEqual(course_response.status_code, 200)

        class_one = self.client.post(
            "/school-platform/api/classes",
            headers=headers,
            json={
                "course_slug": course_slug,
                "name": "衝堂班 A",
                "teacher_name": "Aki Mori",
                "start_date": "2026-06-01",
                "end_date": "2026-07-01",
                "weekday": "Tue",
                "start_time": "19:00:00",
                "end_time": "20:30:00",
                "capacity": 12,
                "location_label": "Zoom Live",
                "status": "open",
            },
        )
        self.assertEqual(class_one.status_code, 200)

        class_two = self.client.post(
            "/school-platform/api/classes",
            headers=headers,
            json={
                "course_slug": course_slug,
                "name": "衝堂班 B",
                "teacher_name": "Aki Mori",
                "start_date": "2026-06-10",
                "end_date": "2026-07-10",
                "weekday": "Tue",
                "start_time": "20:00:00",
                "end_time": "21:30:00",
                "capacity": 12,
                "location_label": "Zoom Live",
                "status": "open",
            },
        )
        self.assertEqual(class_two.status_code, 200)

        response = self.client.get("/school-platform/api/admin/schedule", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("summary", payload)
        self.assertIn("conflicts", payload)
        self.assertGreaterEqual(payload["summary"]["detected_conflicts"], 1)
        self.assertTrue(any("衝堂班 A" in item["class_names"] and "衝堂班 B" in item["class_names"] for item in payload["conflicts"]))

    def test_admin_ai_teaching_page(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        response = self.client.get(
            f"/school-platform/admin/ai-teaching?class_id={class_id}&lesson_focus=租屋會話&duration_minutes=80"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI 教案草稿中心", response.text)
        self.assertIn("教學目標", response.text)
        self.assertIn("租屋會話", response.text)

    def test_ai_lesson_plan_draft_api(self) -> None:
        headers = self.login_headers()
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        response = self.client.post(
            "/school-platform/api/ai/lesson-plan-draft",
            headers=headers,
            json={
                "class_id": class_id,
                "lesson_focus": "藥局購物與詢問症狀",
                "duration_minutes": 90,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["lesson_focus"], "藥局購物與詢問症狀")
        self.assertGreaterEqual(len(payload["teaching_steps"]), 3)
        self.assertIn("objective", payload)
        self.assertIn("homework", payload)

    def test_admin_applicant_detail_page_and_api(self) -> None:
        headers = self.login_headers()
        job_response = self.client.post(
            "/school-platform/api/recruiting/jobs",
            headers=headers,
            json={
                "title": "招生顧問候選人",
                "department": "Admissions",
                "employment_type": "full_time",
                "location_label": "Taipei",
                "salary_range": "JPY 55,000 - 70,000 / month",
                "summary": "負責招生追蹤與轉換。",
                "requirements": ["CRM", "溝通能力", "教育產業加分"],
                "status": "open",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        position_id = job_response.json()["data"]["id"]

        applicant_response = self.client.post(
            "/school-platform/api/public/applicants",
            json={
                "position_id": position_id,
                "name": "顧問候選人",
                "email": "consultant-candidate@example.com",
                "phone": "0911666888",
                "resume_link": "https://example.com/consultant-resume.pdf",
                "note": "有教育顧問與招生經驗。",
            },
        )
        self.assertEqual(applicant_response.status_code, 200)
        applicant_id = applicant_response.json()["data"]["id"]

        page_response = self.client.get(f"/school-platform/admin/recruiting/applicants/{applicant_id}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("應徵者詳情", page_response.text)
        self.assertIn("建議面試題", page_response.text)
        self.assertIn("顧問候選人", page_response.text)

        api_response = self.client.get(f"/school-platform/api/recruiting/applicants/{applicant_id}", headers=headers)
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertEqual(payload["applicant"]["name"], "顧問候選人")
        self.assertEqual(payload["position"]["title"], "招生顧問候選人")
        self.assertIn("evaluation", payload)
        self.assertGreaterEqual(len(payload["evaluation"]["suggested_questions"]), 1)

    def test_student_ai_practice_page_and_api(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "ai-practice@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "AI 練習學員",
                "email": student_email,
                "phone": "0911999111",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        page_response = self.client.get(f"/school-platform/ai-practice?email={student_email}&theme=租屋與看房會話")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("AI 練習區", page_response.text)
        self.assertIn("租屋與看房會話", page_response.text)
        self.assertIn("關鍵句型", page_response.text)

        headers = self.login_headers()
        api_response = self.client.get(
            f"/school-platform/api/student/ai-practice?email={student_email}&theme=租屋與看房會話",
            headers=headers,
        )
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertEqual(payload["theme"], "租屋與看房會話")
        self.assertGreaterEqual(len(payload["key_phrases"]), 2)
        self.assertIn("ai_opening", payload)

    def test_teacher_portal_and_grading_flow(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "teacher-workspace@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "教師工作台學員",
                "email": student_email,
                "phone": "0911999000",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        headers = self.login_headers()
        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "待評分作業",
                "content": "請完成一段購物情境。",
                "due_at": "2026-05-03T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(assignment_response.status_code, 200)
        assignment_id = assignment_response.json()["data"]["id"]
        exam_response = self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "待評分測驗",
                "exam_type": "quiz",
                "instructions": "請完成 5 題文法題。",
                "total_score": 100,
                "due_at": "2026-05-04T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(exam_response.status_code, 200)
        exam_id = exam_response.json()["data"]["id"]

        assignment_submit = self.client.post(
            f"/school-platform/api/student/assignments/{assignment_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是我的作業內容"},
        )
        self.assertEqual(assignment_submit.status_code, 200)
        assignment_submission_id = assignment_submit.json()["data"]["id"]

        exam_submit = self.client.post(
            f"/school-platform/api/student/exams/{exam_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是我的測驗答案"},
        )
        self.assertEqual(exam_submit.status_code, 200)
        exam_submission_id = exam_submit.json()["data"]["id"]

        portal_response = self.client.get("/school-platform/teacher-portal?teacher_name=Aki%20Mori")
        self.assertEqual(portal_response.status_code, 200)
        self.assertIn("教師工作台", portal_response.text)
        self.assertIn("待評分作業", portal_response.text)
        self.assertIn("待評分測驗", portal_response.text)

        assignment_grade = self.client.post(
            f"/school-platform/api/assignments/submissions/{assignment_submission_id}/grade",
            headers=headers,
            json={"score": 92, "feedback": "內容完整", "graded_by": "Aki Mori"},
        )
        self.assertEqual(assignment_grade.status_code, 200)
        self.assertEqual(assignment_grade.json()["data"]["status"], "graded")

        exam_grade = self.client.post(
            f"/school-platform/api/exams/submissions/{exam_submission_id}/grade",
            headers=headers,
            json={"score": 95, "feedback": "表現很好", "graded_by": "Aki Mori"},
        )
        self.assertEqual(exam_grade.status_code, 200)
        self.assertEqual(exam_grade.json()["data"]["status"], "graded")

        dashboard = self.client.get(
            "/school-platform/api/teacher/dashboard?teacher_name=Aki%20Mori",
            headers=headers,
        )
        self.assertEqual(dashboard.status_code, 200)
        self.assertGreaterEqual(dashboard.json()["data"]["summary"]["class_count"], 1)

    def test_teacher_class_detail_page_and_api(self) -> None:
        headers = self.login_headers()
        class_item = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]
        class_id = class_item["id"]
        student_email = "teacher-class-detail@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "教師班級詳頁學員",
                "email": student_email,
                "phone": "0911777444",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "教師班級詳頁作業",
                "content": "請完成一段租屋對話。",
                "due_at": "2026-05-12T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(assignment_response.status_code, 200)
        assignment_id = assignment_response.json()["data"]["id"]

        exam_response = self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "教師班級詳頁測驗",
                "exam_type": "quiz",
                "instructions": "請完成 3 題生活情境題。",
                "total_score": 100,
                "due_at": "2026-05-13T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(exam_response.status_code, 200)
        exam_id = exam_response.json()["data"]["id"]

        self.client.post(
            "/school-platform/api/attendance",
            headers=headers,
            json={
                "class_id": class_id,
                "student_email": student_email,
                "class_date": "2026-04-25",
                "status": "present",
                "note": "準時到課",
                "marked_by": "Aki Mori",
            },
        )
        self.client.post(
            f"/school-platform/api/student/assignments/{assignment_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是班級詳頁作業答案。"},
        )
        self.client.post(
            f"/school-platform/api/student/exams/{exam_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是班級詳頁測驗答案。"},
        )

        page_response = self.client.get(
            f"/school-platform/teacher/classes/{class_id}?teacher_name=Aki%20Mori"
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("班級教學詳情", page_response.text)
        self.assertIn("學員名單", page_response.text)
        self.assertIn(student_email, page_response.text)
        self.assertIn("教師補充教材", page_response.text)

        api_response = self.client.get(
            f"/school-platform/api/teacher/classes/{class_id}?teacher_name=Aki%20Mori",
            headers=headers,
        )
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertEqual(payload["class_item"]["id"], class_id)
        self.assertGreaterEqual(payload["summary"]["total_students"], 1)
        self.assertTrue(any(item["email"] == student_email for item in payload["roster"]))

    def test_teacher_can_create_supplemental_material(self) -> None:
        teacher_headers = self.login_headers(email="aki@jls.local", password="aki123")
        class_item = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]
        class_id = class_item["id"]

        create_response = self.client.post(
            "/school-platform/api/teaching-materials",
            headers=teacher_headers,
            json={
                "course_slug": class_item["course_slug"],
                "class_id": class_id,
                "title": "老師補充教材測試",
                "description": "針對本班補充的會話講義。",
                "material_url": "https://school-platform.local/teacher-extra",
                "owner_type": "teacher",
                "visibility": "enrolled_only",
                "status": "published",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(create_response.status_code, 200)

        material_list = self.client.get(
            f"/school-platform/api/teaching-materials?class_id={class_id}&owner_type=teacher",
            headers=teacher_headers,
        )
        self.assertEqual(material_list.status_code, 200)
        self.assertTrue(any(item["title"] == "老師補充教材測試" for item in material_list.json()["data"]))

        forbidden = self.client.post(
            "/school-platform/api/teaching-materials",
            headers=teacher_headers,
            json={
                "course_slug": class_item["course_slug"],
                "class_id": class_id,
                "title": "老師不能建立平台教材",
                "description": "不應允許",
                "material_url": "https://school-platform.local/teacher-forbidden",
                "owner_type": "platform",
                "visibility": "public",
                "status": "published",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_uploaded_material_download_requires_enrollment_access(self) -> None:
        headers = self.login_headers()
        class_item = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]
        class_id = class_item["id"]
        student_email = "materials-center@example.com"

        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "教材學員",
                "email": student_email,
                "phone": "0900666777",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        upload_response = self.client.post(
            f"/school-platform/teacher/classes/{class_id}/materials",
            data={
                "teacher_name": "Aki Mori",
                "title": "班級上傳教材測試",
                "description": "這份檔案用來驗證學員教材下載權限。",
                "material_url": "",
                "visibility": "enrolled_only",
            },
            files={"uploaded_file": ("class-notes.txt", b"uploaded lesson notes", "text/plain")},
            follow_redirects=False,
        )
        self.assertEqual(upload_response.status_code, 303)

        materials_response = self.client.get(
            f"/school-platform/api/student/materials?email={student_email}",
            headers=headers,
        )
        self.assertEqual(materials_response.status_code, 200)
        uploaded_item = next(item for item in materials_response.json()["data"] if item["title"] == "班級上傳教材測試")
        self.assertEqual(uploaded_item["storage_kind"], "uploaded_file")

        forbidden_response = self.client.get(
            f"/school-platform/materials/{uploaded_item['id']}/download",
            follow_redirects=False,
        )
        self.assertEqual(forbidden_response.status_code, 403)

        download_response = self.client.get(
            f"/school-platform/materials/{uploaded_item['id']}/download?email={student_email}",
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("text/plain", download_response.headers["content-type"])
        self.assertEqual(download_response.content, b"uploaded lesson notes")

    def test_teacher_class_detail_form_actions(self) -> None:
        headers = self.login_headers()
        class_item = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]
        class_id = class_item["id"]
        student_email = "teacher-class-actions@example.com"

        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "教師班級操作學員",
                "email": student_email,
                "phone": "0911333666",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "班級詳頁待批改作業",
                "content": "請完成一段餐廳會話。",
                "due_at": "2026-05-15T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(assignment_response.status_code, 200)
        assignment_id = assignment_response.json()["data"]["id"]

        exam_response = self.client.post(
            "/school-platform/api/exams",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "班級詳頁待批改測驗",
                "exam_type": "quiz",
                "instructions": "請完成 4 題情境題。",
                "total_score": 100,
                "due_at": "2026-05-16T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(exam_response.status_code, 200)
        exam_id = exam_response.json()["data"]["id"]

        assignment_submit = self.client.post(
            f"/school-platform/api/student/assignments/{assignment_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是班級操作作業答案。"},
        )
        self.assertEqual(assignment_submit.status_code, 200)
        assignment_submission_id = assignment_submit.json()["data"]["id"]

        exam_submit = self.client.post(
            f"/school-platform/api/student/exams/{exam_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是班級操作測驗答案。"},
        )
        self.assertEqual(exam_submit.status_code, 200)
        exam_submission_id = exam_submit.json()["data"]["id"]

        class_path = f"/school-platform/teacher/classes/{class_id}?teacher_name=Aki%20Mori"
        page_response = self.client.get(class_path)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("快速點名", page_response.text)
        self.assertIn("待批改作業", page_response.text)
        self.assertIn("待批改測驗", page_response.text)

        attendance_submit = self.client.post(
            f"/school-platform/teacher/classes/{class_id}/attendance",
            data={
                "teacher_name": "Aki Mori",
                "student_email": student_email,
                "class_date_value": "2026-05-11",
                "status_value": "late",
                "note": "晚到 8 分鐘",
            },
            follow_redirects=False,
        )
        self.assertEqual(attendance_submit.status_code, 303)
        self.assertIn(f"/school-platform/teacher/classes/{class_id}", attendance_submit.headers["location"])

        assignment_grade_submit = self.client.post(
            f"/school-platform/teacher/assignment-submissions/{assignment_submission_id}/grade",
            data={
                "teacher_name": "Aki Mori",
                "score": "93",
                "feedback": "句型使用自然。",
                "graded_by": "Aki Mori",
                "return_to": class_path,
            },
            follow_redirects=False,
        )
        self.assertEqual(assignment_grade_submit.status_code, 303)
        self.assertIn(f"/school-platform/teacher/classes/{class_id}", assignment_grade_submit.headers["location"])

        exam_grade_submit = self.client.post(
            f"/school-platform/teacher/exam-submissions/{exam_submission_id}/grade",
            data={
                "teacher_name": "Aki Mori",
                "score": "96",
                "feedback": "理解很好。",
                "graded_by": "Aki Mori",
                "return_to": class_path,
            },
            follow_redirects=False,
        )
        self.assertEqual(exam_grade_submit.status_code, 303)
        self.assertIn(f"/school-platform/teacher/classes/{class_id}", exam_grade_submit.headers["location"])

        api_response = self.client.get(
            f"/school-platform/api/teacher/classes/{class_id}?teacher_name=Aki%20Mori",
            headers=headers,
        )
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertTrue(any(item["status"] == "late" for item in payload["attendance_records"]))
        self.assertTrue(any(item["feedback"] == "句型使用自然。" for item in payload["assignment_submissions"]))
        self.assertTrue(any(item["feedback"] == "理解很好。" for item in payload["exam_submissions"]))

    def test_teaching_session_record_workflow_api_and_form(self) -> None:
        headers = self.login_headers()
        class_item = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]
        class_id = class_item["id"]
        class_path = f"/school-platform/teacher/classes/{class_id}?teacher_name=Aki%20Mori"

        submit_response = self.client.post(
            f"/school-platform/teacher/classes/{class_id}/session-records",
            data={
                "teacher_name": "Aki Mori",
                "class_date_value": "2026-05-12",
                "summary_text": "完成租屋問答與藥局購藥情境演練。",
                "materials_link": "https://example.com/materials/lesson-12",
                "homework_summary": "錄製 60 秒租屋自我介紹。",
                "next_class_focus": "病院掛號與症狀描述",
                "student_risk_notes": "王小明：連續兩週未交作業\n陳小華：出席不穩定",
                "approval_status_value": "submitted",
                "return_to": class_path,
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)
        self.assertIn(f"/school-platform/teacher/classes/{class_id}", submit_response.headers["location"])

        teacher_page = self.client.get(class_path)
        self.assertEqual(teacher_page.status_code, 200)
        self.assertIn("新增 / 更新課後紀錄", teacher_page.text)
        self.assertIn("完成租屋問答與藥局購藥情境演練", teacher_page.text)

        teacher_dashboard = self.client.get(
            "/school-platform/api/teacher/dashboard?teacher_name=Aki%20Mori",
            headers=headers,
        )
        self.assertEqual(teacher_dashboard.status_code, 200)
        dashboard_payload = teacher_dashboard.json()["data"]
        self.assertGreaterEqual(dashboard_payload["summary"]["session_record_count"], 1)
        self.assertGreaterEqual(dashboard_payload["summary"]["pending_session_reviews"], 1)

        session_list = self.client.get(
            f"/school-platform/api/teaching/session-records?class_id={class_id}",
            headers=headers,
        )
        self.assertEqual(session_list.status_code, 200)
        session_payload = session_list.json()["data"]
        self.assertGreaterEqual(len(session_payload), 1)
        session_record_id = session_payload[0]["id"]
        self.assertEqual(session_payload[0]["approval_status"], "submitted")

        admin_page = self.client.get("/school-platform/admin/teaching")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("待審核課後紀錄", admin_page.text)

        review_submit = self.client.post(
            f"/school-platform/admin/teaching/session-records/{session_record_id}/review",
            data={
                "approval_status_value": "approved",
                "review_note": "教材與高風險學員追蹤都已補齊。",
                "reviewed_by": "Yuki Wang",
            },
            follow_redirects=False,
        )
        self.assertEqual(review_submit.status_code, 303)
        self.assertEqual(review_submit.headers["location"], "/school-platform/admin/teaching")

        class_api = self.client.get(
            f"/school-platform/api/teacher/classes/{class_id}?teacher_name=Aki%20Mori",
            headers=headers,
        )
        self.assertEqual(class_api.status_code, 200)
        snapshot = class_api.json()["data"]
        self.assertTrue(any(item["approval_status"] == "approved" for item in snapshot["session_records"]))
        self.assertTrue(any(item["review_note"] == "教材與高風險學員追蹤都已補齊。" for item in snapshot["session_records"]))

    def test_teacher_verification_flow_api_and_pages(self) -> None:
        teacher_headers = self.login_headers(email="aki@jls.local", password="aki123")

        page_response = self.client.get("/school-platform/teacher/verification?teacher_name=Aki%20Mori")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("教師教學手冊與開課驗證", page_response.text)
        self.assertIn("開課驗證測驗", page_response.text)

        api_response = self.client.get(
            "/school-platform/api/teacher/verification?teacher_name=Aki%20Mori",
            headers=teacher_headers,
        )
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertGreaterEqual(len(payload["manual_sections"]), 3)
        self.assertGreaterEqual(len(payload["questions"]), 6)
        self.assertIn(payload["pass_status"], {"not_started", "passed", "retry_required"})

        answer_key = {
            "老師登入平台後的第一件事應該是什麼？": "B",
            "學員口說流暢度追蹤卡最晚應在何時提交？": "A",
            "平台要求每堂真人課至少保留多少 Shadowing 時間？": "C",
            "最符合平台黃金口說教學法的開場方式是？": "B",
            "老師在課前面對 AI 草稿時，最正確的做法是什麼？": "B",
            "如果老師觀察到的弱點與 AI 建議不同，應如何處理？": "B",
        }
        answers = {item["id"]: answer_key[item["prompt"]] for item in payload["questions"]}

        submit_response = self.client.post(
            "/school-platform/api/teacher/verification",
            headers=teacher_headers,
            json={"teacher_name": "Aki Mori", "answers": answers},
        )
        self.assertEqual(submit_response.status_code, 200)
        self.assertTrue(submit_response.json()["data"]["passed"])
        self.assertTrue(submit_response.json()["data"]["unlocked_permission"])

        follow_up = self.client.get(
            "/school-platform/api/teacher/verification?teacher_name=Aki%20Mori",
            headers=teacher_headers,
        )
        self.assertEqual(follow_up.status_code, 200)
        follow_payload = follow_up.json()["data"]
        self.assertEqual(follow_payload["pass_status"], "passed")
        self.assertTrue(follow_payload["unlocked_permission"])
        self.assertGreaterEqual(follow_payload["latest_attempt"]["score"], 85)

        current_user = self.client.get("/school-platform/api/auth/me", headers=teacher_headers)
        self.assertEqual(current_user.status_code, 200)
        self.assertIn("teaching:verified", current_user.json()["data"]["permissions"])

        admin_page = self.client.get("/school-platform/admin/teacher-verification")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("教師開課驗證總覽", admin_page.text)
        self.assertIn("Aki Mori", admin_page.text)

        admin_api = self.client.get("/school-platform/api/admin/teacher-verification", headers=self.login_headers())
        self.assertEqual(admin_api.status_code, 200)
        self.assertTrue(any(item["teacher_name"] == "Aki Mori" for item in admin_api.json()["data"]))

        teachers_page = self.client.get("/school-platform/admin/teachers")
        self.assertEqual(teachers_page.status_code, 200)
        self.assertIn("查看教學驗證", teachers_page.text)

    def test_public_jobs_page_and_apply_flow(self) -> None:
        jobs_response = self.client.get("/school-platform/api/public/jobs")
        self.assertEqual(jobs_response.status_code, 200)
        jobs = jobs_response.json()["data"]
        self.assertGreaterEqual(len(jobs), 1)

        page_response = self.client.get(f"/school-platform/jobs?position_id={jobs[0]['id']}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("加入 AI 日語補習班團隊", page_response.text)

        submit_response = self.client.post(
            "/school-platform/jobs/apply",
            data={
                "position_id": jobs[0]["id"],
                "name": "應徵者小林",
                "email": "job-applicant@example.com",
                "phone": "0911222333",
                "resume_link": "https://example.com/resume.pdf",
                "note": "具日語教學與招生經驗",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)
        self.assertIn("/school-platform/jobs/success?", submit_response.headers["location"])

    def test_admin_recruiting_page_and_interview_flow(self) -> None:
        headers = self.login_headers()
        job_response = self.client.post(
            "/school-platform/api/recruiting/jobs",
            headers=headers,
            json={
                "title": "行政客服",
                "department": "Operations",
                "employment_type": "full_time",
                "location_label": "Taipei",
                "salary_range": "JPY 180,000 - 240,000 / month",
                "summary": "負責行政與客服支援。",
                "requirements": ["細心", "可處理家長與學員需求"],
                "status": "open",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        job_id = job_response.json()["data"]["id"]

        applicant_response = self.client.post(
            "/school-platform/api/public/applicants",
            json={
                "position_id": job_id,
                "name": "面試候選人",
                "email": "recruit-candidate@example.com",
                "phone": "0911555777",
                "resume_link": "https://example.com/candidate.pdf",
                "note": "曾任教務行政",
            },
        )
        self.assertEqual(applicant_response.status_code, 200)
        applicant_id = applicant_response.json()["data"]["id"]

        recruiting_page = self.client.get("/school-platform/admin/recruiting")
        self.assertEqual(recruiting_page.status_code, 200)
        self.assertIn("招聘管理", recruiting_page.text)
        self.assertIn("新增職缺", recruiting_page.text)

        interview_response = self.client.post(
            "/school-platform/api/recruiting/interviews",
            headers=headers,
            json={
                "applicant_id": applicant_id,
                "interview_at": "2026-05-05T14:00:00+08:00",
                "interviewer_name": "Yuki Wang",
                "format": "google_meet",
                "status": "scheduled",
            },
        )
        self.assertEqual(interview_response.status_code, 200)
        self.assertEqual(interview_response.json()["data"]["status"], "scheduled")

    def test_recruiting_review_api_updates_interview_and_applicant(self) -> None:
        headers = self.login_headers()
        job_response = self.client.post(
            "/school-platform/api/recruiting/jobs",
            headers=headers,
            json={
                "title": "教務主任",
                "department": "Operations",
                "employment_type": "full_time",
                "location_label": "Taipei",
                "salary_range": "JPY 260,000 - 320,000 / month",
                "summary": "負責教務排程與班務協調。",
                "requirements": ["排課協調", "跨部門溝通"],
                "status": "open",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        position_id = job_response.json()["data"]["id"]

        applicant_response = self.client.post(
            "/school-platform/api/public/applicants",
            json={
                "position_id": position_id,
                "name": "招聘流程測試者",
                "email": "recruiting-review@example.com",
                "phone": "0911888999",
                "resume_link": "https://example.com/recruiting-review.pdf",
                "note": "有教務與行政管理經驗。",
            },
        )
        self.assertEqual(applicant_response.status_code, 200)
        applicant_id = applicant_response.json()["data"]["id"]

        interview_response = self.client.post(
            "/school-platform/api/recruiting/interviews",
            headers=headers,
            json={
                "applicant_id": applicant_id,
                "interview_at": "2026-05-12T10:00:00+08:00",
                "interviewer_name": "Yuki Wang",
                "format": "google_meet",
                "status": "scheduled",
            },
        )
        self.assertEqual(interview_response.status_code, 200)
        interview_id = interview_response.json()["data"]["id"]

        review_response = self.client.patch(
            f"/school-platform/api/recruiting/interviews/{interview_id}",
            headers=headers,
            json={"status": "completed", "feedback": "面試表現穩定，適合進第二輪。"},
        )
        self.assertEqual(review_response.status_code, 200)
        self.assertEqual(review_response.json()["data"]["status"], "completed")

        applicant_update = self.client.patch(
            f"/school-platform/api/recruiting/applicants/{applicant_id}/status",
            headers=headers,
            json={"interview_status": "shortlisted", "note": "安排第二輪與試教。"},
        )
        self.assertEqual(applicant_update.status_code, 200)
        self.assertEqual(applicant_update.json()["data"]["interview_status"], "shortlisted")

        detail_response = self.client.get(f"/school-platform/api/recruiting/applicants/{applicant_id}", headers=headers)
        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()["data"]
        self.assertEqual(payload["applicant"]["interview_status"], "shortlisted")
        self.assertIn("安排第二輪與試教", payload["applicant"]["note"])
        self.assertTrue(any(item["status"] == "completed" for item in payload["interviews"]))
        self.assertTrue(any("適合進第二輪" in (item["feedback"] or "") for item in payload["interviews"]))

    def test_admin_applicant_detail_review_form_submit(self) -> None:
        headers = self.login_headers()
        job_response = self.client.post(
            "/school-platform/api/recruiting/jobs",
            headers=headers,
            json={
                "title": "HR 測試職缺",
                "department": "Operations",
                "employment_type": "full_time",
                "location_label": "Taipei",
                "salary_range": "JPY 200,000 - 260,000 / month",
                "summary": "測試應徵者詳頁表單。",
                "requirements": ["表單測試"],
                "status": "open",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        position_id = job_response.json()["data"]["id"]

        applicant_response = self.client.post(
            "/school-platform/api/public/applicants",
            json={
                "position_id": position_id,
                "name": "表單面試候選人",
                "email": "applicant-form-review@example.com",
                "phone": "0911222555",
                "resume_link": "https://example.com/form-review.pdf",
                "note": "先安排一輪正式面談。",
            },
        )
        self.assertEqual(applicant_response.status_code, 200)
        applicant_id = applicant_response.json()["data"]["id"]

        interview_response = self.client.post(
            "/school-platform/api/recruiting/interviews",
            headers=headers,
            json={
                "applicant_id": applicant_id,
                "interview_at": "2026-05-18T15:00:00+08:00",
                "interviewer_name": "Yuki Wang",
                "format": "onsite",
                "status": "scheduled",
            },
        )
        self.assertEqual(interview_response.status_code, 200)
        interview_id = interview_response.json()["data"]["id"]

        submit_response = self.client.post(
            f"/school-platform/admin/recruiting/interviews/{interview_id}/review",
            data={
                "interview_status_value": "hired",
                "applicant_status": "hired",
                "feedback": "整體表現成熟，可直接錄取。",
                "note": "安排 offer 與報到流程。",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 303)
        self.assertIn(f"/school-platform/admin/recruiting/applicants/{applicant_id}", submit_response.headers["location"])

        page_response = self.client.get(submit_response.headers["location"])
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("整體表現成熟，可直接錄取。", page_response.text)
        self.assertIn("hired", page_response.text)
        self.assertIn("到職 / 試用追蹤", page_response.text)

        detail_response = self.client.get(f"/school-platform/api/recruiting/applicants/{applicant_id}", headers=headers)
        self.assertEqual(detail_response.status_code, 200)
        self.assertIsNotNone(detail_response.json()["data"]["onboarding"])
        self.assertEqual(detail_response.json()["data"]["onboarding"]["stage"], "preboarding")

    def test_recruiting_onboarding_api_and_form(self) -> None:
        headers = self.login_headers()
        job_response = self.client.post(
            "/school-platform/api/recruiting/jobs",
            headers=headers,
            json={
                "title": "到職流程測試職缺",
                "department": "Operations",
                "employment_type": "full_time",
                "location_label": "Taipei",
                "salary_range": "JPY 230,000 - 300,000 / month",
                "summary": "測試 onboarding 與 probation 追蹤。",
                "requirements": ["流程管理", "文件整理"],
                "status": "open",
            },
        )
        self.assertEqual(job_response.status_code, 200)
        position_id = job_response.json()["data"]["id"]

        applicant_response = self.client.post(
            "/school-platform/api/public/applicants",
            json={
                "position_id": position_id,
                "name": "到職流程候選人",
                "email": "onboarding-flow@example.com",
                "phone": "0911333444",
                "resume_link": "https://example.com/onboarding.pdf",
                "note": "可於下月報到。",
            },
        )
        self.assertEqual(applicant_response.status_code, 200)
        applicant_id = applicant_response.json()["data"]["id"]

        hired_response = self.client.patch(
            f"/school-platform/api/recruiting/applicants/{applicant_id}/status",
            headers=headers,
            json={"interview_status": "hired", "note": "直接建立到職與試用流程。"},
        )
        self.assertEqual(hired_response.status_code, 200)

        onboarding_response = self.client.put(
            f"/school-platform/api/recruiting/applicants/{applicant_id}/onboarding",
            headers=headers,
            json={
                "owner_name": "Yuki Wang",
                "stage": "active",
                "start_date": "2026-06-01",
                "probation_status": "in_progress",
                "probation_end_date": "2026-08-31",
                "checklist_items": ["建立帳號", "完成校務訓練", "安排第一次主管回饋"],
                "notes": "第一週完成系統權限與班務流程說明。",
            },
        )
        self.assertEqual(onboarding_response.status_code, 200)
        self.assertEqual(onboarding_response.json()["data"]["probation_status"], "in_progress")

        form_response = self.client.post(
            f"/school-platform/admin/recruiting/applicants/{applicant_id}/onboarding",
            data={
                "owner_name": "Yuki Wang",
                "stage": "completed",
                "start_date": "2026-06-01",
                "probation_status": "passed",
                "probation_end_date": "2026-08-31",
                "checklist_items": "建立帳號\n完成校務訓練\n安排第一次主管回饋",
                "notes": "已完成 onboarding，試用評估通過。",
            },
            follow_redirects=False,
        )
        self.assertEqual(form_response.status_code, 303)
        self.assertIn(f"/school-platform/admin/recruiting/applicants/{applicant_id}", form_response.headers["location"])

        detail_response = self.client.get(f"/school-platform/api/recruiting/applicants/{applicant_id}", headers=headers)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["data"]["onboarding"]["stage"], "completed")
        self.assertEqual(detail_response.json()["data"]["onboarding"]["probation_status"], "passed")
        self.assertIn("已完成 onboarding", detail_response.json()["data"]["onboarding"]["notes"])

    def test_reports_and_ai_center_pages(self) -> None:
        headers = self.login_headers()
        reports_page = self.client.get("/school-platform/admin/reports")
        self.assertEqual(reports_page.status_code, 200)
        self.assertIn("報表中心", reports_page.text)
        self.assertIn("班級滿班率", reports_page.text)
        self.assertIn("線上學習紀錄摘要", reports_page.text)
        self.assertIn("加盟組招生流程摘要", reports_page.text)
        self.assertIn("/school-platform/api/reports/student-learning", reports_page.text)
        self.assertIn("/school-platform/api/reports/franchise-groups", reports_page.text)

        ai_center_page = self.client.get("/school-platform/admin/ai-center")
        self.assertEqual(ai_center_page.status_code, 200)
        self.assertIn("AI 助理中心", ai_center_page.text)
        self.assertIn("AI 操作紀錄", ai_center_page.text)
        self.assertIn("AI Provider 狀態", ai_center_page.text)
        self.assertIn("/school-platform/api/ai/status", ai_center_page.text)

        reports_api = self.client.get("/school-platform/api/reports/overview", headers=headers)
        self.assertEqual(reports_api.status_code, 200)
        self.assertIn("lead_status_counts", reports_api.json()["data"])

        learning_reports_api = self.client.get("/school-platform/api/reports/student-learning", headers=headers)
        self.assertEqual(learning_reports_api.status_code, 200)
        self.assertIn("summary", learning_reports_api.json()["data"])
        self.assertIn("items", learning_reports_api.json()["data"])

        franchise_reports_api = self.client.get("/school-platform/api/reports/franchise-groups", headers=headers)
        self.assertEqual(franchise_reports_api.status_code, 200)
        self.assertEqual(len(franchise_reports_api.json()["data"]["groups"]), 3)
        self.assertTrue(any(item["group_name"] == "大阪單區加盟組" for item in franchise_reports_api.json()["data"]["groups"]))

        operations_reports_api = self.client.get("/school-platform/api/reports/operations", headers=headers)
        self.assertEqual(operations_reports_api.status_code, 200)
        self.assertIn("student_learning", operations_reports_api.json()["data"])
        self.assertIn("franchise_groups", operations_reports_api.json()["data"])

        weekly_api = self.client.get("/school-platform/api/reports/weekly-summary", headers=headers)
        self.assertEqual(weekly_api.status_code, 200)
        self.assertIn("headline", weekly_api.json()["data"])
        self.assertIn("actions", weekly_api.json()["data"])

        ai_logs_api = self.client.get("/school-platform/api/ai/logs", headers=headers)
        self.assertEqual(ai_logs_api.status_code, 200)
        self.assertGreaterEqual(len(ai_logs_api.json()["data"]), 1)

        ai_status_api = self.client.get("/school-platform/api/ai/status", headers=headers)
        self.assertEqual(ai_status_api.status_code, 200)
        self.assertIn("service_ready", ai_status_api.json()["data"])
        self.assertIn("active_provider", ai_status_api.json()["data"])
        self.assertIn("supported_features", ai_status_api.json()["data"])

    def test_learning_and_franchise_report_pages(self) -> None:
        headers = self.login_headers()
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "learning-report@example.com"
        self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "學習報表學員",
                "email": student_email,
                "phone": "0911555777",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        assignment_response = self.client.post(
            "/school-platform/api/assignments",
            headers=headers,
            json={
                "class_id": class_id,
                "title": "學習報表作業",
                "content": "請提交一段自我介紹錄音稿。",
                "due_at": "2026-05-18T20:00:00+08:00",
                "created_by": "Aki Mori",
            },
        )
        self.assertEqual(assignment_response.status_code, 200)
        assignment_id = assignment_response.json()["data"]["id"]
        attendance_response = self.client.post(
            "/school-platform/api/attendance",
            headers=headers,
            json={
                "class_id": class_id,
                "student_email": student_email,
                "class_date": "2026-05-12",
                "status": "present",
                "note": "正常到課",
                "marked_by": "Aki Mori",
            },
        )
        self.assertEqual(attendance_response.status_code, 200)
        submit_response = self.client.post(
            f"/school-platform/api/student/assignments/{assignment_id}/submit",
            headers=headers,
            json={"email": student_email, "content": "這是加盟管理學員的學習作業。"},
        )
        self.assertEqual(submit_response.status_code, 200)

        learning_page = self.client.get("/school-platform/admin/reports/learning")
        self.assertEqual(learning_page.status_code, 200)
        self.assertIn("線上學習紀錄報表", learning_page.text)
        self.assertIn("目前線上學習紀錄", learning_page.text)
        self.assertIn(student_email, learning_page.text)

        franchise_page = self.client.get("/school-platform/admin/reports/franchise")
        self.assertEqual(franchise_page.status_code, 200)
        self.assertIn("加盟組招生流程報表", franchise_page.text)
        self.assertIn("大阪單區加盟組", franchise_page.text)

    def test_admin_executive_dashboard_page_and_api(self) -> None:
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "executive-dashboard@example.com"
        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "主管工作台學員",
                "email": student_email,
                "phone": "0911777333",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)
        self.client.post(
            "/school-platform/help-center/submit",
            data={
                "email": student_email,
                "topic": "上課問題",
                "preferred_channel": "email",
                "message": "想確認最近一堂課的 Zoom 連結。",
            },
            follow_redirects=False,
        )

        page_response = self.client.get("/school-platform/admin/executive")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("主管工作台", page_response.text)
        self.assertIn("營運警示", page_response.text)
        self.assertIn("線上學習追蹤", page_response.text)
        self.assertIn("加盟組招商追蹤", page_response.text)
        self.assertIn("熱度最高名單", page_response.text)
        self.assertIn("高風險學員", page_response.text)

        headers = self.login_headers()
        api_response = self.client.get("/school-platform/api/admin/executive-dashboard", headers=headers)
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertIn("summary", payload)
        self.assertIn("alerts", payload)
        self.assertIn("hot_leads", payload)
        self.assertIn("class_watchlist", payload)
        self.assertGreaterEqual(payload["summary"]["active_classes"], 1)
        self.assertGreaterEqual(payload["summary"]["active_students"], 1)

    def test_admin_executive_dashboard_api_recommendations(self) -> None:
        headers = self.login_headers()
        api_response = self.client.get("/school-platform/api/admin/executive-dashboard", headers=headers)
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()["data"]
        self.assertGreaterEqual(len(payload["alerts"]), 1)
        self.assertGreaterEqual(len(payload["recommendations"]), 1)
        self.assertIn("ai_module_usage", payload)
        self.assertGreaterEqual(len(payload["ai_module_usage"]), 1)

    def test_admin_teaching_page_links(self) -> None:
        response = self.client.get("/school-platform/admin/teaching")
        self.assertEqual(response.status_code, 200)
        self.assertIn("教務管理", response.text)
        self.assertIn("發布作業", response.text)
        self.assertIn("建立測驗", response.text)

    def test_manager_can_create_course_and_class(self) -> None:
        headers = self.login_headers()

        course_response = self.client.post(
            "/school-platform/api/courses",
            headers=headers,
            json={
                "slug": "survival-japanese-night",
                "name": "日本生活生存會話夜間班",
                "course_type": "生活日語",
                "level": "N5",
                "delivery_mode": "online",
                "price": 11800,
                "short_description": "給晚間上班族的生活會話班。",
                "objectives": ["生活自理", "會話應答"],
                "highlights": ["夜間上課"],
                "modules": ["問路", "購物"],
                "teacher_names": ["Aki Mori"],
            },
        )
        self.assertEqual(course_response.status_code, 200)

        class_response = self.client.post(
            "/school-platform/api/classes",
            headers=headers,
            json={
                "course_slug": "survival-japanese-night",
                "name": "6 月夜間班",
                "teacher_name": "Aki Mori",
                "start_date": "2026-06-01",
                "end_date": "2026-07-15",
                "weekday": "Tue / Thu",
                "start_time": "19:30:00",
                "end_time": "21:00:00",
                "capacity": 16,
                "location_label": "Zoom Live",
                "status": "open",
            },
        )
        self.assertEqual(class_response.status_code, 200)

        consultant_headers = self.login_headers(email="mika@jls.local", password="mika123")
        forbidden = self.client.post(
            "/school-platform/api/courses",
            headers=consultant_headers,
            json={
                "slug": "forbidden-course",
                "name": "Forbidden",
                "course_type": "生活日語",
                "level": "N5",
                "delivery_mode": "online",
                "price": 1,
                "short_description": "x",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_student_dashboard_and_notifications(self) -> None:
        headers = self.login_headers()
        class_id = self.client.get("/school-platform/api/public/classes/open").json()["data"][0]["id"]
        student_email = "portal@example.com"

        enrollment_response = self.client.post(
            "/school-platform/api/public/enrollments",
            json={
                "chinese_name": "學員中心測試",
                "email": student_email,
                "phone": "0900999888",
                "class_id": class_id,
                "payment_method": "card",
            },
        )
        self.assertEqual(enrollment_response.status_code, 200)

        dashboard_response = self.client.get(
            f"/school-platform/api/student/dashboard?email={student_email}",
            headers=headers,
        )
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard = dashboard_response.json()["data"]
        self.assertEqual(dashboard["student"]["email"], student_email)
        self.assertGreaterEqual(len(dashboard["active_courses"]), 1)

        courses_response = self.client.get(
            f"/school-platform/api/student/courses?email={student_email}",
            headers=headers,
        )
        self.assertEqual(courses_response.status_code, 200)
        self.assertGreaterEqual(len(courses_response.json()["data"]), 1)

        materials_response = self.client.get(
            f"/school-platform/api/student/materials?email={student_email}",
            headers=headers,
        )
        self.assertEqual(materials_response.status_code, 200)
        self.assertGreaterEqual(len(materials_response.json()["data"]), 1)

        payments_response = self.client.get(
            f"/school-platform/api/student/payments?email={student_email}",
            headers=headers,
        )
        self.assertEqual(payments_response.status_code, 200)
        self.assertGreaterEqual(len(payments_response.json()["data"]), 1)

        notifications_response = self.client.get(
            f"/school-platform/api/student/notifications?email={student_email}",
            headers=headers,
        )
        self.assertEqual(notifications_response.status_code, 200)
        self.assertGreaterEqual(len(notifications_response.json()["data"]), 1)

        portal_page_response = self.client.get(f"/school-platform/student-portal?email={student_email}")
        self.assertEqual(portal_page_response.status_code, 200)
        self.assertIn("學員中心總覽", portal_page_response.text)
        self.assertIn(student_email, portal_page_response.text)
        self.assertIn("教材中心", portal_page_response.text)

        materials_page_response = self.client.get(f"/school-platform/my-materials?email={student_email}")
        self.assertEqual(materials_page_response.status_code, 200)
        self.assertIn("教材中心", materials_page_response.text)

    def test_course_detail_page(self) -> None:
        courses = self.client.get("/school-platform/api/public/courses").json()["data"]
        slug = courses[0]["slug"]

        response = self.client.get(f"/school-platform/courses/{slug}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("目前可報名班級", response.text)
        self.assertIn(slug, response.text)
        self.assertIn("平台標準教材", response.text)
        self.assertIn("教師補充內容", response.text)

    def test_public_course_content_snapshot(self) -> None:
        slug = self.client.get("/school-platform/api/public/courses").json()["data"][0]["slug"]
        response = self.client.get(f"/school-platform/api/public/courses/{slug}/content")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("core_modules", payload)
        self.assertIn("platform_materials", payload)
        self.assertIn("teacher_materials", payload)
        self.assertGreaterEqual(len(payload["core_modules"]), 1)
        self.assertGreaterEqual(len(payload["governance_notes"]), 1)

    def test_admin_leads_page(self) -> None:
        response = self.client.get("/school-platform/admin/leads")
        self.assertEqual(response.status_code, 200)
        self.assertIn("招生名單管理", response.text)
        self.assertIn("熱度", response.text)

    def test_admin_lead_detail_page(self) -> None:
        headers = self.login_headers()
        leads = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]
        lead_id = leads[0]["id"]

        response = self.client.get(f"/school-platform/admin/leads/{lead_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("跟進紀錄", response.text)
        self.assertIn(leads[0]["name"], response.text)

    def test_admin_classes_page(self) -> None:
        response = self.client.get("/school-platform/admin/classes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("班級管理", response.text)
        self.assertIn("名額", response.text)

    def test_admin_courses_page(self) -> None:
        response = self.client.get("/school-platform/admin/courses")
        self.assertEqual(response.status_code, 200)
        self.assertIn("課程管理", response.text)
        self.assertIn("新增課程", response.text)
        self.assertIn("課程內容治理", response.text)

    def test_admin_course_content_governance_pages_and_form(self) -> None:
        headers = self.login_headers()
        slug = self.client.get("/school-platform/api/public/courses").json()["data"][0]["slug"]

        page_response = self.client.get("/school-platform/admin/course-content")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("課程內容治理", page_response.text)

        detail_response = self.client.get(f"/school-platform/admin/course-content/{slug}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("平台核心章節", detail_response.text)
        self.assertIn("平台標準教材", detail_response.text)

        create_response = self.client.post(
            f"/school-platform/admin/course-content/{slug}/modules/create",
            data={
                "title": "追加平台核心章節",
                "description": "這是平台維護的核心章節。",
                "sort_order": "99",
                "material_url": "https://school-platform.local/platform-extra-module",
                "created_by": "Platform Curriculum Team",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        modules_response = self.client.get(
            f"/school-platform/api/course-modules?course_slug={slug}",
            headers=headers,
        )
        self.assertEqual(modules_response.status_code, 200)
        self.assertTrue(any(item["title"] == "追加平台核心章節" for item in modules_response.json()["data"]))

    def test_admin_teachers_page(self) -> None:
        response = self.client.get("/school-platform/admin/teachers")
        self.assertEqual(response.status_code, 200)
        self.assertIn("教師管理", response.text)
        self.assertIn("日語講師", response.text)
        self.assertIn("教師工作台", response.text)

    def test_admin_page_links_recruiting(self) -> None:
        response = self.client.get("/school-platform/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/school-platform/admin/recruiting", response.text)
        self.assertIn("/school-platform/admin/reports", response.text)
        self.assertIn("/school-platform/admin/ai-center", response.text)

    def test_admin_page_links_support_inbox(self) -> None:
        response = self.client.get("/school-platform/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/school-platform/admin/support-inbox", response.text)

    def test_admin_lead_forms_submit(self) -> None:
        headers = self.login_headers()
        leads = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]
        lead_id = leads[0]["id"]

        status_response = self.client.post(
            f"/school-platform/admin/leads/{lead_id}/status",
            data={
                "status_value": "considering",
                "next_follow_up_at": "2026-04-20T10:30",
                "note": "已改成觀望中，三天後追蹤",
            },
            follow_redirects=False,
        )
        self.assertEqual(status_response.status_code, 303)

        lead_detail = self.client.get(f"/school-platform/api/leads/{lead_id}", headers=headers).json()["data"]
        self.assertEqual(lead_detail["status"], "considering")

        log_response = self.client.post(
            f"/school-platform/admin/leads/{lead_id}/logs",
            data={
                "staff_name": "Mika Chen",
                "contact_method": "line",
                "content": "再次確認學員可上課時段",
                "next_action": "本週五再聯繫",
            },
            follow_redirects=False,
        )
        self.assertEqual(log_response.status_code, 303)

        logs = self.client.get(f"/school-platform/api/leads/{lead_id}/logs", headers=headers).json()["data"]
        self.assertTrue(any("再次確認學員可上課時段" in item["content"] for item in logs))

    def test_admin_course_and_class_forms_submit(self) -> None:
        unique_slug = f"intensive-{uuid.uuid4().hex[:8]}"
        course_response = self.client.post(
            "/school-platform/admin/courses/create",
            data={
                "slug": unique_slug,
                "name": "日本生活日語密集班",
                "course_type": "生活日語",
                "level": "N5",
                "delivery_mode": "online",
                "price": "10800",
                "short_description": "密集衝刺生活會話。",
                "objectives": "生活生存\n基礎會話",
                "highlights": "密集班\n直播互動",
                "modules": "租屋\n購物",
                "teacher_names": "Aki Mori",
            },
            follow_redirects=False,
        )
        self.assertEqual(course_response.status_code, 303)

        courses = self.client.get("/school-platform/api/public/courses").json()["data"]
        self.assertTrue(any(item["slug"] == unique_slug for item in courses))

        class_response = self.client.post(
            "/school-platform/admin/classes/create",
            data={
                "course_slug": unique_slug,
                "name": "7 月密集班",
                "teacher_name": "Aki Mori",
                "start_date": "2026-07-01",
                "end_date": "2026-08-01",
                "weekday": "Mon / Wed / Fri",
                "start_time": "19:30",
                "end_time": "21:00",
                "capacity": "18",
                "location_label": "Zoom Live",
            },
            follow_redirects=False,
        )
        self.assertEqual(class_response.status_code, 303)

        classes_page = self.client.get("/school-platform/admin/classes")
        self.assertIn("7 月密集班", classes_page.text)

    def test_admin_lead_assign_form_submit(self) -> None:
        headers = self.login_headers()
        leads = self.client.get("/school-platform/api/leads", headers=headers).json()["data"]
        lead_id = leads[0]["id"]
        staff = self.client.get("/school-platform/api/staff", headers=headers).json()["data"]
        target_staff = next(item for item in staff if item["role"] == "consultant")

        response = self.client.post(
            f"/school-platform/admin/leads/{lead_id}/assign",
            data={"staff_id": target_staff["id"]},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        updated = self.client.get(f"/school-platform/api/leads/{lead_id}", headers=headers).json()["data"]
        self.assertEqual(updated["assigned_staff_name"], target_staff["name"])

    def test_admin_course_edit_form_submit(self) -> None:
        course = self.client.get("/school-platform/api/public/courses").json()["data"][0]
        edit_page = self.client.get(f"/school-platform/admin/courses/{course['slug']}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn("編輯課程", edit_page.text)

        response = self.client.post(
            f"/school-platform/admin/courses/{course['slug']}/edit",
            data={
                "slug": course["slug"],
                "name": "更新後課程名稱",
                "course_type": course["course_type"],
                "level": course["level"],
                "delivery_mode": course["delivery_mode"],
                "price": str(course["price"]),
                "short_description": "更新後摘要",
                "objectives": "目標 A\n目標 B",
                "highlights": "亮點 A",
                "modules": "章節 A",
                "teacher_names": "Aki Mori",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        updated = self.client.get(f"/school-platform/api/public/courses/{course['slug']}").json()["data"]
        self.assertEqual(updated["name"], "更新後課程名稱")
        self.assertEqual(updated["short_description"], "更新後摘要")

    def test_admin_class_edit_form_submit(self) -> None:
        classes_page = self.client.get("/school-platform/api/public/classes/open").json()["data"]
        class_item = classes_page[0]
        edit_page = self.client.get(f"/school-platform/admin/classes/{class_item['id']}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn("編輯班級", edit_page.text)

        response = self.client.post(
            f"/school-platform/admin/classes/{class_item['id']}/edit",
            data={
                "course_slug": class_item["course_slug"],
                "name": "更新後班級名稱",
                "teacher_name": class_item["teacher_name"],
                "start_date": class_item["start_date"],
                "end_date": class_item["end_date"],
                "weekday": class_item["weekday"],
                "start_time": "18:30",
                "end_time": "20:00",
                "capacity": "22",
                "location_label": "Taipei Main + Zoom",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        classes_after = self.client.get("/school-platform/api/public/classes/open").json()["data"]
        updated = next(item for item in classes_after if item["id"] == class_item["id"])
        self.assertEqual(updated["name"], "更新後班級名稱")
        self.assertEqual(updated["capacity"], 22)


if __name__ == "__main__":
    unittest.main()
