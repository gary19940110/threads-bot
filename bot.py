#!/usr/bin/env python3
"""阿正 Threads 自動發文機器人（GitHub Actions 執行）

指令：
  python bot.py publish    發布已核准且到時間的草稿
  python bot.py replies    掃描自己貼文的留言，依規則自動回覆，其餘放進待回清單
  python bot.py insights   更新每篇貼文數據，計算鉤子分數與時段分數
  python bot.py trends     用關鍵字搜尋 Threads 熱門貼文，給 AI 選題參考
  python bot.py refresh    更新 Threads 長效權杖（60 天到期，每週自動續）
  python bot.py index      重建 data/index.json（中控台讀這份）

環境變數：THREADS_TOKEN、THREADS_USER_ID、REPO（owner/name）、BRANCH
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
    footer = SETTINGS.get("brand_footer", "").strip()
    return f"{body}\n\n{footer}" if footer and footer not in body else body


def image_url(rel):
    if rel.startswith("http"):
        return rel
    repo = os.environ["REPO"]
    branch = os.environ.get("BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel.lstrip('/')}"


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
    imgs = d.get("images") or []
    base = {}
    if d.get("topic_tag"):
        base["topic_tag"] = d["topic_tag"].replace(".", "").replace("&", "")
    if not imgs:
        c = call("POST", f"{USER_ID}/threads", media_type="TEXT", text=text, **base)
    elif len(imgs) == 1:
        c = call("POST", f"{USER_ID}/threads", media_type="IMAGE", image_url=image_url(imgs[0]), text=text, **base)
    else:
        kids = []
        for rel in imgs[:20]:
            k = call("POST", f"{USER_ID}/threads", media_type="IMAGE", image_url=image_url(rel), is_carousel_item="true")
            kids.append(k["id"])
        for k in kids:
            wait_ready(k)
        c = call("POST", f"{USER_ID}/threads", media_type="CAROUSEL", children=",".join(kids), text=text, **base)
    wait_ready(c["id"])
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
        except Exception as e:  # noqa: BLE001
            d["tries"] = d.get("tries", 0) + 1
            d["error"] = str(e)[:400]
            if d["tries"] >= 3:
                d["status"] = "failed"
            p("發布失敗", d["id"], e)
        save_draft(d)
    cmd_index()


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
            if kind and c.get("username") not in users_done and sent < budget:
                msg = pick_reply(rule_by_id[kind], cid)
                try:
                    r = call("POST", f"{USER_ID}/threads", media_type="TEXT", text=msg, reply_to_id=cid)
                    wait_ready(r["id"])
                    call("POST", f"{USER_ID}/threads_publish", creation_id=r["id"])
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
            "error": d.get("error", ""), "images": len(d.get("images") or []),
        })
    idx.sort(key=lambda x: x.get("publish_at") or "", reverse=True)
    save("data/index.json", {"updated_at": now().isoformat(), "drafts": idx})


COMMANDS = {"publish": cmd_publish, "replies": cmd_replies, "insights": cmd_insights,
            "trends": cmd_trends, "refresh": cmd_refresh, "index": cmd_index}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] != "index" and not TOKEN and not DRY:
        p("缺少 THREADS_TOKEN，請到 GitHub Settings → Secrets 設定")
        sys.exit(1)
    for name in sys.argv[1:]:
        COMMANDS[name]()
