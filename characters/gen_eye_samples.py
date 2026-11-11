#!/usr/bin/env python3
"""目・眉の組み合わせサンプル生成（ユーザー指示 2026-11-08）
「目を大きくして目で表情作りたい」に応える検討用サンプル。全員分には展開しない。
- 目の形：丸目 / 吊り目 / 下り目 / ジト目 / 糸目（ベタ塗り・ハイライトなし）
- 眉の向き：上がり眉 / 下がり眉 / 平行眉
- 眉の形：細眉 / 太眉 / 細→太 / 太→細 / まろ眉
出力: sheets/eye_chart.png（組み合わせ表）, sheets/eye_samples.png（キャラ別サンプル）
顔の土台（体・顔・前髪・ヘルメット・特徴パーツ）は gen_portraits.py の現行画風に合わせる。
サンプル用に前髪は少し短くし（y11〜12＋両端y13）、眉のゾーン（y14〜16）を確保する。
"""
from PIL import Image, ImageDraw, ImageFont
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C, shade, add_outline, FACE_SPANS, INK

OUT = os.path.dirname(os.path.abspath(__file__))
EYE_TOP = 17

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    if 0 <= x < 48 and 0 <= y < 48:
        d.point((x, y), fill=col)

# ---------- 目（cx=中心, side: 左目=-1 / 右目=+1、u は「外側が正」に変換） ----------
def draw_eye(d, cx, kind, side):
    def P(u, v):
        px(d, cx + u * side, EYE_TOP + v, INK)
    if kind == 'round':                       # 丸目：楕円 7×9
        d.ellipse([cx - 3, EYE_TOP, cx + 3, EYE_TOP + 8], fill=INK)
    elif kind == 'tsuri':                     # 吊り目：外側が上がるアーモンド
        pts = [(-4, 6), (-2, 2), (2, 0), (4, 1), (2, 6), (-1, 8)]
        d.polygon([(cx + u * side, EYE_TOP + v) for u, v in pts], fill=INK)
    elif kind == 'tare':                      # 下り目：外側が垂れるアーモンド
        pts = [(-4, 2), (-2, 0), (1, 1), (4, 5), (2, 8), (-1, 7)]
        d.polygon([(cx + u * side, EYE_TOP + v) for u, v in pts], fill=INK)
    elif kind == 'jito':                      # ジト目：重い上まぶた＋半開き
        rect(d, cx - 4, EYE_TOP, cx + 4, EYE_TOP + 1, INK)
        rect(d, cx - 3, EYE_TOP + 2, cx + 3, EYE_TOP + 5, INK)
        rect(d, cx - 2, EYE_TOP + 6, cx + 2, EYE_TOP + 6, INK)
    elif kind == 'ito':                       # 糸目：細い弧のライン
        for u in range(-4, 5):
            v = 2 if abs(u) >= 3 else 3
            P(u, v)
            if abs(u) <= 2:
                P(u, v + 1)

# ---------- 眉（向き×形） ----------
def draw_brow(d, cx, direction, shape, side, col):
    by = 15
    if shape == 'maro':                       # まろ眉：短い楕円の blob
        d.ellipse([cx - 2, by - 1, cx + 2, by + 1], fill=col)
        return
    tilt = {'up': -2, 'down': 2, 'flat': 0}[direction]
    for i in range(11):                       # 内側(i=0) → 外側(i=10)
        t = i / 10
        x = cx - 5 * side + i * side
        cy = by + round(tilt * t)
        if shape == 'thin':
            th = 1
        elif shape == 'thick':
            th = 3
        elif shape == 'thin2thick':
            th = 1 + round(2 * t)
        elif shape == 'thick2thin':
            th = 3 - round(2 * t)
        else:
            th = 1
        top = cy - (th - 1) // 2
        rect(d, x, top, x, top + th - 1, col)

