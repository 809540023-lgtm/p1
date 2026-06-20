# Gmail / LINE 真實通知接入

這份文件專門給「今天要把真實 Email 與 LINE 通知接上」的情境使用。

## 1. Gmail 真實發信

目前平台已支援 SMTP 模式，所以可以直接用 Gmail SMTP。

### 你要準備的不是 Gmail 密碼

你要準備的是：

- `rokaizumi@gmail.com`
- Google 兩步驟驗證
- 一組 `App Password`

### 建議環境變數

```env
SCHOOL_PLATFORM_EMAIL_PROVIDER=smtp
SCHOOL_PLATFORM_SMTP_HOST=smtp.gmail.com
SCHOOL_PLATFORM_SMTP_PORT=587
SCHOOL_PLATFORM_SMTP_USERNAME=rokaizumi@gmail.com
SCHOOL_PLATFORM_SMTP_PASSWORD=你的16碼AppPassword
SCHOOL_PLATFORM_SMTP_FROM_EMAIL=rokaizumi@gmail.com
SCHOOL_PLATFORM_SMTP_USE_TLS=true
SCHOOL_PLATFORM_NOTIFICATION_TEST_EMAIL=rokaizumi@gmail.com
```

## 2. LINE 真實外發

LINE 外發憑證不是你的 LINE 登入密碼，而是 LINE 官方帳號 Messaging API 的金鑰。

### 你要準備的值

```env
SCHOOL_PLATFORM_LINE_CHANNEL_ACCESS_TOKEN=你的token
SCHOOL_PLATFORM_LINE_CHANNEL_SECRET=你的secret
SCHOOL_PLATFORM_LINE_FALLBACK_USER_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SCHOOL_PLATFORM_LINE_API_BASE_URL=https://api.line.me
SCHOOL_PLATFORM_NOTIFICATION_TEST_LINE_USER_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 三個欄位用途

- `CHANNEL_ACCESS_TOKEN`
  讓機器人可以把訊息推送出去。
- `CHANNEL_SECRET`
  之後若要接 webhook 驗證請求來源會用到。
- `FALLBACK_USER_ID`
  先指定一個測試收訊者，最常是你自己的 LINE user ID。

## 3. 驗證腳本

平台已經附上一支測試腳本，補完環境變數後可直接驗證。

### 測 Email

```bash
python3 scripts/test_school_platform_notification_providers.py \
  --channel email \
  --user-email rokaizumi@gmail.com
```

### 測 LINE

```bash
python3 scripts/test_school_platform_notification_providers.py \
  --channel line \
  --recipient Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 4. 後台查看位置

接入後可直接從下面頁面看狀態：

- `/school-platform/admin/messages`
- `/school-platform/system`
- `/school-platform/operational-readiness`
- `/school-platform/admin/messages` 內建 Provider Smoke Test 表單，可直接送測試 Email / LINE

## 5. Demo 信箱安全護欄

如果你把真實 SMTP 打開，平台現在會自動攔下這類示範地址，不會真的往外寄：

- `example.com` / `example.net` / `example.org`
- `*.local` / `localhost`
- 內部示範帳號例如 `admin@jls.local`

這些通知會被標成 `suppressed`，方便你在後台分辨「測試資料被安全攔下」和「真實外發失敗」。

## 6. 今天最短落地順序

1. 先把 Gmail SMTP 接好
2. 跑 Email 測試腳本
3. 再補 LINE token 與 fallback user
4. 用後台訊息中心送一封 Email 與一則 LINE 測試通知
