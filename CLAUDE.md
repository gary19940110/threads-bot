# CLAUDE.md — 阿正 Threads 自動發文系統

給 Claude Code 看的專案說明。**跟使用者（阿正）一律用繁體中文回覆，他看不懂英文。**
他是台中房仲（連續五年千萬經紀人，台灣房屋 松竹11期），不是工程師：解釋時講白話、講操作步驟，不要講程式名詞。

## 這是什麼

一套自動發 Threads（帳號 @jng01.10）的系統：
中控台（手機/電腦網頁）寫文案、排程 → GitHub Actions 機器人準時發文、自己留言、自動回覆留言導 LINE @a0110 → 每天抓數據替鉤子打分。

- 中控台網址：https://gary19940110.github.io/threads-bot/ （GitHub Pages，來源是 `docs/`）
- 儲存庫：https://github.com/gary19940110/threads-bot （**公開**，Threads 讀圖片需要公開網址）
- 沒有伺服器、沒有資料庫：所有資料都是這個 repo 裡的 JSON 檔，中控台用 GitHub API 直接讀寫。

## 檔案地圖

| 路徑 | 用途 |
|---|---|
| `docs/index.html` | 中控台（單一檔案，純 HTML/CSS/JS，沒有建置步驟）。分頁：📁文案庫、📅排程、📈數據、💬留言待回、⚙️設定 |
| `bot.py` | 機器人主程式。指令：`publish` `replies` `insights` `trends` `refresh` `index` `wait` |
| `cards.py` | 把草稿的 `card` 欄位畫成 1080×1350 圖卡 `images/card-<id>.png`（Pillow＋Noto CJK） |
| `generate.py` | 每天用 Claude API 產草稿（需要 secret `ANTHROPIC_API_KEY`，沒有就跳過） |
| `.github/workflows/publish.yml` | 每 15 分鐘（實際 GitHub 常延遲到 30～45 分）：產圖卡 → 發文＋回覆 → 存檔 → **等待接下來 25 分鐘內要發的貼文準時發** |
| `.github/workflows/daily.yml` | 每天 06:30：數據、熱門話題、AI 草稿 |
| `.github/workflows/refresh-token.yml` | 每週一續期 Threads 權杖 |
| `config/settings.json` | 署名、常用時段、話題、自動回覆開關、預設自己留言等 |
| `config/hooks.json` | 鉤子清單 H01～H12 |
| `config/reply_rules.json` | 一般貼文的關鍵字自動回覆規則 |
| `data/library.json` | 📁文案庫（可重複使用的文案） |
| `data/index.json` | 所有草稿摘要（中控台與數據頁讀這份，`bot.py index` 產生） |
| `data/stats.json` | 鉤子分數、時段分數、低流量貼文 |
| `data/inbox.json` / `data/replied.json` | 待人工回的留言 / 已回覆紀錄 |
| `drafts/<id>.json` | 每一篇貼文一個檔 |
| `images/` | 上傳的照片（中控台會縮到長邊 1440 的 JPEG）與圖卡 |
| `tools/connect-web.js`／`tools/connect-yt-web.js` | 連結 FB 粉專＋IG／YouTube 的網頁版小幫手（`node --use-system-ca tools/connect-yt-web.js`；阿正電腦會攔截 Google 憑證，不加 `--use-system-ca` 會 fetch failed）。開 localhost 網頁 → 阿正貼密鑰、按授權 → 顯示要貼到 GitHub Secrets 的值。Meta 應用程式：AZheng Video Share（2484796785384900，粉專「台中房仲推薦x神案先生」）；Google Cloud 專案 evident-flame-513103-q7（OAuth 已發布為正式版）。權杖要重拿就重跑這兩支。`tools/connect.js` 是舊的終端機版 |
| `data/platforms.json` | 機器人寫入：哪些平台已連結（中控台顯示「還沒連結」用） |
| `docs/videos/` | 上傳的影片（28MB 內；GitHub 網頁 API 實測超過約 30MB 回 422，所以超過就在瀏覽器自動壓縮）。放 docs/ 是為了走 GitHub Pages 網址，Threads 才讀得到正確影片格式；上傳後約 2 分鐘 Pages 才更新 |