# ---------- 顔全体（現行画風ベース、目・眉だけ差し替え） ----------
def draw_sample(ch, eye_kind, brow_dir, brow_shape):
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
    # 前髪（サンプル版は眉ゾーン確保のため短め：y11〜12＋両端 y13）
    for fy in (11, 12):
        fx0, fx1 = FACE_SPANS[fy]
        rect(d, fx0, fy, fx1, fy, hair)
    fx0, fx1 = FACE_SPANS[13]
    rect(d, fx0, 13, fx0 + 8, 13, hair); rect(d, fx1 - 8, 13, fx1, 13, hair)
    # ヘルメット/帽子
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
    # 眉 → 目
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    draw_brow(d, 15, brow_dir, brow_shape, -1, brow_col)
    draw_brow(d, 32, brow_dir, brow_shape, +1, brow_col)
    draw_eye(d, 15, eye_kind, -1)
    draw_eye(d, 32, eye_kind, +1)
    # 特徴パーツ
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([9, 14, 21, 27], outline=g)
        d.rectangle([26, 14, 38, 27], outline=g)
        rect(d, 22, 19, 25, 19, g)
    if 'mustache' in ch['extra']:
        mo = C('#a9a9ae')
        rect(d, 14, 28, 21, 29, mo); rect(d, 26, 28, 33, 29, mo)
        px(d, 14, 30, mo); px(d, 33, 30, mo)
    if 'stubble' in ch['extra']:
        for (x, y) in [(9, 34), (14, 36), (19, 37), (24, 37), (29, 36), (34, 34), (11, 35), (31, 35), (21, 35), (26, 35)]:
            if y in FACE_SPANS and FACE_SPANS[y][0] <= x <= FACE_SPANS[y][1]:
                px(d, x, y, sh)
    if 'towel' in ch['extra']:
        rect(d, 14, 39, 33, 40, C('#eef0ea')); rect(d, 14, 41, 33, 41, C('#2470c2'))
        rect(d, 29, 42, 32, 45, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(4):
            rect(d, 20 + (i + 1) // 2, 39 + i, 27 - (i + 1) // 2, 39 + i, C('#1a5290'))
    if 'pencil' in ch['extra']:
        rect(d, 44, 15, 45, 21, C('#f2c018')); px(d, 44, 14, C('#e08a2e')); px(d, 45, 14, C('#e08a2e'))
    if 'beard' in ch['extra']:
        rect(d, 5, 30, 7, 36, hair); rect(d, 40, 30, 42, 36, hair)
        rect(d, 8, 34, 12, 36, hair); rect(d, 35, 34, 39, 36, hair)
        rect(d, 18, 35, 29, 35, hair); rect(d, 13, 36, 34, 36, hair)
    return add_outline(img)

EYES = [('round', '丸目'), ('tsuri', '吊り目'), ('tare', '下り目'), ('jito', 'ジト目'), ('ito', '糸目')]
BROWS = [('up', 'thick', '上がり眉×太眉'), ('up', 'thin2thick', '上がり眉×細→太'),
         ('flat', 'thick', '平行眉×太眉'), ('flat', 'thin', '平行眉×細眉'),
         ('down', 'thin', '下がり眉×細眉'), ('flat', 'maro', 'まろ眉')]
SAMPLE_COMBOS = {   # id: (目の形, 眉の向き, 眉の形, ラベル)
    'hero':   ('round', 'flat', 'thin2thick', '丸目＋平行眉・細→太'),
    'kacho':  ('tsuri', 'up', 'thick', '吊り目＋上がり眉・太眉'),
    'shocho': ('ito', 'flat', 'maro', '糸目＋まろ眉'),
    'tobi':   ('jito', 'up', 'thick2thin', 'ジト目＋上がり眉・太→細'),
    'denki':  ('tare', 'down', 'thin', '下り目＋下がり眉・細眉'),
    'eisei':  ('round', 'down', 'thin2thick', '丸目＋下がり眉・細→太'),
}

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
    cell, pad = 48 * 4, 14
    head_h, rowlab_w = 46, 92
    W = rowlab_w + cell * len(BROWS) + pad * (len(BROWS) + 1)
    H = head_h + (cell + 8) * len(EYES) + pad
    chart = Image.new('RGB', (W, H), C('#f4f1ea'))
    d = ImageDraw.Draw(chart)
    f = load_font(24)
    for j, (_, _, lab) in enumerate(BROWS):
        x = rowlab_w + pad + j * (cell + pad)
        if f: d.text((x + cell // 2, 8), lab, font=f, fill=C('#2b2b33'), anchor='ma')
    for i, (ek, elab) in enumerate(EYES):
        y = head_h + i * (cell + 8)
        if f: d.text((rowlab_w - 10, y + cell // 2), elab, font=f, fill=C('#2b2b33'), anchor='rm')
        for j, (bd, bs, _) in enumerate(BROWS):
            x = rowlab_w + pad + j * (cell + pad)
            spr = draw_sample(hero, ek, bd, bs).resize((cell, cell), Image.NEAREST)
            chart.paste(spr, (x, y), spr)
    chart.save(os.path.join(OUT, 'sheets', 'eye_chart.png'))

    ids = list(SAMPLE_COMBOS.keys())
    cell2, lab_h = 48 * 6, 74
    W2 = cell2 * 3 + pad * 4
    H2 = (cell2 + lab_h) * 2 + pad * 3
    sheet = Image.new('RGB', (W2, H2), C('#f4f1ea'))
    d2 = ImageDraw.Draw(sheet)
    f2, f3 = load_font(30), load_font(24)
    for i, cid in enumerate(ids):
        ch = by_id[cid]
        ek, bd, bs, lab = SAMPLE_COMBOS[cid]
        x = pad + (i % 3) * (cell2 + pad)
        y = pad + (i // 3) * (cell2 + lab_h + pad)
        spr = draw_sample(ch, ek, bd, bs).resize((cell2, cell2), Image.NEAREST)
        sheet.paste(spr, (x, y), spr)
        if f2: d2.text((x + cell2 // 2, y + cell2 + 4), ch['name'], font=f2, fill=C('#2b2b33'), anchor='ma')
        if f3: d2.text((x + cell2 // 2, y + cell2 + 40), lab, font=f3, fill=C('#6b6f7a'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'eye_samples.png'))
    print('eye samples generated: chart', len(EYES), 'x', len(BROWS), '/ char samples', len(ids))

if __name__ == '__main__':
    main()
