# Production Config 與 Release 說明

這份文件把正式 repo、Render 佈署、環境變數與 release 前後順序整理成一套固定流程。

## 1. Repo 目前結構

目前同一個 repo 同時承載兩個 surface：

- `/school-platform`
  AI 日語補習班平台主產品
- `/marketplace`
  舊的二手商品頁入口

正式對外主入口應以 `/school-platform` 為準。

## 2. Production 環境變數來源

可直接參考根目錄：

- `.env.production.example`

重點分組如下：

### Storage

- `SCHOOL_PLATFORM_STORAGE_BACKEND`
- `SCHOOL_PLATFORM_JSON_PATH`
- `SCHOOL_PLATFORM_POSTGRES_DSN`
- `SCHOOL_PLATFORM_APP_BASE_URL`

### Payments

- `SCHOOL_PLATFORM_PAYMENT_PROVIDER`
- `SCHOOL_PLATFORM_PAYMENT_CURRENCY`
- `SCHOOL_PLATFORM_STRIPE_SECRET_KEY`
- `SCHOOL_PLATFORM_STRIPE_PUBLISHABLE_KEY`
- `SCHOOL_PLATFORM_STRIPE_WEBHOOK_SECRET`
- `SCHOOL_PLATFORM_STRIPE_SUCCESS_URL`
- `SCHOOL_PLATFORM_STRIPE_CANCEL_URL`
- `SCHOOL_PLATFORM_STRIPE_WEBHOOK_TOLERANCE_SECONDS`

### Notifications

- `SCHOOL_PLATFORM_EMAIL_PROVIDER`
- `SCHOOL_PLATFORM_SMTP_*`
- `SCHOOL_PLATFORM_RESEND_*`
- `SCHOOL_PLATFORM_LINE_*`

## 3. Release 順序

建議固定照這個順序：

1. 更新 repo 程式碼
2. 跑本地 / CI 測試
3. 準備正式 env vars
4. 初始化 PostgreSQL tables
5. 跑 JSON -> PostgreSQL 搬遷
6. 部署 web service
7. 設定 Stripe webhook
8. 執行正式站 smoke test
9. 做一筆真實小額付款驗證
10. 驗證通知外發與 retry

## 4. Render 佈署建議

建議在 Render 至少拆成：

- Web Service
  - 提供 FastAPI 與平台頁面
- PostgreSQL
  - 作為正式資料層
- Cron Job
  - 若要保留定期 smoke、週報或後續 AI batch 任務

### Web Service 必要檢查

- 啟動命令正確
- Python 依賴完整
- Health endpoint 正常
- 正式域名已指向
- `APP_BASE_URL` / `SCHOOL_PLATFORM_APP_BASE_URL` 已同步

### 正式 GitHub 部署來源

如果目前 Render 還是靠臨時 bootstrap 或外部 bundle 啟動，先不要直接把整個 monorepo 丟上去。

先用：

```bash
python3 scripts/export_school_platform_render_source.py
```

產出乾淨的 school-platform 專用來源，再同步到正式 GitHub repo。

完整 cutover 流程請看：

- `docs/japanese-school-platform/16-render-formal-repo-cutover.md`

## 5. 發版後第一輪驗證

部署完成後，至少看這幾頁：

- `/school-platform/system`
- `/school-platform/launch-readiness`
- `/school-platform/admin/messages`
- `/school-platform/payment?...`

至少驗證這幾個 API：

- `GET /school-platform/api/system/storage`
- `GET /school-platform/api/system/launch-readiness`
- `POST /school-platform/api/payments/{payment_id}/reconcile`
- `POST /school-platform/api/payments/stripe/webhook`
- `POST /school-platform/api/notifications/{notification_id}/retry`

## 6. 若發版後出問題

優先檢查：

1. PostgreSQL DSN 是否可連
2. Stripe webhook secret 是否正確
3. `SCHOOL_PLATFORM_APP_BASE_URL` 是否與正式域名一致
4. Email provider 是否仍落到 mock
5. LINE token 是否遺漏

回退原則：

- 若是 webhook / 通知 provider 壞掉，但主站可用，先維持站點在線並切回人工處理
- 若是 PostgreSQL readiness 不通，先暫停 cutover，回到最後一份已驗證 snapshot
- 若是正式站 smoke test 失敗，不要宣布正式上線
