"""Missile launcher (Stinger) stuck after it is picked up: it never fires and sits half raised in the hands.
The first-person weapon mesh SG1_weapons_1st.sg1_wep_stinger has no animation set linked (its Animation is None, every other
weapon mesh links its sg1_wep_*_HUD_anim), so the weapon's own PlayAnim('get_out' / 'put_away' / 'Fire' / 'Reload') fails
("Sequence 'get_out' not found for mesh 'sg1_wep_stinger'") and the weapon never finishes raising. The set exists and has all of
them: sg1_wep_stinger_HUD_anim (Idle, put_away, get_out, Move, Fire, Reload, to_zoom, from_zoom, fidget).
This links it as the mesh's default set (Animations/SG1_weapons_1st.ukx; the mesh data moves behind the export table, its lazy
array offsets are fixed, header and tables unchanged).
The missile: StingerProjectile.Explode stops it with Velocity = 0 and collision off, but the acceleration set at launch
(StargateProjectile.SetRange) stays, so after hitting a wall it sped on through it for the 5 s until it was destroyed.
StargateContent.u: Explode also sets Acceleration = vect(0,0,0) and SetPhysics(PHYS_None).
Its explosion: the own effect (StingerExplode, one emitter of smoke puffs) is commented out in System/tweak/Weapons/Stinger.ini,
and Explode played no sound. Now it uses the frag grenade's: Stinger.ini ExplodeEmitter=class'StargateContent.FragGrenadeExplosion'
and ImpactSound[0]=Sound'weaponsounds.GRENADE.grenadeimpact', and Explode plays ImpactSound[0] on the server
(if (Role == ROLE_Authority) PlaySound(ImpactSound[0],,1.0), as the other projectiles do).
Usage: python patch_stinger_anim.py "<game folder>" [--revert]   (backups <file>.orig_stinger)
"""
import sys, os, shutil, struct, math

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
            self.ex.append(dict(cls=cls, outer=outer, name=self.names[nm], size=sz, off=off, szp=szp, offp=offp, start=s, end=o))
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
            elif it[0] == 'it': m += 3 + memlen(it[1])
        return m
    def build(self, base, ext):
        lab = dict(ext); m = base
        for it in self.items:
            if isinstance(it, bytes): m += memlen(it)
            elif it[0] == 'j': m += 3 + (memlen(it[3]) if it[3] else 0)
            elif it[0] == 'it': m += 3 + memlen(it[1])
            else: lab[it[1]] = m
        out = b''
        for it in self.items:
            if isinstance(it, bytes): out += it
            elif it[0] == 'j': out += bytes([it[1]]) + H(lab[it[2]]) + (it[3] or b'')
            elif it[0] == 'it': out += b'\x2f' + it[1] + H(lab[it[2]])
        assert memlen(out) == self.size()
        return out

def rebuild(script, prepend=None, repl={}, extlab={}):
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
    bpos = {st_: new_m[i] for i, (st_, a_) in enumerate(stm)}
    xl = {k: bpos[v] for k, v in extlab.items()}
    if prepend: out += prepend.build(0, dict(xl, next=new_m[0]))
    for i, (s, a) in enumerate(stm):
        e = stm[i + 1][0] if i + 1 < len(stm) else len(script)
        nxt = new_m[i + 1] if i + 1 < len(stm) else m
        if s in repl:
            out += repl[s].build(new_m[i], dict(xl, next=nxt)); continue
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

ANIMSET = b'sg1_anim.sg1_p90_anim_default'
JAFFASET = b'jaffa_anim.jaffa_anims'

def finder(P):
    def top(n):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == n and e['outer'] == 0 and P.clsname(e) == 'Class']
        if len(r) != 1: sys.exit('class %s not found' % n)
        return r[0]
    def imp(cls, outer, name):
        r = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name and (outer is None or (im[1] and P.imports[-im[1] - 1][2] == outer))]
        if len(r) != 1: sys.exit('import %s %s.%s not found' % (cls, outer, name))
        return r[0]
    def member(cls, name):
        r = [i for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == cls]
        if len(r) != 1: sys.exit('%s not found' % name)
        return r[0]
    def nm(n):                                          # names compare without case ('ZATGUN' is ZatGun)
        r = [i for i, x in enumerate(P.names) if x.lower() == n.lower()]
        if not r: sys.exit('name %s not in the package' % n)
        return write_ci(r[0])
    return top, imp, member, nm

