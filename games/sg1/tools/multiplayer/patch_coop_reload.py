"""Client fix 9: reload animations of other players are visible (host <-> client, also AI squadmates on clients).
Before: StargatePawn.PlayReloading only ran on the machine that runs the weapon's Reloading state, and it returned early for ANY human in first
person (so the host never saw a client reload either); clients have no Weapon object for other pawns, so nothing replicated.
Now (StargateGame.u, bytecode only, join-safe: no new names/imports):
 1. StargateWeapon.Reloading.BeginState: attachment.FiringMode = 'Reloading' + IncrementFlashCount() (FlashCount/FiringMode replicate, like melee).
 2. StargateWeaponAttachment.ThirdPersonEffects: FiringMode 'Reloading' -> StargatePawn(Instigator).PlayReloading(); return (no muzzle effects).
 3. StargateWeapon.Reloading.AnimEnd and SetupMuzzleFlash: FiringMode 'Reloading' is set back to MODE_Auto/MODE_Normal (as Clubbing.EndState does).
 4. StargatePawn.PlayReloading: the first-person skip also needs IsLocallyControlled(); a pawn without Weapon takes PawnReloadAnims/ReloadSpeed
    from GetWeaponClass() defaults (needs patch_coop_animfix.py).
Shotgun shell-by-shell reload shows as the normal reload on other screens.
Usage: python patch_coop_reload.py "<game folder>" [--revert]      or  --in X --out Y   (backup <file>.orig_coopreload)
Run after patch_coop_pkgext.py and patch_coop_animfix.py.
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




# ---------------------------------------------------------------- the patch
I = lambda r: b'\x01' + write_ci(r)
H = lambda v: struct.pack('<H', v)

def AND(a, b): return b'\x82' + a + b'\x18' + H(memlen(b) + 1) + b + b'\x16'

class Asm:
    """Tiny assembler: items are bytes or ('j', opcode, label, cond-bytes) or ('L', label). Jump words are absolute memory positions."""
    def __init__(self, items): self.items = items
    def size(self):
        m = 0
        for it in self.items:
            if isinstance(it, bytes): m += memlen(it)
            elif it[0] == 'j': m += 3 + (memlen(it[3]) if it[3] else 0)
        return m
    def build(self, base, ext):
        lab = dict(ext); m = base
        for it in self.items:
            if isinstance(it, bytes): m += memlen(it)
            elif it[0] == 'j': m += 3 + (memlen(it[3]) if it[3] else 0)
            else: lab[it[1]] = m
        out = b''
        for it in self.items:
            if isinstance(it, bytes): out += it
            elif it[0] == 'j': out += bytes([it[1]]) + H(lab[it[2]]) + (it[3] or b'')
        assert memlen(out) == self.size()
        return out

def rebuild(script, prepend=None, repl={}):
    """prepend: Asm placed at memory 0 (label 'next' = new position of the old first statement).
    repl: {old statement byte position: Asm}; its label 'next' = new position of the following old statement.
    Every jump word of the kept statements is moved to the new statement positions."""
    fix = []; stm = statements(script, fix)
    old_m = []; m = 0
    for s, a in stm: old_m.append(m); m += a
    old_end = m
    pre = prepend.size() if prepend else 0
    new_m = []; m = pre
    for (s, a) in stm:
        new_m.append(m); m += repl[s].size() if s in repl else a
    mp = dict(zip(old_m, new_m)); mp[old_end] = m
    out = b''
    if prepend: out += prepend.build(0, {'next': new_m[0]})
    for i, (s, a) in enumerate(stm):
        e = stm[i + 1][0] if i + 1 < len(stm) else len(script)
        nxt = new_m[i + 1] if i + 1 < len(stm) else m
        if s in repl:
            out += repl[s].build(new_m[i], {'next': nxt}); continue
        seg = bytearray(script[s:e])
        for fp in fix:
            if s <= fp < e:
                t = struct.unpack_from('<H', seg, fp - s)[0]
                if t == 0xffff: continue
                if t not in mp: sys.exit('jump target %d is not a statement start' % t)
                struct.pack_into('<H', seg, fp - s, mp[t])
        out += bytes(seg)
    assert memlen(out) == m, (memlen(out), m)
    return out

def relocate(d, P, fn, newscr):
    e = P.ex[fn]
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
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
    if bad or mp != c_ or scr != newscr: sys.exit('verification failed: %r' % (bad[:2],))
    return P2

def get_script(d, P, fn):
    e = P.ex[fn]; szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
    return bytes(d[st0:en])

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    def opt(n, dflt=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else dflt
    exp = '--in' in sys.argv
    if not args and not exp: sys.exit(__doc__)
    if exp:
        f = opt('--in'); out_path = opt('--out'); bak = None
    else:
        f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_coopreload'; out_path = f
        if '--revert' in sys.argv:
            if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
            shutil.copyfile(bak, f); os.remove(bak); print('reverted'); return
    d = bytearray(open(f, 'rb').read()); P = Pkg(bytes(d))
    def top(n):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == n and e['outer'] == 0 and P.clsname(e) == 'Class']
        if len(r) != 1: sys.exit('class %s not found' % n)
        return r[0]
    def sub(outer, n, cls):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == n and e['outer'] == outer and P.clsname(e) == cls]
        if len(r) != 1: sys.exit('%s %s not found' % (cls, n))
        return r[0]
    def fnc(outer, n):
        r = [i for i, e in enumerate(P.ex) if e['name'] == n and e['outer'] == outer and e['size'] and P.clsname(e) == 'Function']
        if len(r) != 1: sys.exit('function %s not found' % n)
        return r[0]
    def nm(n):
        if n not in P.names: sys.exit('name %s missing' % n)
        return P.names.index(n)
    def imp(cls, name, owner):
        r = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name and P.imports[-im[1] - 1][2] == owner]
        if len(r) != 1: sys.exit('import %s.%s not found (%d)' % (owner, name, len(r)))
        return r[0]
    c_pawn = top('StargatePawn'); c_wpn = top('StargateWeapon'); c_att = top('StargateWeaponAttachment'); c_wa = -[i + 1 for i, im in enumerate(P.imports) if im[0] == 'Class' and im[2] == 'WeaponAttachment'][0]
    st_rel = sub(c_wpn, 'Reloading', 'State')
    f_play = fnc(c_pawn, 'PlayReloading'); f_begin = fnc(st_rel, 'BeginState'); f_animend = fnc(st_rel, 'AnimEnd')
    f_muzzle = fnc(c_wpn, 'SetupMuzzleFlash'); f_tpe = fnc(c_att, 'ThirdPersonEffects')
    def mem(outer, n):
        r = [i + 1 for i, x in enumerate(P.ex) if x['name'] == n and x['outer'] == outer]
        if len(r) != 1: sys.exit('%s not found' % n)
        return r[0]
    r_tpa = imp('ObjectProperty', 'ThirdPersonActor', 'Inventory'); r_fm = imp('NameProperty', 'FiringMode', 'WeaponAttachment')
    r_inst = imp('ObjectProperty', 'Instigator', 'Actor')
    r_wfm = mem(c_wpn, 'FiringMode'); r_pra = mem(c_wpn, 'PawnReloadAnims'); r_rs = mem(c_wpn, 'ReloadSpeed')
    r_crouch = imp('BoolProperty', 'bIsCrouched', 'Pawn'); r_ranim = mem(c_pawn, 'ReloadAnim')
    n_rel = nm('Reloading'); n_auto = nm('MODE_Auto'); n_norm = nm('MODE_Normal')
    CALL = lambda n: b'\x1b' + write_ci(nm(n)) + b'\x16'
    NAME = lambda n: b'\x21' + write_ci(n)
    def ctx(e1, e2, size): return b'\x19' + e1 + H(memlen(e2)) + bytes([size]) + e2
    def cctx(e1, e2, size): return b'\x12' + e1 + H(memlen(e2)) + bytes([size]) + e2
    TPA = I(r_tpa)
    TPA_OK = b'\x77' + TPA + b'\x2a\x16'                                     # ThirdPersonActor != None
    ATT_FM = ctx(b'\x2e' + write_ci(c_wa) + TPA, I(r_fm), 4)              # WeaponAttachment(ThirdPersonActor).FiringMode
    IS_REL = b'\xfe' + ATT_FM + NAME(n_rel) + b'\x16'                      # ... == 'Reloading'
    AUTO = b'\x9a\x39\x3a' + I(r_wfm) + b'\x2c\x02\x16'                    # FiringMode == MODE_Auto
    # 1) Reloading.BeginState: if (ThirdPersonActor != None) { att.FiringMode = 'Reloading'; IncrementFlashCount(); }
    pre_begin = Asm([('j', 7, 'next', TPA_OK), b'\x0f' + ATT_FM + NAME(n_rel), CALL('IncrementFlashCount')])
    # 2) restore (Reloading.AnimEnd and SetupMuzzleFlash): if (TPA != None && att.FiringMode == 'Reloading') att.FiringMode = Auto/Normal like Clubbing.EndState
    def restore(): return Asm([('j', 7, 'next', AND(TPA_OK, IS_REL)), ('j', 7, 'else', AUTO), b'\x0f' + ATT_FM + NAME(n_auto),
                               ('j', 6, 'next', None), ('L', 'else'), b'\x0f' + ATT_FM + NAME(n_norm)])
    # 3) StargateWeaponAttachment.ThirdPersonEffects: if (FiringMode == 'Reloading') { if (StargatePawn(Instigator) != None) StargatePawn(Instigator).PlayReloading(); return; }
    SGP = b'\x2e' + write_ci(c_pawn) + I(r_inst)
    pre_tpe = Asm([('j', 7, 'next', b'\xfe' + I(r_fm) + NAME(n_rel) + b'\x16'), ('j', 7, 'ret', b'\x77' + SGP + b'\x2a\x16'),
                   ctx(SGP, CALL('PlayReloading'), 0), ('L', 'ret'), b'\x04\x0b'])
    # 4) StargatePawn.PlayReloading: first-person skip only for the LOCAL player (the host skipped every human's reload),
    #    and pawns without a Weapon object (other players on a client) take the animation from the replicated weapon class.
    sc_play = get_script(d, P, f_play); fx = []; stm = statements(sc_play, fx)
    nexts = {s: (stm[i + 1][0] if i + 1 < len(stm) else len(sc_play)) for i, (s, a) in enumerate(stm)}
    fp_cond = [s for s, a in stm if sc_play[s] == 0x07 and sc_play[s + 3] == 0x82 and sc_play[s + 4] == 0x77 and sc_play[s + 5] == 0x2e and nexts[s] in nexts and sc_play[nexts[s]:nexts[s] + 2] == b'\x04\x0b']
    old_else = b'\x61\x03' + I(r_ranim) + b'\x1e' + struct.pack('<f', 1.0) + b'\x1e' + struct.pack('<f', 0.1) + b'\x2c\x0f\x16'
    fp_else = [s for s, a in stm if sc_play[s:nexts[s]] == old_else]
    if CALL('IsLocallyControlled') in sc_play or CALL('IncrementFlashCount') in get_script(d, P, f_begin): print('already patched'); return
    if len(fp_cond) != 1 or len(fp_else) != 1: sys.exit('PlayReloading layout not recognised (%d, %d)' % (len(fp_cond), len(fp_else)))
    s = fp_cond[0]; cond_old = sc_play[s + 3:nexts[s]]
    new_cond = Asm([('j', 7, 'retlbl', AND(cond_old, CALL('IsLocallyControlled')))])
    GWC = CALL('GetWeaponClass')
    def PA(idx): return b'\x61\x03' + b'\x1a' + idx + cctx(GWC, b'\x02' + write_ci(r_pra), 8) + cctx(GWC, b'\x02' + write_ci(r_rs), 4) + b'\x1e' + struct.pack('<f', 0.1) + b'\x2c\x0f\x16'
    new_else = Asm([('j', 7, 'cls', b'\x72' + GWC + b'\x2a\x16'), old_else, ('j', 6, 'next', None),
                    ('L', 'cls'), ('j', 7, 'stand', b'\x2d' + I(r_crouch)), PA(b'\x26'), ('j', 6, 'next', None),
                    ('L', 'stand'), PA(b'\x25')])
    # the if's jump target is the old target of that statement (after the return): compute through rebuild by a label
    tgt_old = struct.unpack_from('<H', sc_play, s + 1)[0]
    # map tgt_old -> new: rebuild once with a placeholder, then read
    m = 0; old_m = {}
    for st, a in stm: old_m[m] = st; m += a
    old_m[m] = len(sc_play)
    if tgt_old not in old_m: sys.exit('unexpected jump target')
    class Wrap(Asm):
        pass
    tgt_stmt = old_m[tgt_old]
    # compute the new memory position of tgt_stmt
    delta_cond = new_cond.size() - (nexts[s] and memlen(sc_play[s:nexts[s]]))
    delta_else = new_else.size() - memlen(old_else)
    newpos = tgt_old + (delta_cond if tgt_stmt > s else 0) + (delta_else if tgt_stmt > fp_else[0] else 0)
    new_cond = Asm([('j', 7, 'retlbl', AND(cond_old, CALL('IsLocallyControlled')))]); new_cond.build_ext = newpos
    orig_build = new_cond.build
    new_cond.build = lambda base, ext: orig_build(base, dict(ext, retlbl=newpos))
    newscr = {}
    newscr[f_play] = rebuild(sc_play, None, {s: new_cond, fp_else[0]: new_else})
    newscr[f_begin] = rebuild(get_script(d, P, f_begin), pre_begin)
    newscr[f_animend] = rebuild(get_script(d, P, f_animend), restore())
    newscr[f_muzzle] = rebuild(get_script(d, P, f_muzzle), restore())
    newscr[f_tpe] = rebuild(get_script(d, P, f_tpe), pre_tpe)
    # sanity: walk each new body
    for k, v in newscr.items():
        rec = []; bad = []; pp = 0; mp_ = 0
        while pp < len(v):
            aa, pp = walk(v, pp, mp_, rec, bad); mp_ += aa
        if bad: sys.exit('bad body %s %r' % (P.ex[k]['name'], bad[:2]))
    if bak and not os.path.exists(bak): shutil.copyfile(f, bak)
    for k, v in newscr.items():
        P = relocate(d, P, k, v)
    open(out_path, 'wb').write(bytes(d))
    print('patched: reload animation replicates (Reloading.BeginState/AnimEnd, SetupMuzzleFlash, Attachment.ThirdPersonEffects, Pawn.PlayReloading) ->', out_path)

main()
