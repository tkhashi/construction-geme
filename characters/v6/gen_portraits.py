#!/usr/bin/env python3
"""ドット絵ポートレート生成 v4（超ちび・デコ狭め・口と鼻なし）
現場監督ゲーム キャラ作り サンプル6名。
ユーザーフィードバック反映：もっとチビ化／デコ（額）が広すぎる→目と眉をツバに寄せる／
口と鼻はいらない→表情は目・眉・汗・涙・怒りマークだけで作る。
ベース解像度 48x56、NEAREST拡大。旧版は v1/ v2/ v3/ に退避。
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
    if 0 <= x < BASE_W and 0 <= y < BASE_H:
        d.point((x, y), fill=col)

OUTLINE_COL = (43, 36, 31, 255)

def add_outline(img):
    """ポケモンR/S風：シルエットの外周に濃い輪郭線を1px入れる"""
    w, h = img.size
    alpha = img.split()[3]
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(out)
    pxa = alpha.load()
    for y in range(h):
        for x in range(w):
            if pxa[x, y] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and pxa[nx, ny] > 0:
                        od.point((x, y), fill=OUTLINE_COL)
                        break
    out.alpha_composite(img)
    return out

# 顔の行スパン（頭がほぼ全部・額は狭く）
FACE_SPANS = {}
for _y in range(11, 48):
    if _y == 11: FACE_SPANS[_y] = (15, 32)
    elif _y == 12: FACE_SPANS[_y] = (12, 35)
    elif _y == 13: FACE_SPANS[_y] = (9, 38)
    elif _y == 14: FACE_SPANS[_y] = (7, 40)
    elif _y <= 42: FACE_SPANS[_y] = (6, 41)
    elif _y == 43: FACE_SPANS[_y] = (7, 40)
    elif _y == 44: FACE_SPANS[_y] = (8, 39)
    elif _y == 45: FACE_SPANS[_y] = (10, 37)
    elif _y == 46: FACE_SPANS[_y] = (12, 35)
    elif _y == 47: FACE_SPANS[_y] = (15, 32)

def draw(ch, expr):
    img = Image.new('RGBA', (BASE_W, BASE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, sh = C(ch['skin']), C(ch['skin_shadow'])
    hair = C(ch['hair'])

    # ---- ちいさな体 ----
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 20, 48, 27, 48, sh)
    rect(d, 16, 49, 31, 55, jacket)
    rect(d, 21, 49, 26, 55, shirt)
    if ch.get('tie'):
        rect(d, 22, 49, 25, 55, C(ch['tie']))
    rect(d, 17, 49, 20, 55, vest); rect(d, 27, 49, 30, 55, vest)
    rect(d, 17, 52, 20, 53, C('#dfe4ea')); rect(d, 27, 52, 30, 53, C('#dfe4ea'))

    # ---- 大きな丸い顔 ----
    for y, (x0, x1) in FACE_SPANS.items():
        rect(d, x0, y, x1, y, skin)
    rect(d, 4, 28, 5, 34, skin); rect(d, 42, 28, 43, 34, skin)   # 耳
    px(d, 5, 31, sh); px(d, 42, 31, sh)
    side_h = 29 if ch.get('young') else 26
    rect(d, 6, 16, 7, side_h, hair); rect(d, 40, 16, 41, side_h, hair)

    # ---- ヘルメット（ツバを目に寄せる）----
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    rect(d, 20, 2, 27, 2, hel)
    rect(d, 17, 3, 30, 3, hel)
    rect(d, 14, 4, 33, 4, hel)
    rect(d, 12, 5, 35, 5, hel)
    rect(d, 10, 6, 37, 9, hel)
    rect(d, 3, 10, 44, 11, hel)                    # つば
    rect(d, 3, 12, 9, 12, held); rect(d, 38, 12, 44, 12, held)
    rect(d, 22, 2, 25, 9, stripe)
    for y in range(28, 45):                        # あご紐
        px(d, 8, y, C('#3c3f47')); px(d, 39, y, C('#3c3f47'))

    # ---- 眉（ツバのすぐ下・太く）----
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    def brow(x0, pts, thick=2):
        for i, yy in enumerate(pts):
            for t in range(thick):
                px(d, x0 + i, yy - t, brow_col)
    if expr == 'normal':
        brow(12, [17, 17, 17, 17, 17, 17, 17]); brow(29, [17, 17, 17, 17, 17, 17, 17])
    elif expr == 'smile':
        brow(12, [16, 15, 15, 15, 15, 15, 16]); brow(29, [16, 15, 15, 15, 15, 15, 16])
    elif expr == 'worried':
        brow(12, [19, 18, 17, 16, 15, 15, 15]); brow(29, [15, 15, 15, 16, 17, 18, 19])
    elif expr == 'angry':
        brow(12, [15, 16, 17, 18, 19, 20, 21]); brow(29, [21, 20, 19, 18, 17, 16, 15])

    # ---- 目（口と鼻はなし。表情は目で作る）----
    def eye(cx, mode, side):
        if mode == 'smile':                        # 大きな ∩ 目
            pts = [(-5, 2), (-4, 1), (-3, 0), (-2, -1), (-1, -1), (0, -1),
                   (1, -1), (2, -1), (3, 0), (4, 1), (5, 2)]
            for dx, dy in pts:
                px(d, cx + dx, 24 + dy, INK); px(d, cx + dx, 25 + dy, INK)
        elif mode == 'worried':                    # 白目＋内寄りの瞳＋涙
            rect(d, cx - 2, 20, cx + 2, 27, WHITE)
            rect(d, cx - 2, 20, cx + 2, 20, INK)
            pin = -side
            rect(d, cx + pin - 1, 24, cx + pin, 26, INK)
            tear = C('#57a8d8')
            tx = cx + side * 4
            px(d, tx, 28, tear); px(d, tx, 29, tear)
        elif mode == 'angry':                      # つり目
            for i in range(7):
                yy = 20 + (i if side < 0 else 6 - i) // 2
                px(d, cx - 3 + i, yy, INK); px(d, cx - 3 + i, yy + 1, INK)
            rect(d, cx - 1, 24, cx, 27, INK)
        else:                                      # 大きなキラキラ目
            rect(d, cx - 2, 20, cx + 2, 27, INK)
            px(d, cx - 2, 20, WHITE); px(d, cx - 1, 20, WHITE); px(d, cx - 2, 21, WHITE)
            px(d, cx + 1, 26, WHITE)
            px(d, cx + 3, 19, INK)
    eye(16, expr, -1); eye(31, expr, +1)

    # ほっぺ
    bl = C('#eda184')
    rect(d, 8, 31, 11, 32, bl); rect(d, 36, 31, 39, 32, bl)

    # ---- 個別の特徴（口・鼻は描かない）----
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([9, 18, 22, 29], outline=g)
        d.rectangle([25, 18, 38, 29], outline=g)
        rect(d, 23, 22, 24, 22, g)
    if 'mustache' in ch['extra']:                  # 口髭は両翼の形で（口そのものは描かない）
        mo = C('#a9a9ae')
        rect(d, 17, 34, 22, 35, mo); rect(d, 25, 34, 30, 35, mo)
        px(d, 17, 36, mo); px(d, 30, 36, mo)
    if 'stubble' in ch['extra']:
        for (x, y) in [(13, 44), (18, 46), (23, 47), (28, 46), (33, 44), (15, 45), (31, 45), (21, 44), (26, 44)]:
            if y in FACE_SPANS and FACE_SPANS[y][0] <= x <= FACE_SPANS[y][1]:
                px(d, x, y, sh)
    if 'towel' in ch['extra']:
        rect(d, 17, 48, 30, 50, C('#eef0ea'))
        rect(d, 17, 50, 30, 50, C('#2470c2'))
        rect(d, 27, 51, 30, 54, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(4):
            rect(d, 21 + (i + 1) // 2, 48 + i, 26 - (i + 1) // 2, 48 + i, C('#1a5290'))
    if 'pencil' in ch['extra']:
        rect(d, 43, 18, 44, 25, C('#f2c018')); px(d, 43, 17, C('#e08a2e')); px(d, 44, 17, C('#e08a2e'))

    # ---- 表情の小物 ----
    if expr == 'worried':
        sw = C('#57a8d8')
        px(d, 45, 17, sw); rect(d, 44, 18, 46, 21, sw); px(d, 45, 22, sw)
        px(d, 1, 21, sw); rect(d, 0, 22, 2, 24, sw)
    if expr == 'angry':
        r = C('#d8402e')
        rect(d, 42, 1, 45, 4, r)
        for (x, y) in [(41, 2), (46, 2), (41, 3), (46, 3), (43, 0), (44, 0), (43, 5), (44, 5)]:
            px(d, x, y, r)
    if expr == 'smile':
        s = C('#e8b93c')
        for (cx, cy) in [(2, 15), (45, 13)]:
            px(d, cx, cy - 2, s); px(d, cx, cy + 2, s); px(d, cx - 2, cy, s); px(d, cx + 2, cy, s); px(d, cx, cy, s)

    return img

def main():
    for ch in CHARS:
        for expr in EXPRS:
            img = add_outline(draw(ch, expr))
            img.resize((BASE_W * SCALE, BASE_H * SCALE), Image.NEAREST).save(
                os.path.join(OUT, 'sprites', f"{ch['id']}_{expr}.png"))
        icon = add_outline(draw(ch, 'normal')).crop((2, 0, 46, 49)).resize((176, 196), Image.NEAREST)
        icon.save(os.path.join(OUT, 'icons', f"{ch['id']}.png"))
        strip = Image.new('RGBA', (BASE_W * 4 + 30, BASE_H), (0, 0, 0, 0))
        for i, expr in enumerate(EXPRS):
            strip.paste(add_outline(draw(ch, expr)), (i * (BASE_W + 10), 0))
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
        spr = add_outline(draw(ch, 'normal')).resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (cx, cy), spr)
        if font:
            d.text((cx + cell_w // 2, cy + cell_h + 6), ch['name'], font=font,
                   fill=C('#2b2b33'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'contact_sheet.png'))
    print('generated v4:', len(CHARS), 'chars x', len(EXPRS), 'exprs')

if __name__ == '__main__':
    main()
