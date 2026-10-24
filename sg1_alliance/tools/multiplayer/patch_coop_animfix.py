"""EXPERIMENTAL: animation sync for remote pawns in co-op / multiplayer (client sees the host's weapon pose wrong, crouch not synced).

Cause: a client has no Weapon object for other players' pawns (Pawn.Weapon is not replicated to non-owners), but every StargatePawn Animate*()
function, PlayFiring and the crouch code get the weapon's animation set through GetWeaponClass(), which returned None when Weapon == None.
So remote pawns used the unarmed animation set (staff held wrongly, wrong crouch/idle/walk torso). AnimationSetID (the weapon index) IS replicated
to everyone, so GetWeaponClass now only gives up on Weapon == None when Role == ROLE_Authority; on clients it picks the class from AnimationSetID.
Also adds log lines "ANIMLOG StartCrouch <pawn>" / "ANIMLOG EndCrouch <pawn>" to StargatePawn.StartCrouch/EndCrouch (look for them in the game log).
New bodies go to the unused ScriptText buffer of StoryModeGame (+20480 GetWeaponClass, +24576 StartCrouch, +28672 EndCrouch).

Usage:  python patch_coop_animfix.py "<game folder>"            apply (backup System\\StargateGame.u.orig_coopanimfix)
        python patch_coop_animfix.py "<game folder>" --revert   restore the backup
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

def weapon_to_class(script, r_sw, r_weapon, n_gwc):
    """StargateWeapon(Weapon) -> GetWeaponClass() in  'X != None'  and in  StargateWeapon(Weapon).Var  (becomes GetWeaponClass().Default.Var)"""
    CAST = b'\x2e' + write_ci(r_sw) + b'\x01' + write_ci(r_weapon)
    GWC = b'\x1b' + write_ci(n_gwc) + b'\x16'
    rec = []; bad = []; p = 0
    while p < len(script):
        a, p = walk(script, p, sum(0 for _ in ()) if False else (rec[-1][1] if False else 0), rec, bad) if False else (None, None)
        break
    # walk statement by statement keeping a running memory position
    rec = []; bad = []; p = 0; mp = 0
    while p < len(script):
        a, p = walk(script, p, mp, rec, bad); mp += a
    if bad: sys.exit('input script fails the skip/context check: %r' % (bad[:3],))
    reps = []                                                           # (bytepos, mem pos, kind)
    for (bp, mpos, op) in rec:
        if op == 0x19 and script[bp + 1:bp + 1 + len(CAST)] == CAST: reps.append((bp, mpos, 'ctx'))
        elif op == 0x77 and script[bp + 1:bp + 1 + len(CAST)] == CAST and script[bp + 1 + len(CAST):bp + 3 + len(CAST)] == b'\x2a\x16': reps.append((bp, mpos, 'cond'))
    sc = bytearray(script)
    # jump targets
    fix = []; statements(script, fix)
    delta = memlen(GWC) - memlen(CAST)
    for fp in fix:
        t = struct.unpack_from('<H', sc, fp)[0]
        if t == 0xffff: continue
        n = sum(1 for (bp, mpos, k) in reps if mpos + 1 + memlen(CAST) <= t)     # replaced tokens that end at or before the target
        struct.pack_into('<H', sc, fp, t + n * delta)
    for (bp, mpos, k) in sorted(reps, reverse=True):
        if k == 'cond':
            sc[bp + 1:bp + 1 + len(CAST)] = GWC
        else:
            q = bp + 1 + len(CAST)                                       # word, size byte, then  01 <ref>
            if sc[q + 3] != 0x01: sys.exit('unexpected member access after the weapon cast')
            sc[q + 3] = 0x02                                             # InstanceVariable -> DefaultVariable
            sc[bp:bp + 1 + len(CAST)] = b'\x12' + GWC
    rec = []; bad = []; p = 0; mp = 0
    while p < len(sc):
        a, p = walk(bytes(sc), p, mp, rec, bad); mp += a
    if bad: sys.exit('transformed script fails the skip/context check: %r' % (bad[:3],))
    return bytes(sc), len(reps)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_coopanimfix'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    P = Pkg(bytes(d))
    def top(name):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == 0 and P.clsname(e) == 'Class']
        if len(r) != 1: sys.exit('class %s not found' % name)
        return r[0]
    c_pawn = top('StargatePawn'); c_smg = top('StoryModeGame')
    def fnidx(name):
        r = [i for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == c_pawn and e['size']]
        if len(r) != 1: sys.exit('StargatePawn.%s not found' % name)
        return r[0]
    r_role = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == 'ByteProperty' and im[2] == 'Role' and P.imports[-im[1] - 1][2] == 'Actor']
    if len(r_role) != 1: sys.exit('Role import not found')
    r_role = r_role[0]
    r_sw = c_sw = top('StargateWeapon')
    r_weapon = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == 'ObjectProperty' and im[2] == 'Weapon']
    if len(r_weapon) != 1: sys.exit('Weapon property import not found')
    r_weapon = r_weapon[0]
    n_gwc = P.names.index('GetWeaponClass')
    tb = [i for i, x in enumerate(P.ex) if x['name'] == 'ScriptText' and x['outer'] == c_smg and x['size']]
    if len(tb) != 1: sys.exit('ScriptText of StoryModeGame not found')
    text = P.ex[tb[0]]
    I = lambda r: b'\x01' + write_ci(r)
    # Self.Name as string, copied from SetSniping's log call
    ss = fnidx('SetSniping'); e = P.ex[ss]
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
    sc = bytes(d[st0:en]); k = sc.find(b'\xe7\x70\x70\x39\x57')
    if k < 0: sys.exit('Self.Name pattern not found')
    a, _ = tok(sc, k + 3, []); NAMESTR = sc[k + 3:k + 3 + 0]
    # tok returns (mem size, next pos)
    _, nxt = tok(sc, k + 3, [])
    NAMESTR = sc[k + 3:nxt]
    def LOG(txt): return b'\xe7\x70' + b'\x1f' + txt + b'\x00' + NAMESTR + b'\x16\x16'
    def relocate(name, newscr, rel):
        i = fnidx(name); e = P.ex[i]
        szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
        blob = bytes(d[e['off']:e['off'] + e['size']])
        q = szp - e['off']; s0_ = st0 - e['off']; e0_ = en - e['off']
        nblob = blob[:q] + struct.pack('<i', memlen(newscr)) + blob[q + 4:s0_] + newscr + blob[e0_:]
        cur = text['off'] + rel
        if cur + len(nblob) > text['off'] + text['size'] or cur + len(nblob) >= 1048576 + 0: sys.exit('buffer limit for ' + name)
        szc = fit(len(nblob), e['offp'] - e['szp']); offc = fit(cur, e['end'] - e['offp'])
        d[cur:cur + len(nblob)] = nblob
        d[e['szp']:e['offp']] = szc; d[e['offp']:e['end']] = offc
        return i, cur, len(nblob), memlen(newscr)
    def shifted(script, start, g):          # add g to every jump target > start
        fix = []; statements(script, fix); sc2 = bytearray(script)
        for fp in fix:
            t = struct.unpack_from('<H', sc2, fp)[0]
            if t != 0xffff and t > start: struct.pack_into('<H', sc2, fp, t + g)
        return bytes(sc2)
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    done = []
    # 1. GetWeaponClass: if (Weapon == None) return None;   ->   if (Weapon == None && Role == ROLE_Authority) return None;
    gw = fnidx('GetWeaponClass'); e = P.ex[gw]
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size']); script = bytes(d[st0:en])
    if script[:1] != b'\x07': sys.exit('GetWeaponClass has an unexpected layout')
    cm, cend = tok(script, 3, [])
    cond = script[3:cend]
    if cond[:1] != b'\x72': sys.exit('GetWeaponClass first condition unexpected: ' + cond.hex())
    if b'\x82' == cond[:1]: print('already patched'); return
    ROLEAUTH = b'\x9a\x39\x3a' + I(r_role) + b'\x39\x3a\x24\x04\x16'               # Role == ROLE_Authority
    new_cond = b'\x82' + cond + b'\x18' + struct.pack('<H', memlen(ROLEAUTH) + 1) + ROLEAUTH + b'\x16'
    g = memlen(new_cond) - cm
    sc2 = shifted(script, 3 + cm - 1, g)         # targets beyond the condition move; the if's own target too
    newscr = sc2[:3] + new_cond + sc2[cend:]
    done.append(relocate('GetWeaponClass', newscr, 20480))
    # 2. log lines
    for nm, rel in (('StartCrouch', 24576), ('EndCrouch', 28672)):
        i = fnidx(nm); e = P.ex[i]
        szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size']); script = bytes(d[st0:en])
        script, nrep = weapon_to_class(script, r_sw, r_weapon, n_gwc)
        print('%s: %d weapon references now use the replicated weapon class' % (nm, nrep))
        lg = LOG(('ANIMLOG %s ' % nm).encode())
        sc2 = shifted(script, -1, memlen(lg))
        done.append(relocate(nm, lg + sc2, rel))
    P2 = Pkg(bytes(d))
    for (i, cur, n, ml) in done:
        e2 = P2.ex[i]
        assert e2['off'] == cur and e2['size'] == n and len(d) == os.path.getsize(f)
        a, b, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
        assert c_ == ml
    open(f, 'wb').write(bytes(d))
    print('patched: remote pawns use the replicated weapon animation set; crouch log lines added')

main()
