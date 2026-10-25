"""Client fix 5: other players' look up/down without new imports or names (the client rejects any change to the name/import tables).
Host/server side (Role==Authority): for every StargatePawn controlled by this PlayerController, StargatePawn.Energy (an existing replicated float
that nothing else reads) = float(Rotation.Pitch + 100000).  Client side (Role!=Authority): every StargatePawn that is not downed, has no Controller
and Energy > 1: KnockDesiredRot.<axis> = int(Energy) - 100000 (KnockDesiredRot is a server-only rotator), then SetBoneRotation('Bip01 Spine1', KnockDesiredRot, 0, alpha).
Options: --axis pitch|yaw|roll (rotator member the bone bends around, default pitch)  --neg (negate)  --alpha 0.6
         --in <file> --out <file>  (experiment mode, does not touch the game folder)
Works on System\\StargateGame.u.orig_coopmplog if it exists (then re-run patch_coop_mplog.py). Backup <file>.orig_coopfx5.
Usage:  python patch_coop_clientfx5.py "<game folder>"  [--axis ..] [--neg] [--alpha x] [--revert]
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
    def opt(n, dflt=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else dflt
    axis = opt('--axis', 'pitch'); alpha = float(opt('--alpha', '1.0')); neg = '--neg' in sys.argv
    exp = '--in' in sys.argv
    if not args and not exp: sys.exit(__doc__)
    if exp:
        f = opt('--in'); out_path = opt('--out'); bak = None
    else:
        f = os.path.join(args[0], 'System', 'StargateGame.u')
        base = f + '.orig_coopmplog'
        if os.path.exists(base): f = base
        bak = f + '.orig_coopfx5'; out_path = f
        if '--revert' in sys.argv:
            if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
            shutil.copyfile(bak, f); print('reverted'); return
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
        if len(r) != 1: sys.exit('import %s.%s not found (%d)' % (owner, name, len(r)))
        return r[0]
    def nm(n):
        if n not in P.names: sys.exit('name %s missing' % n)
        return P.names.index(n)
    r_unc = member('bBeingUnconscious'); r_energy = member('Energy'); r_kdr = member('KnockDesiredRot')
    r_role = imp('ByteProperty', 'Role', 'Actor'); r_ctl = imp('ObjectProperty', 'Controller', 'Pawn')
    r_rot = imp('StructProperty', 'Rotation', 'Actor')
    r_ax = {k: [-(i + 1) for i, im in enumerate(P.imports) if im[0] == 'IntProperty' and im[2] == k.capitalize() and P.imports[-im[1] - 1][2] == 'Rotator'] for k in ('pitch', 'yaw', 'roll')}
    for k, v in r_ax.items():
        if len(v) != 1: sys.exit('Rotator.%s import not unique: %r' % (k, v))
    r_pitch = r_ax['pitch'][0]; r_axis = r_ax[axis][0]
    r_sbr = imp('Function', 'SetBoneRotation', 'Actor')
    r_lvl = imp('ObjectProperty', 'Level', 'Actor'); r_nm = imp('ByteProperty', 'NetMode', 'LevelInfo')
    r_sb2 = imp('NameProperty', 'SpineBone2', 'Pawn')
    r_lta = imp('ObjectProperty', 'LookTargetActor', 'Pawn')
    both = '--one-bone' not in sys.argv
    I = lambda r: b'\x01' + write_ci(r)
    L = lambda r: b'\x00' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    def AND(a, b): return b'\x82' + a + b'\x18' + struct.pack('<H', memlen(b) + 1) + b + b'\x16'
    NOT = lambda a: b'\x81' + a + b'\x16'
    IC = lambda v: b'\x1d' + struct.pack('<i', v)
    FC = lambda v: b'\x1e' + struct.pack('<f', v)
    SGP = L(loc[0])
    enum = b'\x61\x39' + b'\x20' + write_ci(c_pawn) + SGP + b'\x16'
    ROLE = b'\x39\x3a' + I(r_role); FOUR = b'\x39\x3a\x24\x04'
    ROLEEQ = b'\x9a' + ROLE + FOUR + b'\x16'
    NETNE = b'\x9b\x39\x3a' + b'\x19' + I(r_lvl) + struct.pack('<H', memlen(I(r_nm))) + b'\x01' + I(r_nm) + b'\x39\x3a\x24\x00\x16'   # Level.NetMode != NM_Standalone: single player never runs the host block
    ROLENE = b'\x9b' + ROLE + FOUR + b'\x16'
    UNC = ctx(SGP, b'\x2d' + I(r_unc), 4)
    CTLNONE = b'\x72' + ctx(SGP, I(r_ctl), 4) + b'\x2a\x16'
    CTLSELF = b'\x72' + ctx(SGP, I(r_ctl), 4) + b'\x17\x16'
    ENERGY = ctx(SGP, I(r_energy), 4)
    ENERGYGT = b'\xb1' + ENERGY + FC(1.0) + b'\x16'
    # host: SGP.Energy = float(Rotation.Pitch + 100000)
    PITCH = b'\x36' + write_ci(r_pitch) + I(r_rot)
    S_host = b'\x0f' + ctx(SGP, I(r_energy), 4) + b'\x39\x3f' + b'\x92' + b'\x9c' + b'\x92' + PITCH + IC(32768) + b'\x16' + IC(65535) + b'\x16' + IC(67232) + b'\x16'
    # client: SGP.KnockDesiredRot.<axis> = int(SGP.Energy) - 100000   (negated with --neg)
    KSC = float(opt('--k', '0.35'))
    NATIVE = '--native' in sys.argv      # engine's own math (sub_0019E430): SpineBone2 roll = clamp(signed ViewPitch<<8, -9361, 9102), alpha 1
    VAL = b'\x39\x44' + b'\xab' + b'\x39\x3f' + b'\x93' + b'\x39\x44' + ENERGY + IC(100000) + b'\x16' + FC(KSC if not neg else -KSC) + b'\x16'
    if NATIVE: VAL = b'\xfb' + b'\x93' + b'\x39\x44' + ENERGY + IC(100000) + b'\x16' + IC(-9361) + IC(9102) + b'\x16'
    S_set = b'\x0f' + b'\x36' + write_ci(r_axis) + ctx(SGP, I(r_kdr), 12) + VAL
    S_bone = ctx(SGP, b'\x1c' + write_ci(r_sbr) + b'\x21' + write_ci(nm('Bip01 Spine1')) + ctx(SGP, I(r_kdr), 12) + IC(0) + FC(alpha) + b'\x16', 0)
    S_bone2 = ctx(SGP, b'\x1c' + write_ci(r_sbr) + ctx(SGP, I(r_sb2), 8) + ctx(SGP, I(r_kdr), 12) + IC(0) + FC(alpha) + b'\x16', 0)
    S_mark = b'\x0f' + ctx(SGP, I(r_lta), 4) + SGP     # SGP.LookTargetActor = SGP  (marker read by the patched native UpdateTwistLook, game_hooks/recomp_0027_remote_player_look.patch)
    def block(B, role, enum, stmts):
        """if (role) foreach enum { if (cond) stmt; ... }  starting at memory position B. Returns (bytes, end position)."""
        head = 3 + memlen(role)
        pos = B + head + 1 + memlen(enum) + 2
        sizes = [3 + memlen(c) + memlen(s) for c, s in stmts]
        pos_next = pos + sum(sizes); pos_pop = pos_next + 1; end = pos_pop + 1
        out = b'\x07' + struct.pack('<H', end) + role + b'\x2f' + enum + struct.pack('<H', pos_pop)
        for (c, s), sz in zip(stmts, sizes):
            pos += sz
            out += b'\x07' + struct.pack('<H', pos if pos != pos_next else pos_next) + c + s
        out += b'\x31\x30'
        assert memlen(out) == end - B, (memlen(out), end - B)
        return out, end
    COND_H = CTLSELF
    COND_C = AND(AND(NOT(UNC), CTLNONE), ENERGYGT)
    blkA, endA = block(0, AND(ROLEEQ, NETNE), enum, [(COND_H, S_host)])
    MARK = '--marker' in sys.argv
    blkB, endB = block(endA, ROLENE, enum, [(COND_C, S_mark)] if MARK else [(COND_C, S_set)] + ([(COND_C, S_bone)] if NATIVE else [(COND_C, S_bone)] + ([(COND_C, S_bone2)] if both else [])))
    new = blkA + blkB; end = endB
    assert memlen(new) == end
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
    if len(nblob) > (1 << (6 + 7 * (nszsz - 1))) - 1: sys.exit('size field too small (run patch_coop_pkgext.py first)')
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
    open(out_path, 'wb').write(bytes(d))
    print('patched PlayerTick (axis=%s neg=%s alpha=%s) ->' % (axis, neg, alpha), out_path)

main()
