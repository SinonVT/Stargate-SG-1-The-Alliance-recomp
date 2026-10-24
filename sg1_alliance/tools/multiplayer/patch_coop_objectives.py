"""EXPERIMENTAL: the host's in-game OBJECTIVES tab was empty in the co-op campaign while the joining player saw the objectives.

ObjectivesPanel builds its full objective list (MyCompleteData) only once, when the panel object is created. A panel that is created (or kept)
before / across a level load, as happens on a listen-server host (e.g. after a restart), keeps pointing at objective actors that no longer exist.
InGameInfoPanel.Update (called every time the info screen opens) now rebuilds that list from the live MissionObjective actors first:
    Objectives.MyCompleteData.Remove(0, Objectives.MyCompleteData.Length);
    foreach PC.DynamicActors(class'Actor', obj) { Mo = MissionObjective(obj);
        if (Mo != None) Objectives.AddObjective(Mo, Mo.ParentObjective != None);   <- new
        ...existing UpdateActive/UpdateDone... }
Only System\\StargateMenus.u changes (same size; new body placed in the unused ScriptText buffer of InGameInfoPanel).

Usage:  python patch_coop_objectives.py "<game folder>"            apply (backup System\\StargateMenus.u.orig_coopobj)
        python patch_coop_objectives.py "<game folder>" --revert   restore the backup
"""
import sys, os, shutil, struct

# ---------------------------------------------------------------- package helpers
def read_ci(d, o):
    b = d[o]; o += 1
    neg = b & 0x80; v = b & 0x3F
    if b & 0x40:
        sh = 6
        while True:
            b = d[o]; o += 1
            v |= (b & 0x7F) << sh; sh += 7
            if not b & 0x80: break
    return (-v if neg else v), o

def write_ci(v):
    neg = v < 0; v = abs(v)
    b = (0x80 if neg else 0) | (v & 0x3F); v >>= 6
    out = bytearray()
    if v:
        b |= 0x40; out.append(b)
        while True:
            c = v & 0x7F; v >>= 7
            if v: c |= 0x80
            out.append(c)
            if not v: break
    else:
        out.append(b)
    return bytes(out)

class Pkg:
    def __init__(self, d):
        self.d = d
        tag, ver, lic, flags, nn, no, ne, eo, ni, io = struct.unpack_from('<IHHIIIIIII', d, 0)
        if tag != 0x9E2A83C1: raise SystemExit('not an Unreal package')
        self.eo = eo
        self.names = []; o = no
        for _ in range(nn):
            l, o = read_ci(d, o); self.names.append(d[o:o + l - 1].decode('latin1')); o += l + 4
        self.imports = []; o = io
        for _ in range(ni):
            cp, o = read_ci(d, o); cn, o = read_ci(d, o); pk = struct.unpack_from('<i', d, o)[0]; o += 4; on, o = read_ci(d, o)
            self.imports.append((self.names[cn], pk, self.names[on]))
        self.ex = []; o = eo
        for _ in range(ne):
            s = o
            cls, o = read_ci(d, o); sup, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
            nm, o = read_ci(d, o); o += 4; szp = o; sz, o = read_ci(d, o); offp = o; off = 0
            if sz > 0: off, o = read_ci(d, o)
            self.ex.append(dict(cls=cls, outer=outer, name=self.names[nm], size=sz, off=off, szp=szp, offp=offp, end=o))
    def clsname(self, e):
        c = e['cls']
        return self.imports[-c - 1][2] if c < 0 else (self.ex[c - 1]['name'] if c > 0 else 'Class')

# ---------------------------------------------------------------- bytecode walker (validated against 3259 of 3273 functions of StargateGame.u)
class Bad(Exception): pass

