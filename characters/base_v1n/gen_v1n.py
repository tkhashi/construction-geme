#!/usr/bin/env python3
"""ドット絵ポートレート生成（現場監督ゲーム キャラ作り サンプル6名）
ベース解像度 48x56 のピクセルグリッドで描き、NEARESTで拡大する。
画風・パレット・サイズを全員で統一し、本編（対話画面/人物カード/ヘッダー顔アイコン）に
そのまま流用できる素材として出力する。
出力: sprites/<id>_<expr>.png (384x448), icons/<id>.png, sheets/*.png
"""
from PIL import Image, ImageDraw, ImageFont
import os

BASE_W, BASE_H = 48, 56
SCALE = 8
OUT = os.path.dirname(os.path.abspath(__file__))

INK = (38, 36, 44)          # 輪郭・目
WHITE = (245, 245, 245)

def C(hexs):
    hexs = hexs.lstrip('#')
    return tuple(int(hexs[i:i+2], 16) for i in (0, 2, 4))

CHARS = [
    dict(
        id='hero', name='主人公（担当者）',
        skin='#f2c49b', skin_shadow='#d99e6c', hair='#4a3423',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#1f7a8c',
        jacket='#2e4a66', vest='#8fa3b8', shirt='#eef2f5', tie='#1f7a8c',
        extra=[], young=True,
    ),
    dict(
        id='kacho', name='課長',
        skin='#eebd90', skin_shadow='#cf9459', hair='#2e2a28',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#1f7a8c',
        jacket='#2e4a66', vest='#8fa3b8', shirt='#eef2f5', tie='#1f7a8c',
        extra=['glasses'], lines=True,
    ),
    dict(
        id='shocho', name='所長',
        skin='#e8b489', skin_shadow='#c98d55', hair='#b9b9bc',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#1f7a8c',
        jacket='#2e4a66', vest='#8fa3b8', shirt='#eef2f5', tie='#1f7a8c',
        extra=['mustache'], lines=True, gray_brow=True,
    ),
    dict(
        id='tobi', name='鳶職長',
        skin='#d99a5f', skin_shadow='#b97a3e', hair='#1d1a17',
        helmet='#7a4fa3', helmet_dark='#5d3a80', stripe='#e8d44d',
        jacket='#33395e', vest='#565d8f', shirt='#cfd4e8', tie=None,
        extra=['stubble', 'towel'], sharp=True,
    ),
    dict(
        id='denki', name='電気職長',
        skin='#f4cda6', skin_shadow='#dda26e', hair='#6b4423',
        helmet='#f2c018', helmet_dark='#c99612', stripe='#2b2b33',
        jacket='#4c5560', vest='#f2c018', shirt='#eef0ea', tie=None,
        extra=['pencil'], friendly=True,
    ),
    dict(
        id='eisei', name='衛生職長',
        skin='#f0c096', skin_shadow='#d2955e', hair='#22242c',
        helmet='#2470c2', helmet_dark='#1a5290', stripe='#f2f3f5',
        jacket='#5b7d9e', vest='#2470c2', shirt='#eaf2f8', tie=None,
        extra=['neckerchief'], soft=True,
    ),
    dict(
        id='seshu', name='施主担当',
        skin='#f6d3ab', skin_shadow='#e0aa70', hair='#7a4a2b',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#1f7a8c',
        jacket='#2b3a55', vest='#2b3a55', shirt='#f5f5f7', tie=None,
        extra=['longhair', 'suit'], friendly=True,
    ),
]
EXPRS = ['normal', 'smile', 'worried', 'angry']

def rect(d, x0, y0, x1, y1, col):
    d.rectangle([x0, y0, x1, y1], fill=col)

def px(d, x, y, col):
    d.point((x, y), fill=col)

