#!/usr/bin/env python3
"""歩行スプライト生成（ポケモン風オーバーワールド）
現場監督ゲーム キャラ作り：サンプル6名 × 4方向（下/上/左/右）× 3フレーム（止/歩1/歩2）。
グリッド 32x40、ポートレートv4と同じパレット・同じ「口と鼻なし」の顔で統一。
出力: walk/<id>_<dir>_<frame>.png, sheets/walk_<id>.png, sheets/walk_preview.gif
"""
from PIL import Image, ImageDraw
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 32, 40
INK = (38, 36, 44)
WHITE = (245, 245, 245)
PANTS = (58, 63, 74)
BOOTS = (74, 56, 38)

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    if 0 <= x < W and 0 <= y < H:
        d.point((x, y), fill=col)

def legs_front(d, frame, pants=PANTS):
    if frame == 0:
        rect(d, 11, 27, 14, 34, pants); rect(d, 17, 27, 20, 34, pants)
        rect(d, 10, 35, 14, 37, BOOTS); rect(d, 17, 35, 21, 37, BOOTS)
    elif frame == 1:   # 左足が前
        rect(d, 10, 27, 13, 35, pants); rect(d, 9, 36, 13, 38, BOOTS)
        rect(d, 18, 27, 21, 32, pants); rect(d, 18, 33, 22, 35, BOOTS)
    else:              # 右足が前
        rect(d, 18, 27, 21, 35, pants); rect(d, 18, 36, 22, 38, BOOTS)
        rect(d, 11, 27, 14, 32, pants); rect(d, 10, 33, 14, 35, BOOTS)

def arms_front(d, ch, frame):
    jacket, skin = C(ch['jacket']), C(ch['skin'])
    # frame: 0=両手下, 1=左手前(下)/右手後(上), 2=逆
    lo = 0 if frame != 2 else -1
    ro = 0 if frame != 1 else -1
    rect(d, 6, 19, 8, 25 + lo, jacket); rect(d, 6, 26 + lo, 8, 27 + lo, skin)
    rect(d, 23, 19, 25, 25 + ro, jacket); rect(d, 23, 26 + ro, 25, 27 + ro, skin)

def helmet(d, ch, xoff=0):
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    rect(d, 12 + xoff, 2, 19 + xoff, 2, hel)
    rect(d, 10 + xoff, 3, 21 + xoff, 3, hel)
    rect(d, 9 + xoff, 4, 22 + xoff, 7, hel)
    rect(d, 6 + xoff, 8, 25 + xoff, 9, hel)
    rect(d, 6 + xoff, 10, 8 + xoff, 10, held); rect(d, 23 + xoff, 10, 25 + xoff, 10, held)
    rect(d, 14 + xoff, 2, 17 + xoff, 7, stripe)

