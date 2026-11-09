"""Revisa todos los bordes compartidos entre mapas generados: dónde llega una
carretera al borde de un mapa, el de al lado tiene que tener carretera ahí
(en una franja de 40 tiles por si una calle del pueblo acaba un poco antes).
Uso: python check_bordes.py <knox/output> [mapas a ignorar...]"""
import json, os, sys
import numpy as np
from PIL import Image
OUT = sys.argv[1]
B = {}
for e in sorted(os.listdir(OUT)):
    try:
        p = json.load(open(f'{OUT}/{e}/placement.json')); i = json.load(open(f'{OUT}/{e}/{e}_info.json'))
        B[e] = (p['cell_x'], p['cell_y'], i['cells_x'], i['cells_y'])
    except Exception:
        pass
img = {}
def R(n):
    if n not in img: img[n] = np.array(Image.open(f'{OUT}/{n}/{n}_road_hierarchy.bmp'))
    return img[n]
def runs(v):
    out=[]; s=None
    for i,x in enumerate(list(v)+[0]):
        if x and s is None: s=i
        if not x and s is not None: out.append((s,i-1)); s=None
    return out
names=list(B); bad=0; n_j=0
over=0
for i,a in enumerate(names):
    for b in names[i+1:]:
        ax,ay,aw,ah=B[a]; bx,by,bw,bh=B[b]
        if ax<bx+bw and bx<ax+aw and ay<by+bh and by<ay+ah: print('SOLAPE',a,b); over+=1
        for A,Bn in ((a,b),(b,a)):
            ax,ay,aw,ah=B[A]; bx,by,bw,bh=B[Bn]
            if ax+aw==bx and ay<by+bh and by<ay+ah:      # A a la izquierda de B
                lo,hi=max(ay,by)*300,min(ay+ah,by+bh)*300
                ra=R(A)[lo-ay*300:hi-ay*300,-40:]; rb=R(Bn)[lo-by*300:hi-by*300,:40]
                ea=R(A)[lo-ay*300:hi-ay*300,-1]>=3; eb=R(Bn)[lo-by*300:hi-by*300,0]>=3
                ba=(ra>=3).any(1); bb=(rb>=3).any(1)
            elif ay+ah==by and ax<bx+bw and bx<ax+aw:    # A encima de B
                lo,hi=max(ax,bx)*300,min(ax+aw,bx+bw)*300
                ra=R(A)[-40:,lo-ax*300:hi-ax*300]; rb=R(Bn)[:40,lo-bx*300:hi-bx*300]
                ea=R(A)[-1,lo-ax*300:hi-ax*300]>=3; eb=R(Bn)[0,lo-bx*300:hi-bx*300]>=3
                ba=(ra>=3).any(0); bb=(rb>=3).any(0)
            else:
                continue
            # cada carretera que toca el borde por un lado debe tener carretera enfrente
            for side,e,other,on in ((A,ea,bb,Bn),(Bn,eb,ba,A)):
                for s,t in runs(e):
                    n_j+=1
                    if not other[s:t+1].any():
                        bad+=1
                        print(f'CORTE: carretera de {side} llega al borde con {on} ({t-s+1} tiles) y al otro lado no hay nada')
print(f'{len(B)} mapas, {over} solapes, {n_j} cruces de borde revisados, {bad} cortes')