def ctx(e1, e2, size): return b'\x19' + e1 + H(memlen(e2)) + bytes([size]) + e2

def check(scr):
    rec = []; bad = []; pp = 0; mp_ = 0
    while pp < len(scr):
        aa, pp = walk(scr, pp, mp_, rec, bad); mp_ += aa
    if bad: sys.exit('bad body %r' % (bad[:2],))

def netgame(imp):
    level = imp('ObjectProperty', 'Actor', 'Level'); netmode = imp('ByteProperty', 'LevelInfo', 'NetMode')
    return b'\x9b\x39\x3a' + ctx(I(level), I(netmode), 1) + b'\x39\x3a\x24\x00\x16'        # Level.NetMode != NM_Standalone


def pnbp_tail(P, imp, nm, mp, sp):
    """the code after Super.PostNetBeginPlay() and the bone name lets; mp: human set in network games, sp: Jaffa set always"""
    link = imp('Function', 'Actor', 'LinkSkelAnim'); dlo = imp('Function', 'Object', 'DynamicLoadObject')
    manim = imp('Class', None, 'MeshAnimation')
    def LINKSET(path):
        return (b'\x1c' + write_ci(link) + b'\x2e' + write_ci(manim) + b'\x1c' + write_ci(dlo) + b'\x1f' + path + b'\x00'
                + b'\x20' + write_ci(manim) + b'\x16' + b'\x16')
    items = [b'\x61\x07\x21' + nm('bip01') + b'\x16']                  # HasAnim('bip01')
    if mp: items += [('j', 7, 'skip', netgame(imp)), LINKSET(ANIMSET), ('L', 'skip')]
    if sp: items += [LINKSET(JAFFASET)]
    return Asm(items + [b'\x04\x0b', b'\x47'])

def rebuild_pnbp(d, P, fn, sc, mp, sp, imp, nm):
    stm = statements(sc, [])
    hasanim = b'\x61\x07\x21' + nm('bip01') + b'\x16'
    cut = [p_ for p_, a_ in stm if sc[p_] == 0x07 or sc[p_:p_ + len(hasanim)] == hasanim or sc[p_:p_ + 2] == b'\x04\x0b']
    if not cut or any(sc[p_] in (0x06, 0x07) for p_, a_ in stm if p_ < cut[0]): sys.exit('unexpected PostNetBeginPlay layout')
    head = sc[:cut[0]]                                                 # Super.PostNetBeginPlay() + the bone name lets, no jumps
    if len(statements(head + b'\x47', [])) != 8: sys.exit('unexpected PostNetBeginPlay layout')
    return head + pnbp_tail(P, imp, nm, mp, sp).build(memlen(head), {})

