#!/usr/bin/env python3
"""Extracts the UnrealScript source text that is stored inside the game's script packages.

usage: python extract_scripts.py <game dir> <output dir>
Writes <output dir>\<Package>\<Class>.uc for every class in System\*.u.
This is the game's own source code: keep the output for your own reading, do not publish it.
"""
import sys,os,glob,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import utx
gdir,out=sys.argv[1],sys.argv[2]; tot=0
for f in sorted(glob.glob(os.path.join(gdir,'System','*.u'))):
    pkg=os.path.basename(f)[:-2]
    d,names,imps,exps,ver=utx.load(f)
    os.makedirs(os.path.join(out,pkg),exist_ok=True)
    for e in exps:
        if utx.clsname(e['cls'],names,imps,exps)!='TextBuffer' or not e['size']: continue
        raw=bytes(d[e['off']:e['off']+e['size']])
        for k in range(24):                      # the text is a compact-index length + bytes that end the object
            try: r=utx.R(raw,k); n=r.ci()
            except Exception: continue
            if n>0 and r.p+n==len(raw):
                owner=exps[e['grp']-1]['name'] if e['grp']>0 else 'unknown'
                open(os.path.join(out,pkg,re.sub(r'[^A-Za-z0-9_.-]','_',owner)+'.uc'),'w',encoding='utf-8',newline='').write(raw[r.p:r.p+n].rstrip(b'\0').decode('latin1'))
                tot+=1; break
print('extracted',tot,'scripts')
