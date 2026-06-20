# Render 正式 GitHub Repo Cutover

這份文件是把目前已經跑起來的 Render 站，從「臨時 bootstrap / 外部 bundle」切到「Render 直接拉正式 GitHub repo 原始碼」的標準流程。

## 1. 目標狀態

正式狀態應該長這樣：

- Render Web Service 直接連到正式 GitHub repo
- repo 內就是 school-platform 原始碼，不再下載外部 zip / tmpfiles bundle
- Render 每次重新部署，都只依賴 GitHub repo 當下的 commit
- smoke test 與 DB migration 文件也跟著同一份 repo 一起管理

## 2. 為什麼要 cutover

臨時 bootstrap 雖然能先把站點救活，但長期有三個風險：

1. 外部 bundle 失效時，Render 重新部署會直接壞掉
2. GitHub 上看到的不是完整原始碼，後續維護容易失真
3. deploy 問題會被切成兩層，debug 成本高

## 3. 正式化來源的做法

目前 monorepo 內仍混有其他產品，因此正式部署來源不應直接把整個 workspace 當成 Render source。

建議做法是：

1. 用匯出腳本產生乾淨 source
2. 把這份 source 同步到正式 GitHub repo
3. 讓 Render service 直接監看這個 repo

匯出指令：

```bash
python3 scripts/export_school_platform_render_source.py
```

預設輸出到：

```text
dist/japan-life-language-school-os-render-source
```

## 4. 匯出內容

匯出的正式來源會包含：

- school-platform 專用 `api.py`
- 精簡版 `config.py`
- `school_platform/` 主程式
- PostgreSQL 初始化 / 搬遷 / smoke / cutover scripts
- `sql/` domain tables 與 snapshot store schema
- 上線與 migration 文件
- `render.yaml`
- `.env.example` / `.env.production.example`

## 5. GitHub repo 應有的特徵

正式 repo 應符合：

- repo 根目錄直接可給 Render build
- `render.yaml` 在 repo root
- `api.py` 在 repo root
- `requirements.txt` 在 repo root
- 沒有外部下載 bundle 的 bootstrap 程式

## 6. Render 端切換方式

如果 Render 已經綁定同一個 repo，只要把 repo 內容正式化即可，之後 Render 會直接從新 commit 重新部署。

如果 Render 還綁到錯的 repo，則需要在 Render Dashboard 把 service 的 GitHub source 改到正式 repo。

## 7. Cutover 後驗證

至少驗證下面幾項：

- `GET /health`
- `GET /school-platform`
- `GET /school-platform/api/public/courses`
- `GET /school-platform/api/system/operational-readiness`
- manager demo 帳號可登入

正式 smoke 指令：

```bash
python3 scripts/smoke_test_school_platform_deployment.py --base-url https://your-render-domain
```

## 8. 真正完成的判定標準

只有同時滿足下面條件，才算正式化完成：

1. GitHub repo 內已是完整 school-platform 原始碼
2. Render deploy log 不再出現外部 bundle download
3. `/health` 與主要 school-platform 頁面 smoke test 通過
4. 後續改動只要更新 GitHub repo 就能穩定觸發部署
