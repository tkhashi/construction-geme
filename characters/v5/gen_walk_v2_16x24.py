#!/usr/bin/env python3
"""歩行スプライト生成 v2（ポケモン ルビー/サファイア準拠）
16x24pxグリッド、濃い輪郭線、制限パレット（1キャラ約12色）、4方向×3フレーム。
現場監督ゲーム キャラ作り：サンプル6名。顔は口・鼻なし、パレットはポートレートと共通。
出力: walk/<id>_<dir>_<frame>.png, sheets/walk_<id>.png, sheets/walk_all_front.png,
      sheets/walk_preview.gif
"""
from PIL import Image, ImageDraw
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 16, 24
INK = (38, 36, 44)
WHITE = (245, 245, 245)
PANTS = (58, 63, 74)
PANTS_D = (44, 48, 58)
BOOTS = (74, 56, 38)
OUTLINE_COL = (43, 36, 31, 255)

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    if 0 <= x < W and 0 <= y < H:
        d.point((x, y), fill=col)

def add_outline(img):
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

def helmet(d, ch):
    hel, stripe = C(ch['helmet']), C(ch['stripe'])
    rect(d, 5, 1, 10, 1, hel)
    rect(d, 4, 2, 11, 2, hel)
    rect(d, 3, 3, 12, 4, hel)
    rect(d, 2, 5, 13, 5, hel)          # ツバ
    rect(d, 7, 1, 8, 4, stripe)

def legs(d, frame):
    if frame == 0:
        rect(d, 5, 19, 6, 21, PANTS); rect(d, 9, 19, 10, 21, PANTS)
        rect(d, 4, 22, 6, 23, BOOTS); rect(d, 9, 22, 11, 23, BOOTS)
    elif frame == 1:
        rect(d, 4, 19, 5, 22, PANTS); rect(d, 3, 23, 5, 23, BOOTS)
        rect(d, 10, 19, 11, 21, PANTS); rect(d, 10, 22, 12, 22, BOOTS)
    else:
        rect(d, 10, 19, 11, 22, PANTS); rect(d, 10, 23, 12, 23, BOOTS)
        rect(d, 5, 19, 6, 21, PANTS); rect(d, 3, 22, 5, 22, BOOTS)

def arms(d, ch, frame):
    jacket, skin = C(ch['jacket']), C(ch['skin'])
    lo = 1 if frame == 1 else 0        # 左腕は歩1で下がる
    ro = 1 if frame == 2 else 0
    rect(d, 2, 13, 3, 16 + lo, jacket); px(d, 2, 17 + lo, skin); px(d, 3, 17 + lo, skin)
    rect(d, 12, 13, 13, 16 + ro, jacket); px(d, 12, 17 + ro, skin); px(d, 13, 17 + ro, skin)

def torso(d, ch, back=False):
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 4, 13, 11, 18, jacket)
    if back:
        rect(d, 4, 14, 5, 18, vest); rect(d, 10, 14, 11, 18, vest)
        rect(d, 4, 16, 11, 16, C('#dfe4ea'))
    else:
        rect(d, 7, 13, 8, 18, shirt)
        if ch.get('tie'):
            rect(d, 7, 13, 8, 18, C(ch['tie']))
        rect(d, 4, 14, 5, 18, vest); rect(d, 10, 14, 11, 18, vest)
        px(d, 4, 16, C('#dfe4ea')); px(d, 5, 16, C('#dfe4ea'))
        px(d, 10, 16, C('#dfe4ea')); px(d, 11, 16, C('#dfe4ea'))
    if 'towel' in ch['extra']:
        rect(d, 6, 13, 9, 13, C('#eef0ea'))

