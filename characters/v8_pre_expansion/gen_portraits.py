#!/usr/bin/env python3
"""ドット絵ポートレート生成 v6（48x48・顔は6:4横長・口と鼻なし）
現場監督ゲーム キャラ作り。
ユーザー指示（2026-11-08）：顔が大き過ぎ・縦長過ぎ → キャンバス 48x48、
顔の外形は幅42px×高さ28px（横：縦＝6：4の横長）に変更。ヘルメットはその上、
体は下に小さな帯状。目・眉はツバ直下、目はベタの黒・ハイライトなし。
口と鼻は描かず、表情は目・眉・汗・涙・怒りマークだけで作る。
NEAREST拡大。旧版は v1/ 〜 v6/ に退避。
出力: sprites/<id>_<expr>.png (384x384), icons/<id>.png, sheets/*.png
"""
from PIL import Image, ImageDraw, ImageFont
import os

BASE_W, BASE_H = 48, 48
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

# 顔の行スパン（幅42px×高さ28px＝6:4横長、y10〜37）
FACE_SPANS = {}
for _y in range(10, 38):
    if _y == 10: FACE_SPANS[_y] = (10, 37)
    elif _y == 11: FACE_SPANS[_y] = (7, 40)
    elif _y == 12: FACE_SPANS[_y] = (5, 42)
    elif _y == 13: FACE_SPANS[_y] = (4, 43)
    elif _y <= 33: FACE_SPANS[_y] = (3, 44)
    elif _y == 34: FACE_SPANS[_y] = (4, 43)
    elif _y == 35: FACE_SPANS[_y] = (5, 42)
    elif _y == 36: FACE_SPANS[_y] = (7, 40)
    elif _y == 37: FACE_SPANS[_y] = (10, 37)

