#!/usr/bin/env python3
"""ドット絵ポートレート生成 v7（48x48・顔は6:4横長・全22名）
現場監督ゲーム キャラ作り。
画風（ユーザー確定 2026-11-08、参考：reference/user_style_ref_chibi.jpg）：
- 視点はやや斜め上（見下ろし気味）：ヘルメットの天面を広く見せ、顔パーツは下半分に寄せる
- 目は小さな縦バー（3×5px、間隔広め）、ハイライトなし。通常・笑顔では眉を描かない
  （眉は困り・怒りのときだけ小さく出す）
- 口・鼻は描かない。頬のピンクなし、肌はフラット。横髪の外側に一段濃い影色
- 表情差は目の形・小さい眉・汗・涙・怒りマークで作る
NEAREST拡大。旧版は v1/ 〜 v9_expanded_oldface/ に退避。
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

def shade(col, f=0.7):
    return tuple(max(0, int(c * f)) for c in col)

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
    # ---- 追加キャスト（全員分への展開・2026-11-08）職長8名 ----
    dict(
        id='tekkin', name='鉄筋職長',
        skin='#e8ac72', skin_shadow='#c98a4e', hair='#241f1c',
        helmet='#6a7078', helmet_dark='#4c5158', stripe='#2b2b33',
        jacket='#4a4a52', vest='#c96a28', shirt='#dfe3e6', tie=None,
        extra=['stubble'],
    ),
    dict(
        id='katawaku', name='型枠職長',
        skin='#f0c08c', skin_shadow='#d29c5c', hair='#4a423c',
        helmet='#8a8578', helmet_dark='#6b665a', stripe='#a33327',
        jacket='#5a4632', vest='#9a8a72', shirt='#ece7db', tie=None,
        extra=['pencil'],
    ),
    dict(
        id='tekko', name='鉄骨職長',
        skin='#dfa668', skin_shadow='#bd843f', hair='#1d1a17',
        helmet='#46586a', helmet_dark='#33424f', stripe='#f2f3f5',
        jacket='#333c46', vest='#5d6d7d', shirt='#d5dbe0', tie=None,
        extra=['beard'],
    ),
    dict(
        id='doko', name='土工職長',
        skin='#dda15e', skin_shadow='#c07f3c', hair='#2a2320',
        helmet='#8b5a2b', helmet_dark='#6e4520', stripe='#f2f3f5',
        jacket='#6b5a41', vest='#b98a4a', shirt='#e5ddcb', tie=None,
        extra=['towel'],
    ),
    dict(
        id='kucho', name='空調職長',
        skin='#f6cfa4', skin_shadow='#e0a96e', hair='#33383f',
        helmet='#7ec8e3', helmet_dark='#57a5c4', stripe='#2b2b33',
        jacket='#4c6472', vest='#7ec8e3', shirt='#eef4f6', tie=None,
        extra=['pencil'], friendly=True,
    ),
    dict(
        id='naiso', name='内装職長',
        skin='#f8d2a8', skin_shadow='#e2aa70', hair='#54402c',
        helmet='#e08a3c', helmet_dark='#b96f2a', stripe='#f2f3f5',
        jacket='#7a5a44', vest='#e0a05a', shirt='#f2ede2', tie=None,
        extra=['smudge'],
    ),
    dict(
        id='gaiso', name='外装職長',
        skin='#eec39a', skin_shadow='#d29f63', hair='#2e2a28',
        helmet='#3d8b4f', helmet_dark='#2e6b3c', stripe='#f2f3f5',
        jacket='#46604e', vest='#69a86f', shirt='#e9f0e6', tie=None,
        extra=['glasses', 'smudge'],
    ),
    dict(
        id='ev', name='EV職長',
        skin='#f2c294', skin_shadow='#d69c5f', hair='#3c3a38',
        helmet='#b9bec6', helmet_dark='#9499a1', stripe='#2470c2',
        jacket='#3a4048', vest='#8b939e', shirt='#eef0f2', tie=None,
        extra=['glasses'],
    ),
    # ---- ステークホルダー7名（ポートレートは現場訪問時のヘルメット姿。近隣のみ帽子） ----
    dict(
        id='kanrisha', name='監理者',
        skin='#eec39a', skin_shadow='#d29f63', hair='#6a6a6e',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#2e3a5c',
        jacket='#333a45', vest='#59616e', shirt='#eef0f4', tie='#2e3a5c',
        extra=['glasses'], gray_brow=True,
    ),
    dict(
        id='seshu', name='施主担当',
        skin='#f8d8b4', skin_shadow='#e6b57e', hair='#7a4a2b',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#b0503c',
        jacket='#584a5e', vest='#7d6d84', shirt='#f4eef2', tie=None,
        extra=['longhair'],
    ),
    dict(
        id='sekkeisha', name='設計者',
        skin='#f4c69c', skin_shadow='#d89e66', hair='#26221f',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#2e7d5b',
        jacket='#36455c', vest='#5d6d84', shirt='#edf1f5', tie='#2e7d5b',
        extra=['glasses', 'pencil'],
    ),
    dict(
        id='honsha_anzen', name='本社・安全担当',
        skin='#eec39a', skin_shadow='#d29f63', hair='#2e2a28',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#2e7d32',
        jacket='#2f353f', vest='#3d8b4f', shirt='#eef0f2', tie='#a33327',
        extra=[], gray_brow=True,
    ),
    dict(
        id='honsha_genka', name='本社・原価担当',
        skin='#f2c294', skin_shadow='#d69c5f', hair='#211d1a',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#7a5a20',
        jacket='#4a3f35', vest='#6e6154', shirt='#f0ece4', tie='#5d1f24',
        extra=['glasses'],
    ),
    dict(
        id='kinrin', name='近隣代表',
        skin='#f6d3ac', skin_shadow='#e2af76', hair='#9a958e',
        helmet='#a34a5e', helmet_dark='#843c4c', stripe='#a34a5e',
        jacket='#7a5c6e', vest='#8d7180', shirt='#f2e9ec', tie=None,
        extra=['cap', 'longhair'], gray_brow=True,
    ),
    dict(
        id='dairinin', name='業者代理人',
        skin='#f6cfa4', skin_shadow='#e0a96e', hair='#2b2622',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#55606e',
        jacket='#3c4654', vest='#67707e', shirt='#eef0f2', tie='#55606e',
        extra=[], young=True, friendly=True,
    ),
    dict(
        id='senpai', name='先輩担当者',
        skin='#f8d6ac', skin_shadow='#e3aa72', hair='#4a3423',
        helmet='#f2f3f5', helmet_dark='#c9ccd4', stripe='#e07830',
        jacket='#37605a', vest='#7d9b94', shirt='#eef2f0', tie='#e07830',
        extra=[], young=True,
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
    rect(d, 1, 22, 2, 27, skin); rect(d, 45, 22, 46, 27, skin)   # 耳（肌はフラットに）
    haird = shade(hair)
    if 'longhair' in ch['extra']:
        side_h = 33
    else:
        side_h = 27 if ch.get('young') else 24
    # 横髪：外側の列に一段濃い影色（参考画風の髪の陰影）
    rect(d, 3, 12, 3, side_h, haird); rect(d, 4, 12, 4, side_h, hair)
    rect(d, 43, 12, 43, side_h, hair); rect(d, 44, 12, 44, side_h, haird)

    # ---- ヘルメット：やや見下ろし視点で天面を広く見せる。近隣代表だけは帽子 ----
    hel, held, stripe = C(ch['helmet']), C(ch['helmet_dark']), C(ch['stripe'])
    if 'cap' in ch['extra']:
        rect(d, 16, 3, 31, 3, hel)
        rect(d, 14, 4, 33, 4, hel)
        rect(d, 12, 5, 35, 5, hel)
        rect(d, 11, 6, 36, 7, hel)
        rect(d, 2, 8, 45, 9, hel)                  # 帽子のつば
        px(d, 2, 10, held); px(d, 45, 10, held)
    else:
        rect(d, 17, 1, 30, 1, hel)                 # 天面（広め）
        rect(d, 14, 2, 33, 2, hel)
        rect(d, 12, 3, 35, 3, hel)
        rect(d, 10, 4, 37, 4, hel)
        rect(d, 9, 5, 38, 8, hel)
        rect(d, 1, 9, 46, 10, hel)                 # つば（顔の上端）
        rect(d, 1, 11, 8, 11, held); rect(d, 39, 11, 46, 11, held)
        rect(d, 22, 1, 25, 8, stripe)
        for y in range(22, 37):                    # あご紐
            px(d, 6, y, C('#3c3f47')); px(d, 41, y, C('#3c3f47'))

    # ---- 眉：通常・笑顔では描かない。困り・怒りのときだけ小さく出す ----
    brow_col = C('#8f8f96') if ch.get('gray_brow') else C('#2e2a26')
    if expr == 'worried':                         # 内側が上がる小さい眉
        for (x, y) in [(12, 17), (13, 16), (14, 15), (15, 15),
                       (35, 17), (34, 16), (33, 15), (32, 15)]:
            px(d, x, y, brow_col)
    elif expr == 'angry':                          # 内側が下がる小さい眉
        for (x, y) in [(12, 14), (13, 15), (14, 16), (15, 17),
                       (35, 14), (34, 15), (33, 16), (32, 17)]:
            px(d, x, y, brow_col)

    # ---- 目：小さな縦バー（ハイライトなし）。口・鼻は描かない（ユーザー確定） ----
    # 顔の下半分に寄せて配置（やや見下ろし視点）
    def eye(cx, mode, side):
        if mode == 'smile':                        # 小さな ∩ 目
            for dx, dy in [(-3, 3), (-2, 1), (-1, 0), (0, 0), (1, 0), (2, 1), (3, 3)]:
                px(d, cx + dx, 20 + dy, INK)
        elif mode == 'worried':                    # 内寄りの小さいバー＋涙
            pin = -side
            rect(d, cx + pin - 1, 20, cx + pin, 23, INK)
            tear = C('#57a8d8')
            tx = cx + side * 5
            px(d, tx, 26, tear); px(d, tx, 27, tear)
        elif mode == 'angry':                      # 斜めの小さいバー
            for i in range(3):
                yy = 20 + (i if side < 0 else 2 - i)
                px(d, cx - 1 + i, yy, INK); px(d, cx - 1 + i, yy + 1, INK)
        else:                                      # 縦バー 3×5
            rect(d, cx - 1, 20, cx + 1, 24, INK)
    eye(15, expr, -1); eye(32, expr, +1)

    # ---- 個別の特徴（口・鼻は描かない）----
    if 'glasses' in ch['extra']:
        g = C('#26262c')
        d.rectangle([9, 17, 21, 27], outline=g)
        d.rectangle([26, 17, 38, 27], outline=g)
        rect(d, 22, 21, 25, 21, g)
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
    if 'beard' in ch['extra']:                     # 顎髭（頬下〜顎のライン。口は描かない）
        rect(d, 5, 30, 7, 36, hair); rect(d, 40, 30, 42, 36, hair)
        rect(d, 8, 34, 12, 36, hair); rect(d, 35, 34, 39, 36, hair)
        rect(d, 18, 35, 29, 35, hair); rect(d, 13, 36, 34, 36, hair)
    if 'smudge' in ch['extra']:                    # ボード粉・シーリング材などの汚れ跡（ベスト上）
        sm = C('#e9e6dd')
        px(d, 16, 41, sm); px(d, 17, 41, sm); px(d, 31, 45, sm); px(d, 15, 46, sm)

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
