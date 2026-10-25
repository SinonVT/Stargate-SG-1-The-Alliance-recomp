#!/usr/bin/env python3
"""SG-1 HD texture pack builder.
The game uploads reduced copies of its textures; the original, larger art is still inside Textures\\*.utx.
This tool finds, for every texture the game can upload, the biggest original (up to <max_size>, default 1024)
and writes it as a PNG into <texpack>\\hd plus a lookup file <texpack>\\index.txt that the game reads.

usage:  python make_hdpack.py <game dir> <texpack dir> [max_size=1024]
   e.g. python make_hdpack.py "C:\\SG-1 The_Alliance" "out\\build\\release\\texpack"
needs:  Python 3, numpy, Pillow  (pip install numpy pillow). Takes a few minutes; safe to run again (it resumes).
        A C compiler (gcc/cc/clang/zig cc) makes it faster; without one a slower pure-Python hash is used.
Only your own game files are read. Nothing from the game is stored in the repository.
"""
import sys,os,re,glob,mmap,ctypes,struct,collections
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import utx
ALL=True; av=[a for a in sys.argv if a!='--all']
gdir,tp=av[1],av[2]; CAP=int(av[3]) if len(av)>3 else 1024
def _load_hash():
    here=os.path.dirname(os.path.abspath(__file__)); ext='.dll' if os.name=='nt' else '.so'
    path=os.path.join(here,'libhdhash'+ext)
    if not os.path.exists(path):
        import subprocess,shutil
        for cc in (['gcc'],['cc'],['clang'],['zig','cc']):
            if shutil.which(cc[0]):
                try:
                    subprocess.run(cc+['-O2','-shared','-o',path,os.path.join(here,'hdhash.c')]+([] if os.name=='nt' else ['-fPIC']),check=True,capture_output=True)
                    break
                except Exception: pass
    try:
        lib=ctypes.CDLL(path); lib.hd_hash.restype=ctypes.c_uint64; lib.hd_hash.argtypes=[ctypes.c_char_p,ctypes.c_size_t]
        return lib.hd_hash
    except Exception:
        print('no C compiler found - using the slow pure-Python hash (several minutes)')
        M=(1<<64)-1
        def py(buf,n):
            h=1469598103934665603; mv=memoryview(buf); k=n//8*8
            for (w,) in struct.iter_unpack('<Q',mv[:k]):
                h=((h^w)*1099511628211)&M; h^=h>>29
            for c in bytes(mv[k:n]): h=((h^c)*1099511628211)&M
            return h
        return py
hd_hash=_load_hash()
class lib: hd_hash=staticmethod(hd_hash)
RT={3:0x0C,7:0x0E,8:0x0F,5:0x06}   # UE2 ETextureFormat -> NV2A colour format
def mipparse(d,names,e):
    pr,end=utx.props(d,e['off'],names)
    r=utx.R(d,end); n=r.ci(); out=[]
    for i in range(n):
        r.u32(); cnt=r.ci(); o=r.p; r.p+=cnt
        u=r.i32(); v=r.i32(); r.u8(); r.u8()
        out.append((u,v,o,cnt))
    return pr,out
def swizzle(bgra,w,h):
    # Morton swizzle for power-of-two textures (Xbox); returns bytes
    if w&(w-1) or h&(h-1): return None
    a=np.frombuffer(bgra,dtype='<u4').reshape(h,w)
    ys,xs=np.mgrid[0:h,0:w]
    def spread(v,bits):
        out=np.zeros_like(v)
        for b in range(bits): out|=((v>>b)&1)<<(2*b)
        return out
    m=min(w,h); bits=m.bit_length()-1
    if w==h: idx=spread(xs,bits)|(spread(ys,bits)<<1)
    else:
        idx=spread(xs&(m-1),bits)|(spread(ys&(m-1),bits)<<1)
        if w>h: idx=idx|((xs>>bits)<<(2*bits))
        else: idx=idx|((ys>>bits)<<(2*bits))
    out=np.empty(w*h,dtype='<u4'); out[idx.ravel()]=a.ravel()
    return out.tobytes()
