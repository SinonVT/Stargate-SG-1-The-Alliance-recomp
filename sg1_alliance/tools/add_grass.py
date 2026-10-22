#!/usr/bin/env python3
"""Add a DecoLayers (grass) layer to every TerrainInfo of an Xbox SG-1 .unr map.
usage: add_grass.py in.unr out.unr [--mesh M02_deco_grass_03_clamp] [--layers 1,2]
       [--dens 0.15] [--maxperquad 32] [--fade 3000,5000] [--scale 1.0,1.0]"""
import sys,struct,argparse
ap=argparse.ArgumentParser()
ap.add_argument('inp');ap.add_argument('out')
ap.add_argument('--mesh',default='M02_deco_grass_03_clamp')
ap.add_argument('--like',default='M02_deco_plant_01_clamp',help='existing StaticMesh import to copy package/class from')
ap.add_argument('--layers',default='1,2');ap.add_argument('--dens',type=float,default=0.15)
ap.add_argument('--maxperquad',type=int,default=32);ap.add_argument('--fade',default='3000,5000')
ap.add_argument('--alpha',action='store_true',help='one deco layer per --layers entry, DensityMap = that terrain layer AlphaMap')
ap.add_argument('--scale',default='1.0,1.0');ap.add_argument('--extent',type=float,default=150.0)
a=ap.parse_args()
d=open(a.inp,'rb').read()
class R:
    def __init__(s,d,p=0):s.d=d;s.p=p
    def u8(s):v=s.d[s.p];s.p+=1;return v
    def u32(s):v=struct.unpack_from('<I',s.d,s.p)[0];s.p+=4;return v
    def i32(s):v=struct.unpack_from('<i',s.d,s.p)[0];s.p+=4;return v
    def ci(s):
        b=s.u8();neg=b&0x80;v=b&0x3f
        if b&0x40:
            sh=6
            while True:
                b=s.u8();v|=(b&0x7f)<<sh;sh+=7
                if not b&0x80:break
        return -v if neg else v
def enc_ci(v):
    neg=v<0;n=abs(v);b=(0x80 if neg else 0)|(n&0x3f);n>>=6
    out=[]
    if n:b|=0x40
    out.append(b)
    while n:
        c=n&0x7f;n>>=7
        if n:c|=0x80
        out.append(c)
    return bytes(out)
tag,ver,lic,flags,nc,no,ec,eo,ic,io=struct.unpack('<IHHIIIIIII',d[:36])
HDR=d[:68]
# names
r=R(d,no);names=[];nflags=[]
for i in range(nc):
    n=r.ci()
    if n<0:
        n=-n;s=d[r.p:r.p+n*2].decode('utf-16le');r.p+=n*2
    else:
        s=d[r.p:r.p+n].decode('latin1');r.p+=n
    names.append(s.rstrip('\0'));nflags.append(r.u32())
# imports (raw ints)
r=R(d,io);imps=[]
for i in range(ic):
    imps.append([r.ci(),r.ci(),r.i32(),r.ci()])
# exports
r=R(d,eo);exps=[]
for i in range(ec):
    e=dict(cls=r.ci(),sup=r.ci(),grp=r.i32(),nm=r.ci(),fl=r.u32(),sz=r.ci());e['off']=r.ci() if e['sz']>0 else 0
    exps.append(e)
def clsname(c):
    if c<0:return names[imps[-c-1][3]]
    if c>0:return names[exps[c-1]['nm']]
    return 'Class'
newnames=list(names);newflags=list(nflags)
std_flags=max(set(nflags),key=nflags.count)
def N(s):
    if s in newnames:return newnames.index(s)
    newnames.append(s);newflags.append(std_flags);return len(newnames)-1
# new import
like=[i for i,x in enumerate(imps) if names[x[3]]==a.like]
if not like:sys.exit('import %s not found'%a.like)
if a.mesh in names and any(names[x[3]]==a.mesh for x in imps):
    mesh_idx=[i for i,x in enumerate(imps) if names[x[3]]==a.mesh][0]
    newimps=[list(x) for x in imps]
else:
    newimps=[list(x) for x in imps]
    t=list(imps[like[0]]);t[3]=N(a.mesh);newimps.append(t);mesh_idx=len(newimps)-1
mesh_ref=-(mesh_idx+1)
# struct property encoders
def tag_(name,typ,payload,sname=None,arr=None):
    b=enc_ci(N(name));n=len(payload)
    sc={1:0,2:1,4:2,12:3,16:4}.get(n)
    if sc is None:sc=5 if n<256 else (6 if n<65536 else 7)
    b+=bytes([typ|(sc<<4)])
    if typ==10:b+=enc_ci(N(sname))
    if sc==5:b+=bytes([n])
    elif sc==6:b+=struct.pack('<H',n)
    elif sc==7:b+=struct.pack('<I',n)
    return b+payload
