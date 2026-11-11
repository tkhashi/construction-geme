#!/usr/bin/env python3
"""愛嬌のある目のサンプル（ユーザー指示 2026-11-08「今までの目に関する指示は無視して愛嬌ある感じに」）
これまでの目のルール（小さい縦バー・ハイライトなし等）は一旦すべて外し、
「愛嬌」を狙った大きめの目を4スタイル試す。サンプル止まりで全員には展開しない。
出力: sheets/eye_charming.png（主人公で4スタイル比較＋他キャラへの適用例）
"""
from PIL import Image, ImageDraw, ImageFont
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C, shade, add_outline, FACE_SPANS, INK, WHITE

OUT = os.path.dirname(os.path.abspath(__file__))
EYE_TOP = 16

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    if 0 <= x < 48 and 0 <= y < 48:
        d.point((x, y), fill=col)

def draw_eye_charming(d, cx, style, side):
    """side: 左目=-1 / 右目=+1（u は外側が正）"""
    def P(u, v, col=INK):
        px(d, cx + u * side, EYE_TOP + v, col)
    if style == 'A':      # キラキラ丸目：大きな楕円＋ハイライト2つ
        d.ellipse([cx - 4, EYE_TOP, cx + 4, EYE_TOP + 10], fill=INK)
        rect(d, cx - 2, EYE_TOP + 2, cx - 1, EYE_TOP + 3, WHITE)
        px(d, cx + 2, EYE_TOP + 7, WHITE)
    elif style == 'B':    # まつ毛丸目：太い上のライン＋外側の跳ね＋ハイライト
        d.ellipse([cx - 4, EYE_TOP + 1, cx + 4, EYE_TOP + 10], fill=INK)
        rect(d, cx - 4, EYE_TOP, cx + 4, EYE_TOP + 1, INK)
        P(5, 0); P(6, -1)                       # 外側のまつ毛の跳ね
        rect(d, cx - 2, EYE_TOP + 3, cx - 1, EYE_TOP + 4, WHITE)
    elif style == 'C':    # たれ目：外側が下がる優しい楕円＋ハイライト
        pts = [(-4, 3), (-2, 1), (2, 1), (4, 4), (3, 8), (0, 10), (-3, 8)]
        d.polygon([(cx + u * side, EYE_TOP + v) for u, v in pts], fill=INK)
        rect(d, cx - 2, EYE_TOP + 3, cx - 1, EYE_TOP + 4, WHITE)
        px(d, cx + 2, EYE_TOP + 7, WHITE)
    elif style == 'D':    # 縦長キラ目：縦長の楕円＋大きめハイライト
        d.ellipse([cx - 3, EYE_TOP, cx + 3, EYE_TOP + 10], fill=INK)
        rect(d, cx - 2, EYE_TOP + 2, cx - 1, EYE_TOP + 4, WHITE)
        px(d, cx + 1, EYE_TOP + 7, WHITE)

def draw_soft_brow(d, cx, side, col):
    """愛嬌寄せの柔らかい平行眉（薄い弧）"""
    for i in range(11):
        x = cx - 5 * side + i * side
        cy = 14 + (1 if 2 <= i <= 8 else 0)
        px(d, x, cy, col)

