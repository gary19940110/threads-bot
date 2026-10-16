#!/usr/bin/env python3
"""把草稿裡的 card 欄位畫成 1080x1350 的 Threads 圖卡（阿正品牌樣式）

草稿格式：
  "card": {"label": "台中買房筆記", "title": "大標，可用 \\n 換行", "points": ["重點1", "重點2", "重點3"]}
有 card、還沒有圖片的草稿（pending / approved）會產生 images/card-<id>.png 並自動掛到草稿上。
用法：python cards.py            （產生所有缺圖的圖卡）
     python cards.py <draft_id>  （只畫一張，覆蓋舊的）
"""
import glob
import json
import os
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1350
NAVY, NAVY2 = (17, 32, 58), (28, 52, 88)
GOLD = (233, 185, 73)
WHITE = (255, 255, 255)
SOFT = (200, 210, 225)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-{w}.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-{w}.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-{w}.ttc",
]


def font(weight, size):
    from PIL import ImageFont
    fallback = {"Black": ["Black", "Bold"], "Medium": ["Medium", "Regular", "Bold"], "Bold": ["Bold"]}.get(weight, [weight])
    for w in fallback:
        for c in FONT_CANDIDATES:
            p = c.format(w=w)
            if os.path.exists(p):
                return ImageFont.truetype(p, size, index=3)  # index 3 = 繁中 TC
    raise SystemExit("找不到中文字型，請先安裝 fonts-noto-cjk")


def wrap(draw, text, f, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=f) <= max_w:
                cur += ch
            elif ch in "，。、！？」）：；…—" and len(cur) > 1:  # 標點不放行首
                lines.append(cur[:-1])
                cur = cur[-1] + ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def render(card, out_path, brand="阿正｜台灣房屋北屯松竹十一期店", line_id="LINE @a0110"):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(H):  # 上深下淺的漸層
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(NAVY[i] + (NAVY2[i] - NAVY[i]) * t) for i in range(3)))
    M = 88
    # 標籤
    label = card.get("label", "台中買房筆記")
    fl = font("Bold", 34)
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle([M, 110, M + lw + 48, 110 + 64], radius=32, fill=GOLD)
    d.text((M + 24, 110 + 10), label, font=fl, fill=NAVY)
    # 大標
    title = card["title"]
    size = 92
    while True:
        ft = font("Black", size)
        lines = wrap(d, title, ft, W - 2 * M)
        if len(lines) <= 4 or size <= 64:
            break
        size -= 6
    y = 230
    for ln in lines:
        d.text((M, y), ln, font=ft, fill=WHITE)
        y += int(size * 1.32)
    y += 30
    d.rectangle([M, y, M + 120, y + 8], fill=GOLD)
    y += 70
    # 重點
    fp = font("Medium", 50)
    fn = font("Black", 50)
    for i, pt in enumerate(card.get("points", [])[:5], 1):
        num = f"{i:02d}"
        d.text((M, y), num, font=fn, fill=GOLD)
        pl = wrap(d, pt, fp, W - 2 * M - 100)
        for j, ln in enumerate(pl):
            d.text((M + 100, y + j * 70), ln, font=fp, fill=SOFT if j else WHITE)
        y += 70 * len(pl) + 40
        if y > H - 260:
            break
    # 底部品牌列
    d.rectangle([0, H - 150, W, H], fill=(10, 20, 38))
    fb = font("Medium", 34)
    d.text((M, H - 98), brand, font=fb, fill=SOFT)
    fg = font("Black", 40)
    lw = d.textlength(line_id, font=fg)
    d.text((W - M - lw, H - 102), line_id, font=fg, fill=GOLD)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)


def todo():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "drafts", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            dft = json.load(fh)
        rel = f"images/card-{dft.get('id')}.png"
        if dft.get("card") and dft.get("status") in ("pending", "approved") and rel not in (dft.get("images") or []):
            out.append(dft["id"])
    return out


def main():
    if sys.argv[1:] == ["check"]:
        print("yes" if todo() else "no")
        return
    only = sys.argv[1] if len(sys.argv) > 1 else None
    made = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "drafts", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            dft = json.load(fh)
        card = dft.get("card")
        if not card:
            continue
        if only and dft["id"] != only:
            continue
        rel = f"images/card-{dft['id']}.png"
        if not only and (dft.get("status") not in ("pending", "approved") or rel in (dft.get("images") or [])):
            continue
        render(card, os.path.join(ROOT, rel))
        imgs = [x for x in (dft.get("images") or []) if x != rel]
        dft["images"] = [rel] + imgs
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(dft, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        made += 1
        print("已產生圖卡", rel)
    print(f"共 {made} 張")


if __name__ == "__main__":
    main()