NONE=enc_ci(N('None'))
def fl(name,v):return tag_(name,4,struct.pack('<f',v))
def rng(lo,hi):return fl('Min',lo)+fl('Max',hi)+NONE
def rangep(name,lo,hi):return tag_(name,10,rng(lo,hi),'Range')
sx,sy=[float(x) for x in a.scale.split(',')]
rv=tag_('X',10,rng(sx,sx),'Range')+tag_('Y',10,rng(sx,sx),'Range')+tag_('Z',10,rng(sy,sy),'Range')+NONE
f0,f1=[float(x) for x in a.fade.split(',')]
mask=0
for l in a.layers.split(','):mask|=1<<int(l)
def build_layer(mask,dens_ref=None):
    return (tag_('ShowOnTerrain',2,struct.pack('<i',mask))
     +(tag_('DensityMap',5,enc_ci(dens_ref)) if dens_ref else b'')
     +tag_('StaticMesh',5,enc_ci(mesh_ref))
     +rangep('FadeoutRadius',f0,f1)
     +tag_('ScaleMultiplier',10,rv,'RangeVector')
     +rangep('MeshExtents',a.extent,a.extent)
     +rangep('DensityMultiplier',a.dens,a.dens)
     +tag_('MaxPerQuad',2,struct.pack('<i',a.maxperquad))
     +tag_('RandomYaw',2,struct.pack('<i',1))
     +NONE)
newprop=tag_('DecoLayers',9,enc_ci(1)+build_layer(mask))
# patch every TerrainInfo
blobs=[];patch={}
for idx,e in enumerate(exps):
    if e['sz']<=0 or clsname(e['cls'])!='TerrainInfo':continue
    f=e['fl'];r=R(d,e['off'])
    if f&0x02000000:
        n=r.ci();r.ci();r.p+=12
        if n:r.ci()
    last_end=None;has=False;layers=[]
    while True:
        nm=names[r.ci()]
        if nm=='None':break
        info=r.u8();t=info&15;sc=(info>>4)&7;arr=info&0x80
        if t==10:r.ci()
        sz=[1,2,4,12,16][sc] if sc<5 else (r.u8() if sc==5 else struct.unpack_from('<H',d,r.p)[0] if sc==6 else struct.unpack_from('<I',d,r.p)[0])
        if sc==6:r.p+=2
        elif sc==7:r.p+=4
        if arr and t!=3:
            b=r.u8()
            if b>=0xC0:r.p+=3
            elif b>=0x80:r.p+=1
        vstart=r.p
        if t!=3:r.p+=sz
        if nm=='DecoLayers':has=True
        if nm=='Layers':
            last_end=r.p
            ii=len(layers);layers.append(d[vstart:vstart+sz])
    if has:print('  %s already has DecoLayers, skipped'%e['name']);continue
    if a.alpha:
        items=[]
        for l in [int(x) for x in a.layers.split(',')]:
            lb=layers[l];rr=R(lb,0);am=None
            while True:
                nm2=names[rr.ci()]
                if nm2=='None':break
                inf=rr.u8();t2=inf&15;sc2=(inf>>4)&7
                if t2==10:rr.ci()
                sz2=[1,2,4,12,16][sc2] if sc2<5 else (rr.u8() if sc2==5 else 0)
                if t2==3:continue
                if nm2=='AlphaMap':am=R(lb,rr.p).ci()
                rr.p+=sz2
            if not am:print('  no alphamap for layer',l);continue
            items.append(build_layer(1,am))
        pv=enc_ci(len(items))+b''.join(items)
        np_=tag_('DecoLayers',9,pv)
    else:
        np_=newprop
    blob=d[e['off']:last_end]+np_+d[last_end:e['off']+e['sz']]
    patch[idx]=blob
print('terrains patched:',len(patch),' new prop bytes:',len(newprop),' mesh import #%d (%s)'%(mesh_idx+1,a.mesh))
out=bytearray(d)
while len(out)%16:out.append(0)
def put_names():
    b=bytearray()
    for s,f in zip(newnames,newflags):
        z=s.encode('latin1')+b'\0'
        b+=enc_ci(len(z))+z+struct.pack('<I',f)
    return bytes(b)
nt=put_names();new_no=len(out);out+=nt
new_io=len(out)
for x in newimps:out+=enc_ci(x[0])+enc_ci(x[1])+struct.pack('<i',x[2])+enc_ci(x[3])
for idx,blob in patch.items():
    exps[idx]['off']=len(out);exps[idx]['sz']=len(blob);out+=blob
new_eo=len(out)
for e in exps:
    out+=enc_ci(e['cls'])+enc_ci(e['sup'])+struct.pack('<i',e['grp'])+enc_ci(e['nm'])+struct.pack('<I',e['fl'])+enc_ci(e['sz'])
    if e['sz']>0:out+=enc_ci(e['off'])
hdr=bytearray(out[:68])
struct.pack_into('<IHHIIIIIII',hdr,0,tag,ver,lic,flags,len(newnames),new_no,ec,new_eo,len(newimps),new_io)
# generation entry (export count, name count)
gen=struct.unpack_from('<I',hdr,52)[0]
if gen==1:struct.pack_into('<II',hdr,56,ec,len(newnames))
out[:68]=hdr
open(a.out,'wb').write(out)
print('wrote',a.out,len(out),'bytes; names',len(names),'->',len(newnames))