所有 workflow 用同一個 `concurrency: group: bot`，不會同時跑兩個。

## 資料格式（改程式前一定要看）

**草稿 `drafts/<id>.json`**
```
id, status(pending待審|approved已核准|posted已發布|failed失敗|rejected已刪除), type(listing物件文|knowledge|owner|market|poll|story|news|area|brand),
text(第一行=標題), images[], videos[](docs/videos/*.mp4|mov，發文時排在照片前), card{label,title,points[]}|null, card_pos(first|last), topic_tag, publish_at(ISO +08:00),
commission_signed(物件文必須 true 才能發), lib_id(來自哪份文案庫), hook_id, why,
auto_reply{enabled,text,link,images[],keywords[]}|null, first_comment{enabled,text,link,images[],contact(加聯繫方式,預設true),sign(加署名,預設true)},
share{fb,ig,yt,yt_title}(影片貼文發到 Threads 後同步發 FB 粉專 Reels／IG Reels／YouTube Shorts),
— 機器人寫入：share_status{fb|ig|yt:{id,url,at}|{error,tries}}, threads_id, permalink, posted_at, metrics{views,likes,replies,...}, error, tries, first_comment_done
```
**文案庫 `data/library.json`**：陣列，每份 `{id:"L…", name, tags[], type, text, images[], videos[], card, card_pos, topic_tag, auto_reply, first_comment, updated_at, prev_text?}`。
從文案庫排程會複製成草稿並記 `lib_id`；改文案庫可同步所有同 `lib_id` 且 pending/approved 的草稿（中控台 `syncFromLib`）。

**`config/settings.json` 重點欄位**：`brand_footer`（署名：尚峰不動產｜林建宏（103）中市經紀字00667號）、`contact_block`（聯繫方式：黃守正｜阿正／連續五年千萬經紀人／電話／LINE）、`footer_in_comment`（true＝署名不放主文，放在自己第一則留言）、`first_comment`（預設自己留言）、`slots`（常用時段）、`topic_tags`、`dup_days`（同一篇間隔幾天內要提醒）、`reply`、`max_chars`(500)。

## 鐵則（不能破）

1. **物件文要已簽委託才能發**（經紀業管理條例第21條）：`type=listing` 且 `commission_signed!==true` → 機器人會標 failed，中控台也會擋。不可移除這個檢查。
2. **主文不放聯繫方式和署名**（阿正要求，2026-10-25）：電話、LINE、署名、經紀字號一律不寫進主文，避免像自製廣告文；全部放在發文後「自己的第一則留言」。留言可逐篇勾選「加入聯繫方式」(`contact`)、「加入署名」(`sign`)，預設都勾；主文或留言文字已有的不重複加（`bot.py first_comment()`）。署名（`尚峰不動產｜林建宏（103）中市經紀字00667號`）是法規要求、防同業檢舉，物件文取消勾選時中控台會提醒風險。AI 寫文案的提示詞也照這條。
3. **不編造數字**：價格、坪數、成交行情、利率、政策沒有提供就寫 `[待填:…]`；含 `[待填` 的貼文機器人拒發。
4. **留言不自動刪、低流量貼文只標記不刪**（留言可能是客戶）。
5. **不對別人的貼文大量留言**；自動回覆只回自己貼文底下的留言，每人每篇一次。
6. **repo 是公開的**：不放客戶個資、門牌樓層、權杖。密鑰只放 GitHub Secrets（`THREADS_TOKEN`、`GH_PAT`、`ANTHROPIC_API_KEY`、`FB_PAGE_TOKEN`、`FB_PAGE_ID`、`IG_USER_ID`、`YT_CLIENT_ID`、`YT_CLIENT_SECRET`、`YT_REFRESH_TOKEN`），**絕對不要寫進程式或 commit**。
7. 對外發送（立即發布、核准排程）由阿正自己按；Claude 幫他寫好、排好，要先給他看。

