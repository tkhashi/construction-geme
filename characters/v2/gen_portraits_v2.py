#!/usr/bin/env python3
"""ドット絵ポートレート生成 v2（カイロソフト風ちびキャラ）
現場監督ゲーム キャラ作り サンプル6名。
大きな丸い頭＋小さな体のちび比率、丸い目、ほっぺ、少色数・平坦な塗りで統一。
ベース解像度 48x56、NEAREST拡大。旧版（渋め・等身寄り）は v1/ に退避。
出力: sprites/<id>_<expr>.png (384x448), icons/<id>.png, sheets/*.png
"""
from PIL import Image, ImageDraw, ImageFont
import os

BASE_W, BASE_H = 48, 56
SCALE = 8
OUT = os.path.dirname(os.path.abspath(__file__))

INK = (38, 36, 44)
WHITE = (245, 245, 245)

def C(hexs):
    hexs = hexs.lstrip('#')
    return tuple(int(hexs[i:i+2], 16) for i in (0, 2, 4))

CHARS = [
    dict(
        id='hero', name='主人公（担当者）',
        skin='#f6cfa4', skin_shadow='#e0a96e', hair='#4a3423',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#1f7a8c',
        jacket='#2e4a66', vest='#8fa3b8', shirt='#eef2f5', tie='#1f7a8c',
        extra=[], young=True,
    ),
    dict(
        id='kacho', name='課長',
        skin='#f2c294', skin_shadow='#d69c5f', hair='#2e2a28',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#a33327',
        jacket='#2b3242', vest='#7d8aa0', shirt='#e8ecf2', tie='#a33327',
        extra=['glasses'],
    ),
    dict(
        id='shocho', name='所長',
        skin='#eec39a', skin_shadow='#d29f63', hair='#b9b9bc',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#c9a227',
        jacket='#23242c', vest='#6d7484', shirt='#f0f0f2', tie='#5d1f24',
        extra=['mustache'], gray_brow=True,
    ),
    dict(
        id='tobi', name='鳶職長',
        skin='#e0a05e', skin_shadow='#c07f3c', hair='#1d1a17',
        helmet='#7a4fa3', helmet_dark='#5d3a80', stripe='#e8d44d',
        jacket='#33395e', vest='#565d8f', shirt='#cfd4e8', tie=None,
        extra=['stubble', 'towel'],
    ),
    dict(
        id='denki', name='電気職長',
        skin='#f8d6ac', skin_shadow='#e3aa72', hair='#6b4423',
        helmet='#f2c018', helmet_dark='#c99612', stripe='#2b2b33',
        jacket='#4c5560', vest='#f2c018', shirt='#eef0ea', tie=None,
        extra=['pencil'], friendly=True,
    ),
    dict(
        id='eisei', name='衛生職長',
        skin='#f4c69c', skin_shadow='#d89e66', hair='#22242c',
        helmet='#2470c2', helmet_dark='#1a5290', stripe='#f2f3f5',
        jacket='#5b7d9e', vest='#2470c2', shirt='#eaf2f8', tie=None,
        extra=['neckerchief'], soft=True,
    ),
]
EXPRS = ['normal', 'smile', 'worried', 'angry']

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    d.point((x, y), fill=col)

# 顔（大きな丸頭）の行スパン
FACE_SPANS = {}
for _y in range(14, 45):
    if _y == 14: FACE_SPANS[_y] = (15, 32)
    elif _y == 15: FACE_SPANS[_y] = (13, 34)
    elif _y == 16: FACE_SPANS[_y] = (11, 36)
    elif _y == 17: FACE_SPANS[_y] = (10, 37)
    elif _y <= 40: FACE_SPANS[_y] = (10, 37)
    elif _y == 41: FACE_SPANS[_y] = (11, 36)
    elif _y == 42: FACE_SPANS[_y] = (12, 35)
    elif _y == 43: FACE_SPANS[_y] = (14, 33)
    elif _y == 44: FACE_SPANS[_y] = (16, 31)

