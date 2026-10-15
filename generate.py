#!/usr/bin/env python3
"""每天產生 Threads 草稿（狀態 pending，等阿正在中控台核准）

鉤子挑選：約 70% 用目前分數最高的鉤子，30% 試用得較少的鉤子（探索），
讓系統自己找出最能帶流量和留言的開頭。
需要環境變數 ANTHROPIC_API_KEY。
"""
import datetime as dt
import json
import os
import random
import sys

import requests

from bot import SETTINGS, TZ, drafts, load, now, p, save_draft, cmd_index

STYLE = """你是台中房仲「阿正（黃守正）」的 Threads 小編。阿正連續五年千萬經紀人，主力區域：北屯、北區、東區、南區、南屯、太平、豐原、沙鹿。
寫作風格（守正版）：直接、接地氣、現場仲介思維、像在跟朋友講話；不油、不廢話、不用浮誇形容詞堆疊。
核心觀點：「未來能賣得掉的房子，才是真正的好房子」；重視轉售性、保值、同預算下的其他選擇。
Threads 寫法：
- 第一行就是鉤子，12–24 字，讓人停下來；第二行補一刀。
- 短句、多換行，每段 1–2 行；全文（不含系統自動加的店名署名）控制在 120–380 字。
- 結尾用一個問題邀請留言，或給一個「留言／LINE 拿資料」的理由。
- 引導 LINE 只寫一次：「LINE搜尋 @a0110」或「私訊／加LINE @a0110」。
- 不要放 hashtag（系統會另外設話題標籤），emoji 最多 2 個。
鐵律：
- 只能使用下方「物件資料」與「已知資訊」中的數字與事實。沒有提供的價格、坪數、成交行情、利率、政策數字，一律寫成 [待填:要填什麼]，絕對不可編造。
- 不寫保證增值、保證獲利、穩賺之類的字眼；不寫具體門牌樓層。
- 物件文要看起來像真人分享，不是廣告單；知識文要讓人想收藏或轉給朋友。"""


def pick_hooks(n):
    hooks = load("config/hooks.json", [])
    stats = (load("data/stats.json", {}) or {}).get("hooks", {})
    explore = SETTINGS.get("explore_ratio", 0.3)
    ranked = sorted(hooks, key=lambda h: stats.get(h["id"], {}).get("avg_score", -1), reverse=True)
    tried = [h for h in ranked if stats.get(h["id"], {}).get("n", 0) >= 2]
    recent = [d.get("hook_id") for d in drafts()[-6:]]
    chosen = []
    for _ in range(n):
        pool_exploit = [h for h in tried[:4] if h["id"] not in chosen and h["id"] not in recent[-2:]]
        pool_explore = sorted([h for h in hooks if h["id"] not in chosen],
                              key=lambda h: (stats.get(h["id"], {}).get("n", 0), random.random()))
        if pool_exploit and random.random() > explore:
            chosen.append(random.choice(pool_exploit)["id"])
        else:
            chosen.append(pool_explore[0]["id"])
    by_id = {h["id"]: h for h in hooks}
    return [by_id[i] for i in chosen]


def next_slots(n):
    slots = SETTINGS.get("slots", ["08:30", "12:30", "21:00"])
    taken = {d.get("publish_at", "")[:16] for d in drafts() if d.get("status") in ("pending", "approved")}
    out = []
    day = now().date()
    for offset in range(0, 4):
        for s in slots:
            hh, mm = map(int, s.split(":"))
            t = dt.datetime.combine(day + dt.timedelta(days=offset), dt.time(hh, mm), TZ)
            if t <= now() + dt.timedelta(minutes=90) or t.isoformat()[:16] in taken:
                continue
            out.append(t)
            if len(out) == n:
                return out
    return out


