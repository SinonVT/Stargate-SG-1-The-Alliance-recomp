"""Client fixes 3 (needs clientfx2): (1) after a downed pawn is revived the client never played an idle animation again, so the revived host kept
lying on the floor: PlayerTick now notes downed remote pawns in StargatePawn.bRevived (unused on clients, only pawns without a Controller) and calls
PlayWaiting() once when bBeingUnconscious ends. (2) the revive/hack progress bar stayed on screen when the trigger was destroyed mid-update: a client
hides it every frame unless the controller is in state UsingProgressTrigger or Hacking.
Works on System\\StargateGame.u.orig_coopmplog if it exists (then re-run patch_coop_mplog.py), else on System\\StargateGame.u.
Usage:  python patch_coop_clientfx3.py "<game folder>"  [--revert]
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




# ---- token walker that records (byte position, memory position, opcode) of every token and checks skip / context words
def walk(d, p, base, rec, bad):
    op = d[p]; start = p; p += 1; m = 1
    rec.append((start, base, op))
    def ci():
        nonlocal p
        _, p = read_ci(d, p)
    def ex():
        nonlocal p, m
        a, p = walk(d, p, base + m, rec, bad); m += a
        return a
    def params():
        nonlocal p, m
        while True:
            if d[p] == 0x16: p += 1; m += 1; return
            ex()
    if op in (0, 1, 2, 3, 0x20, 0x29): ci(); m += 4
    elif op == 4: ex()
    elif op == 5: p += 1; m += 1; ex()
    elif op == 6: p += 2; m += 2
    elif op == 7: p += 2; m += 2; ex()
    elif op in (8, 0x0b, 0x17, 0x25, 0x26, 0x27, 0x28, 0x2a, 0x30, 0x31, 0x15, 0x16, 0x47): pass
    elif op == 9: p += 3; m += 3; ex()
    elif op == 0x0a:
        w = struct.unpack_from('<H', d, p)[0]; p += 2; m += 2
        if w != 0xffff: ex()
    elif op in (0x0d, 0x0e, 0x2d, 0x37): ex()
    elif op in (0x0f, 0x10, 0x14, 0x1a, 0x46): ex(); ex()
    elif op == 0x11: ex(); ex(); ex(); ex()
    elif op in (0x12, 0x19):
        ex(); w = struct.unpack_from('<H', d, p)[0]; p += 3; m += 3; a = ex()
        if w != a: bad.append(('ctx', start, w, a))
    elif op == 0x13: ci(); m += 4; ex()
    elif op == 0x18:
        w = struct.unpack_from('<H', d, p)[0]; p += 2; m += 2; a = ex()
        if w != a + 1: bad.append(('skip', start, w, a))
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
    elif op == 0x2f: ex(); p += 2; m += 2
    elif op in (0x32, 0x33): ci(); m += 4; ex(); ex()
    elif op == 0x36: ci(); m += 4; ex()
    elif op == 0x39: p += 1; m += 1; ex()
    elif op in (0x40, 0x41): ex(); ex(); ex()
    elif op >= 0x60:
        if op < 0x70: p += 1; m += 1
        params()
    else: raise Bad('unknown opcode %02x' % op)
    return m, p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    sysdir = os.path.join(args[0], 'System')
    f = os.path.join(sysdir, 'StargateGame.u')
    base = f + '.orig_coopmplog'
    if os.path.exists(base): f = base          # work on the pre-logging file, then re-run patch_coop_mplog.py
    bak = f + '.orig_coopfx3'
    exp_out = None
    if '--in' in sys.argv:                     # experiment: --in <file> --out <file>, game folder untouched
        f = sys.argv[sys.argv.index('--in') + 1]; exp_out = sys.argv[sys.argv.index('--out') + 1]
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    if exp_out is None:
        if os.path.exists(bak): sys.exit('already applied to this file (use --revert first)')
        shutil.copyfile(f, bak)
    d = bytearray(open(f, 'rb').read()); P = Pkg(bytes(d))
    def top(name):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == 0 and P.clsname(e) == 'Class']
        if len(r) != 1: sys.exit('class %s not found' % name)
        return r[0]
    c_pawn = top('StargatePawn'); c_player = top('StargatePlayer')
    fn = [i for i, e in enumerate(P.ex) if e['name'] == 'PlayerTick' and e['outer'] == c_player and e['size']][0]
    e = P.ex[fn]
    loc = [i + 1 for i, x in enumerate(P.ex) if x['name'] == 'SGP' and x['outer'] == fn + 1]
    if len(loc) != 1: sys.exit('local SGP not found')
    def member(name):
        r = [i + 1 for i, x in enumerate(P.ex) if x['name'] == name and x['outer'] == c_pawn]
        if len(r) != 1: sys.exit('%s not found' % name)
        return r[0]
    def imp(cls, name, owner):
        r = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name and P.imports[-im[1] - 1][2] == owner]
        if len(r) != 1: sys.exit('import %s not found' % name)
        return r[0]
    def nm(n):
        if n not in P.names: sys.exit('name %s missing' % n)
        return P.names.index(n)
    r_unc = member('bBeingUnconscious'); r_rev = member('bRevived')
    r_role = imp('ByteProperty', 'Role', 'Actor'); r_ctl = imp('ObjectProperty', 'Controller', 'Pawn')
    I = lambda r: b'\x01' + write_ci(r)
    L = lambda r: b'\x00' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    def AND(a, b): return b'\x82' + a + b'\x18' + struct.pack('<H', memlen(b) + 1) + b + b'\x16'
    NOT = lambda a: b'\x81' + a + b'\x16'
    SGP = L(loc[0])
    enum = b'\x61\x39' + b'\x20' + write_ci(c_pawn) + SGP + b'\x16'
    UNC = ctx(SGP, b'\x2d' + I(r_unc), 4)
    REV = ctx(SGP, b'\x2d' + I(r_rev), 4)
    CTLNONE = b'\x72' + ctx(SGP, I(r_ctl), 4) + b'\x2a\x16'
    SETREV = lambda v: b'\x14' + ctx(SGP, b'\x2d' + I(r_rev), 4) + (b'\x27' if v else b'\x28')
    r_stop = imp('Function', 'StopAnimating', 'Actor')
    # revive on a client: clear every leftover animation channel (the lie-down anim), then run the same local state restore the server's
    # AnimEnd_Revived does (Physics walking, bPhysicsAnimUpdate, bIgnoreForces, collision, ChangeAnimation to restart the movement channels)
    CALL = (ctx(SGP, b'\x1c' + write_ci(r_stop) + b'\x27\x16', 0)
            + ctx(SGP, b'\x1b' + write_ci(nm('AnimEnd_Revived')) + b'\x16', 0))
    ROLENE = b'\x9b\x39\x3a' + I(r_role) + b'\x39\x3a\x24\x04\x16'
    C1 = AND(UNC, CTLNONE); S1 = SETREV(True)
    C2 = AND(AND(NOT(UNC), REV), CTLNONE); S2 = SETREV(False) + CALL
    GSN = b'\x61\x1c\x16'
    ne = lambda n: b'\xff' + GSN + b'\x21' + write_ci(nm(n)) + b'\x16'
    C3 = AND(ne('UsingProgressTrigger'), ne('Hacking')); S3 = b'\x1b' + write_ci(nm('HideProgressBar')) + b'\x16'
    p = 3 + memlen(ROLENE)
    p1 = p + 1 + memlen(enum) + 2
    sz1 = 3 + memlen(C1) + memlen(S1); p2 = p1 + sz1
    sz2 = 3 + memlen(C2) + memlen(S2); pos_next = p2 + sz2
    pos_pop = pos_next + 1; p3 = pos_pop + 1
    sz3 = 3 + memlen(C3) + memlen(S3); end = p3 + sz3
    new = (b'\x07' + struct.pack('<H', end) + ROLENE + b'\x2f' + enum + struct.pack('<H', pos_pop)
           + b'\x07' + struct.pack('<H', p2) + C1 + S1
           + b'\x07' + struct.pack('<H', pos_next) + C2 + S2
           + b'\x31\x30'
           + b'\x07' + struct.pack('<H', end) + C3 + S3)
    assert memlen(new) == end, (memlen(new), end)
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
    script = bytes(d[st0:en]); fix = []; statements(script, fix); sc = bytearray(script)
    for fp in fix:
        t = struct.unpack_from('<H', sc, fp)[0]
        if t != 0xffff: struct.pack_into('<H', sc, fp, t + end)
    newscr = new + bytes(sc)
    blob = bytes(d[e['off']:e['off'] + e['size']])
    q = szp - e['off']; s0_ = st0 - e['off']; e0_ = en - e['off']
    nblob = blob[:q] + struct.pack('<i', memlen(newscr)) + blob[q + 4:s0_] + newscr + blob[e0_:]
    nszsz = e['offp'] - e['szp']; noffsz = e['end'] - e['offp']
    if len(nblob) > (1 << (6 + 7 * (nszsz - 1))) - 1: sys.exit('size field too small')
    cap = (1 << (6 + 7 * (noffsz - 1))) - 1
    cur = None
    for x in P.ex:
        if x['name'] == 'ScriptText' and x['size'] > 200:
            live = max([y['off'] + y['size'] for y in P.ex if y['size'] and x['off'] <= y['off'] < x['off'] + x['size'] and y is not x] + [x['off'] + 64])
            a = (live + 15) & ~15
            if a + len(nblob) <= x['off'] + x['size'] and a + len(nblob) <= cap: cur = a; break
    if cur is None: sys.exit('no free space')
    d[cur:cur + len(nblob)] = nblob
    d[e['szp']:e['offp']] = fit(len(nblob), nszsz); d[e['offp']:e['end']] = fit(cur, noffsz)
    P2 = Pkg(bytes(d)); e2 = P2.ex[fn]
    a_, b_, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
    scr = bytes(d[b_:e_]); rec = []; bad = []; pp = 0; mp = 0
    while pp < len(scr):
        aa, pp = walk(scr, pp, mp, rec, bad); mp += aa
    if bad or mp != c_: sys.exit('verification failed: %r' % (bad[:2],))
    open(exp_out or f, 'wb').write(bytes(d))
    print('patched PlayerTick on', os.path.basename(f), '->', exp_out or f)

main()