def draw_front(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = C(ch['skin']), C(ch['hair'])
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    legs_front(d, frame)
    arms_front(d, ch, frame)
    rect(d, 9, 18, 22, 26, jacket)
    rect(d, 14, 18, 17, 26, shirt)
    if ch.get('tie'):
        rect(d, 15, 18, 16, 26, C(ch['tie']))
    rect(d, 10, 19, 12, 26, vest); rect(d, 19, 19, 21, 26, vest)
    rect(d, 10, 23, 12, 24, C('#dfe4ea')); rect(d, 19, 23, 21, 24, C('#dfe4ea'))
    if 'towel' in ch['extra']:
        rect(d, 12, 18, 19, 19, C('#eef0ea'))
    # 顔
    for y in range(9, 18):
        x0, x1 = (10, 21) if y in (9, 16) else ((12, 19) if y == 17 else (9, 22))
        rect(d, x0, y, x1, y, skin)
    rect(d, 9, 10, 10, 14, hair); rect(d, 21, 10, 22, 14, hair)
    rect(d, 7, 12, 8, 14, skin); rect(d, 23, 12, 24, 14, skin)
    helmet(d, ch)
    rect(d, 12, 12, 13, 14, INK); rect(d, 18, 12, 19, 14, INK)
    px(d, 12, 12, WHITE); px(d, 18, 12, WHITE)
    bl = C('#eda184'); px(d, 10, 15, bl); px(d, 21, 15, bl)
    if 'pencil' in ch['extra']:
        rect(d, 25, 10, 26, 15, C('#f2c018'))
    return img

def draw_back(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hair = C(ch['hair'])
    jacket, vest = C(ch['jacket']), C(ch['vest'])
    legs_front(d, frame)
    arms_front(d, ch, frame)
    rect(d, 9, 18, 22, 26, jacket)
    rect(d, 10, 19, 12, 26, vest); rect(d, 19, 19, 21, 26, vest)
    rect(d, 9, 23, 22, 24, C('#dfe4ea'))           # 背中の反射帯
    if 'towel' in ch['extra']:
        rect(d, 12, 18, 19, 19, C('#eef0ea'))
    for y in range(9, 18):                          # 後ろ頭（髪）
        x0, x1 = (10, 21) if y in (9, 16) else ((12, 19) if y == 17 else (9, 22))
        rect(d, x0, y, x1, y, hair)
    helmet(d, ch)
    return img

def draw_right(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = C(ch['skin']), C(ch['hair'])
    jacket, vest = C(ch['jacket']), C(ch['vest'])
    # 脚（横向き：前後に開く）
    if frame == 0:
        rect(d, 11, 27, 14, 34, PANTS); rect(d, 16, 27, 19, 34, PANTS)
        rect(d, 10, 35, 14, 37, BOOTS); rect(d, 16, 35, 20, 37, BOOTS)
    elif frame == 1:
        rect(d, 15, 27, 18, 35, PANTS); rect(d, 15, 36, 19, 38, BOOTS)   # 前脚が前へ
        rect(d, 9, 27, 12, 32, PANTS); rect(d, 7, 33, 11, 35, BOOTS)     # 後脚は後ろ
    else:
        rect(d, 15, 27, 18, 32, PANTS); rect(d, 16, 33, 20, 35, BOOTS)
        rect(d, 9, 27, 12, 35, PANTS); rect(d, 8, 36, 12, 38, BOOTS)
    # 腕（前側のみ大きく、振りで前後）
    ax = 21 if frame == 1 else (19 if frame == 2 else 20)
    rect(d, 9, 18, 20, 26, jacket)
    rect(d, 17, 19, 19, 26, vest); rect(d, 17, 23, 19, 24, C('#dfe4ea'))
    rect(d, ax, 19, ax + 2, 25, jacket); rect(d, ax, 26, ax + 2, 27, skin)
    if 'towel' in ch['extra']:
        rect(d, 11, 18, 17, 19, C('#eef0ea'))
    # 頭（横顔）
    for y in range(9, 18):
        x0, x1 = (10, 20) if y in (9, 16) else ((12, 18) if y == 17 else (9, 21))
        rect(d, x0, y, x1, y, skin)
    rect(d, 9, 10, 11, 16, hair)                    # 後ろ髪
    rect(d, 10, 12, 11, 14, skin)                   # 耳
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    rect(d, 11, 2, 18, 2, hel); rect(d, 9, 3, 20, 3, hel); rect(d, 8, 4, 21, 7, hel)
    rect(d, 5, 8, 26, 9, hel)                       # ツバは前（右）に長く
    rect(d, 13, 2, 16, 7, stripe)
    rect(d, 17, 12, 18, 14, INK); px(d, 17, 12, WHITE)
    px(d, 20, 15, C('#eda184'))
    return img

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
                draw(ch, dr, f).resize((W * 6, H * 6), Image.NEAREST).save(
                    os.path.join(OUT, 'walk', f"{ch['id']}_{dr}_{f}.png"))
        # 1キャラ分のシート（4方向×3フレーム）
        cell_w, cell_h, gap = W * 4, H * 4, 6
        sheet = Image.new('RGB', (cell_w * 3 + gap * 4, cell_h * 4 + gap * 5), C('#f4f1ea'))
        for r, dr in enumerate(DIRS):
            for f in range(3):
                spr = draw(ch, dr, f).resize((cell_w, cell_h), Image.NEAREST)
                sheet.paste(spr, (gap + f * (cell_w + gap), gap + r * (cell_h + gap)), spr)
        sheet.save(os.path.join(OUT, 'sheets', f"walk_{ch['id']}.png"))

    # 全員・正面立ちの一覧
    cell_w, cell_h, pad = W * 5, H * 5, 16
    sheet = Image.new('RGB', (cell_w * 6 + pad * 7, cell_h + pad * 2), C('#f4f1ea'))
    for i, ch in enumerate(CHARS):
        spr = draw(ch, 'down', 0).resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (pad + i * (cell_w + pad), pad), spr)
    sheet.save(os.path.join(OUT, 'sheets', 'walk_all_front.png'))

    # 歩行プレビューGIF（全員・正面・横一列）
    scale = 5
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
    print('generated walk:', len(CHARS), 'chars x', len(DIRS), 'dirs x 3 frames + gif')

if __name__ == '__main__':
    main()
