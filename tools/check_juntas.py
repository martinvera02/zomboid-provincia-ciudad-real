"""Comprueba que ningún mapa pisa a otro y que cada enlace toca a sus dos pueblos
con su carretera sobre una calle del pueblo. Uso: python check_juntas.py <output> <layout.json>"""
import json, os, sys
from PIL import Image
import numpy as np
OUT, LAY = sys.argv[1], sys.argv[2]
L = json.load(open(LAY))
B = {n: (t['cell_x'], t['cell_y'], *t['cells']) for n, t in L['towns'].items()}
for e in sorted(os.listdir(OUT)):
    if e.startswith('Enlace_'):
        p = json.load(open(f'{OUT}/{e}/placement.json')); i = json.load(open(f'{OUT}/{e}/{e}_info.json'))
        B[e] = (p['cell_x'], p['cell_y'], i['cells_x'], i['cells_y'])
names = list(B); bad = 0
for i, a in enumerate(names):
    for b in names[i+1:]:
        ax, ay, aw, ah = B[a]; bx, by, bw, bh = B[b]
        if ax < bx+bw and bx < ax+aw and ay < by+bh and by < ay+ah:
            print('SOLAPE', a, b); bad += 1
print(f'{len(B)} mapas, {bad} solapes')
img = lambda n: np.array(Image.open(f'{OUT}/{n}/{n}_road_hierarchy.bmp'))
problems = 0
for e in [n for n in names if n.startswith('Enlace_')]:
    lx, ly, lw, lh = B[e]; R = img(e); found = []
    for t in [n for n in names if not n.startswith('Enlace_')]:
        tx, ty, tw, th = B[t]; T = img(t)
        if lx == tx+tw and ly < ty+th and ty < ly+lh:
            ys = range(max(ly, ty)*300, min(ly+lh, ty+th)*300); lr = R[[y-ly*300 for y in ys], 0]; tr = T[[y-ty*300 for y in ys], -40:].max(1)
        elif lx+lw == tx and ly < ty+th and ty < ly+lh:
            ys = range(max(ly, ty)*300, min(ly+lh, ty+th)*300); lr = R[[y-ly*300 for y in ys], -1]; tr = T[[y-ty*300 for y in ys], :40].max(1)
        elif ly == ty+th and lx < tx+tw and tx < lx+lw:
            xs = range(max(lx, tx)*300, min(lx+lw, tx+tw)*300); lr = R[0, [x-lx*300 for x in xs]]; tr = T[-40:, [x-tx*300 for x in xs]].max(0)
        elif ly+lh == ty and lx < tx+tw and tx < lx+lw:
            xs = range(max(lx, tx)*300, min(lx+lw, tx+tw)*300); lr = R[-1, [x-lx*300 for x in xs]]; tr = T[:40, [x-tx*300 for x in xs]].max(0)
        else:
            continue
        on = np.where(lr > 0)[0]
        if len(on):
            found.append((t, (tr[on] >= 3).mean()))
    ends = e[len('Enlace_'):]
    want = [t for t in L['towns'] if ends.startswith(t + '_') or ends.endswith('_' + t)]
    got = {t: f for t, f in found}
    status = 'ok' if all(t in got and got[t] >= 0.5 for t in want) else 'MAL'
    problems += status != 'ok'
    print(f"{status:3s} {e:48s} " + "  ".join(f"{t}: {got[t]:.0%}" if t in got else f"{t}: NO TOCA" for t in want))
print('juntas con problema:', problems)