# ---------------------------------------------------------------- StargateGame.u (functions go to free ScriptText space)
def patch_game(f):
    d = bytearray(open(f, 'rb').read()); P = Pkg(bytes(d)); top, imp, member, nm = finder(P)
    pw = top('StargatePawn'); done = []
    HASANIM = b'\x61\x07\x21' + nm('bip01') + b'\x16'
    fn = member(pw, 'PostNetBeginPlay'); sc = get_script(d, P, fn)
    if ANIMSET in sc and HASANIM not in sc:             # first version (human set linked in front): start again from its backup
        bak = f + '.orig_mpweaponanims'
        if not os.path.exists(bak): sys.exit('old version of this patch found and no backup to redo it from')
        d = bytearray(open(bak, 'rb').read()); P = Pkg(bytes(d)); top, imp, member, nm = finder(P); pw = top('StargatePawn')
        if ANIMSET in get_script(d, P, member(pw, 'PostNetBeginPlay')): sys.exit('the backup %s is not the unpatched file' % bak)
        print('StargateGame.u: redoing the patch from', bak)
    NET = netgame(imp)

    fn = member(pw, 'PostNetBeginPlay'); sc = get_script(d, P, fn)
    # HasAnim('bip01'); if (Level.NetMode != NM_Standalone) LinkSkelAnim(human set);  [+ the Jaffa set of ../patch_staff_melee.py if applied]
    newscr = rebuild_pnbp(d, P, fn, sc, True, JAFFASET in sc, imp, nm)
    if newscr != sc:
        check(newscr); P = relocate(d, P, fn, newscr); done.append('PostNetBeginPlay')

    fn = member(pw, 'GetWeaponBoneFor'); sc = get_script(d, P, fn)
    orig = b'\x04\x21' + nm('bone_weapon') + b'\x04\x0b\x47'      # return 'bone_weapon';
    if sc != orig:                                                     # an earlier version returned HelmetBone in network games
        if I(member(pw, 'HelmetBone') + 1) not in sc: sys.exit('unexpected GetWeaponBoneFor layout')
        P = relocate(d, P, fn, orig); done.append('GetWeaponBoneFor (back to the original)')

    if not done: print('StargateGame.u: already patched'); return
    bak = f + '.orig_mpweaponanims'
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(d))
    print('patched StargateGame.u: StargatePawn.%s' % ', '.join(done))


# ---------------------------------------------------------------- objects behind the export table
def write_behind_table(d, P, new):
    """header and tables stay where they are (the header is in the quick MD5); the objects already behind the export table and the
    changed ones (new: index -> bytes, or a function of the file offset it lands at) are written after it; only their size / offset
    fields in the export table change"""
    tail = {i: d[e['off']:e['off'] + e['size']] for i, e in enumerate(P.ex) if e['size'] and e['off'] >= P.eo}
    tail.update(new)
    order = sorted(tail, key=lambda i: (i in new, P.ex[i]['off'], i))
    data = lambda i, at: tail[i](at) if callable(tail[i]) else tail[i]
    size = {i: len(data(i, 0)) for i in order}
    head = d[:P.eo]
    def table(place):
        t = bytearray()
        for i, e in enumerate(P.ex):
            raw = d[e['start']:e['end']]
            if i in place:
                off, sz = place[i]; raw = d[e['start']:e['szp']] + write_ci(sz) + write_ci(off)
            t += raw
        return t
    place = {i: (0, size[i]) for i in order}
    for _ in range(10):
        at = len(head) + len(table(place)); moved = {}
        for i in order: moved[i] = (at, size[i]); at += size[i]
        if moved == place: break
        place = moved
    else: sys.exit('layout did not settle')
    out = bytearray(head) + table(place)
    for i in order:
        if len(out) != place[i][0]: sys.exit('layout did not settle')
        out += data(i, place[i][0])
    Q = Pkg(bytes(out))
    if Q.names != P.names or Q.imports != P.imports or len(Q.ex) != len(P.ex) or out[:64] != d[:64]: sys.exit('self check failed')
    for i, e in enumerate(P.ex):
        want = data(i, place[i][0]) if i in tail else d[e['off']:e['off'] + e['size']]
        if out[Q.ex[i]['off']:Q.ex[i]['off'] + Q.ex[i]['size']] != want: sys.exit('self check failed (%s)' % e['name'])
    return out


def lazy_arrays(blob, base):
    """lazy arrays: [int file offset of the data end][count][data]; returns [(position, end)] relative to the object"""
    out = []; last = 0
    for k in range(0, len(blob) - 5):
        v = struct.unpack_from('<I', blob, k)[0] - base
        if not (k + 5 <= v <= len(blob)) or k < last: continue
        try: cnt, q = read_ci(blob, k + 4)
        except IndexError: continue
        if cnt <= 0 or (v - q) <= 0 or (v - q) % cnt or (v - q) // cnt > 64: continue
        out.append((k, v)); last = v
    return out