def draw(ch, expr):
    img = Image.new('RGBA', (BASE_W, BASE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, sh = C(ch['skin']), C(ch['skin_shadow'])
    hair = C(ch['hair'])

    # ---- 胴体（バストアップ）----
    jacket, vest, shirt = C(ch['jacket']), C(ch['vest']), C(ch['shirt'])
    rect(d, 9, 45, 38, 55, jacket)                 # 肩〜胴
    rect(d, 7, 48, 9, 55, jacket); rect(d, 38, 48, 40, 55, jacket)
    rect(d, 20, 46, 27, 55, shirt)                 # 前立て
    if ch.get('tie'):
        rect(d, 22, 47, 25, 55, C(ch['tie']))      # ネクタイ
    rect(d, 11, 45, 17, 55, vest); rect(d, 30, 45, 36, 55, vest)   # ベスト
    if 'suit' not in ch['extra']:   # スーツ姿には反射帯を付けない
        rect(d, 11, 50, 17, 51, C('#d8dde2')); rect(d, 30, 50, 36, 51, C('#d8dde2'))  # 反射帯
    # 首
    rect(d, 21, 38, 26, 45, sh)
    rect(d, 21, 40, 26, 45, skin)

    # ---- 顔 ----
    rect(d, 15, 15, 32, 38, skin)
    rect(d, 17, 39, 30, 41, skin)                  # 顎
    rect(d, 13, 26, 14, 31, skin); rect(d, 33, 26, 34, 31, skin)   # 耳
    px(d, 14, 28, sh); px(d, 33, 28, sh)
    # 顔の影（輪郭代わり）
    for y in range(18, 38):
        px(d, 15, y, sh); px(d, 32, y, sh)
    # 頬の陰
    if ch.get('lines'):
        px(d, 17, 33, sh); px(d, 18, 34, sh); px(d, 30, 33, sh); px(d, 29, 34, sh)
    # もみ上げ（前髪なし。深く被ったヘルメットの下端より下だけが見える）
    if 'longhair' in ch['extra']:
        rect(d, 15, 16, 16, 36, hair); rect(d, 31, 16, 32, 36, hair)   # 顔の横を落ちる房
        rect(d, 13, 15, 14, 40, hair); rect(d, 33, 15, 34, 40, hair)   # 耳の外側の長髪
    else:
        side_h = 27 if ch.get('young') else 24
        rect(d, 15, 16, 16, side_h, hair); rect(d, 31, 16, 32, side_h, hair)

    # ---- ヘルメット（施主は被らない：髪の天面＋中央分けの前髪） ----
    if 'suit' in ch['extra']:
        rect(d, 17, 11, 30, 11, hair)
        rect(d, 15, 12, 32, 16, hair)
        rect(d, 15, 17, 20, 17, hair); rect(d, 27, 17, 32, 17, hair)   # 中央分け
        hel = held = stripe = None
    else:
        hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    if 'suit' not in ch['extra']:
        rect(d, 17, 11, 30, 13, hel)               # ヘルメット全体を7px下げて着用（ツバ下端が眉に接する＝オン眉）
        rect(d, 14, 14, 33, 20, hel)                # 横幅も輪郭に寄せた（ツバ28→24px、顔18pxに張り出し3px/側）
        rect(d, 12, 20, 35, 22, hel)
        rect(d, 12, 22, 35, 22, held)              # つばの影
        rect(d, 22, 11, 25, 20, stripe)            # センターライン
    # あご紐は描かない（ユーザ指示：耳の下の黒い線がノイズに見えるため）

    # ---- 眉 ----
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    thick = 2 if ch.get('gray_brow') else 1
    def brow(x0, pts):
        for i, yy in enumerate(pts):
            for t in range(thick):
                px(d, x0 + i, yy - t, brow_col)
    if expr == 'normal':
        brow(18, [23, 23, 23, 23]); brow(27, [23, 23, 23, 23])
    elif expr == 'smile':
        brow(18, [22, 21, 21, 22]); brow(27, [22, 21, 21, 22])
    elif expr == 'worried':
        brow(18, [24, 23, 22, 22]); brow(27, [22, 22, 23, 24])
    elif expr == 'angry':
        brow(18, [22, 23, 24, 25]); brow(27, [25, 24, 23, 22])

    # ---- 目 ----
    def eye(cx, mode):
        if mode == 'smile':                        # 笑い目（^ ^）
            for dx, dy in [(0, 1), (1, 0), (2, 0), (3, 1)]:
                px(d, cx - 1 + dx, 27 + dy - 1, INK)
        elif mode == 'angry':
            rect(d, cx - 1, 26, cx + 2, 27, INK)
            px(d, cx, 28, INK)
        elif mode == 'worried':
            rect(d, cx, 27, cx + 1, 28, INK)
        else:
            rect(d, cx - 1, 26, cx + 1, 28, INK)
            px(d, cx + 1, 26, WHITE)
    eye(20, expr); eye(28, expr)
    # 鼻
    px(d, 24, 30, sh); px(d, 24, 31, sh)

    # ---- 口 ----
    if 'mustache' not in ch['extra']:
        if expr == 'smile':
            for dx, dy in [(0, 0), (1, 1), (2, 1), (3, 1), (4, 0)]:
                px(d, 21 + dx, 34 + dy, INK)
            px(d, 22, 35, C('#8c4a3a')); px(d, 23, 35, C('#8c4a3a')); px(d, 24, 35, C('#8c4a3a'))
        elif expr == 'worried':
            for dx, dy in [(0, 1), (1, 0), (2, 1), (3, 0), (4, 1)]:
                px(d, 21 + dx, 34 + dy, INK)
        elif expr == 'angry':
            for dx, dy in [(0, 1), (1, 0), (2, 0), (3, 0), (4, 1)]:
                px(d, 21 + dx, 33 + dy, INK)
        else:
            rect(d, 22, 34, 25, 34, INK)

    # ---- 個別の特徴 ----
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([17, 24, 23, 30], outline=g)
        d.rectangle([25, 24, 31, 30], outline=g)
        px(d, 24, 26, g)
    if 'mustache' in ch['extra']:
        mo = C('#a9a9ae')
        rect(d, 20, 32, 27, 33, mo); px(d, 23, 33, skin); px(d, 24, 33, skin)
        # 口は髭の下に小さく
        if expr == 'smile':
            rect(d, 22, 35, 25, 35, INK)
        elif expr == 'angry':
            px(d, 22, 36, INK); px(d, 25, 36, INK)
    if 'stubble' in ch['extra']:
        for (x, y) in [(18, 37), (21, 39), (24, 40), (27, 39), (29, 37), (19, 40), (28, 40), (23, 38)]:
            px(d, x, y, sh)
    if 'towel' in ch['extra']:                     # 首タオル
        rect(d, 17, 42, 30, 45, C('#eef0ea'))
        rect(d, 17, 44, 30, 44, C('#2470c2'))
        rect(d, 27, 42, 30, 48, C('#e3e7de'))
    if 'neckerchief' in ch['extra']:
        for i in range(5):
            rect(d, 21 + i // 2, 42 + i, 26 - i // 2, 42 + i, C('#1a5290'))
    if 'pencil' in ch['extra']:                    # 耳ペン
        rect(d, 35, 21, 36, 27, C('#f2c018')); px(d, 35, 20, C('#e08a2e'))

    # ---- 表情の小物 ----
    if expr == 'worried':                          # 汗
        sw = C('#57a8d8')
        px(d, 37, 24, sw); rect(d, 36, 25, 38, 27, sw); px(d, 37, 28, sw)   # 汗はツバの下から
    if expr == 'angry':                            # 怒りマーク
        r = C('#d8402e')
        rect(d, 36, 8, 38, 10, r); px(d, 35, 9, r); px(d, 39, 9, r); px(d, 37, 7, r); px(d, 37, 11, r)
    if expr == 'smile' and (ch.get('friendly') or ch.get('young')):
        bl = C('#e89a7d')
        px(d, 17, 31, bl); px(d, 18, 31, bl); px(d, 29, 31, bl); px(d, 30, 31, bl)

    return img

def save_scaled(img, path, scale):
    img.resize((BASE_W * scale, BASE_H * scale), Image.NEAREST).save(path)

def main():
    for ch in CHARS:
        for expr in EXPRS:
            img = draw(ch, expr)
            save_scaled(img, os.path.join(OUT, 'sprites', f"{ch['id']}_{expr}.png"), SCALE)
        # 顔アイコン（ヘッダー用：顔まわりを切り出し）
        icon = draw(ch, 'normal').crop((7, 2, 41, 40)).resize((136, 152), Image.NEAREST)
        icon.save(os.path.join(OUT, 'icons', f"{ch['id']}.png"))
        # 表情シート（4種横並び）
        strip = Image.new('RGBA', (BASE_W * 4 + 30, BASE_H), (0, 0, 0, 0))
        for i, expr in enumerate(EXPRS):
            strip.paste(draw(ch, expr), (i * (BASE_W + 10), 0))
        strip.resize((strip.width * 5, strip.height * 5), Image.NEAREST).save(
            os.path.join(OUT, 'sheets', f"{ch['id']}_expressions.png"))

    # コンタクトシート（通常顔 6名・3x2）
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
    print('generated:', len(CHARS), 'chars x', len(EXPRS), 'exprs')

if __name__ == '__main__':
    main()
