#!/usr/bin/env python3
"""歩行スプライト生成 v3（ユーザー提供のポケモン素材シートを実物参考に調整）
参考：characters/reference/pokemon_field_sprites_ref.png（ポケモン ドット絵作成所の素材集、
ルビー/サファイア〜ダイヤモンド/パール世代のフィールドスプライト）。
合わせた点：グリッド 16x20px、頭が全体の約半分、色数を絞る（シャツ=白・ブーツ=輪郭色・
ネクタイ=ストライプ色を流用し、1キャラ約10色）、1pxの濃い輪郭、フラットな塗り、影なし。
4方向×3フレーム。顔は口・鼻なし。
画風統一（2026-11-08、reference/user_style_ref_chibi.jpg）：視点はやや斜め上（ヘルメット
天面を広く、肩の上面を見せる）、目は小さい縦バー（正面2px幅・横向き1本）、頬なし・肌
フラット、髪の側面に一段濃い影色。パレット基礎はポートレートと共通（ヘルメット色=工種カラー）。
出力: walk/<id>_<dir>_<frame>.png, sheets/walk_<id>.png, sheets/walk_all_front.png,
      sheets/walk_preview.gif
"""
from PIL import Image, ImageDraw
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C, shade

OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 16, 20
INK = (38, 36, 44)
WHITE = (245, 245, 245)
PANTS = (58, 63, 74)
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
    if 'cap' in ch['extra']:           # 近隣代表は安全帽ではなく普通の帽子（現場の人間ではない）
        rect(d, 5, 2, 10, 2, hel)
        rect(d, 3, 3, 12, 3, hel)      # 帽子のつば
        return
    if 'suit' in ch['extra']:          # 施主はヘルメットなし（髪のまま）
        return
    rect(d, 4, 0, 11, 0, hel)          # 天面（やや見下ろしで広めに）
    rect(d, 3, 1, 12, 1, hel)
    rect(d, 3, 2, 12, 2, hel)
    rect(d, 2, 3, 13, 3, hel)          # ツバ
    rect(d, 7, 0, 8, 2, stripe)

def legs(d, frame):
    # 脚は3px（ズボン2＋靴1）。参考画像の実物に合わせて短く
    if frame == 0:
        rect(d, 5, 17, 6, 18, PANTS); rect(d, 9, 17, 10, 18, PANTS)
        rect(d, 4, 19, 6, 19, INK); rect(d, 9, 19, 11, 19, INK)
    elif frame == 1:                   # 左足が前／右足は浮く
        rect(d, 4, 17, 5, 18, PANTS); rect(d, 3, 19, 5, 19, INK)
        rect(d, 10, 17, 11, 17, PANTS); rect(d, 10, 18, 12, 18, INK)
    else:                              # 右足が前／左足は浮く
        rect(d, 10, 17, 11, 18, PANTS); rect(d, 10, 19, 12, 19, INK)
        rect(d, 5, 17, 6, 17, PANTS); rect(d, 3, 18, 5, 18, INK)

def arms(d, ch, frame):
    jacket, skin = C(ch['jacket']), C(ch['skin'])
    lo = 1 if frame == 1 else 0
    ro = 1 if frame == 2 else 0
    rect(d, 2, 11, 3, 15, jacket); px(d, 2, 16 + lo, skin); px(d, 3, 16 + lo, skin)
    rect(d, 12, 11, 13, 15, jacket); px(d, 12, 16 + ro, skin); px(d, 13, 16 + ro, skin)

def torso(d, ch, back=False):
    jacket, vest = C(ch['jacket']), C(ch['vest'])
    rect(d, 3, 11, 12, 11, jacket)                 # 肩の上面（やや見下ろし）
    rect(d, 4, 12, 11, 16, jacket)
    rect(d, 4, 13, 5, 16, vest); rect(d, 10, 13, 11, 16, vest)
    if back:
        if 'suit' not in ch['extra']:
            rect(d, 4, 14, 11, 14, WHITE)          # 背中の反射帯（スーツには付けない）
    else:
        rect(d, 7, 12, 8, 16, WHITE)               # シャツ（白で色数節約）
        if ch.get('tie'):
            rect(d, 7, 12, 8, 14, C(ch['stripe']))  # ネクタイはストライプ色を流用
        if 'suit' not in ch['extra']:
            px(d, 4, 15, WHITE); px(d, 5, 15, WHITE)
            px(d, 10, 15, WHITE); px(d, 11, 15, WHITE)
    if 'towel' in ch['extra']:
        rect(d, 6, 12, 9, 12, WHITE)

def head_base(d, ch, back=False):
    skin, hair = C(ch['skin']), C(ch['hair'])
    haird = shade(hair)
    base = hair if back else skin
    for y in range(4, 11):
        x0, x1 = (4, 11) if y in (4, 9) else ((5, 10) if y == 10 else (3, 12))
        rect(d, x0, y, x1, y, base)
    if back:
        rect(d, 3, 5, 3, 8, haird); rect(d, 12, 5, 12, 8, haird)   # 後ろ髪の側面影
    else:
        side_end = 9 if 'longhair' in ch['extra'] else 7
        rect(d, 3, 4, 3, side_end, haird); rect(d, 12, 4, 12, side_end, haird)
        rect(d, 4, 4, 11, 4, hair)   # 前髪（デコを狭く）
        rect(d, 4, 5, 5, 5, hair); rect(d, 10, 5, 11, 5, hair)
        px(d, 2, 6, skin); px(d, 13, 6, skin)
    helmet(d, ch)