def find_skel(b, names, rci, start=0, stop=60000):
    for o in range(start, min(stop, len(b)-60)):
        try:
            n,r=rci(b,o)
            if not (1<=n<=255): continue
            bones=[]; ok=True
            for i in range(n):
                nm,r=rci(b,r)
                if not (0<=nm<len(names)): ok=False;break
                q=struct.unpack_from('<4f',b,r+4)
                if abs(sum(x*x for x in q)-1)>1e-3: ok=False;break
                par=struct.unpack_from('<i',b,r+4+44+4)[0]
                if not (0<=par<n) or (i>0 and par>=i) : ok=False;break
                bones.append((names[nm],par)); r+=4+44+8
            if ok and n>=1: return o,bones,r
        except Exception: continue
    return None

MESH = 'sg1_wep_stinger'; ANIM = 'sg1_wep_stinger_HUD_anim'

def patch_missile(game):
    f = os.path.join(game, 'System', 'StargateContent.u'); bak = f + '.orig_stinger'
    d = bytes(open(f, 'rb').read()); P = Pkg(d); top, imp, member, nm = finder(P)
    fn = member(top('StingerProjectile'), 'Explode'); e = P.ex[fn]
    szp, st0, ssz, en = locate_script(d, e['off'], e['size']); sc = d[st0:en]
    vel = imp('StructProperty', 'Actor', 'Velocity'); acc = imp('StructProperty', 'Actor', 'Acceleration')
    ZERO = b'\x23' + b'\x00' * 12
    STOPACC = b'\x0f' + I(acc) + ZERO
    SETPHYS = b'\x6f\x82\x24\x00\x16'                                # SetPhysics(PHYS_None)
    role = imp('ByteProperty', 'Actor', 'Role'); snd = imp('ObjectProperty', 'Projectile', 'ImpactSound')
    AUTH = b'\x9a\x39\x3a' + I(role) + b'\x39\x3a\x24\x04\x16'     # Role == ROLE_Authority
    PLAY = b'\x61\x08\x1a\x25' + I(snd) + b'\x0b\x1e' + struct.pack('<f', 1.0) + b'\x16'   # PlaySound(ImpactSound[0],,1.0)
    if PLAY in sc: print('StargateContent.u: missile already stops and sounds'); return
    stm = statements(sc, [])
    tail = [('j', 7, 'snd', AUTH), PLAY, ('L', 'snd')]
    if STOPACC in sc:                                                  # earlier version: stops, no sound yet
        at = [p_ for p_, a_ in stm if sc[p_:p_ + len(SETPHYS)] == SETPHYS]
        if len(at) != 1: sys.exit('unexpected StingerProjectile.Explode layout')
        newscr = rebuild(sc, None, {at[0]: Asm([SETPHYS] + tail)})
    else:
        at = [p_ for p_, a_ in stm if sc[p_:p_ + len(b'\x0f' + I(vel) + ZERO)] == b'\x0f' + I(vel) + ZERO]
        if len(at) != 1: sys.exit('unexpected StingerProjectile.Explode layout')
        # Velocity = vect(0,0,0);  Acceleration = vect(0,0,0);  SetPhysics(PHYS_None);  if (Role == ROLE_Authority) PlaySound(...)
        newscr = rebuild(sc, None, {at[0]: Asm([b'\x0f' + I(vel) + ZERO, STOPACC, SETPHYS] + tail)})
    check(newscr)
    blob = d[e['off']:e['off'] + e['size']]; q = szp - e['off']
    nb = blob[:q] + struct.pack('<i', memlen(newscr)) + newscr + blob[en - e['off']:]
    out = write_behind_table(d, P, {fn: nb})
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(out)); print('patched StargateContent.u: StingerProjectile.Explode stops the missile and plays its impact sound')

SETTINGS = [(b'ExplodeEmitter', b"ExplodeEmitter=class'StargateContent.FragGrenadeExplosion'"),
            (b'ImpactSound[0]', b"ImpactSound[0]=Sound'weaponsounds.GRENADE.grenadeimpact'")]

