import struct,sys
class R:
    def __init__(s,d,p=0): s.d=d; s.p=p
    def u8(s): v=s.d[s.p]; s.p+=1; return v
    def i32(s): v=struct.unpack_from('<i',s.d,s.p)[0]; s.p+=4; return v
    def u32(s): v=struct.unpack_from('<I',s.d,s.p)[0]; s.p+=4; return v
    def u16(s): v=struct.unpack_from('<H',s.d,s.p)[0]; s.p+=2; return v
    def ci(s):
        b=s.u8(); neg=b&0x80; v=b&0x3f
        if b&0x40:
            sh=6
            while True:
                b=s.u8(); v|=(b&0x7f)<<sh; sh+=7
                if not b&0x80: break
        return -v if neg else v
    def fstr(s):
        n=s.ci()
        if n<0: n=-n; v=s.d[s.p:s.p+n*2].decode('utf-16le','replace'); s.p+=n*2
        else: v=s.d[s.p:s.p+n].decode('latin1'); s.p+=n
        return v.rstrip('\0')
def load(fn):
    d=open(fn,'rb').read()
    tag,ver,lic,flags,nc,no,ec,eo,ic,io=struct.unpack('<IHHIIIIIII',d[:36])
    r=R(d,no); names=[]
    for i in range(nc): names.append(r.fstr()); r.u32()
    r=R(d,io); imps=[]
    for i in range(ic):
        pk=r.ci(); cl=r.ci(); g=r.i32(); nm=r.ci(); imps.append((names[pk],names[cl],names[nm]))
    r=R(d,eo); exps=[]
    for i in range(ec):
        cls=r.ci(); sup=r.ci(); grp=r.i32(); nm=r.ci(); fl=r.u32(); sz=r.ci(); off=r.ci() if sz>0 else 0
        exps.append(dict(cls=cls,name=names[nm],size=sz,off=off,grp=grp))
    return d,names,imps,exps,ver
def clsname(c,names,imps,exps):
    if c<0: return imps[-c-1][2]
    if c>0: return exps[c-1]['name']
    return 'Class'
def props(d,off,names):
    r=R(d,off); out={}
    while True:
        n=names[r.ci()]
        if n=='None': break
        info=r.u8(); t=info&15; sc=(info>>4)&7; arr=info&0x80
        if t==10: r.ci()
        sz=[1,2,4,12,16][sc] if sc<5 else (r.u8() if sc==5 else r.u16() if sc==6 else r.u32())
        if arr and t!=3:
            b=r.u8()
            if b>=0xC0: r.p+=3
            elif b>=0x80: r.p+=1
        val=d[r.p:r.p+(0 if t==3 else sz)]
        if t==3: val=bool(info&0x80)
        elif t==1 and sz==1: val=val[0]
        elif t==2 and sz==4: val=struct.unpack('<i',val)[0]
        elif t==5 and sz==4: val=struct.unpack('<I',val)[0]
        elif t==9 and False: pass
        out[n]=val
        r.p+=0 if t==3 else sz
    return out,r.p
if __name__=='__main__':
    for fn in sys.argv[1:]:
        d,names,imps,exps,ver=load(fn)
        for e in exps:
            c=clsname(e['cls'],names,imps,exps)
            if c in('Texture','Cubemap','TexEnvMap'):
                try: pr,end=props(d,e['off'],names)
                except Exception as ex: pr={'err':str(ex)};end=0
                print(fn,e['name'],c,e['size'],{k:v for k,v in pr.items() if k in('Format','USize','VSize','UClamp','VClamp','bMasked','bAlphaTexture','MipZero','bHasComp','bTwoSided','InternalTime') or True} if len(pr)<12 else pr)