def draw(ch, expr):
    img = Image.new('RGBA', (BASE_W, BASE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, sh = C(ch['skin']), C(ch['skin_shadow'])
    hair = C(ch['hair'])

    # ---- 小さな体 ----
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 17, 47, 30, 47, jacket)
    rect(d, 14, 48, 33, 55, jacket)
    rect(d, 21, 48, 26, 55, shirt)
    if ch.get('tie'):
        rect(d, 22, 48, 25, 55, C(ch['tie']))
    rect(d, 15, 48, 19, 55, vest); rect(d, 28, 48, 32, 55, vest)
    rect(d, 15, 51, 19, 52, C('#dfe4ea')); rect(d, 28, 51, 32, 52, C('#dfe4ea'))
    # 首（頭の下に少しだけ）
    rect(d, 20, 44, 27, 47, sh)

    # ---- 大きな丸い顔 ----
    for y, (x0, x1) in FACE_SPANS.items():
        rect(d, x0, y, x1, y, skin)
    for y in range(20, 41):                        # 輪郭の柔らかい影
        x0, x1 = FACE_SPANS[y]
        px(d, x0, y, sh); px(d, x1, y, sh)
    rect(d, 8, 29, 9, 34, skin); rect(d, 38, 29, 39, 34, skin)   # 耳
    px(d, 9, 31, sh); px(d, 38, 31, sh)
    # 髪（ヘルメット下の横）
    side_h = 29 if ch.get('young') else 26
    rect(d, 10, 17, 11, side_h, hair); rect(d, 36, 17, 37, side_h, hair)

    # ---- ヘルメット（丸ドーム＋広いつば）----
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    rect(d, 19, 3, 28, 3, hel)
    rect(d, 16, 4, 31, 4, hel)
    rect(d, 14, 5, 33, 6, hel)
    rect(d, 12, 7, 35, 12, hel)
    rect(d, 7, 13, 40, 14, hel)                    # つば
    rect(d, 7, 15, 12, 15, held); rect(d, 35, 15, 40, 15, held)
    rect(d, 22, 3, 25, 12, stripe)
    # あご紐
    for y in range(28, 43):
        px(d, 11, y, C('#3c3f47')); px(d, 36, y, C('#3c3f47'))

    # ---- 眉 ----
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    def brow(x0, pts, thick=1):
        for i, yy in enumerate(pts):
            for t in range(thick):
                px(d, x0 + i, yy - t, brow_col)
    th = 2 if ch.get('gray_brow') else 1
    if expr == 'normal':
        brow(16, [24, 24, 24, 24, 24], th); brow(27, [24, 24, 24, 24, 24], th)
    elif expr == 'smile':
        brow(16, [23, 22, 22, 22, 23], th); brow(27, [23, 22, 22, 22, 23], th)
    elif expr == 'worried':
        brow(16, [25, 24, 23, 22, 22], th); brow(27, [22, 22, 23, 24, 25], th)
    elif expr == 'angry':
        brow(16, [22, 23, 24, 25, 26], th); brow(27, [26, 25, 24, 23, 22], th)

    # ---- 目（大きめ・丸）----
    def eye(cx, mode):
        if mode == 'smile':                        # ∩ の笑い目
            for dx, dy in [(-2, 1), (-1, 0), (0, 0), (1, 0), (2, 1)]:
                px(d, cx + dx, 29 + dy, INK); px(d, cx + dx, 30 + dy, INK)
        elif mode == 'angry':
            rect(d, cx - 2, 27, cx + 2, 28, INK)   # まぶた
            rect(d, cx - 1, 29, cx + 1, 31, INK)
        elif mode == 'worried':
            rect(d, cx - 1, 29, cx + 1, 31, INK)
            px(d, cx + 1, 29, WHITE)
        else:
            rect(d, cx - 1, 28, cx + 1, 31, INK)
            px(d, cx - 1, 28, WHITE)
    eye(18, expr); eye(29, expr)
    px(d, 23, 34, sh)                              # 鼻（小さく）

    # ほっぺ（常時うっすら）
    bl = C('#eda184')
    for bx in (12, 13, 34, 35):
        px(d, bx, 35, bl); px(d, bx, 36, bl)

    # ---- 口 ----
    if 'mustache' not in ch['extra']:
        if expr == 'smile':
            for dx, dy in [(-2, 0), (-1, 1), (0, 1), (1, 1), (2, 0)]:
                px(d, 23 + dx, 37 + dy, INK)
            rect(d, 22, 38, 24, 38, C('#8c4a3a'))
        elif expr == 'worried':
            for dx, dy in [(-2, 1), (-1, 0), (0, 1), (1, 0), (2, 1)]:
                px(d, 23 + dx, 37 + dy, INK)
        elif expr == 'angry':
            for dx, dy in [(-2, 1), (-1, 0), (0, 0), (1, 0), (2, 1)]:
                px(d, 23 + dx, 36 + dy, INK)
        else:
            rect(d, 22, 38, 25, 38, INK)

    # ---- 個別の特徴 ----
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([14, 25, 22, 33], outline=g)
        d.rectangle([25, 25, 33, 33], outline=g)
        px(d, 23, 28, g); px(d, 24, 28, g)
    if 'mustache' in ch['extra']:
        mo = C('#a9a9ae')
        rect(d, 19, 36, 28, 37, mo); px(d, 23, 37, skin); px(d, 24, 37, skin)
        if expr == 'smile':
            rect(d, 22, 39, 25, 39, INK)
        elif expr == 'angry':
            px(d, 22, 40, INK); px(d, 25, 40, INK)
        else:
            rect(d, 22, 39, 25, 39, INK)
    if 'stubble' in ch['extra']:
        for (x, y) in [(16, 41), (20, 43), (24, 44), (28, 43), (31, 41), (18, 42), (29, 42), (23, 41)]:
            if y in FACE_SPANS and FACE_SPANS[y][0] <= x <= FACE_SPANS[y][1]:
                px(d, x, y, sh)
    if 'towel' in ch['extra']:
        rect(d, 18, 46, 29, 48, C('#eef0ea'))
        rect(d, 18, 48, 29, 48, C('#2470c2'))
        rect(d, 26, 49, 29, 53, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(4):
            rect(d, 21 + (i + 1) // 2, 46 + i, 26 - (i + 1) // 2, 46 + i, C('#1a5290'))
    if 'pencil' in ch['extra']:
        rect(d, 40, 20, 41, 26, C('#f2c018')); px(d, 40, 19, C('#e08a2e')); px(d, 41, 19, C('#e08a2e'))

    # ---- 表情の小物 ----
    if expr == 'worried':
        sw = C('#57a8d8')
        px(d, 42, 19, sw); rect(d, 41, 20, 43, 22, sw); px(d, 42, 23, sw)
    if expr == 'angry':
        r = C('#d8402e')
        rect(d, 41, 3, 43, 5, r); px(d, 40, 4, r); px(d, 44, 4, r); px(d, 42, 2, r); px(d, 42, 6, r)

    return img

def main():
    for ch in CHARS:
        for expr in EXPRS:
            img = draw(ch, expr)
            img.resize((BASE_W * SCALE, BASE_H * SCALE), Image.NEAREST).save(
                os.path.join(OUT, 'sprites', f"{ch['id']}_{expr}.png"))
        icon = draw(ch, 'normal').crop((4, 0, 44, 48)).resize((160, 192), Image.NEAREST)
        icon.save(os.path.join(OUT, 'icons', f"{ch['id']}.png"))
        strip = Image.new('RGBA', (BASE_W * 4 + 30, BASE_H), (0, 0, 0, 0))
        for i, expr in enumerate(EXPRS):
            strip.paste(draw(ch, expr), (i * (BASE_W + 10), 0))
        strip.resize((strip.width * 5, strip.height * 5), Image.NEAREST).save(
            os.path.join(OUT, 'sheets', f"{ch['id']}_expressions.png"))

    cell_w, cell_h, pad, label_h = BASE_W * 5, BASE_H * 5, 24, 44
    sheet = Image.new('RGB', (cell_w * 3 + pad * 4, (cell_h + label_h) * 2 + pad * 3), C('#f4f1ea'))
    d = ImageDraw.Draw(sheet)
    font = None
    for cand in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc']:
        if os.path.exists(cand):
            try:
                font = ImageFont.truetype(cand, 30)
                break
            except Exception:
                pass
    for i, ch in enumerate(CHARS):
        cx = pad + (i % 3) * (cell_w + pad)
        cy = pad + (i // 3) * (cell_h + label_h + pad)
        spr = draw(ch, 'normal').resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (cx, cy), spr)
        if font:
            d.text((cx + cell_w // 2, cy + cell_h + 6), ch['name'], font=font,
                   fill=C('#2b2b33'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'contact_sheet.png'))
    print('generated v2 chibi:', len(CHARS), 'chars x', len(EXPRS), 'exprs')

if __name__ == '__main__':
    main()
