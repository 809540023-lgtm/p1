# Storage & Migration Readiness

這份文件專門說明 AI 日語補習班平台目前資料層的準備狀態，以及從 JSON store 過渡到 PostgreSQL domain tables 的執行方式。

## 1. Current Storage Modes

### JSON Mode

- backend: `json`
- repository mode: `snapshot_file`
- 作用：本地快速開發、低摩擦驗證流程
- 目前預設：是

### PostgreSQL Mode

- backend: `postgres`
- repository mode: `domain_tables`
- 作用：正式資料層、可持續擴充、可接更多查詢與報表
- 目前狀態：程式與 migration 已完成，等待真實 DSN 與 DB 連線驗證

## 2. Migration Artifacts

### SQL

- `sql/japanese_school_platform_domain_tables.sql`
  建立 staff、users、courses、classes、leads、lead_logs、students、enrollments、payments、notifications 等 domain tables。

- `sql/japanese_school_platform_snapshot_store.sql`
  舊版 snapshot table 定義，保留做過渡參考。

### Scripts

- `scripts/init_school_platform_postgres.py`
  初始化 PostgreSQL domain tables。

- `scripts/migrate_school_platform_json_to_postgres.py`
  把現有 JSON store 內容搬進 PostgreSQL domain tables。

## 3. Environment Variables

### JSON

- `SCHOOL_PLATFORM_STORAGE_BACKEND=json`
- `SCHOOL_PLATFORM_JSON_PATH=data/school_platform_store.json`

### PostgreSQL

- `SCHOOL_PLATFORM_STORAGE_BACKEND=postgres`
- `SCHOOL_PLATFORM_POSTGRES_DSN=postgresql://...`

## 4. Readiness Checklist

切換 PostgreSQL 前需要以下條件：

1. `psycopg` 已安裝
2. `SCHOOL_PLATFORM_POSTGRES_DSN` 已提供
3. DB 可連線
4. domain tables 已初始化
5. migration script 已跑完或決定從空資料開始

## 5. Runtime Verification

系統內可直接查看：

- `/school-platform/system`
- `/school-platform/api/system/storage`

這裡會顯示：

- backend
- repository mode
- driver installed
- dsn present
- connectable
- initialized
- tables ready
- migration artifacts

## 6. Recommended Rollout Order

1. 在 staging 設定 PostgreSQL DSN
2. 執行 `init_school_platform_postgres.py`
3. 執行 `migrate_school_platform_json_to_postgres.py`
4. 驗證 `/school-platform/system`
5. 再把 `SCHOOL_PLATFORM_STORAGE_BACKEND` 切成 `postgres`

## 7. Current Limitation

目前 store 還保有 in-memory 聚合與 domain logic，但 persistence 已經不再只依賴單一 snapshot blob。下一步會繼續把 store 往更細的 domain service / repository 切開。
