#!/usr/bin/env python3
"""Applies our small patches to the GENERATED recompiled code (src/recomp/gen/recomp_XXXX.c).
Needs nothing but Python 3 (no 'patch' tool). Safe to run twice: hunks that are already applied are skipped.

    python game_hooks/apply_hooks.py              (run from the sg1_alliance folder)
    python game_hooks/apply_hooks.py --check      (only report the state)
    python game_hooks/apply_hooks.py --gen PATH   (generated folder, default src/recomp/gen)
"""
import os,re,sys,glob
here=os.path.dirname(os.path.abspath(__file__))
args=sys.argv[1:]; check='--check' in args
gen=os.path.join(os.path.dirname(here),'src','recomp','gen')
if '--gen' in args: gen=args[args.index('--gen')+1]
def parse(text):
    """-> [(target basename, [hunk lines])]"""
    out=[]; cur=None; lines=text.replace('\r\n','\n').split('\n'); i=0
    while i<len(lines):
        l=lines[i]
        if l.startswith('+++ '):
            name=l[4:].split('\t')[0].strip()
            name=re.sub(r'\.bak_\w+$','',os.path.basename(name.replace('\\','/')))
            cur=(name,[]); out.append(cur)
        elif l.startswith('@@') and cur is not None:
            skip=l.startswith('@@ -1,'); h=[]; i+=1
            while i<len(lines) and not lines[i].startswith('@@') and not lines[i].startswith('--- '):
                if lines[i]=='': h.append(' ')
                elif lines[i][0] in ' +-': h.append(lines[i])
                elif lines[i].startswith('\\'): pass
                i+=1
            while h and h[-1]==' ': h.pop()
            if not skip: cur[1].append(h)
            continue
        i+=1
    return out
def find(src,seq,start=0):
    n=len(seq)
    for k in range(len(src)-n+1):
        if src[k:k+n]==seq: return k
    return -1
bad=0
# The recompiler numbers its output files by position, so on another machine a function can land in a different
# recomp_XXXX.c than on ours. Targets are therefore found by CONTENT: the named file is tried first, then all others.
INC='#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n'
def load(path):
    raw=open(path,'rb').read(); crlf=b'\r\n' in raw
    return raw,crlf,raw.decode('utf-8','replace').replace('\r\n','\n').split('\n')
def save(path,raw,crlf,src):
    if not os.path.exists(path+'.orig_sg1'): open(path+'.orig_sg1','wb').write(raw)
    if not any('#include <stdio.h>' in l for l in src[:40]): src=INC.split('\n')[:-1]+src
    data='\n'.join(src)
    if crlf: data=data.replace('\n','\r\n')
    open(path,'wb').write(data.encode('utf-8'))
allfiles=sorted(glob.glob(os.path.join(gen,'recomp_*.c')))
cache={}
def get(path):
    if path not in cache: cache[path]=load(path)
    return cache[path]
def state(src,h):
    old=[x[1:] for x in h if x[0] in ' -']; new=[x[1:] for x in h if x[0] in ' +']
    if old!=new and find(src,new)>=0: return 'already'
    return 'todo' if find(src,old)>=0 else 'no'
def locate(name,hunks):
    cands=[os.path.join(gen,name)]+[f for f in allfiles if os.path.basename(f)!=name]
    for c in cands:
        if not os.path.exists(c): continue
        src=get(c)[2]
        if all(state(src,h)!='no' for h in hunks): return c
    return None
XNET="004191CF,004191DA,004191E5,004191F0,004191FB,00419212,00419229,00419234,0041924E,00419259,00419264,0041926F,0041927A,00419285,00419294,004192A3,004192AE,004192B9,004192C4,004192CF,004192DA,00419303,0041931D,0041932C,00419346,0041938F,004195A0,004195B7,00419735,0041973A,0041A135,0041A292,0041A29B".split(",")
def xnet_rule():
    global bad
    want=set(XNET); tot_n=0; tot_had=0; found=0
    for path in allfiles:
        raw,crlf,src=get(path)
        if not any(re.match(r'^loc_(%s): ;$'%'|'.join(XNET),l) for l in src): continue
        out=[]; n=0; had=0
        for i,l in enumerate(src):
            out.append(l)
            m=re.match(r'^loc_([0-9A-F]{8}): ;$',l)
            if m and m.group(1) in want:
                found+=1
                if i+1<len(src) and 'sg_xnet_hle' in src[i+1]: had+=1
                else:
                    out.append('    { extern int sg_xnet_hle(uint32_t); int hn = sg_xnet_hle(0x%sU); if (hn >= 0) { esp += 4u + (uint32_t)hn; return; } }'%m.group(1)); n+=1
        tot_n+=n; tot_had+=had
        if n and not check: save(path,raw,crlf,out); cache.pop(path,None)
    print('%-34s %-18s %s'%('(xnet rule)','all files','applied %d, already %d (of %d entry points)'%(tot_n,tot_had,len(XNET))))
    if found<len(XNET): print('  WARNING: only %d of %d XNet entry points found'%(found,len(XNET))); bad+=1
xnet_rule()
for pf in sorted(glob.glob(os.path.join(here,'*.patch'))):
    for name,hunks in parse(open(pf,encoding='utf-8',errors='replace').read()):
        hunks=[h for h in hunks if h]
        path=locate(name,hunks)
        if not path: print('%-34s %-18s FAILED (code to patch not found; was the generator run with --all --split 250?)'%(os.path.basename(pf),name)); bad+=1; continue
        raw,crlf,src=get(path); res=[]; changed=False
        for h in hunks:
            st=state(src,h)
            if st=='already': res.append('already'); continue
            old=[x[1:] for x in h if x[0] in ' -']; new=[x[1:] for x in h if x[0] in ' +']
            k=find(src,old); src[k:k+len(old)]=new; changed=True; res.append('applied')
        print('%-34s %-18s %s'%(os.path.basename(pf),os.path.basename(path),', '.join(res)))
        if changed and not check: save(path,raw,crlf,src); cache.pop(path,None)
sys.exit(1 if bad else 0)
