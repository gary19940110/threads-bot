#!/usr/bin/env python3
"""阿正 Threads 自動發文機器人（GitHub Actions 執行）

指令：
  python bot.py publish    發布已核准且到時間的草稿
  python bot.py replies    掃描自己貼文的留言，依規則自動回覆，其餘放進待回清單
  python bot.py insights   更新每篇貼文數據，計算鉤子分數與時段分數
  python bot.py trends     用關鍵字搜尋 Threads 熱門貼文，給 AI 選題參考
  python bot.py refresh    更新 Threads 長效權杖（60 天到期，每週自動續）
  python bot.py index      重建 data/index.json（中控台讀這份）
  python bot.py share      影片貼文同步發到 FB 粉專 Reels／IG Reels／YouTube Shorts（publish 也會順便跑）

環境變數：THREADS_TOKEN、THREADS_USER_ID、REPO（owner/name）、BRANCH
同步發文（有設定才發）：FB_PAGE_TOKEN、FB_PAGE_ID、IG_USER_ID、YT_CLIENT_ID、YT_CLIENT_SECRET、YT_REFRESH_TOKEN
"""
import datetime as dt
import glob
import hashlib
import json
import os
import random
import subprocess
import sys
import time

import requests

API = "https://graph.threads.net/v1.0"
TZ = dt.timezone(dt.timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
DRY = os.environ.get("DRY_RUN") == "1"


def p(*a):
    print(*a, flush=True)


def path(*parts):
    return os.path.join(ROOT, *parts)


def load(rel, default=None):
    try:
        with open(path(rel), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(rel, obj):
    full = path(rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def now():
    return dt.datetime.now(TZ)


def parse_time(s):
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=TZ)


SETTINGS = load("config/settings.json", {})
TOKEN = os.environ.get("THREADS_TOKEN", "")
USER_ID = os.environ.get("THREADS_USER_ID", "me")


class ThreadsError(Exception):
    pass


def call(method, endpoint, **params):
    if DRY:
        p("[DRY]", method, endpoint, {k: v for k, v in params.items() if k != "access_token"})
        return {"id": "dry_" + hashlib.md5(json.dumps(params, ensure_ascii=False).encode()).hexdigest()[:8], "data": []}
    params["access_token"] = TOKEN
    url = endpoint if endpoint.startswith("http") else f"{API}/{endpoint}"
    for attempt in range(3):
        r = requests.request(method, url, params=params if method == "GET" else None,
                             data=params if method != "GET" else None, timeout=60)
        if r.status_code < 500:
            break
        time.sleep(5 * (attempt + 1))
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in body:
        raise ThreadsError(f"{r.status_code} {json.dumps(body, ensure_ascii=False)[:400]}")
    return body


# ---------- 草稿 ----------

def drafts():
    out = []
    for f in sorted(glob.glob(path("drafts", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        d["_file"] = f
        out.append(d)
    return out


def save_draft(d):
    f = d.pop("_file", None) or path("drafts", f"{d['id']}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    d["_file"] = f


def full_text(d):
    body = d["text"].strip()
    if SETTINGS.get("footer_in_comment"):
        return body
    lines = [x.strip() for x in SETTINGS.get("brand_footer", "").split("\n")]
    keep = [x for x in lines if x and x not in body and not ("經紀字" in x and "經紀字" in body)]
    return f"{body}\n\n" + "\n".join(keep) if keep else body


def image_url(rel):
    if rel.startswith("http"):
        return rel
    repo = os.environ["REPO"]
    branch = os.environ.get("BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel.lstrip('/')}"


def media_url(rel):
    """影片放在 docs/videos/，走 GitHub Pages 網址（Threads 需要正確的影片格式標頭）。"""
    if rel.startswith("docs/"):
        owner, name = os.environ["REPO"].split("/")
        return f"https://{owner}.github.io/{name}/{rel[5:]}"
    return image_url(rel)


def is_video(rel):
    return rel.lower().endswith((".mp4", ".mov"))


def media_params(rel):
    if is_video(rel):
        return {"media_type": "VIDEO", "video_url": media_url(rel)}
    return {"media_type": "IMAGE", "image_url": image_url(rel)}


def wait_ready(container_id, tries=12):
    for _ in range(tries):
        st = call("GET", container_id, fields="status,error_message")
        status = st.get("status", "FINISHED" if DRY else "")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise ThreadsError(f"container {status}: {st.get('error_message')}")
        time.sleep(10)
    raise ThreadsError("container 處理逾時")


def publish_one(d):
    text = full_text(d)
    limit = SETTINGS.get("max_chars", 500)
    if len(text) > limit:
        raise ThreadsError(f"字數 {len(text)} 超過 {limit}")
    if "[待填" in text:
        raise ThreadsError("文案還有 [待填] 沒填")
    vids = d.get("videos") or []
    imgs = (vids + (d.get("images") or []))[:20]  # 影片排在照片前面
    tries = 36 if vids else 12  # 影片要等 Threads 轉檔，最多約 6 分鐘
    base = {}
    if d.get("topic_tag"):
        base["topic_tag"] = d["topic_tag"].replace(".", "").replace("&", "")
    if not imgs:
        c = call("POST", f"{USER_ID}/threads", media_type="TEXT", text=text, **base)
    elif len(imgs) == 1:
        c = call("POST", f"{USER_ID}/threads", **media_params(imgs[0]), text=text, **base)
    else:
        kids = []
        for rel in imgs:
            k = call("POST", f"{USER_ID}/threads", **media_params(rel), is_carousel_item="true")
            kids.append(k["id"])
        for k in kids:
            wait_ready(k, tries)
        c = call("POST", f"{USER_ID}/threads", media_type="CAROUSEL", children=",".join(kids), text=text, **base)
    wait_ready(c["id"], tries)
    res = call("POST", f"{USER_ID}/threads_publish", creation_id=c["id"])
    media_id = res["id"]
    link = ""
    try:
        link = call("GET", media_id, fields="permalink").get("permalink", "")
    except ThreadsError:
        pass
    return media_id, link


def cmd_publish():
    t = now()
    due = [d for d in drafts() if d.get("status") == "approved" and parse_time(d["publish_at"]) <= t]
    if not due:
        p("沒有到時間的已核准草稿")
    for d in due[:3]:  # 一次最多 3 篇，避免洗版
        if d.get("type") == "listing" and not d.get("commission_signed"):
            d.update(status="failed", error="物件文未勾選「已簽委託」，依經紀業管理條例第21條不可刊登")
            save_draft(d)
            continue
        try:
            mid, link = publish_one(d)
            d.update(status="posted", threads_id=mid, permalink=link, posted_at=now().isoformat(), error="")
            p("已發布", d["id"], link)
            if first_comment(d):
                d["first_comment_pending"] = True
        except Exception as e:  # noqa: BLE001
            d["tries"] = d.get("tries", 0) + 1
            d["error"] = str(e)[:400]
            if d["tries"] >= 3:
                d["status"] = "failed"
            p("發布失敗", d["id"], e)
        save_draft(d)
    # 發文後自己留言（第一則留言）
    for d in drafts():
        if d.get("status") == "posted" and d.get("first_comment_pending") and d.get("threads_id"):
            fc = first_comment(d)
            try:
                if not DRY:
                    time.sleep(8)
                send_reply(d["threads_id"], fc[0], fc[1])
                d.pop("first_comment_pending", None)
                d["first_comment_done"] = now().isoformat()
                p("已自己留言", d["id"])
            except Exception as e:  # noqa: BLE001
                d["first_comment_tries"] = d.get("first_comment_tries", 0) + 1
                if d["first_comment_tries"] >= 3:
                    d.pop("first_comment_pending", None)
                p("自己留言失敗", d["id"], e)
            save_draft(d)
    cmd_share()
    cmd_index()


# ---------- 同步發到 FB 粉專 Reels／IG Reels／YouTube Shorts ----------
# 影片貼文發到 Threads 之後，照草稿的 share{fb,ig,yt,yt_title} 再發到其他平台。
# 結果寫在 share_status{fb|ig|yt:{id,url,at}|{error,tries}}，失敗最多重試 3 次，不影響 Threads 那篇。

GRAPH = "https://graph.facebook.com/v23.0"
PLATFORMS = {"fb": "FB 粉專", "ig": "IG", "yt": "YouTube"}


def connected():
    e = os.environ.get
    return {"fb": bool(e("FB_PAGE_TOKEN") and e("FB_PAGE_ID")),
            "ig": bool(e("FB_PAGE_TOKEN") and e("IG_USER_ID")),
            "yt": bool(e("YT_CLIENT_ID") and e("YT_CLIENT_SECRET") and e("YT_REFRESH_TOKEN"))}


def graph(method, endpoint, **params):
    if DRY:
        p("[DRY]", method, endpoint, {k: v for k, v in params.items() if k != "access_token"})
        return {"id": "dry", "video_id": "dry", "status_code": "FINISHED", "status": {"video_status": "ready"}, "permalink": ""}
    params["access_token"] = os.environ["FB_PAGE_TOKEN"]
    url = endpoint if endpoint.startswith("http") else f"{GRAPH}/{endpoint}"
    r = requests.request(method, url, params=params if method == "GET" else None,
                         data=params if method != "GET" else None, timeout=120)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in body:
        raise ThreadsError(f"{r.status_code} {json.dumps(body, ensure_ascii=False)[:400]}")
    return body


def share_caption(d, with_contact):
    """FB／IG 說明文字：主文＋主題 hashtag；YouTube 說明欄再加聯繫方式和署名（YouTube 沒有自動自己留言）。"""
    out = d["text"].strip()
    if d.get("topic_tag"):
        out += f"\n\n#{d['topic_tag']}"
    if with_contact:
        fc = first_comment(d)
        if fc and fc[0]:
            out += "\n\n" + fc[0]
    return out


def share_fb(d, video):
    page = os.environ["FB_PAGE_ID"]
    st = graph("POST", f"{page}/video_reels", upload_phase="start")
    vid = st["video_id"]
    if not DRY:
        with open(path(video), "rb") as f:
            data = f.read()
        r = requests.post(f"https://rupload.facebook.com/video-upload/v23.0/{vid}", data=data, timeout=600,
                          headers={"Authorization": f"OAuth {os.environ['FB_PAGE_TOKEN']}", "offset": "0",
                                   "file_size": str(len(data))})
        if r.status_code >= 400:
            raise ThreadsError(f"FB 上傳失敗 {r.status_code} {r.text[:300]}")
    graph("POST", f"{page}/video_reels", upload_phase="finish", video_id=vid, video_state="PUBLISHED",
          description=share_caption(d, False))
    for _ in range(36):  # 等 FB 轉檔，最多約 6 分鐘
        s = graph("GET", vid, fields="status").get("status", {})
        if s.get("video_status") in ("ready", "published") or (s.get("publishing_phase") or {}).get("status") == "complete" or DRY:
            break
        if s.get("video_status") == "error":
            raise ThreadsError(f"FB 轉檔失敗：{json.dumps(s, ensure_ascii=False)[:300]}")
        time.sleep(10)
    return vid, f"https://www.facebook.com/reel/{vid}"


def share_ig(d, video):
    ig = os.environ["IG_USER_ID"]
    c = graph("POST", f"{ig}/media", media_type="REELS", video_url=media_url(video),
              caption=share_caption(d, False)[:2200], share_to_feed="true")
    for _ in range(36):
        s = graph("GET", c["id"], fields="status_code,status")
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            raise ThreadsError(f"IG 轉檔失敗：{s.get('status')}")
        time.sleep(10)
    else:
        raise ThreadsError("IG 轉檔逾時")
    mid = graph("POST", f"{ig}/media_publish", creation_id=c["id"])["id"]
    link = graph("GET", mid, fields="permalink").get("permalink", "")
    return mid, link


def share_comment(d, key, mid):
    """FB／IG 也跟 Threads 一樣：聯繫方式和署名放自己第一則留言。失敗不影響貼文。"""
    fc = first_comment(d)
    if not fc or not fc[0]:
        return
    try:
        graph("POST", f"{mid}/comments", message=fc[0])
    except ThreadsError as e:
        p(f"{PLATFORMS[key]} 自己留言失敗", d["id"], e)


def share_yt(d, video):
    if DRY:
        p("[DRY] YouTube 上傳", video)
        return "dry", ""
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}).json()
    if "access_token" not in tok:
        raise ThreadsError(f"YouTube 授權失敗（可能要重新連結）：{tok}")
    title = (d.get("share") or {}).get("yt_title") or d["text"].strip().split("\n")[0]
    title = title.replace("<", "").replace(">", "").strip()[:90] + " #Shorts"
    meta = {"snippet": {"title": title, "description": share_caption(d, True)[:4900], "categoryId": "22",
                        "tags": [t for t in [d.get("topic_tag"), "台中買房", "Shorts"] if t]},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    with open(path(video), "rb") as f:
        data = f.read()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      json=meta, timeout=60, headers={**h, "X-Upload-Content-Type": "video/*",
                                                      "X-Upload-Content-Length": str(len(data))})
    if r.status_code >= 400 or "Location" not in r.headers:
        raise ThreadsError(f"YouTube 上傳失敗 {r.status_code} {r.text[:300]}")
    r = requests.put(r.headers["Location"], data=data, timeout=900, headers={**h, "Content-Type": "video/*"})
    if r.status_code >= 400:
        raise ThreadsError(f"YouTube 上傳失敗 {r.status_code} {r.text[:300]}")
    vid = r.json()["id"]
    return vid, f"https://youtube.com/shorts/{vid}"


SHARERS = {"fb": share_fb, "ig": share_ig, "yt": share_yt}


def cmd_share():
    ok = connected()
    if load("data/platforms.json", {}).get("connected") != ok:
        save("data/platforms.json", {"connected": ok, "checked_at": now().isoformat()})
    cutoff = now() - dt.timedelta(days=2)
    for d in drafts():
        sh = d.get("share") or {}
        vids = d.get("videos") or []
        if d.get("status") != "posted" or not vids or not any(sh.get(k) for k in PLATFORMS):
            continue
        if not d.get("posted_at") or parse_time(d["posted_at"]) < cutoff:
            continue
        st = d.setdefault("share_status", {})
        for key, name in PLATFORMS.items():
            cur = st.get(key) or {}
            if not sh.get(key) or cur.get("id") or cur.get("tries", 0) >= 3:
                continue
            if not ok[key]:  # 還沒連結就先記著，2 天內連結好會補發
                msg = f"還沒連結 {name}"
                if cur.get("error") != msg:
                    st[key] = {"error": msg, "tries": 0}
                    save_draft(d)
                continue
            try:
                mid, link = SHARERS[key](d, vids[0])
                st[key] = {"id": mid, "url": link, "at": now().isoformat()}
                p(f"已同步到 {name}", d["id"], link)
                if key in ("fb", "ig"):
                    share_comment(d, key, mid)
            except Exception as e:  # noqa: BLE001
                st[key] = {"error": str(e)[:400], "tries": cur.get("tries", 0) + 1}
                p(f"同步到 {name} 失敗", d["id"], e)
            save_draft(d)


def first_comment(d):
    """回傳 (文字, 圖片) 或 None。
    自己留言＝額外文字＋（可勾選）聯繫方式＋（可勾選）署名。主文不放聯繫方式和署名，都放這裡；
    主文或留言文字裡已經有的不重複加。草稿沒設定就用 settings 的預設。"""
    fc = d.get("first_comment")
    dflt = SETTINGS.get("first_comment") or {}
    if fc is None:
        fc = {"enabled": bool(dflt.get("enabled"))}
    if not fc.get("enabled"):
        return None
    body = d.get("text", "")
    text = (fc.get("text") or "").strip() or (dflt.get("text") or "").strip()
    link = (fc.get("link") or "").strip() or ("" if fc.get("text") else (dflt.get("link") or "").strip())
    imgs = fc.get("images") or ([] if fc.get("text") else dflt.get("images") or [])
    out = ar_text({"text": text, "link": link}) if (text or link) else ""
    blocks = []
    contact = (SETTINGS.get("contact_block") or "").strip()
    phone = SETTINGS.get("phone") or "\0"
    if contact and fc.get("contact", dflt.get("contact", True)) and phone not in out and phone not in body:
        blocks.append(contact)
    sign = (SETTINGS.get("brand_footer") or "").strip()
    if sign and SETTINGS.get("footer_in_comment") and fc.get("sign", dflt.get("sign", True)) \
            and "經紀字" not in out and "經紀字" not in body:
        blocks.append(sign)
    if blocks:
        foot = "\n\n".join(blocks)
        out = (out[: 500 - len(foot) - 2].rstrip() + "\n\n" + foot).strip() if out else foot
    if not out and not imgs:
        return None
    return out, imgs


# ---------- 自動回覆 ----------

def classify(text, rules):
    t = (text or "").lower()
    if any(k.lower() in t for k in rules.get("ignore_keywords", [])):
        return "ignore"
    for r in rules["rules"]:
        if any(k.lower() in t for k in r["keywords"]):
            return r["id"]
    return None


def pick_reply(rule, seed):
    opts = rule["replies"]
    i = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(opts)
    return opts[i].replace("{line}", SETTINGS.get("line_id", ""))


def ar_match(ar, text):
    kws = [k for k in (ar.get("keywords") or []) if k.strip()]
    t = (text or "").lower()
    return not kws or any(k.lower() in t for k in kws)


def ar_text(ar):
    t = (ar.get("text") or "").replace("{line}", SETTINGS.get("line_id", ""))
    link = (ar.get("link") or "").strip()
    if "{link}" in t:
        t = t.replace("{link}", link)
    elif link:
        t = f"{t}\n{link}"
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip()[:500]


def send_reply(cid, text, images=None):
    """在留言底下回覆：純文字、單張圖或多張圖（輪播）。圖片失敗就退回純文字。"""
    imgs = [x for x in (images or []) if x][:10]
    try:
        if not imgs:
            c = call("POST", f"{USER_ID}/threads", media_type="TEXT", text=text, reply_to_id=cid)
        elif len(imgs) == 1:
            c = call("POST", f"{USER_ID}/threads", media_type="IMAGE", image_url=image_url(imgs[0]), text=text, reply_to_id=cid)
        else:
            kids = [call("POST", f"{USER_ID}/threads", media_type="IMAGE", image_url=image_url(x), is_carousel_item="true")["id"] for x in imgs]
            for k in kids:
                wait_ready(k)
            c = call("POST", f"{USER_ID}/threads", media_type="CAROUSEL", children=",".join(kids), text=text, reply_to_id=cid)
        wait_ready(c["id"])
        call("POST", f"{USER_ID}/threads_publish", creation_id=c["id"])
    except ThreadsError as e:
        if not imgs:
            raise
        p("附圖回覆失敗，改用純文字", cid, e)
        send_reply(cid, text)


def my_username():
    cache = load("data/me.json")
    if cache:
        return cache.get("username", "")
    me = call("GET", USER_ID, fields="id,username")
    save("data/me.json", {"id": me.get("id"), "username": me.get("username", "")})
    return me.get("username", "")


def cmd_replies():
    cfg = SETTINGS.get("reply", {})
    if not cfg.get("enabled", True):
        p("自動回覆已關閉")
        return
    rules = load("config/reply_rules.json")
    rule_by_id = {r["id"]: r for r in rules["rules"]}
    replied = load("data/replied.json", {})
    inbox = load("data/inbox.json", [])
    inbox_ids = {x["id"] for x in inbox}
    me = my_username()
    cutoff = now() - dt.timedelta(days=cfg.get("max_post_age_days", 14))
    budget = cfg.get("max_per_run", 15)
    sent = 0
    for d in drafts():
        if d.get("status") != "posted" or not d.get("threads_id") or not d.get("posted_at"):
            continue
        if parse_time(d["posted_at"]) < cutoff:
            continue
        try:
            res = call("GET", f"{d['threads_id']}/replies", fields="id,text,username,timestamp,permalink,hide_status")
        except ThreadsError as e:
            p("讀留言失敗", d["id"], e)
            continue
        users_done = set(replied.get(f"users:{d['threads_id']}", []))
        for c in res.get("data", []):
            cid = c["id"]
            if cid in replied or cid in inbox_ids or c.get("username") == me:
                continue
            if c.get("hide_status") not in (None, "NOT_HUSHED", "UNHUSHED"):
                continue
            kind = classify(c.get("text"), rules)
            if kind == "ignore":
                replied[cid] = "ignored"
                continue
            ar = d.get("auto_reply") or {}
            if ar.get("enabled") and (ar.get("text") or ar.get("images")) and ar_match(ar, c.get("text")):
                if c.get("username") in users_done:
                    replied[cid] = "same_user"
                    continue
                if sent >= budget:
                    continue
                try:
                    send_reply(cid, ar_text(ar), ar.get("images") or [])
                    replied[cid] = "auto_reply"
                    users_done.add(c.get("username"))
                    sent += 1
                    p("已用預設資料回覆", c.get("username"), d["id"])
                    if not DRY:
                        time.sleep(random.randint(cfg.get("min_delay_sec", 20), cfg.get("max_delay_sec", 45)))
                except ThreadsError as e:
                    p("回覆失敗", cid, e)
                continue
            if kind and c.get("username") not in users_done and sent < budget:
                msg = pick_reply(rule_by_id[kind], cid)
                try:
                    send_reply(cid, msg)
                    replied[cid] = kind
                    users_done.add(c.get("username"))
                    sent += 1
                    p("已回覆", c.get("username"), kind)
                    if not DRY:
                        time.sleep(random.randint(cfg.get("min_delay_sec", 20), cfg.get("max_delay_sec", 45)))
                except ThreadsError as e:
                    p("回覆失敗", cid, e)
            elif kind and c.get("username") in users_done:
                replied[cid] = "same_user"
            else:
                inbox.append({
                    "id": cid, "draft_id": d["id"], "post_first_line": d["text"].strip().split("\n")[0][:40],
                    "username": c.get("username"), "text": c.get("text"), "timestamp": c.get("timestamp"),
                    "permalink": c.get("permalink") or d.get("permalink"), "handled": False,
                })
                inbox_ids.add(cid)
        replied[f"users:{d['threads_id']}"] = sorted(u for u in users_done if u)
    save("data/replied.json", replied)
    save("data/inbox.json", inbox[-300:])
    p(f"本輪自動回覆 {sent} 則，待你親自回 {sum(1 for x in inbox if not x.get('handled'))} 則")


# ---------- 數據 ----------

METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]


def engagement(m):
    return m.get("likes", 0) + 3 * m.get("replies", 0) + 2 * (m.get("reposts", 0) + m.get("quotes", 0) + m.get("shares", 0))


def score(m):
    v = m.get("views", 0)
    er = engagement(m) / v if v else 0
    return round(v * (1 + 20 * er), 1)


def cmd_insights():
    cutoff = now() - dt.timedelta(days=45)
    for d in drafts():
        if d.get("status") != "posted" or not d.get("threads_id"):
            continue
        if d.get("posted_at") and parse_time(d["posted_at"]) < cutoff and d.get("metrics"):
            continue
        try:
            res = call("GET", f"{d['threads_id']}/insights", metric=",".join(METRICS))
        except ThreadsError as e:
            p("數據讀取失敗", d["id"], e)
            continue
        m = {}
        for item in res.get("data", []):
            vals = item.get("values") or []
            val = vals[0].get("value") if vals else item.get("total_value", {}).get("value", 0)
            m[item.get("name")] = val or 0
        m["score"] = score(m)
        m["updated_at"] = now().isoformat()
        d["metrics"] = m
        save_draft(d)
    # 鉤子、類型、時段統計
    hooks = {h["id"]: h for h in load("config/hooks.json", [])}
    agg = {}
    hours = {}
    types = {}
    for d in drafts():
        m = d.get("metrics")
        if d.get("status") != "posted" or not m:
            continue
        for bucket, key in ((agg, d.get("hook_id") or "—"), (types, d.get("type") or "—")):
            b = bucket.setdefault(key, {"n": 0, "views": 0, "eng": 0, "score": 0})
            b["n"] += 1
            b["views"] += m.get("views", 0)
            b["eng"] += engagement(m)
            b["score"] += m.get("score", 0)
        h = parse_time(d["posted_at"]).astimezone(TZ).hour
        hb = hours.setdefault(str(h), {"n": 0, "views": 0})
        hb["n"] += 1
        hb["views"] += m.get("views", 0)

    def finish(b):
        return {k: {"n": v["n"], "avg_views": round(v["views"] / v["n"]), "avg_eng": round(v["eng"] / v["n"], 1),
                    "avg_score": round(v["score"] / v["n"], 1)} for k, v in b.items()}

    hs = finish(agg)
    for k, v in hs.items():
        v["name"] = hooks.get(k, {}).get("name", k)
    # 鉤子汰弱留強：和中位數比較
    scores = sorted(v["avg_score"] for v in hs.values() if v["n"] >= 2)
    med = scores[len(scores) // 2] if scores else 0
    for k, v in hs.items():
        if v["n"] < 2 or not med:
            v["status"] = "測試中"
        elif v["n"] >= 3 and v["avg_score"] < med * 0.5:
            v["status"] = "淘汰"
        elif v["avg_score"] >= med * 1.3:
            v["status"] = "主力"
        else:
            v["status"] = "觀察"
    # 低流量貼文：發布超過 72 小時、觀看低於近 30 篇中位數的 3 成
    posted = [d for d in drafts() if d.get("status") == "posted" and d.get("metrics") and d.get("posted_at")]
    views = sorted(d["metrics"].get("views", 0) for d in posted[-30:])
    vmed = views[len(views) // 2] if views else 0
    low = []
    for d in posted:
        if now() - parse_time(d["posted_at"]) < dt.timedelta(hours=72) or not vmed:
            continue
        m = d["metrics"]
        if m.get("views", 0) < vmed * 0.3:
            low.append({"id": d["id"], "first_line": d["text"].strip().split("\n")[0][:40], "views": m.get("views", 0),
                        "replies": m.get("replies", 0), "permalink": d.get("permalink"), "hook_id": d.get("hook_id")})
    save("data/stats.json", {
        "updated_at": now().isoformat(), "hooks": hs, "types": finish(types), "median_views": vmed, "low_posts": low,
        "hours": {k: {"n": v["n"], "avg_views": round(v["views"] / v["n"])} for k, v in hours.items()},
    })
    try:
        acct = call("GET", f"{USER_ID}/threads_insights", metric="followers_count")
        fc = 0
        for item in acct.get("data", []):
            fc = item.get("total_value", {}).get("value", fc)
        hist = load("data/followers.json", [])
        today = now().date().isoformat()
        hist = [x for x in hist if x["date"] != today] + [{"date": today, "followers": fc}]
        save("data/followers.json", hist[-180:])
    except ThreadsError as e:
        p("粉絲數讀取失敗", e)
    cmd_index()


def cmd_trends():
    out = {"updated_at": now().isoformat(), "keywords": {}}
    for kw in SETTINGS.get("search_keywords", [])[:10]:
        try:
            res = call("GET", "keyword_search", q=kw, search_type="TOP",
                       fields="id,text,media_type,permalink,timestamp,username")
        except ThreadsError as e:
            p("搜尋失敗", kw, e)
            continue
        out["keywords"][kw] = [
            {"text": (x.get("text") or "")[:220], "permalink": x.get("permalink"), "timestamp": x.get("timestamp")}
            for x in res.get("data", [])[:12]
        ]
    save("data/trends.json", out)


def cmd_refresh():
    res = call("GET", "https://graph.threads.net/refresh_access_token", grant_type="th_refresh_token")
    new = res.get("access_token")
    if not new or DRY:
        p("權杖未更新", res if DRY else "")
        return
    days = int(res.get("expires_in", 0)) // 86400
    subprocess.run(["gh", "secret", "set", "THREADS_TOKEN", "--repo", os.environ["REPO"]], input=new.encode(), check=True)
    save("data/token_status.json", {"refreshed_at": now().isoformat(), "expires_in_days": days})
    p(f"權杖已更新，有效 {days} 天")


def cmd_index():
    idx = []
    for d in drafts():
        idx.append({
            "id": d["id"], "status": d.get("status"), "type": d.get("type"), "hook_id": d.get("hook_id"),
            "publish_at": d.get("publish_at"), "posted_at": d.get("posted_at"), "permalink": d.get("permalink"),
            "first_line": d.get("text", "").strip().split("\n")[0][:60], "metrics": d.get("metrics"),
            "error": d.get("error", ""), "images": len(d.get("images") or []), "videos": len(d.get("videos") or []), "lib_id": d.get("lib_id", ""),
            "share": {k: v.get("url") or ("失敗" if v.get("error") else "") for k, v in (d.get("share_status") or {}).items()},
        })
    idx.sort(key=lambda x: x.get("publish_at") or "", reverse=True)
    save("data/index.json", {"updated_at": now().isoformat(), "drafts": idx})


def cmd_wait():
    """GitHub 排程常延遲 30~45 分鐘；若接下來 25 分鐘內有要發的貼文，就在這裡等到時間（只印 yes / no）。"""
    lim = now() + dt.timedelta(minutes=int(os.environ.get("WAIT_MIN", "25")))
    ups = [parse_time(d["publish_at"]) for d in drafts()
           if d.get("status") == "approved" and d.get("publish_at") and now() < parse_time(d["publish_at"]) <= lim]
    if not ups:
        print("no")
        return
    if not DRY:
        time.sleep(max(0, (min(ups) - now()).total_seconds() + 5))
    print("yes")


COMMANDS = {"wait": cmd_wait, "publish": cmd_publish, "replies": cmd_replies, "insights": cmd_insights,
            "trends": cmd_trends, "refresh": cmd_refresh, "index": cmd_index, "share": cmd_share}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] != "index" and not TOKEN and not DRY:
        p("缺少 THREADS_TOKEN，請到 GitHub Settings → Secrets 設定")
        sys.exit(1)
    for name in sys.argv[1:]:
        COMMANDS[name]()