def draw(ch, expr):
    img = Image.new('RGBA', (BASE_W, BASE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, sh = C(ch['skin']), C(ch['skin_shadow'])
    hair = C(ch['hair'])

    # ---- 小さな帯状の体 ----
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 20, 38, 27, 38, sh)
    rect(d, 13, 39, 34, 47, jacket)
    rect(d, 21, 39, 26, 47, shirt)
    if ch.get('tie'):
        rect(d, 22, 39, 25, 47, C(ch['tie']))
    rect(d, 14, 39, 18, 47, vest); rect(d, 29, 39, 33, 47, vest)
    rect(d, 14, 43, 18, 44, C('#dfe4ea')); rect(d, 29, 43, 33, 44, C('#dfe4ea'))

    # ---- 横長の顔（42×28）----
    for y, (x0, x1) in FACE_SPANS.items():
        rect(d, x0, y, x1, y, skin)
    rect(d, 1, 22, 2, 27, skin); rect(d, 45, 22, 46, 27, skin)   # 耳
    px(d, 2, 24, sh); px(d, 45, 24, sh)
    side_h = 27 if ch.get('young') else 24
    rect(d, 3, 12, 4, side_h, hair); rect(d, 43, 12, 44, side_h, hair)

    # ---- ヘルメット（ツバを目に寄せる）----
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    rect(d, 19, 1, 28, 1, hel)
    rect(d, 16, 2, 31, 2, hel)
    rect(d, 13, 3, 34, 3, hel)
    rect(d, 11, 4, 36, 4, hel)
    rect(d, 9, 5, 38, 8, hel)
    rect(d, 1, 9, 46, 10, hel)                     # つば
    rect(d, 1, 11, 8, 11, held); rect(d, 39, 11, 46, 11, held)
    rect(d, 22, 1, 25, 8, stripe)
    for y in range(22, 37):                        # あご紐
        px(d, 6, y, C('#3c3f47')); px(d, 41, y, C('#3c3f47'))

    # ---- 眉（ツバのすぐ下・太く）----
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    def brow(x0, pts, thick=2):
        for i, yy in enumerate(pts):
            for t in range(thick):
                px(d, x0 + i, yy - t, brow_col)
    if expr == 'normal':
        brow(11, [14, 14, 14, 14, 14, 14, 14]); brow(28, [14, 14, 14, 14, 14, 14, 14])
    elif expr == 'smile':
        brow(11, [13, 12, 12, 12, 12, 12, 13]); brow(28, [13, 12, 12, 12, 12, 12, 13])
    elif expr == 'worried':
        brow(11, [16, 15, 14, 13, 12, 12, 12]); brow(28, [12, 12, 12, 13, 14, 15, 16])
    elif expr == 'angry':
        brow(11, [12, 13, 14, 15, 16, 17, 18]); brow(28, [18, 17, 16, 15, 14, 13, 12])

    # ---- 目（口と鼻はなし。表情は目で作る）----
    def eye(cx, mode, side):
        if mode == 'smile':                        # 大きな ∩ 目
            pts = [(-5, 2), (-4, 1), (-3, 0), (-2, -1), (-1, -1), (0, -1),
                   (1, -1), (2, -1), (3, 0), (4, 1), (5, 2)]
            for dx, dy in pts:
                px(d, cx + dx, 21 + dy, INK); px(d, cx + dx, 22 + dy, INK)
        elif mode == 'worried':                    # 白目＋内寄りの瞳＋涙
            rect(d, cx - 2, 16, cx + 2, 23, WHITE)
            rect(d, cx - 2, 16, cx + 2, 16, INK)
            pin = -side
            rect(d, cx + pin - 1, 20, cx + pin, 22, INK)
            tear = C('#57a8d8')
            tx = cx + side * 4
            px(d, tx, 24, tear); px(d, tx, 25, tear)
        elif mode == 'angry':                      # つり目
            for i in range(7):
                yy = 16 + (i if side < 0 else 6 - i) // 2
                px(d, cx - 3 + i, yy, INK); px(d, cx - 3 + i, yy + 1, INK)
            rect(d, cx - 1, 20, cx, 23, INK)
        else:                                      # 大きなベタ目（ハイライトは入れない）
            rect(d, cx - 2, 17, cx + 2, 23, INK)
            px(d, cx + 3, 16, INK)
    eye(15, expr, -1); eye(32, expr, +1)

    # ほっぺ
    bl = C('#eda184')
    rect(d, 5, 25, 9, 26, bl); rect(d, 38, 25, 42, 26, bl)

    # ---- 個別の特徴（口・鼻は描かない）----
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([8, 15, 22, 24], outline=g)
        d.rectangle([25, 15, 39, 24], outline=g)
        rect(d, 23, 19, 24, 19, g)
    if 'mustache' in ch['extra']:                  # 口髭は両翼の形で（口そのものは描かない）
        mo = C('#a9a9ae')
        rect(d, 14, 28, 21, 29, mo); rect(d, 26, 28, 33, 29, mo)
        px(d, 14, 30, mo); px(d, 33, 30, mo)
    if 'stubble' in ch['extra']:
        for (x, y) in [(9, 34), (14, 36), (19, 37), (24, 37), (29, 36), (34, 34), (11, 35), (31, 35), (21, 35), (26, 35)]:
            if y in FACE_SPANS and FACE_SPANS[y][0] <= x <= FACE_SPANS[y][1]:
                px(d, x, y, sh)
    if 'towel' in ch['extra']:
        rect(d, 14, 39, 33, 40, C('#eef0ea'))
        rect(d, 14, 41, 33, 41, C('#2470c2'))
        rect(d, 29, 42, 32, 45, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(4):
            rect(d, 20 + (i + 1) // 2, 39 + i, 27 - (i + 1) // 2, 39 + i, C('#1a5290'))
    if 'pencil' in ch['extra']:
        rect(d, 44, 15, 45, 21, C('#f2c018')); px(d, 44, 14, C('#e08a2e')); px(d, 45, 14, C('#e08a2e'))

    # ---- 表情の小物 ----
    if expr == 'worried':
        sw = C('#57a8d8')
        px(d, 46, 13, sw); rect(d, 45, 14, 47, 16, sw); px(d, 46, 17, sw)
        px(d, 1, 17, sw); rect(d, 0, 18, 2, 20, sw)
    if expr == 'angry':
        r = C('#d8402e')
        rect(d, 42, 1, 45, 4, r)
        for (x, y) in [(41, 2), (46, 2), (41, 3), (46, 3), (43, 0), (44, 0), (43, 5), (44, 5)]:
            px(d, x, y, r)
    if expr == 'smile':
        s = C('#e8b93c')
        for (cx, cy) in [(2, 15), (45, 14)]:
            px(d, cx, cy - 2, s); px(d, cx, cy + 2, s); px(d, cx - 2, cy, s); px(d, cx + 2, cy, s); px(d, cx, cy, s)

    return img

def main():
    for ch in CHARS:
        for expr in EXPRS:
            img = add_outline(draw(ch, expr))
            img.resize((BASE_W * SCALE, BASE_H * SCALE), Image.NEAREST).save(
                os.path.join(OUT, 'sprites', f"{ch['id']}_{expr}.png"))
        icon = add_outline(draw(ch, 'normal')).crop((0, 0, 48, 40)).resize((192, 160), Image.NEAREST)
        icon.save(os.path.join(OUT, 'icons', f"{ch['id']}.png"))
        strip = Image.new('RGBA', (BASE_W * 4 + 30, BASE_H), (0, 0, 0, 0))
        for i, expr in enumerate(EXPRS):
            strip.paste(add_outline(draw(ch, expr)), (i * (BASE_W + 10), 0))
        strip.resize((strip.width * 5, strip.height * 5), Image.NEAREST).save(
            os.path.join(OUT, 'sheets', f"{ch['id']}_expressions.png"))

    cell_w, cell_h, pad, label_h = BASE_W * 5, BASE_H * 5, 24, 44
    cols = 3 if len(CHARS) <= 6 else 4
    rows = (len(CHARS) + cols - 1) // cols
    sheet = Image.new('RGB', (cell_w * cols + pad * (cols + 1),
                              (cell_h + label_h) * rows + pad * (rows + 1)), C('#f4f1ea'))
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
        cx = pad + (i % cols) * (cell_w + pad)
        cy = pad + (i // cols) * (cell_h + label_h + pad)
        spr = add_outline(draw(ch, 'normal')).resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (cx, cy), spr)
        if font:
            d.text((cx + cell_w // 2, cy + cell_h + 6), ch['name'], font=font,
                   fill=C('#2b2b33'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'contact_sheet.png'))
    print('generated v6 (48x48, face 42x28):', len(CHARS), 'chars x', len(EXPRS), 'exprs')

if __name__ == '__main__':
    main()