def decode(buf,fmt,u,v):
    if fmt in(3,7,8):
        bw,bh=(u+3)//4,(v+3)//4; bs=8 if fmt==3 else 16
        a=np.frombuffer(buf,dtype=np.uint8,count=bw*bh*bs).reshape(bw*bh,bs)
        off=0 if fmt==3 else 8
        c=a[:,off:off+4].copy().view('<u2').reshape(-1,2).astype(np.int32); c0,c1=c[:,0],c[:,1]
        rgb=lambda x:np.stack([((x>>11)&31)*255//31,((x>>5)&63)*255//63,(x&31)*255//31],1)
        p0,p1=rgb(c0),rgb(c1)
        pal=np.zeros((len(a),4,3),np.int32); pal[:,0]=p0; pal[:,1]=p1
        four=(c0>c1) if fmt==3 else np.ones(len(a),bool)
        pal[:,2]=np.where(four[:,None],(2*p0+p1)//3,(p0+p1)//2)
        pal[:,3]=np.where(four[:,None],(p0+2*p1)//3,0)
        idx=a[:,off+4:off+8].copy().view('<u4').reshape(-1)
        ix=(idx[:,None]>>(np.arange(16)*2)[None,:])&3
        px=np.take_along_axis(pal,ix[:,:,None],1)
        al=np.full((len(a),16),255,np.int32)
        if fmt==3: al=np.where((~four[:,None])&(ix==3),0,255); px=np.where(((~four[:,None])&(ix==3))[:,:,None],0,px)
        elif fmt==7:
            ab=a[:,0:8].copy().view('<u8').reshape(-1)
            al=((ab[:,None]>>(np.arange(16)*4)[None,:].astype(np.uint64))&np.uint64(15)).astype(np.int32)*17
        else:
            a0,a1=a[:,0].astype(np.int32),a[:,1].astype(np.int32)
            bits=np.zeros(len(a),np.uint64)
            for i in range(6): bits|=a[:,2+i].astype(np.uint64)<<np.uint64(8*i)
            ai=((bits[:,None]>>(np.arange(16)*3)[None,:].astype(np.uint64))&np.uint64(7)).astype(np.int32)
            tab=np.zeros((len(a),8),np.int32); tab[:,0]=a0; tab[:,1]=a1
            g=(a0>a1)
            for k in range(1,7): tab[:,k+1]=np.where(g,((7-k)*a0+k*a1)//7,0)
            for k in range(1,5): tab[:,k+1]=np.where(g,tab[:,k+1],((5-k)*a0+k*a1)//5)
            tab[:,6]=np.where(g,tab[:,6],0); tab[:,7]=np.where(g,tab[:,7],255)
            al=np.take_along_axis(tab,ai,1)
        img=np.concatenate([px,al[:,:,None]],2).reshape(bh,bw,4,4,4).transpose(0,2,1,3,4).reshape(bh*4,bw*4,4)
        return img[:v,:u].astype(np.uint8)
    if fmt==5:
        a=np.frombuffer(buf,dtype=np.uint8,count=u*v*4).reshape(v,u,4)
        return np.stack([a[:,:,2],a[:,:,1],a[:,:,0],a[:,:,3]],2)
    return None
def sig(img):
    h,w=img.shape[:2]; s=min(8,w,h)
    return img[:h//s*s,:w//s*s,:3].reshape(s,h//s,s,w//s,3).mean((1,3)).astype(np.float32).ravel()
# ---- index every texture in every package
print('indexing packages...')
tex=[]   # dict(pkg,name,fmt,mips,mm)
byhash={}
for fn in sorted(glob.glob(os.path.join(gdir,'Textures','*.utx'))):
    f=open(fn,'rb'); mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
    d=mm  # mmap supports slicing/struct
    try: _,names,imps,exps,ver=utx.load(fn)
    except Exception as ex: print('skip',fn,ex); continue
    for e in exps:
        if utx.clsname(e['cls'],names,imps,exps)!='Texture': continue
        try: pr,ms=mipparse(mm,names,e)
        except Exception: continue
        fmt=pr.get('Format')
        if fmt not in RT or not isinstance(fmt,int): continue
        T=dict(pkg=os.path.basename(fn),name=e['name'],fmt=fmt,mips=ms,mm=mm)
        tex.append(T)
        for lvl,(u,v,o,cnt) in enumerate(ms):
            if u<16 or v<16: continue
            raw=mm[o:o+cnt]
            if fmt==5:
                raw=swizzle(raw,u,v)
                if raw is None: continue
            h=lib.hd_hash(raw,len(raw))
            byhash.setdefault((RT[fmt],u,v,h),[]).append((T,lvl))
print(len(tex),'textures,',len(byhash),'mip hashes')
byname=collections.defaultdict(list)
for T in tex: byname[T['name'].lower()].append(T)

sigcache={}
def getsig(T,l):
    k=(id(T),l)
    if k not in sigcache:
        u,v,o,cnt=T['mips'][l]
        im=decode(T['mm'][o:o+cnt],T['fmt'],u,v)
        sigcache[k]=sig(im) if im is not None else None
    return sigcache[k]
def find_best(T0,lvl0):
    u,v=T0['mips'][lvl0][0],T0['mips'][lvl0][1]
    cands=[(T0,l) for l in range(lvl0)]
    for T in byname[T0['name'].lower()]:
        if T is T0 or T['fmt'] not in(3,5,7,8): continue
        for l in range(len(T['mips'])): cands.append((T,l))
    cands=[c for c in cands if c[0]['mips'][c[1]][0]<=CAP and c[0]['mips'][c[1]][1]<=CAP and c[0]['mips'][c[1]][0]*c[0]['mips'][c[1]][1]>u*v and c[0]['mips'][c[1]][0]*v==c[0]['mips'][c[1]][1]*u]
    cands.sort(key=lambda c:-c[0]['mips'][c[1]][0]*c[0]['mips'][c[1]][1])
    s0=None
    for T,l in cands:
        if T is T0: return T,l
        if s0 is None: s0=getsig(T0,lvl0)
        sc=getsig(T,l)
        if s0 is None or sc is None: continue
        # compare at the lower resolution: candidate signature is resolution independent (8x8 mean)
        if np.abs(sc-s0).mean()<=14: return T,l
    return None
def safe(s): return re.sub(r'[^A-Za-z0-9_.-]','_',s)
stats=collections.Counter(); rep=[]; written={}; index=[]
def emit(code,u,v,h,T,l):
    cu,cv,o,cnt=T['mips'][l]
    fn='%s__%s__%dx%d.png'%(safe(os.path.splitext(T['pkg'])[0]),safe(T['name']),cu,cv)
    if fn not in written:
        out=os.path.join(tp,'hd',fn)
        if not os.path.exists(out):
            img=decode(T['mm'][o:o+cnt],T['fmt'],cu,cv)
            Image.fromarray(img,'RGBA').save(out,compress_level=1)
        written[fn]=1; stats['png']+=1
    index.append('f%02X_%dx%d_%016X hd/%s'%(code,u,v,h,fn))
if ALL:
    import json,time
    t0=time.time(); BUDGET=float(os.environ.get('HD_BUDGET','1e9'))
    os.makedirs(os.path.join(tp,'hd'),exist_ok=True)
    pf=os.path.join(tp,'progress.json')
    done=json.load(open(pf)) if os.path.exists(pf) else {}
    tmap={(T['pkg'],T['name']):T for T in tex}
    todo=0; finished=True
    for (code,u,v,h),hits in byhash.items():
        key='%02X_%d_%d_%016X'%(code,u,v,h)
        if key not in done:
            if time.time()-t0>BUDGET: finished=False; break
            T0,l0=hits[0]
            b=find_best(T0,l0)
            if b:
                cu,cv,o,cnt=b[0]['mips'][b[1]]
                emit(code,u,v,h,b[0],b[1])
                done[key]=index[-1].split(' ',1)[1]
            else: done[key]=None
    json.dump(done,open(pf,'w'))
    if not finished:
        print('PARTIAL',len(done),'of',len(byhash)); sys.exit(2)
    lines=['f%s_%sx%s_%s %s'%(k.split('_')[0],k.split('_')[1],k.split('_')[2],k.split('_')[3],v) for k,v in done.items() if v]
    open(os.path.join(tp,'index.txt'),'w').write('\n'.join(sorted(lines))+'\n')
    print('DONE',len(lines),'ids,',len(set(v for v in done.values() if v)),'images'); sys.exit(0)
