"""Approximate the dataviz validator: OKLab distances under normal vision and CVD simulation (Machado 2009, severity 1)."""
import sys, itertools
import numpy as np
def hex2rgb(h): h=h.lstrip('#'); return np.array([int(h[i:i+2],16)/255 for i in (0,2,4)])
def lin(c): return np.where(c<=0.04045, c/12.92, ((c+0.055)/1.055)**2.4)
def oklab(rgb):
    r,g,b=lin(rgb)
    l=0.4122214708*r+0.5363325363*g+0.0514459929*b
    m=0.2119034982*r+0.6806995451*g+0.1073969566*b
    s=0.0883024619*r+0.2817188376*g+0.6299787005*b
    l,m,s=np.cbrt(l),np.cbrt(m),np.cbrt(s)
    return np.array([0.2104542553*l+0.7936177850*m-0.0040720468*s,
                     1.9779984951*l-2.4285922050*m+0.4505937099*s,
                     0.0259040371*l+0.7827717662*m-0.8086757660*s])
M={'protan':np.array([[0.152286,1.052583,-0.204868],[0.114503,0.786281,0.099216],[-0.003882,-0.048116,1.051998]]),
   'deutan':np.array([[0.367322,0.860646,-0.227968],[0.280085,0.672501,0.047413],[-0.011820,0.042940,0.968881]]),
   'tritan':np.array([[1.255528,-0.076749,-0.178779],[-0.078411,0.930809,0.147602],[0.004733,0.691367,0.303900]])}
def sim(rgb,kind):
    l=lin(rgb); out=M[kind]@l; out=np.clip(out,0,1)
    return np.where(out<=0.0031308, 12.92*out, 1.055*out**(1/2.4)-0.055)
cols=sys.argv[1].split(',')
labs={c:oklab(hex2rgb(c)) for c in cols}
print('lightness L*:',{c:round(float(labs[c][0]*100),1) for c in cols})
print('chroma:',{c:round(float(np.hypot(*labs[c][1:])*100),1) for c in cols})
worst=[]
for a,b in itertools.combinations(cols,2):
    dn=np.linalg.norm(labs[a]-labs[b])*100
    dc=min(np.linalg.norm(oklab(sim(hex2rgb(a),k))-oklab(sim(hex2rgb(b),k)))*100 for k in M)
    flag='' if dc>=8 and dn>=15 else ('  <-- FAIL' if (dc<6 or dn<15) else '  <-- weak')
    print(f'{a} vs {b}: normal {dn:5.1f}  cvd-min {dc:5.1f}{flag}')