def tok(d, p, fix):
    """Walk one expression/statement. Returns (memory size, next position). fix collects (position of a jump-target word)."""
    op = d[p]; p += 1; m = 1
    def ci():
        nonlocal p
        _, p = read_ci(d, p)
    def ex():
        nonlocal p, m
        a, p = tok(d, p, fix); m += a
    def params():
        nonlocal p, m
        while True:
            if d[p] == 0x16: p += 1; m += 1; return
            ex()
    if op in (0, 1, 2, 3, 0x20, 0x29): ci(); m += 4
    elif op == 4: ex()
    elif op == 5: p += 1; m += 1; ex()
    elif op == 6: fix.append(p); p += 2; m += 2
    elif op == 7: fix.append(p); p += 2; m += 2; ex()
    elif op in (8, 0x0b, 0x17, 0x25, 0x26, 0x27, 0x28, 0x2a, 0x30, 0x31, 0x15, 0x16, 0x47): pass
    elif op == 9: p += 3; m += 3; ex()
    elif op == 0x0a:
        w = struct.unpack_from('<H', d, p)[0]; fix.append(p); p += 2; m += 2
        if w != 0xffff: ex()
    elif op == 0x0c: raise Bad('label table')
    elif op in (0x0d, 0x0e, 0x2d, 0x37): ex()
    elif op in (0x0f, 0x10, 0x14, 0x1a, 0x46): ex(); ex()
    elif op == 0x11: ex(); ex(); ex(); ex()
    elif op in (0x12, 0x19): ex(); p += 3; m += 3; ex()
    elif op == 0x13: ci(); m += 4; ex()
    elif op == 0x18: p += 2; m += 2; ex()
    elif op in (0x1b, 0x38): ci(); m += 4; params()
    elif op == 0x1c: ci(); m += 4; params()
    elif op in (0x1d, 0x1e): p += 4; m += 4
    elif op == 0x1f:
        while d[p] != 0: p += 1; m += 1
        p += 1; m += 1
    elif op == 0x21: ci(); m += 4
    elif op in (0x22, 0x23): p += 12; m += 12
    elif op in (0x24, 0x2c): p += 1; m += 1
    elif op == 0x2e: ci(); m += 4; ex()
    elif op == 0x2f: ex(); fix.append(p); p += 2; m += 2
    elif op in (0x32, 0x33): ci(); m += 4; ex(); ex()
    elif op == 0x34:
        while d[p:p + 2] != b'\0\0': p += 2; m += 2
        p += 2; m += 2
    elif op == 0x36: ci(); m += 4; ex()
    elif op == 0x39: p += 1; m += 1; ex()
    elif op in (0x40, 0x41): ex(); ex(); ex()
    elif op >= 0x60:
        if op < 0x70: p += 1; m += 1
        params()
    else: raise Bad('unknown opcode %02x' % op)
    return m, p

def memlen(b):
    p = 0; m = 0
    while p < len(b):
        a, p = tok(b, p, []); m += a
    return m

def locate_script(d, off, size):
    """Returns (position of the ScriptSize int, script start, script size (memory), script end)."""
    blob = d[off:off + size]
    for q in range(4, min(60, len(blob) - 8)):
        sz = struct.unpack_from('<i', blob, q)[0]
        if not 2 < sz < 40000: continue
        p = off + q + 4; m = 0
        try:
            while m < sz:
                a, p = tok(d, p, []); m += a
        except Exception:
            continue
        if m == sz and d[p - 1] == 0x47: return off + q, off + q + 4, sz, p
    raise SystemExit('script not found')


# ---------------------------------------------------------------- the patch
def fit(v, n):
    b = bytearray(write_ci(v))
    if len(b) > n: sys.exit('table entry would change length')
    while len(b) < n:                               # redundant continuation byte: same value, longer encoding
        b[-1] |= (0x40 if len(b) == 1 else 0x80); b.append(0)
    return bytes(b)

def statements(script, fix):
    out = []; p = 0
    while True:
        s = p; a, p = tok(script, p, fix); out.append((s, a))
        if script[s] == 0x47: return out