## 怎麼改、怎麼上線

- 改完 → `git add` → `git commit` → `git push` 到 `main`。
  - `docs/index.html` 推上去約 1～2 分鐘 GitHub Pages 自動更新（請阿正按 Ctrl+F5）。
  - `bot.py` / workflow 推上去，下一次排程就生效；要馬上跑：`gh workflow run publish.yml`。
- **機器人也會 commit**（發文狀態、數據）：push 前先 `git pull --rebase`，衝突時以遠端的 `drafts/`、`data/` 為準，不要覆蓋機器人寫的發文狀態（否則可能重複發文）。
- 中控台用 `updateJSON()`（讀最新 → 修改 → 寫回，遇 409 重試），新功能寫檔請沿用它。
- 改 `docs/index.html` 後先檢查語法：
  `node -e "const h=require('fs').readFileSync('docs/index.html','utf8');const p=h.split('<script>');new Function(p[p.length-1].split('</script>')[0]);console.log('ok')"`
- 測機器人不真的發文：`DRY_RUN=1 REPO=gary19940110/threads-bot python bot.py publish`（DRY 模式只印出要呼叫的 API）。
- 中控台互動測試：可用 Playwright 開 `docs/index.html`，把 `api.github.com` 攔截到本機假 repo 資料夾（不要對真的 repo 做測試寫入）。

## 已知行為 / 容易踩雷

- GitHub 排程不準（常 30～45 分才跑一次），所以 `publish.yml` 最後有 `bot.py wait` 步驟等即將到時間的貼文；中控台「⚡立即發布」會用 workflow_dispatch 馬上觸發。
- 每次 `publish` 最多發 3 篇（防洗版）。
- 圖卡在 `publish.yml` 第一步產生；草稿改了 `card` 會清掉舊圖卡讓它重畫。
- 照片排序用 SortableJS（cdnjs）；確認視窗用頁內 `ask()`，**不要用 `confirm()/prompt()`**（在某些 Chrome 分頁會被擋）。
- Threads 一篇只能掛一個主題（`topic_tag`，不能有 `.` `&`）；回覆／自己留言用 `reply_to_id`，圖片最多 10 張輪播。
- 同步發文（`bot.py cmd_share`，publish 結束時跑）：只處理 2 天內發出、有影片、有勾 share 的貼文；FB 直接上傳影片檔，IG 用 GitHub Pages 影片網址，YouTube 用 refresh token 上傳。FB／IG 聯繫方式＋署名放自己第一則留言，YouTube 放說明欄。每平台失敗最多重試 3 次，不影響 Threads。Google 未審核的 API 專案上傳的影片會被強制設為私人，要申請 YouTube API 稽核才會公開；OAuth 同意畫面要設「正式版」不然 refresh token 7 天失效。
- 權杖 60 天到期，每週一自動續；`data/token_status.json` 可看狀態。

## 阿正的文案偏好（寫／改貼文時照這個）

- 主文越短越好、口語、帶一點幽默，**不要像廣告**；重複的句子要刪。
- 結構：地標或爆點開頭 → 2～3 行重點 → 一句笑點 → 「留言『關鍵字』」導私訊。**主文不寫電話、LINE、署名**，都放第一則自己留言。
- 鉤子優先順序（參考同事 @taichung.good.house）：①地標定位「○○國小／高中旁」②價格反差 ③價格留白（2字頭、萬不寫數字）④情緒驚嘆 ⑤屋主故事 ⑥留言關鍵字 CTA。
- 優化貼文時：先建議用哪種鉤子＋原因，再給 2～3 個不同鉤子版本讓他挑。
- 同一篇物件文間隔至少 3 天再發，重發要換開頭。