def draw_face(ch, style, blush=True):
    img = Image.new('RGBA', (48, 48), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, sh = C(ch['skin']), C(ch['skin_shadow'])
    hair = C(ch['hair'])
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 20, 38, 27, 38, sh)
    rect(d, 13, 39, 34, 47, jacket)
    rect(d, 21, 39, 26, 47, shirt)
    if ch.get('tie'):
        rect(d, 22, 39, 25, 47, C(ch['tie']))
    rect(d, 14, 39, 18, 47, vest); rect(d, 29, 39, 33, 47, vest)
    rect(d, 14, 43, 18, 44, C('#dfe4ea')); rect(d, 29, 43, 33, 44, C('#dfe4ea'))
    for y, (x0, x1) in FACE_SPANS.items():
        rect(d, x0, y, x1, y, skin)
    rect(d, 1, 22, 2, 27, skin); rect(d, 45, 22, 46, 27, skin)
    haird = shade(hair)
    side_h = 33 if 'longhair' in ch['extra'] else (27 if ch.get('young') else 24)
    rect(d, 3, 12, 3, side_h, haird); rect(d, 4, 12, 4, side_h, hair)
    rect(d, 43, 12, 43, side_h, hair); rect(d, 44, 12, 44, side_h, haird)
    for fy in (11, 12):
        fx0, fx1 = FACE_SPANS[fy]
        rect(d, fx0, fy, fx1, fy, hair)
    fx0, fx1 = FACE_SPANS[13]
    rect(d, fx0, 13, fx0 + 8, 13, hair); rect(d, fx1 - 8, 13, fx1, 13, hair)
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    if 'cap' in ch['extra']:
        rect(d, 16, 3, 31, 3, hel); rect(d, 14, 4, 33, 4, hel)
        rect(d, 12, 5, 35, 5, hel); rect(d, 11, 6, 36, 7, hel)
        rect(d, 2, 8, 45, 9, hel)
        px(d, 2, 10, held); px(d, 45, 10, held)
    else:
        rect(d, 17, 1, 30, 1, hel); rect(d, 14, 2, 33, 2, hel)
        rect(d, 12, 3, 35, 3, hel); rect(d, 10, 4, 37, 4, hel)
        rect(d, 9, 5, 38, 8, hel)
        rect(d, 1, 9, 46, 10, hel)
        rect(d, 1, 11, 8, 11, held); rect(d, 39, 11, 46, 11, held)
        rect(d, 22, 1, 25, 8, stripe)
        for y in range(22, 37):
            px(d, 6, y, C('#3c3f47')); px(d, 41, y, C('#3c3f47'))
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#4a3a30')
    draw_soft_brow(d, 15, -1, brow_col)
    draw_soft_brow(d, 32, +1, brow_col)
    draw_eye_charming(d, 15, style, -1)
    draw_eye_charming(d, 32, style, +1)
    if blush:   # 愛嬌の小道具として薄い頬（サンプル判断用）
        bl = C('#eda184')
        rect(d, 7, 27, 9, 28, bl); rect(d, 38, 27, 40, 28, bl)
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([8, 13, 22, 28], outline=g)
        d.rectangle([25, 13, 39, 28], outline=g)
        rect(d, 23, 19, 24, 19, g)
    if 'mustache' in ch['extra']:
        mo = C('#a9a9ae')
        rect(d, 14, 30, 21, 31, mo); rect(d, 26, 30, 33, 31, mo)
        px(d, 14, 32, mo); px(d, 33, 32, mo)
    if 'stubble' in ch['extra']:
        for (x, y) in [(9, 34), (14, 36), (19, 37), (24, 37), (29, 36), (34, 34), (11, 35), (31, 35), (21, 35), (26, 35)]:
            if y in FACE_SPANS and FACE_SPANS[y][0] <= x <= FACE_SPANS[y][1]:
                px(d, x, y, sh)
    if 'pencil' in ch['extra']:
        rect(d, 44, 15, 45, 21, C('#f2c018')); px(d, 44, 14, C('#e08a2e')); px(d, 45, 14, C('#e08a2e'))
    if 'towel' in ch['extra']:
        rect(d, 14, 39, 33, 40, C('#eef0ea')); rect(d, 14, 41, 33, 41, C('#2470c2'))
        rect(d, 29, 42, 32, 45, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(4):
            rect(d, 20 + (i + 1) // 2, 39 + i, 27 - (i + 1) // 2, 39 + i, C('#1a5290'))
    return add_outline(img)

STYLES = [('A', 'A：キラキラ丸目'), ('B', 'B：まつ毛丸目'), ('C', 'C：たれ目'), ('D', 'D：縦長キラ目')]
APPLY = [('denki', 'A'), ('eisei', 'C'), ('seshu', 'B'), ('senpai', 'D')]

def load_font(size):
    for cand in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return None

def main():
    by_id = {c['id']: c for c in CHARS}
    hero = by_id['hero']
    pad, cell = 14, 48 * 5
    lab_h = 40
    # 上段：主人公で4スタイル比較
    W = cell * 4 + pad * 5
    H = (cell + lab_h) + (cell + lab_h) + pad * 3
    sheet = Image.new('RGB', (W, H), C('#f4f1ea'))
    d = ImageDraw.Draw(sheet)
    f = load_font(26)
    for j, (st, lab) in enumerate(STYLES):
        x = pad + j * (cell + pad)
        spr = draw_face(hero, st).resize((cell, cell), Image.NEAREST)
        sheet.paste(spr, (x, pad), spr)
        if f: d.text((x + cell // 2, pad + cell + 4), lab, font=f, fill=C('#2b2b33'), anchor='ma')
    # 下段：他キャラへの適用例
    for j, (cid, st) in enumerate(APPLY):
        ch = by_id[cid]
        x = pad + j * (cell + pad)
        y = pad * 2 + cell + lab_h
        spr = draw_face(ch, st).resize((cell, cell), Image.NEAREST)
        sheet.paste(spr, (x, y), spr)
        if f: d.text((x + cell // 2, y + cell + 4), f"{ch['name']}（{st}）", font=f, fill=C('#2b2b33'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'eye_charming.png'))
    print('charming eye samples generated')

if __name__ == '__main__':
    main()
