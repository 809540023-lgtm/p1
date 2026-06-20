# DB Cutover Runbook

這份文件是 AI 日語補習班平台從 JSON store 切到 PostgreSQL domain tables 的正式切換手冊。

## 1. Goal

把目前開發期使用的 JSON persistence 切換到 PostgreSQL，並保持：

- 課程資料可讀
- 名單資料可讀
- 報名付款流程不斷線
- 後台頁面維持可操作

## 2. Preconditions

切換前應確認：

1. `SCHOOL_PLATFORM_POSTGRES_DSN` 已設定
2. `SCHOOL_PLATFORM_STORAGE_BACKEND=postgres`
3. `psycopg` 已安裝
4. `python-multipart` 已安裝
5. `/school-platform/system` 顯示連線條件已具備

## 3. Required Artifacts

- `sql/japanese_school_platform_domain_tables.sql`
- `scripts/init_school_platform_postgres.py`
- `scripts/migrate_school_platform_json_to_postgres.py`

## 4. Cutover Steps

### Step 1: Initialize Tables

執行：

`python scripts/init_school_platform_postgres.py`

或呼叫：

`POST /school-platform/api/system/storage/init`

### Step 2: Migrate Existing JSON Data

執行：

`python scripts/migrate_school_platform_json_to_postgres.py`

### Step 3: Verify Readiness

查看：

- `/school-platform/system`
- `/school-platform/api/system/storage`

確認：

- `connectable=true`
- `initialized=true`
- `tables_ready=true`
- `ready=true`

### Step 4: Switch Runtime Backend

把執行環境切到：

- `SCHOOL_PLATFORM_STORAGE_BACKEND=postgres`

重新啟動服務後做 smoke test。

## 5. Smoke Test Checklist

1. 課程列表可讀
2. 班級列表可讀
3. lead list / detail 可讀
4. lead logs 可讀
5. staff / notifications 可讀
6. 後台頁面仍能正常載入

## 6. Rollback

如果 PostgreSQL 切換後出現阻塞：

1. 將 backend 改回 `json`
2. 重啟服務
3. 保留 PostgreSQL 資料，不立即刪除
4. 重新檢查 DSN、表結構與 migration 是否完整
