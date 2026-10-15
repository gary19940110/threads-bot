# 阿正 Threads 自動發文系統

每天早上 AI 依「鉤子分數」寫好 3 篇草稿 → 你在手機中控台按核准 → 機器人準時發到 Threads → 有人留言問價、問地點、約看屋就自動回覆並導 LINE @a0110 → 隔天抓數據，分數高的鉤子多用、分數低的淘汰。

| 時間（台灣） | 自動做的事 |
|---|---|
| 每 15 分鐘 | 發布已核准且到時間的貼文、掃留言自動回覆 |
| 每天 06:30 | 更新每篇觀看／互動、搜尋 Threads 熱門話題、AI 產 3 篇新草稿 |
| 每週一 | 自動續期 Threads 權杖（不用每 60 天手動換） |

## 一次性設定（約 30 分鐘）

### 1. 建 GitHub 儲存庫
1. 登入 GitHub（gary19940110）→ 右上角「＋」→ New repository
2. 名稱填 `threads-bot`，選 **Public**（Threads 讀圖片需要公開網址），其他不用勾 → Create
3. 點「uploading an existing file」，把這個資料夾**裡面全部的東西**（包含 `.github` 資料夾）拖進去 → Commit changes
4. Settings → Pages → Branch 選 `main`、資料夾選 `/docs` → Save
   中控台網址會是：`https://gary19940110.github.io/threads-bot/`

> 公開儲存庫的意思是：草稿和物件資料別人找得到。所以物件只寫路段，不要寫門牌樓層；這裡不放任何客戶個資。

### 2. 建 GitHub 權杖（中控台和機器人共用）
GitHub 右上頭像 → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
- Repository access：Only select repositories → `threads-bot`
- Permissions → Repository permissions：**Contents：Read and write**、**Actions：Read and write**、**Secrets：Read and write**
- 有效期限選 1 年 → 產生後複製（只會顯示一次）

### 3. 申請 Threads API 權杖
1. 到 developers.facebook.com 用你的 FB 登入 → 我的應用程式 → 建立應用程式
2. 使用案例選「**Access the Threads API**」
3. 在使用案例的權限裡加入：`threads_basic`、`threads_content_publish`、`threads_read_replies`、`threads_manage_replies`、`threads_manage_insights`、`threads_keyword_search`
4. 應用程式角色 → 新增「Threads 測試人員」→ 填你的 Threads 帳號
5. 打開 Threads App → 設定 → 帳號 → 網站權限 → 邀請 → 接受
6. 回到開發者後台 → Threads API 設定 → User Token Generator → 產生權杖（長效權杖，60 天，系統會自動續）
7. 用瀏覽器打開下面網址（把權杖貼在最後），記下回傳的 `id`：
   `https://graph.threads.net/v1.0/me?fields=id,username&access_token=你的權杖`

### 4. 申請 Claude API 金鑰（AI 寫文案用）
console.anthropic.com → 註冊 → Billing 儲值 5 美元 → API Keys → Create Key。
每天 3 篇草稿，費用大約每月 1–2 美元。

### 5. 把金鑰放進 GitHub（加密保存，別人看不到）
儲存庫 → Settings → Secrets and variables → Actions → New repository secret，新增四個：

| 名稱 | 內容 |
|---|---|
| `THREADS_TOKEN` | 第 3 步的 Threads 權杖 |
| `THREADS_USER_ID` | 第 3 步的 id |
| `ANTHROPIC_API_KEY` | 第 4 步的 Claude 金鑰 |
| `GH_PAT` | 第 2 步的 GitHub 權杖 |

### 6. 啟動
1. 儲存庫 → Actions → 按「I understand my workflows, go ahead and enable them」
2. 點「每日數據與新草稿」→ Run workflow，2 分鐘後會出現新草稿
3. 手機打開中控台網址 → 填 `gary19940110/threads-bot` 和第 2 步的權杖 → 加到主畫面

## 每天你只要做一件事
早上打開中控台「審核」，看一下文案、補 [待填]、物件文勾「已簽委託」、需要的話加照片 → 按「核准排程」。

## 調整
- 自動回覆的關鍵字和回覆句子：`config/reply_rules.json`
- 鉤子庫：`config/hooks.json`（可以自己加新的鉤子）
- 發文時段、署名、話題標籤、追蹤關鍵字：中控台「設定」
- 物件資料：中控台「物件」

## 安全規則（寫在程式裡）
- 物件文沒勾「已簽委託」不能核准也不會發布（不動產經紀業管理條例第 21 條）
- 每篇自動加經紀業名稱署名
- 文案有 [待填] 不能發布；AI 被要求不得編造價格、坪數、行情數字
- 自動回覆只回**自己貼文**底下的留言，同一個人同一篇只回一次，每輪最多 15 則、每則間隔 20–45 秒
- 不去別人的貼文留言、不洗版