def draw_front(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    legs(d, frame); arms(d, ch, frame); torso(d, ch); head_base(d, ch)
    rect(d, 5, 7, 6, 8, INK); rect(d, 9, 7, 10, 8, INK)   # 小さい縦バー目（顔の下半分・頬なし）
    if 'pencil' in ch['extra']:
        px(d, 14, 5, C('#f2c018')); px(d, 14, 6, C('#f2c018'))
    return add_outline(img)

def draw_back(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    legs(d, frame); arms(d, ch, frame); torso(d, ch, back=True); head_base(d, ch, back=True)
    return add_outline(img)

def draw_right(ch, frame):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = C(ch['skin']), C(ch['hair'])
    jacket, vest = C(ch['jacket']), C(ch['vest'])
    # 脚（横向き・3px）
    if frame == 0:
        rect(d, 5, 17, 6, 18, PANTS); rect(d, 4, 19, 6, 19, INK)
        rect(d, 8, 17, 9, 18, PANTS); rect(d, 8, 19, 10, 19, INK)
    elif frame == 1:
        rect(d, 9, 17, 10, 18, PANTS); rect(d, 9, 19, 12, 19, INK)   # 前脚が前
        rect(d, 4, 17, 5, 17, PANTS); rect(d, 2, 18, 4, 18, INK)     # 後脚は浮く
    else:
        rect(d, 7, 17, 8, 18, PANTS); rect(d, 6, 19, 8, 19, INK)
        rect(d, 10, 17, 11, 17, PANTS); rect(d, 10, 18, 12, 18, INK)
    # 体と腕
    rect(d, 4, 11, 12, 11, jacket)                  # 肩の上面（やや見下ろし）
    rect(d, 5, 12, 11, 16, jacket)
    rect(d, 9, 13, 11, 16, vest)
    if 'suit' not in ch['extra']:
        px(d, 9, 15, WHITE); px(d, 10, 15, WHITE)
    ax = 12 if frame == 1 else (10 if frame == 2 else 11)
    rect(d, ax, 11, ax + 1, 15, jacket); px(d, ax, 16, skin); px(d, ax + 1, 16, skin)
    if 'towel' in ch['extra']:
        rect(d, 6, 12, 9, 12, WHITE)
    # 頭（横顔）
    for y in range(4, 11):
        x0, x1 = (5, 11) if y in (4, 9) else ((6, 10) if y == 10 else (4, 11))
        rect(d, x0, y, x1, y, skin)
    rect(d, 4, 4, 4, 9, shade(hair)); rect(d, 5, 4, 5, 9, hair)   # 後ろ髪＋側面影
    rect(d, 10, 4, 11, 4, hair)   # 横向きの前髪
    px(d, 6, 7, skin)
    hel, stripe = C(ch['helmet']), C(ch['stripe'])
    if 'cap' in ch['extra']:                        # 近隣代表は普通の帽子
        rect(d, 5, 2, 12, 2, hel); rect(d, 3, 3, 13, 3, hel)
    elif 'suit' in ch['extra']:                     # 施主はヘルメットなし
        pass
    else:
        rect(d, 5, 0, 12, 0, hel); rect(d, 4, 1, 12, 1, hel); rect(d, 4, 2, 12, 2, hel)
        rect(d, 3, 3, 14, 3, hel)                   # ツバは前に長く
        rect(d, 7, 0, 8, 2, stripe)
    rect(d, 10, 7, 10, 8, INK)                      # 横向きは1本バー目（顔の下半分）
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
        cell_w, cell_h, gap = W * 11, H * 11, 6
        sheet = Image.new('RGB', (cell_w * 3 + gap * 4, cell_h * 4 + gap * 5), C('#f4f1ea'))
        for r, dr in enumerate(DIRS):
            for f in range(3):
                spr = draw(ch, dr, f).resize((cell_w, cell_h), Image.NEAREST)
                sheet.paste(spr, (gap + f * (cell_w + gap), gap + r * (cell_h + gap)), spr)
        sheet.save(os.path.join(OUT, 'sheets', f"walk_{ch['id']}.png"))

    cell_w, cell_h, pad = W * 11, H * 11, 16
    n = len(CHARS)
    sheet = Image.new('RGB', (cell_w * n + pad * (n + 1), cell_h + pad * 2), C('#f4f1ea'))
    for i, ch in enumerate(CHARS):
        spr = draw(ch, 'down', 0).resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(spr, (pad + i * (cell_w + pad), pad), spr)
    sheet.save(os.path.join(OUT, 'sheets', 'walk_all_front.png'))

    # プレビューGIFは横幅の都合で主要8名（監督側3＋職長5）に絞る
    gif_chars = CHARS[:8]
    scale = 11
    cw, chh = W * scale, H * scale
    frames = []
    for f in [0, 1, 0, 2]:
        canvas = Image.new('RGB', (cw * len(gif_chars) + pad * (len(gif_chars) + 1),
                                   chh + pad * 2 + 10), C('#e8e0cd'))
        dd = ImageDraw.Draw(canvas)
        dd.rectangle([0, chh + pad - 6, canvas.width, canvas.height], fill=C('#cdbfa3'))
        for i, ch in enumerate(gif_chars):
            spr = draw(ch, 'down', f).resize((cw, chh), Image.NEAREST)
            canvas.paste(spr, (pad + i * (cw + pad), pad), spr)
        frames.append(canvas)
    frames[0].save(os.path.join(OUT, 'sheets', 'walk_preview.gif'),
                   save_all=True, append_images=frames[1:], duration=170, loop=0)
    print('generated walk v3 (16x20, ref-based):', len(CHARS), 'chars')

if __name__ == '__main__':
    main()
