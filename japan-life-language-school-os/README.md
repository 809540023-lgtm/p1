# Japan Life Language School OS

這個 repo 是 AI 日語補習班平台的正式 Render 部署來源。

## 內容範圍

- `/school-platform`
  AI 日語補習班完整營運平台主入口
- `/health`
  Render health check
- `school_platform/`
  招生 CRM、教務、學員、教師、財務、通知、AI 助理與系統 readiness

根路徑 `/` 會直接導向 `/school-platform`。

## 目標

這份來源的目的，是讓 Render 直接從正式 GitHub repo 拉取 school-platform 原始碼，不再依賴外部 bundle、tmpfiles 或臨時 bootstrap。

## 主要指令

```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

## PostgreSQL 流程

```bash
python3 scripts/init_school_platform_postgres.py
python3 scripts/migrate_school_platform_json_to_postgres.py
python3 scripts/smoke_test_school_platform_postgres.py
python3 scripts/cutover_school_platform_postgres.py
python3 scripts/verify_school_platform_postgres_row_writes.py
```

## 正式上線前仍需補齊

- 真實 PostgreSQL cutover 驗證
- 真實 Stripe 收款驗證
- 真實 Email / LINE 外發驗證
- 正式 HTTPS 網站 smoke test