def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateMenus.u'); bak = f + '.orig_coopobj'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    P = Pkg(bytes(d))
    def top(name):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == 0 and P.clsname(e) == 'Class']
        if len(r) != 1: sys.exit('class %s not found' % name)
        return r[0]
    def member(name, outer):
        r = [i + 1 for i, x in enumerate(P.ex) if x['name'] == name and x['outer'] == outer]
        if len(r) != 1: sys.exit('%s not found' % name)
        return r[0]
    c_info = top('InGameInfoPanel'); c_obj = top('ObjectivesPanel')
    fi = [i for i, e in enumerate(P.ex) if e['name'] == 'Update' and e['outer'] == c_info and e['size']]
    if len(fi) != 1: sys.exit('InGameInfoPanel.Update not found')
    e = P.ex[fi[0]]
    r_mo = member('Mo', fi[0] + 1); r_objs = member('Objectives', c_info); r_mcd = member('MyCompleteData', c_obj)
    r_parent = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == 'ObjectProperty' and im[2] == 'ParentObjective' and P.imports[-im[1] - 1][2] == 'MissionObjective']
    if len(r_parent) != 1: sys.exit('MissionObjective.ParentObjective import not found')
    r_parent = r_parent[0]
    if 'AddObjective' not in P.names: sys.exit('name AddObjective missing')
    n_add = P.names.index('AddObjective')
    tb = [i for i, x in enumerate(P.ex) if x['name'] == 'ScriptText' and x['outer'] == c_info and x['size']]
    if len(tb) != 1: sys.exit('ScriptText of InGameInfoPanel not found')
    text = P.ex[tb[0]]
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
    script = bytes(d[st0:en])
    L = lambda r: b'\x00' + write_ci(r)
    I = lambda r: b'\x01' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    if b'\x1b' + write_ci(n_add) in script: print('already patched'); return
    stm0 = []; fix0 = []; stm0 = statements(script, fix0)
    # statement indexes: 0 objectiveIdx=0, 1 PC=..., 2 jumpifnot, 3 return, 4 foreach, 5 Mo=cast, 6 jumpifnot(...)
    if len(stm0) < 8 or script[stm0[4][0]] != 0x2f or script[stm0[5][0]] != 0x0f or script[stm0[6][0]] != 0x07: sys.exit('InGameInfoPanel.Update has an unexpected layout')
    def memat(stm, idx): return sum(a for s, a in stm[:idx])
    # new statements
    A = b'\x41' + ctx(I(r_objs), I(r_mcd), 0) + b'\x25' + ctx(I(r_objs), b'\x37' + I(r_mcd), 4)             # Objectives.MyCompleteData.Remove(0, Length)
    PAR = b'\x77' + ctx(L(r_mo), I(r_parent), 4) + b'\x2a\x16'                              # Mo.ParentObjective != None
    CALL = ctx(I(r_objs), b'\x1b' + write_ci(n_add) + L(r_mo) + PAR + b'\x16', 0)            # Objectives.AddObjective(Mo, ...)
    B = b'\x07' + struct.pack('<H', 0) + b'\x77' + L(r_mo) + b'\x2a\x16' + CALL              # if (Mo != None) ...  (target patched below)
    if os.environ.get('OBJDBG'):
        LG = lambda t: b'\xe7\x1f' + t + b'\x00\x16'
        A = A + LG(b'OBJDBG update start'); B = B + LG(b'OBJDBG add')
    def insert(sc, bytepos, mempos, new, strict):
        fix = []; statements(sc, fix); sc = bytearray(sc); g = memlen(new)
        for fp in fix:
            t = struct.unpack_from('<H', sc, fp)[0]
            if t != 0xffff and (t > mempos if strict else t >= mempos): struct.pack_into('<H', sc, fp, t + g)
        return bytes(sc[:bytepos]) + new + bytes(sc[bytepos:])
    # B first (later position), its own jump skips the call: target = mem after B
    mB = memat(stm0, 6); mA = memat(stm0, 4)
    B = b'\x07' + struct.pack('<H', mB + memlen(B)) + B[3:]
    sc = insert(script, stm0[6][0], mB, B, False)
    # A: targets equal to mA (the early-return jump lands on the foreach) now land on A, which is fine
    stm1 = statements(sc, []); 
    sc = insert(sc, stm1[4][0], mA, A, True)
    # B's own target must be corrected for A (it was inside the shifted range): done by insert() since it is a jump word in sc
    newscr = sc
    blob = bytes(d[e['off']:e['off'] + e['size']])
    q = szp - e['off']; s0_ = st0 - e['off']; e0_ = en - e['off']
    nblob = blob[:q] + struct.pack('<i', memlen(newscr)) + blob[q + 4:s0_] + newscr + blob[e0_:]
    cur = text['off'] + 1024
    if cur + len(nblob) > text['off'] + text['size']: sys.exit('source-text buffer too small')
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    szc = fit(len(nblob), e['offp'] - e['szp']); offc = fit(cur, e['end'] - e['offp'])
    d[cur:cur + len(nblob)] = nblob
    d[e['szp']:e['offp']] = szc; d[e['offp']:e['end']] = offc
    P2 = Pkg(bytes(d)); e2 = P2.ex[fi[0]]
    assert e2['off'] == cur and e2['size'] == len(nblob) and len(d) == os.path.getsize(f)
    a, b, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
    assert c_ == memlen(newscr)
    open(f, 'wb').write(bytes(d))
    print('patched: the info screen now rebuilds the objectives list every time it opens')

main()
