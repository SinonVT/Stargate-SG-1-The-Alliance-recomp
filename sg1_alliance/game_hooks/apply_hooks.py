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
            h=[]; i+=1
            while i<len(lines) and not lines[i].startswith('@@') and not lines[i].startswith('--- '):
                if lines[i]=='': h.append(' ')
                elif lines[i][0] in ' +-': h.append(lines[i])
                elif lines[i].startswith('\\'): pass
                i+=1
            while h and h[-1]==' ': h.pop()
            cur[1].append(h); continue
        i+=1
    return out
def find(src,seq,start=0):
    n=len(seq)
    for k in range(len(src)-n+1):
        if src[k:k+n]==seq: return k
    return -1
bad=0
for pf in sorted(glob.glob(os.path.join(here,'*.patch'))):
    for name,hunks in parse(open(pf,encoding='utf-8',errors='replace').read()):
        path=os.path.join(gen,name)
        if not os.path.exists(path): print('MISSING  %s (generate it first)'%path); bad+=1; continue
        raw=open(path,'rb').read(); crlf=b'\r\n' in raw
        src=raw.decode('utf-8','replace').replace('\r\n','\n').split('\n')
        changed=False; res=[]
        for h in hunks:
            old=[x[1:] for x in h if x[0] in ' -']; new=[x[1:] for x in h if x[0] in ' +']
            if find(src,new)>=0 and old!=new: res.append('already'); continue
            k=find(src,old)
            if k<0: res.append('FAILED'); bad+=1; continue
            src[k:k+len(old)]=new; changed=True; res.append('applied')
        print('%-28s %-34s %s'%(os.path.basename(pf),name,', '.join(res)))
        if changed and not check:
            open(path+'.orig_sg1','wb').write(raw) if not os.path.exists(path+'.orig_sg1') else None
            data='\n'.join(src)
            if crlf: data=data.replace('\n','\r\n')
            open(path,'wb').write(data.encode('utf-8'))
sys.exit(1 if bad else 0)