def draw_front(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = C(ch['skin']), C(ch['hair'])
    legs(d, frame); arms(d, ch, frame); torso(d, ch)
    for y in range(6, 13):
        x0, x1 = (4, 11) if y in (6, 11) else ((5, 10) if y == 12 else (3, 12))
        rect(d, x0, y, x1, y, skin)
    rect(d, 3, 6, 3, 9, hair); rect(d, 12, 6, 12, 9, hair)
    px(d, 2, 8, skin); px(d, 13, 8, skin)
    helmet(d, ch)
    rect(d, 5, 8, 6, 9, INK); rect(d, 9, 8, 10, 9, INK)
    px(d, 5, 8, WHITE); px(d, 9, 8, WHITE)
    bl = C('#eda184'); px(d, 4, 10, bl); px(d, 11, 10, bl)
    if 'pencil' in ch['extra']:
        px(d, 14, 7, C('#f2c018')); px(d, 14, 8, C('#f2c018'))
    return add_outline(img)

def draw_back(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hair = C(ch['hair'])
    legs(d, frame); arms(d, ch, frame); torso(d, ch, back=True)
    for y in range(6, 13):
        x0, x1 = (4, 11) if y in (6, 11) else ((5, 10) if y == 12 else (3, 12))
        rect(d, x0, y, x1, y, hair)
    helmet(d, ch)
    return add_outline(img)

def draw_right(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = C(ch['skin']), C(ch['hair'])
    jacket, vest = C(ch['jacket']), C(ch['vest'])
    # 脚（横向き）
    if frame == 0:
        rect(d, 5, 19, 6, 21, PANTS_D); rect(d, 4, 22, 6, 23, BOOTS)
        rect(d, 8, 19, 9, 21, PANTS); rect(d, 8, 22, 10, 23, BOOTS)
    elif frame == 1:
        rect(d, 9, 19, 10, 22, PANTS); rect(d, 9, 23, 12, 23, BOOTS)    # 前脚が前
        rect(d, 4, 19, 5, 21, PANTS_D); rect(d, 2, 21, 4, 22, BOOTS)    # 後脚は後ろ
    else:
        rect(d, 8, 19, 9, 21, PANTS); rect(d, 7, 22, 9, 22, BOOTS)
        rect(d, 5, 19, 6, 22, PANTS_D); rect(d, 4, 23, 6, 23, BOOTS)
    # 体と腕
    rect(d, 5, 13, 11, 18, jacket)
    rect(d, 9, 14, 11, 18, vest); px(d, 9, 16, C('#dfe4ea')); px(d, 10, 16, C('#dfe4ea'))
    ax = 12 if frame == 1 else (10 if frame == 2 else 11)
    rect(d, ax, 13, ax + 1, 16, jacket); px(d, ax, 17, skin); px(d, ax + 1, 17, skin)
    if 'towel' in ch['extra']:
        rect(d, 6, 13, 9, 13, C('#eef0ea'))
    # 頭（横顔）
    for y in range(6, 13):
        x0, x1 = (5, 11) if y in (6, 11) else ((6, 10) if y == 12 else (4, 11))
        rect(d, x0, y, x1, y, skin)
    rect(d, 4, 6, 5, 11, hair)
    px(d, 6, 9, C(ch['skin_shadow']))
    hel, stripe = C(ch['helmet']), C(ch['stripe'])
    rect(d, 6, 1, 11, 1, hel); rect(d, 5, 2, 12, 2, hel); rect(d, 4, 3, 12, 4, hel)
    rect(d, 3, 5, 14, 5, hel)                       # ツバは前に長く
    rect(d, 7, 1, 8, 4, stripe)
    rect(d, 9, 8, 10, 9, INK); px(d, 9, 8, WHITE)
    px(d, 11, 10, C('#eda184'))
    return add_outline(img)

DIRS = ['down', 'up', 'left', 'right']

def draw(ch, direction, frame):
    if direction == 'down':
        return draw_front(ch, frame)
    if direction == 'up':
        return draw_back(ch, frame)
    if direction == 'right':
        return draw_right(ch, frame)
    return draw_right(ch, frame).transpose(Image.FLIP_LEFT_RIGHT)

def main():
    os.makedirs(os.path.join(OUT, 'walk'), exist_ok=True)
    for ch in CHARS:
        for dr in DIRS:
            for f in range(3):
                draw(ch, dr, f).resize((W * 12, H * 12), Image.NEAREST).save(
                    os.path.join(OUT, 'walk', f"{ch['id']}_{dr}_{f}.png"))
        cell_w, cell_h, gap = W * 9, H * 9, 6
        sheet = Image.new('RGB', (cell_w * 3 + gap * 4, cell_h * 4 + gap * 5), C('#f4f1ea'))
        for r, dr in enumerate(DIRS):
            for f in range(3):
                spr = draw(ch, dr, f).resize((cell_w, cell_h), Image.NEAREST)
                sheet.paste(spr, (gap + f * (cell_w + gap), gap + r * (cell_h + gap)), spr)
        sheet.save(os.path.join(OUT, 'sheets', f"walk_{ch['id']}.png"))

    cell_w, cell_h, pad = W * 10, H * 10, 16
    sheet = Image.new('RGB', (cell_w * 6 + pad * 7, cell_h + pad * 2), C('#f4f1ea'))
    for i, ch in enumerate(CHARS):
        spr = draw(ch, 'down', 0).resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (pad + i * (cell_w + pad), pad), spr)
    sheet.save(os.path.join(OUT, 'sheets', 'walk_all_front.png'))

    scale = 10
    cw, chh = W * scale, H * scale
    frames = []
    for f in [0, 1, 0, 2]:
        canvas = Image.new('RGB', (cw * 6 + pad * 7, chh + pad * 2 + 10), C('#e8e0cd'))
        dd = ImageDraw.Draw(canvas)
        dd.rectangle([0, chh + pad - 6, canvas.width, canvas.height], fill=C('#cdbfa3'))
        for i, ch in enumerate(CHARS):
            spr = draw(ch, 'down', f).resize((cw, chh), Image.NEAREST)
            canvas.paste(spr, (pad + i * (cw + pad), pad), spr)
        frames.append(canvas)
    frames[0].save(os.path.join(OUT, 'sheets', 'walk_preview.gif'),
                   save_all=True, append_images=frames[1:], duration=170, loop=0)
    print('generated walk v2 (16x24 RS-style):', len(CHARS), 'chars')

if __name__ == '__main__':
    main()
