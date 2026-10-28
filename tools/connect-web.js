// 連結 FB 粉專＋IG 的網頁版小幫手（只在你自己電腦上跑，不會上傳任何東西）
//   node tools/connect-web.js
// 會自動打開 Chrome：貼上應用程式密鑰 → 按按鈕 → FB 授權 → 顯示要貼到 GitHub Secrets 的值（每個都有複製鈕）
const http = require("http");
const { execSync } = require("child_process");
const G = "https://graph.facebook.com/v23.0";
const APP_ID = "2484796785384900"; // AZheng Video Share
const PORT = 8765, HOME = `http://localhost:${PORT}/`, CB = `${HOME}cb`;
const SCOPE = "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,instagram_basic,instagram_content_publish,instagram_manage_comments,business_management";
const NEW_SECRET = "https://github.com/gary19940110/threads-bot/settings/secrets/actions/new";
let secret = "", pages = [];

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const page = body => `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>連結 FB／IG</title><style>body{font:18px/1.6 system-ui,"Microsoft JhengHei";max-width:640px;margin:40px auto;padding:0 16px;color:#222}
input{width:100%;font-size:18px;padding:10px;box-sizing:border-box}button,.btn{font-size:18px;padding:10px 18px;margin:8px 0;background:#1877f2;color:#fff;border:0;border-radius:8px;cursor:pointer;text-decoration:none;display:inline-block}
.box{border:1px solid #ddd;border-radius:10px;padding:14px;margin:14px 0}.name{font-weight:bold;font-size:20px}.err{color:#c00}.small{color:#666;font-size:15px}</style>${body}`;

async function getJSON(url) {
  const r = await fetch(url); const j = await r.json();
  if (!r.ok || j.error) throw new Error((j.error && j.error.message) || JSON.stringify(j));
  return j;
}

function result(p) {
  const vals = [["FB_PAGE_ID", p.id], ["FB_PAGE_TOKEN", p.access_token]];
  if (p.instagram_business_account) vals.push(["IG_USER_ID", p.instagram_business_account.id]);
  return page(`<h2>✅ 拿到了！粉專：${esc(p.name)}</h2>
  ${p.instagram_business_account ? "" : `<p class="err">⚠️ 這個粉專沒綁 IG 專業帳號，IG 先不會發。</p>`}
  <p>接著把下面 ${vals.length} 組貼到 GitHub（每組做一次）：</p>
  <ol><li>按「打開 GitHub」</li><li>Name 欄：按「複製名稱」貼上</li><li>Secret 欄：按「複製值」貼上</li><li>按綠色「Add secret」</li></ol>
  ${vals.map(([k, v]) => `<div class="box"><div class="name">${k}</div>
    <button onclick="navigator.clipboard.writeText('${k}');this.textContent='已複製名稱 ✓'">複製名稱</button>
    <button onclick="navigator.clipboard.writeText(document.getElementById('${k}').value);this.textContent='已複製值 ✓'">複製值</button>
    <a class="btn" href="${NEW_SECRET}" target="_blank">打開 GitHub</a>
    <input type="hidden" id="${k}" value="${esc(v)}"></div>`).join("")}
  <p class="small">⚠️ 這些值等於你粉專的鑰匙，不要傳給別人。全部貼完回 Claude 說「好了」，這個網頁就可以關掉。</p>`);
}

const srv = http.createServer(async (req, res) => {
  const u = new URL(req.url, HOME);
  const send = (html, code = 200) => { res.writeHead(code, { "Content-Type": "text/html; charset=utf-8" }); res.end(html); };
  try {
    if (u.pathname === "/" ) return send(page(`<h2>連結 FB 粉專＋IG</h2>
      <p>1. 打開 <a href="https://developers.facebook.com/apps/${APP_ID}/settings/basic/" target="_blank">應用程式設定</a>，在「應用程式密鑰」按「顯示」，複製那 32 碼。</p>
      <p>2. 貼到下面，按「下一步」：</p>
      <form method="post" action="/start"><input name="s" type="password" autocomplete="off" placeholder="貼上應用程式密鑰（32 碼）"><button>下一步</button></form>`));
    if (u.pathname === "/start" && req.method === "POST") {
      let body = ""; for await (const c of req) body += c;
      secret = (new URLSearchParams(body).get("s") || "").trim();
      if (!/^[0-9a-f]{32}$/i.test(secret)) return send(page(`<p class="err">密鑰格式不對：應該是 32 碼英文數字，不是密碼或電話。</p><a class="btn" href="/">重來</a>`));
      res.writeHead(302, { Location: "https://www.facebook.com/v23.0/dialog/oauth?" + new URLSearchParams({ client_id: APP_ID, redirect_uri: CB, scope: SCOPE, response_type: "code" }) });
      return res.end();
    }
    if (u.pathname === "/cb") {
      if (!u.searchParams.get("code")) return send(page(`<p class="err">沒有授權：${esc(u.searchParams.get("error_description") || "")}</p><a class="btn" href="/">重來</a>`));
      const short = (await getJSON(`${G}/oauth/access_token?` + new URLSearchParams({ client_id: APP_ID, client_secret: secret, redirect_uri: CB, code: u.searchParams.get("code") }))).access_token;
      const long = (await getJSON(`${G}/oauth/access_token?` + new URLSearchParams({ grant_type: "fb_exchange_token", client_id: APP_ID, client_secret: secret, fb_exchange_token: short }))).access_token;
      pages = (await getJSON(`${G}/me/accounts?fields=id,name,access_token,instagram_business_account&access_token=${long}`)).data || [];
      if (!pages.length) return send(page(`<p class="err">找不到粉專：授權時要勾選你的粉專。</p><a class="btn" href="/">重來</a>`));
      if (pages.length === 1) return send(result(pages[0]));
      return send(page(`<h2>要發到哪個粉專？</h2>${pages.map((p, i) => `<p><a class="btn" href="/pick?i=${i}">${esc(p.name)}${p.instagram_business_account ? "（已綁 IG）" : ""}</a></p>`).join("")}`));
    }
    if (u.pathname === "/pick") return send(result(pages[Number(u.searchParams.get("i"))]));
    send("", 404);
  } catch (e) {
    send(page(`<p class="err">❌ 失敗：${esc(e.message)}</p><a class="btn" href="/">重來</a>`));
  }
});
srv.listen(PORT, () => {
  console.log("已在 Chrome 打開連結網頁：" + HOME + "（這個視窗不要關，做完再關）");
  try { execSync(`start "" "${HOME}"`); } catch (_) { /* 手動打開 */ }
});