def claude(prompt):
    key = os.environ.get("ANTHROPIC_API_KEY")
    last = None
    for model in SETTINGS.get("models", ["claude-sonnet-5-5"]):
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 4000, "system": STYLE,
                  "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            return "".join(b.get("text", "") for b in r.json()["content"])
        last = f"{model}: {r.status_code} {r.text[:200]}"
        p("模型失敗，換下一個", last)
    raise SystemExit(last)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        p("尚未設定 ANTHROPIC_API_KEY：今天不自動產草稿（可在中控台手動新增，或請 Claude 代寫）")
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else SETTINGS.get("drafts_per_day", 3)
    pending = [d for d in drafts() if d.get("status") == "pending"]
    if len(pending) >= 6:
        p(f"還有 {len(pending)} 篇待審，今天先不產新的")
        return
    listings = [x for x in load("data/listings.json", []) if x.get("active") and x.get("commission_signed")]
    mix = SETTINGS.get("mix", {"listing": 1, "knowledge": 2})
    types = (["listing"] * mix.get("listing", 1) if listings else []) + ["knowledge"] * n
    types = types[:n]
    hooks = pick_hooks(n)
    slots = next_slots(n)
    posted = [d for d in drafts() if d.get("status") == "posted"][-15:]
    top = sorted([d for d in posted if d.get("metrics")], key=lambda d: d["metrics"].get("score", 0), reverse=True)[:3]
    trends = load("data/trends.json", {}) or {}
    trend_lines = []
    for kw, items in (trends.get("keywords") or {}).items():
        for it in items[:3]:
            trend_lines.append(f"[{kw}] {it['text'][:120]}")
    used_listing = [d.get("listing_id") for d in drafts()[-6:]]
    listings.sort(key=lambda x: used_listing.count(x["id"]))

    jobs = []
    li = 0
    for i, t in enumerate(types):
        job = {"no": i + 1, "type": t, "hook": hooks[i]}
        if t == "listing":
            job["listing"] = listings[li % len(listings)]
            li += 1
        jobs.append(job)

    prompt = f"""今天是 {now():%Y-%m-%d（%a）}，請寫 {len(jobs)} 篇 Threads 貼文。

【每篇的任務】
{json.dumps(jobs, ensure_ascii=False, indent=1)}

【近期表現最好的貼文（學它的開頭和節奏，不要抄）】
{chr(10).join('- ' + d['text'].strip().split(chr(10))[0] + f"（觀看 {d['metrics'].get('views', 0)}、留言 {d['metrics'].get('replies', 0)}）" for d in top) or '（還沒有數據）'}

【最近已發過的開頭（避免重複）】
{chr(10).join('- ' + d['text'].strip().split(chr(10))[0] for d in posted[-8:]) or '（無）'}

【Threads 上台中房地產最近熱門話題（選題參考，不可抄）】
{chr(10).join(trend_lines[:15]) or '（尚無資料）'}

knowledge 類型：寫台中買房／換屋／看屋／議價／預售屋／轉售性等實用觀念，要有阿正的現場觀點。
listing 類型：用該物件資料寫，突出 1–2 個最強賣點和適合誰，讓人想私訊問價；price 空白時不要寫價格。
每篇都要用指定的鉤子類型寫第一行。

只輸出 JSON 陣列，不要其他文字：
[{{"no":1,"text":"貼文全文","topic_tag":"從 {SETTINGS.get('topic_tags')} 選一個","why":"一句話說明這篇想打中誰"}}]"""
    raw = claude(prompt)
    raw = raw[raw.find("["): raw.rfind("]") + 1]
    items = json.loads(raw)
    stamp = now().strftime("%Y%m%d%H%M")
    for job, item, slot in zip(jobs, items, slots):
        d = {
            "id": f"{stamp}-{job['no']}",
            "status": "pending",
            "type": job["type"],
            "hook_id": job["hook"]["id"],
            "listing_id": job.get("listing", {}).get("id"),
            "commission_signed": bool(job.get("listing", {}).get("commission_signed")),
            "text": item["text"].strip(),
            "topic_tag": item.get("topic_tag") or (SETTINGS.get("topic_tags") or [""])[0],
            "why": item.get("why", ""),
            "images": list(job.get("listing", {}).get("images") or [])[:10],
            "publish_at": slot.isoformat(),
            "created_at": now().isoformat(),
            "created_by": "ai",
        }
        save_draft(d)
        p("新草稿", d["id"], d["hook_id"], d["text"].split("\n")[0])
    cmd_index()


if __name__ == "__main__":
    main()
