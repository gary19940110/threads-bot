// 連結 YouTube 的網頁版小幫手（只在你自己電腦上跑，不會上傳任何東西）
//   node tools/connect-yt-web.js
// 打開 http://localhost:8766/：貼上 Google OAuth 用戶端 ID 和密鑰 → Google 授權 → 顯示要貼到 GitHub Secrets 的值
const http = require("http");
const PORT = 8766, HOME = `http://localhost:${PORT}/`, CB = `http://127.0.0.1:${PORT}/cb`;
const NEW_SECRET = "https://github.com/gary19940110/threads-bot/settings/secrets/actions/new";
let cid = "", csec = "";

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const page = body => `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>連結 YouTube</title><style>body{font:18px/1.6 system-ui,"Microsoft JhengHei";max-width:640px;margin:40px auto;padding:0 16px;color:#222}
input{width:100%;font-size:18px;padding:10px;box-sizing:border-box;margin:4px 0 12px}button,.btn{font-size:18px;padding:10px 18px;margin:8px 0;background:#c00;color:#fff;border:0;border-radius:8px;cursor:pointer;text-decoration:none;display:inline-block}
.box{border:1px solid #ddd;border-radius:10px;padding:14px;margin:14px 0}.name{font-weight:bold;font-size:20px}.err{color:#c00}.small{color:#666;font-size:15px}</style>${body}`;

const srv = http.createServer(async (req, res) => {
  const u = new URL(req.url, HOME);
  const send = (html, code = 200) => { res.writeHead(code, { "Content-Type": "text/html; charset=utf-8" }); res.end(html); };
  try {
    if (u.pathname === "/") return send(page(`<h2>連結 YouTube</h2>
      <p>把 Google Cloud「OAuth 用戶端」的兩個值貼到下面：</p>
      <form method="post" action="/start">用戶端 ID（結尾是 .apps.googleusercontent.com）<input name="id" autocomplete="off">
      用戶端密鑰（GOCSPX- 開頭）<input name="s" type="password" autocomplete="off"><button>下一步</button></form>`));
    if (u.pathname === "/start" && req.method === "POST") {
      let body = ""; for await (const c of req) body += c;
      const f = new URLSearchParams(body); cid = (f.get("id") || "").trim(); csec = (f.get("s") || "").trim();
      if (!cid.endsWith(".apps.googleusercontent.com")) return send(page(`<p class="err">用戶端 ID 不對：結尾應該是 .apps.googleusercontent.com</p><a class="btn" href="/">重來</a>`));
      res.writeHead(302, { Location: "https://accounts.google.com/o/oauth2/v2/auth?" + new URLSearchParams({
        client_id: cid, redirect_uri: CB, response_type: "code", access_type: "offline", prompt: "consent",
        scope: "https://www.googleapis.com/auth/youtube.upload" }) });
      return res.end();
    }
    if (u.pathname === "/cb") {
      if (!u.searchParams.get("code")) return send(page(`<p class="err">沒有授權：${esc(u.searchParams.get("error") || "")}</p><a class="btn" href="${HOME}">重來</a>`));
      const r = await fetch("https://oauth2.googleapis.com/token", { method: "POST", body: new URLSearchParams({
        code: u.searchParams.get("code"), client_id: cid, client_secret: csec, redirect_uri: CB, grant_type: "authorization_code" }) });
      const tok = await r.json();
      if (!tok.refresh_token) throw new Error(tok.error_description || tok.error || "沒拿到 refresh_token");
      const vals = [["YT_CLIENT_ID", cid], ["YT_CLIENT_SECRET", csec], ["YT_REFRESH_TOKEN", tok.refresh_token]];
      return send(page(`<h2>✅ YouTube 授權成功！</h2><p>把下面 3 組貼到 GitHub（Name 欄 Claude 會幫你填）：</p>
        ${vals.map(([k, v]) => `<div class="box"><div class="name">${k}</div>
        <button onclick="navigator.clipboard.writeText(document.getElementById('${k}').value);this.textContent='已複製值 ✓'">複製值</button>
        <input type="hidden" id="${k}" value="${esc(v)}"></div>`).join("")}
        <p class="small">⚠️ 這些值等於你頻道的鑰匙，不要傳給別人。</p>`));
    }
    send("", 404);
  } catch (e) {
    send(page(`<p class="err">❌ 失敗：${esc(e.message)}</p><a class="btn" href="${HOME}">重來</a>`));
  }
});
srv.listen(PORT, () => console.log("YouTube 連結網頁：" + HOME + "（做完再關）"));