def patch_ini(game):
    f = os.path.join(game, 'System', 'tweak', 'Weapons', 'Stinger.ini')
    if not os.path.exists(f): sys.exit('no ' + f)
    raw = open(f, 'rb').read(); nl = b'\r\n' if b'\r\n' in raw else b'\n'; lines = raw.split(nl)
    sec = [i for i, l in enumerate(lines) if l.strip().lower() == b'[stargatecontent.stingerprojectile]']
    if len(sec) != 1: sys.exit('Stinger.ini: no [Stargatecontent.StingerProjectile]')
    end = next((i for i in range(sec[0] + 1, len(lines)) if lines[i].strip().startswith(b'[')), len(lines))
    changed = 0
    for key, want in SETTINGS:
        hit = [i for i in range(sec[0] + 1, end) if lines[i].strip().lstrip(b'/').strip().lower().startswith(key.lower() + b'=')]
        if hit:
            if lines[hit[0]].strip() != want: lines[hit[0]] = want; changed += 1
            for i in hit[1:]:
                if not lines[i].strip().startswith(b'/'): lines[i] = b'//' + lines[i]; changed += 1
        else:
            lines.insert(sec[0] + 1, want); end += 1; changed += 1
    if not changed: print('Stinger.ini: grenade explosion already set'); return
    if not os.path.exists(f + '.orig_stinger'): shutil.copyfile(f, f + '.orig_stinger')
    open(f, 'wb').write(nl.join(lines)); print('Stinger.ini: missile uses the frag grenade explosion and sound')

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    if '--revert' in sys.argv:
        for x in (os.path.join(args[0], 'System', 'StargateContent.u'), os.path.join(args[0], 'System', 'tweak', 'Weapons', 'Stinger.ini')):
            if os.path.exists(x + '.orig_stinger'): shutil.copyfile(x + '.orig_stinger', x); print('reverted', x)
    else:
        patch_missile(args[0]); patch_ini(args[0])
    adir = os.path.join(args[0], 'Animations')
    f = [os.path.join(adir, n) for n in os.listdir(adir) if n.lower() == 'sg1_weapons_1st.ukx']
    if len(f) != 1: sys.exit('no Animations/SG1_weapons_1st.ukx')
    f = f[0]; bak = f + '.orig_stinger'
    if '--revert' in sys.argv:
        if os.path.exists(bak): shutil.copyfile(bak, f); print('reverted', f)
        return
    d = bytes(open(f, 'rb').read()); P = Pkg(d)
    m = [i for i, e in enumerate(P.ex) if e['name'] == MESH and P.clsname(e) == 'SkeletalMesh']
    a = [i for i, e in enumerate(P.ex) if e['name'] == ANIM and P.clsname(e) == 'MeshAnimation']
    if len(m) != 1 or len(a) != 1: sys.exit('mesh / animation set not found')
    i = m[0]; e = P.ex[i]; b = d[e['off']:e['off'] + e['size']]
    s = find_skel(b, P.names, read_ci)
    if not s: sys.exit(MESH + ': skeleton not found')
    _, bones, end = s
    cur, q = read_ci(b, end)
    if cur == a[0] + 1: print('SG1_weapons_1st.ukx: missile launcher already has its animations'); return
    if cur != 0: sys.exit(MESH + ': unexpected animation link %d' % cur)
    if struct.unpack_from('<i', b, q)[0] != 13 and not (0 < struct.unpack_from('<i', b, q)[0] < 64): sys.exit(MESH + ': unexpected layout')
    ref = write_ci(a[0] + 1); ins = len(ref) - (q - end)
    lz = lazy_arrays(b, e['off'])
    if not lz or any(k < q for k, v in lz): sys.exit(MESH + ': unexpected layout')
    nb = b[:end] + ref + b[q:]
    def make(at, nb=nb, lz=lz, ins=ins):
        out = bytearray(nb)
        for k, v in lz: struct.pack_into('<I', out, k + ins, at + v + ins)
        return bytes(out)
    out = write_behind_table(d, P, {i: make})
    Q = Pkg(bytes(out)); qe = Q.ex[i]; qb = out[qe['off']:qe['off'] + qe['size']]
    s2 = find_skel(qb, Q.names, read_ci)
    if not s2 or read_ci(qb, s2[2])[0] != a[0] + 1 or len(lazy_arrays(qb, qe['off'])) != len(lz): sys.exit('self check failed')
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(out))
    print('patched SG1_weapons_1st.ukx: %s links %s (the missile launcher raises, fires and reloads)' % (MESH, ANIM))

main()
