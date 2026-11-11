#!/usr/bin/env python3
"""年齢帯で目を分けるサンプル（ユーザー指摘 2026-11-08「おじさんの顔がキラキラしてたらキモい」）
- おじさん組：ハイライトなしの落ち着いた目（目・眉の組み合わせシステム）＋頬なし
- 若手・女性組：愛嬌のあるキラキラ目＋薄い頬
出力: sheets/eye_age_groups.png
"""
from PIL import Image, ImageDraw, ImageFont
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_portraits import CHARS, C
from gen_eye_samples import draw_sample
from gen_eye_charming import draw_face

OUT = os.path.dirname(os.path.abspath(__file__))

OLDER = [   # (id, 目の形, 眉の向き, 眉の形)
    ('kacho', 'tsuri', 'up', 'thick'),
    ('shocho', 'ito', 'flat', 'maro'),
    ('tobi', 'jito', 'up', 'thick2thin'),
    ('kanrisha', 'round', 'flat', 'thick'),
    ('tekko', 'tsuri', 'flat', 'thick'),
]
YOUNG = [   # (id, 愛嬌スタイル)
    ('hero', 'A'), ('denki', 'D'), ('eisei', 'C'),
    ('seshu', 'B'), ('senpai', 'D'), ('kinrin', 'C'),
]

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
    pad, cell, lab_h, head_h = 12, 48 * 4, 36, 44
    cols = max(len(OLDER), len(YOUNG))
    W = cell * cols + pad * (cols + 1)
    H = head_h * 2 + (cell + lab_h) * 2 + pad * 3
    sheet = Image.new('RGB', (W, H), C('#f4f1ea'))
    d = ImageDraw.Draw(sheet)
    f, f2 = load_font(28), load_font(24)
    y = pad
    if f: d.text((pad, y), 'おじさん組（キラキラなし・落ち着いた目と眉）', font=f, fill=C('#2b2b33'))
    y += head_h
    for j, (cid, ek, bd, bs) in enumerate(OLDER):
        ch = by_id[cid]
        x = pad + j * (cell + pad)
        spr = draw_sample(ch, ek, bd, bs).resize((cell, cell), Image.NEAREST)
        sheet.paste(spr, (x, y), spr)
        if f2: d.text((x + cell // 2, y + cell + 4), ch['name'], font=f2, fill=C('#2b2b33'), anchor='ma')
    y += cell + lab_h + pad
    if f: d.text((pad, y), '若手・女性組（愛嬌のあるキラキラ目）', font=f, fill=C('#2b2b33'))
    y += head_h
    for j, (cid, st) in enumerate(YOUNG):
        ch = by_id[cid]
        x = pad + j * (cell + pad)
        spr = draw_face(ch, st).resize((cell, cell), Image.NEAREST)
        sheet.paste(spr, (x, y), spr)
        if f2: d.text((x + cell // 2, y + cell + 4), f"{ch['name']}（{st}）", font=f2, fill=C('#2b2b33'), anchor='ma')
    sheet.save(os.path.join(OUT, 'sheets', 'eye_age_groups.png'))
    print('age-group eye samples generated')

if __name__ == '__main__':
    main()
