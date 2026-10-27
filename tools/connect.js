// 連結 FB 粉專／IG／YouTube 的小幫手（在自己電腦執行，不會上傳任何東西）
//   node tools/connect.js meta      取得 FB_PAGE_TOKEN、FB_PAGE_ID、IG_USER_ID
//   node tools/connect.js youtube   取得 YT_CLIENT_ID、YT_CLIENT_SECRET、YT_REFRESH_TOKEN
// 跑完會列出「名稱 → 值」，貼到 GitHub：threads-bot → Settings → Secrets and variables → Actions → New repository secret
const http = require("http");
const { execSync } = require("child_process");
const rl = require("readline").createInterface({ input: process.stdin, output: process.stdout });
const ask = q => new Promise(r => rl.question(q, a => r(a.trim())));
const G = "https://graph.facebook.com/v23.0";
const SECRETS_URL = "https://github.com/gary19940110/threads-bot/settings/secrets/actions";

async function getJSON(url, opt) {
  const r = await fetch(url, opt); const j = await r.json();
  if (!r.ok || j.error) throw new Error(JSON.stringify(j.error || j));
  return j;
}
function show(out) {
  console.log("\n✅ 完成！把下面每一行貼到 GitHub Secrets（名稱 → 值）：\n");
  for (const [k, v] of Object.entries(out)) console.log(`${k}\n${v}\n`);
  console.log("GitHub Secrets 頁面：" + SECRETS_URL);
  console.log("⚠️ 這些值等於你帳號的鑰匙，不要傳給別人、不要貼到 LINE 或群組。");
}
function openBrowser(url) {
  try { execSync(process.platform === "win32" ? `start "" "${url}"` : `open "${url}"`); } catch (_) { /* 打不開就手動貼 */ }
}

async function meta() {
  console.log("先到 https://developers.facebook.com/tools/explorer/ 選你的應用程式，按「Generate Access Token」，");
  console.log("權限要勾：pages_show_list, pages_read_engagement, pages_manage_posts, pages_manage_engagement,");
  console.log("          instagram_basic, instagram_content_publish, instagram_manage_comments, business_management\n");
  const appId = await ask("應用程式編號（App ID）：");
  const secret = await ask("應用程式密鑰（App Secret）：");
  const short = await ask("剛產生的存取權杖（Access Token）：");
  const long = await getJSON(`${G}/oauth/access_token?grant_type=fb_exchange_token&client_id=${appId}&client_secret=${secret}&fb_exchange_token=${encodeURIComponent(short)}`);
  const pages = (await getJSON(`${G}/me/accounts?fields=id,name,access_token,instagram_business_account&access_token=${long.access_token}`)).data || [];
  if (!pages.length) throw new Error("找不到粉專：權杖要有 pages_show_list 權限，而且你是粉專管理員");
  pages.forEach((p, i) => console.log(`${i + 1}. ${p.name}${p.instagram_business_account ? "（已綁 IG）" : "（沒綁 IG）"}`));
  const pick = pages.length === 1 ? pages[0] : pages[Number(await ask("要發到哪個粉專？輸入號碼：")) - 1];
  const out = { FB_PAGE_ID: pick.id, FB_PAGE_TOKEN: pick.access_token };
  if (pick.instagram_business_account) out.IG_USER_ID = pick.instagram_business_account.id;
  else console.log("\n⚠️ 這個粉專沒綁 IG 專業帳號：到 IG →設定→帳號類型→切換為專業帳號，再到粉專設定連結 IG，然後重跑一次。");
  show(out);
}

async function youtube() {
  console.log("先到 Google Cloud Console 建立「OAuth 用戶端 ID」（類型：電腦版應用程式），並啟用 YouTube Data API v3。\n");
  const id = await ask("用戶端 ID（Client ID）：");
  const secret = await ask("用戶端密鑰（Client Secret）：");
  const port = 8765, redirect = `http://127.0.0.1:${port}`;
  const url = "https://accounts.google.com/o/oauth2/v2/auth?" + new URLSearchParams({
    client_id: id, redirect_uri: redirect, response_type: "code", access_type: "offline", prompt: "consent",
    scope: "https://www.googleapis.com/auth/youtube.upload" });
  const code = await new Promise((resolve, reject) => {
    const srv = http.createServer((req, res) => {
      const q = new URL(req.url, redirect).searchParams;
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(q.get("code") ? "<h2>✅ 已授權，可以關掉這頁回到黑色視窗</h2>" : "<h2>❌ 沒有授權</h2>");
      srv.close(); q.get("code") ? resolve(q.get("code")) : reject(new Error(q.get("error") || "沒有授權"));
    }).listen(port, "127.0.0.1", () => {
      console.log("\n瀏覽器會打開 Google 登入頁，請選你的 YouTube 頻道帳號並按允許。沒自動打開就複製這個網址：\n" + url + "\n");
      openBrowser(url);
    });
  });
  const tok = await getJSON("https://oauth2.googleapis.com/token", { method: "POST",
    body: new URLSearchParams({ code, client_id: id, client_secret: secret, redirect_uri: redirect, grant_type: "authorization_code" }) });
  if (!tok.refresh_token) throw new Error("沒拿到 refresh_token，請到 https://myaccount.google.com/permissions 移除這個應用程式後重跑");
  show({ YT_CLIENT_ID: id, YT_CLIENT_SECRET: secret, YT_REFRESH_TOKEN: tok.refresh_token });
}

const which = process.argv[2];
(which === "meta" ? meta() : which === "youtube" ? youtube() : Promise.reject(new Error("用法：node tools/connect.js meta 或 youtube")))
  .catch(e => console.log("\n❌ 失敗：" + e.message)).finally(() => rl.close());
