# 正式上線檢查清單

這份清單是 AI 日語補習班平台從「可展示 MVP」進到「可正式營運」前，最後一輪必做檢查。

## 1. 基礎環境

- 確認正式網址已固定，例如 `https://your-school-platform-domain`
- 確認 `SCHOOL_PLATFORM_APP_BASE_URL` 使用 HTTPS
- 確認 Render / 雲端服務的 health check 正常
- 確認 root `/` 會導向 `/school-platform`
- 確認舊 marketplace 內容只保留在 `/marketplace`

## 2. PostgreSQL cutover

- `SCHOOL_PLATFORM_STORAGE_BACKEND=postgres`
- `SCHOOL_PLATFORM_POSTGRES_DSN` 已配置
- 跑過 `python3 scripts/init_school_platform_postgres.py`
- 跑過 `python3 scripts/migrate_school_platform_json_to_postgres.py`
- 跑過 `python3 scripts/cutover_school_platform_postgres.py`
- `GET /school-platform/system`
  - `backend=postgres`
  - `readiness.ready=true`
  - `tables_ready=true`
- `GET /school-platform/launch-readiness`
  - `Storage backend` 不可為 blocker
  - `Storage readiness` 不可為 blocker

## 3. 金流

- `SCHOOL_PLATFORM_PAYMENT_PROVIDER=stripe`
- Stripe secret / publishable key / webhook secret 已配置
- Stripe Dashboard webhook 指向：
  - `POST /school-platform/api/payments/stripe/webhook`
- 成功 / 取消導回 URL 已配置
- 付款中心頁：
  - 可建立 Checkout Session
  - 可看到 `provider_mode`
  - 可看到 `checkout_expires_at`
  - 可手動執行「向 Stripe 重新同步」
- 至少做一次真實小額付款驗證
- 驗證 webhook 抵達後：
  - payment 變成 `paid`
  - enrollment 狀態同步
  - 付款通知已建立

## 4. 通知外發

- Email provider 不可再是 mock
- 至少擇一完成：
  - SMTP
  - Resend
- LINE 若是正式招生 / 客服流程需要外發，需補齊 token 與 fallback user
- `GET /school-platform/admin/messages`
  - 可看到 provider readiness
  - 失敗通知可單筆 retry
  - queued 通知可批次 drain
- 驗證至少各一筆：
  - Email 寄送成功
  - LINE 推播成功或明確標示為 optional
  - in-app 通知正常顯示

## 5. Smoke test

- 本地 / CI 測試通過：
  - `python3 -m unittest tests.test_school_platform_api`
- 正式站 smoke test：
  - `python3 scripts/smoke_test_school_platform_deployment.py --base-url https://your-school-platform-domain`
- 建議手動再點一次：
  - `/school-platform`
  - `/school-platform/progress`
  - `/school-platform/system`
  - `/school-platform/launch-readiness`
  - `/school-platform/payment?...`
  - `/school-platform/admin/messages`

## 6. 人工驗收

- 課程頁顯示中文內容與日幣價格
- 簡體中文切換可用
- 報名成功可建立學生 / enrollment / payment
- 學員中心可看到課程、付款與通知
- 招生 / 管理端登入正常
- 招聘、報表、AI 中心頁面可正常打開

## 7. 上線判定

可正式上線的最低條件：

- `launch-readiness` 沒有 blocker
- PostgreSQL 已切換成功
- Stripe 真實小額付款成功
- 至少一個真實 Email provider 成功送達
- 正式站 smoke test 全部通過

如果其中任何一項未完成，建議維持 staging / internal beta 狀態，不要對外宣稱已正式營運。
