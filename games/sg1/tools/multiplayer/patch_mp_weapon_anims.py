"""Fix 26: Jacob / Selmak, Tok'ra and the Horus / Serpent / Jackal Jaffa in multiplayer: no P90 / shotgun / pistol animations, and
the gun in their hands could not be seen.

1. Animations. Their skeletons come with their own animation sets (jaffa_anims: staff and zat only, Tokra_anim_set: no P90 ...),
   so with one of those guns the body stood still. All SG-1 skeletons share the Bip01 bone names, so the human set works on them.
   StargateGame.u, StargatePawn.PostNetBeginPlay (runs on the server and on every client), network games only:
       if (Level.NetMode != NM_Standalone) { HasAnim('bip01'); LinkSkelAnim(MeshAnimation(DynamicLoadObject("sg1_anim.sg1_p90_anim_default", class'MeshAnimation'))); }
   The engine links a mesh's own animation set only on the first animation lookup, and a lookup takes the first linked set that has
   the sequence. Linked first, the human set would win over the character's own (the Jaffa staff idle / walk / melee were replaced).
   HasAnim does a lookup, so the own set is linked first and stays in front; the human set only fills in what it lacks.
   (The staff melee for everyone, the Jaffa set linked behind these in single player too, is ../patch_staff_melee.py; both tools keep
   each other's part of PostNetBeginPlay.)
2. Gun position. A weapon is attached to the bone GetWeaponBoneFor names:
   - StargatePawn: 'bone_weapon', which the Tok'ra / Jacob meshes (sg1_anim.tokra_generic / tokra_selmak) did not have: the attach
     failed and the gun was not drawn. sg1_anim.ukx: both meshes get O'Neill's bone_weapon (a child of Bip01 R Hand, no skin on it).
     The human animations move that bone per weapon (a gun sits in the grip, the staff is turned ~95 degrees), so they now hold
     every weapon like the humans do. (An earlier version attached to the bare hand: guns sat in the wrong place, the staff pointed
     up. Its changes, HelmetBone defaults and a GetWeaponBoneFor branch, are undone.)
     The animations only carry bone directions; bone lengths come from each skeleton. The Tok'ra arms are built differently
     (collar bone 2.8 instead of 7.1 from the spine, longer forearm, shorter upper arm), so with the human poses the left hand
     missed the gun's fore grip. Their arm bones (collar, upper arm, forearm, hand, forearm twist) get O'Neill's lengths (same
     directions), so both hands land where O'Neill's do; the arm mesh follows its bones (shoulders a little wider).
   - JaffaBase: 'weapon bone', turned ~90 degrees to hold a staff; it stays in that pose under the human animations, so a P90 points
     the wrong way. JaffaBase.GetWeaponBoneFor in a network game returns 'Bip01 R Hand' for every weapon except the staff and zat.
The script parts are gated on Level.NetMode (single player unchanged); the added mesh bone has no skin, so it only matters where a
weapon is attached to it. Bytecode / defaults only, no new names, imports or exports (join-safe).
Mesh data moved behind the export table keeps the package header (sound / animation packages are not in Packages.md5 anyway).
Usage: python patch_mp_weapon_anims.py "<game folder>" [--revert]   (backups <file>.orig_mpweaponanims)
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


# ---------------------------------------------------------------- StargateContent.u (changed objects go after the export table)
def patch_content(f):
    d = bytes(open(f, 'rb').read()); P = Pkg(d); top, imp, member, nm = finder(P)
    new = {}                                            # export index (0-based) -> new data
    HAND = nm('Bip01 R Hand')

    jb = top('JaffaBase'); fn = member(jb, 'GetWeaponBoneFor')
    e = P.ex[fn]; szp, st0, ssz, en = locate_script(d, e['off'], e['size']); sc = d[st0:en]
    if b'\x21' + HAND not in sc:
        if sc != b'\x04\x21' + nm('weapon bone') + b'\x04\x0b\x47': sys.exit('unexpected JaffaBase.GetWeaponBoneFor layout')
        arg = [i + 1 for i, x in enumerate(P.ex) if x['outer'] == fn + 1 and x['name'].lower() == 'i']
        if len(arg) != 1: sys.exit('GetWeaponBoneFor parameter not found')
        def notisa(cls): return b'\x81' + ctx(b'\x00' + write_ci(arg[0]), b'\x61\x2f\x21' + nm(cls) + b'\x16', 4) + b'\x16'
        # if (Level.NetMode != NM_Standalone) if (!I.IsA('StaffWeapon')) if (!I.IsA('ZatGun')) return 'Bip01 R Hand';   return 'weapon bone';
        newscr = Asm([('j', 7, 'out', netgame(imp)), ('j', 7, 'out', notisa('StaffWeapon')), ('j', 7, 'out', notisa('ZatGun')),
                      b'\x04\x21' + HAND, ('L', 'out'), b'\x04\x21' + nm('weapon bone'), b'\x04\x0b', b'\x47']).build(0, {})
        check(newscr)
        blob = d[e['off']:e['off'] + e['size']]; q = szp - e['off']
        new[fn] = blob[:q] + struct.pack('<i', memlen(newscr)) + newscr + blob[en - e['off']:]

    # an earlier version gave Tok'ra / Jacob_Selmak the default HelmetBone='Bip01 R Hand' (weapon on the bare hand): taken out again,
    # their meshes have a real bone_weapon now (patch_meshes)
    TAG = nm('HelmetBone') + b'\x16' + HAND
    for cname in ('Tokra', 'Jacob_Selmak'):
        c = top(cname) - 1; e = P.ex[c]; blob = d[e['off']:e['off'] + e['size']]
        if blob.endswith(TAG + b'\x00'): new[c] = blob[:-len(TAG) - 1] + b'\x00'

    if not new: print('StargateContent.u: already patched'); return
    out = write_behind_table(d, P, new)
    bak = f + '.orig_mpweaponanims'
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(out))
    print('patched StargateContent.u: %s' % ', '.join(P.ex[i]['name'] for i in new))


def skeleton(blob, P):
    """RefSkeleton of a SkeletalMesh: (position of the count, [(entry start, name, numchildren position, parent)], end)"""
    for root in [i for i, n in enumerate(P.names) if n.lower() == 'bip01']:
        pat = write_ci(root); o = -1
        while True:
            o = blob.find(pat, o + 1)
            if o < 0: break
            try:
                q = struct.unpack_from('<4f', blob, o + len(pat) + 4)
                if abs(sum(x * x for x in q) - 1) > 1e-3: continue
                for back in (1, 2):
                    n, q2 = read_ci(blob, o - back)
                    if q2 == o and 1 < n < 256: break
                else: continue
                r = o; out = []
                for _ in range(n):
                    s0 = r; nm_, r = read_ci(blob, r); r += 4 + 44; nc = r; par = struct.unpack_from('<i', blob, r + 4)[0]; r += 8
                    if not (-1 <= par < n): raise ValueError
                    out.append((s0, P.names[nm_], nc, par))
                if out[0][3] != 0 and out[0][3] != -1: continue
                return o - back, out, r
            except (ValueError, struct.error, IndexError): continue
    return None

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

def patch_meshes(f):
    """sg1_anim.ukx: the Tok'ra meshes get the human bone_weapon (child of Bip01 R Hand, unweighted), so the weapon is held like
    the humans hold it: the human animations move bone_weapon per weapon (a gun in the grip, the staff turned ~95 degrees)"""
    d = bytes(open(f, 'rb').read()); P = Pkg(d)
    def mesh(n):
        r = [i for i, e in enumerate(P.ex) if e['name'] == n and P.clsname(e) == 'SkeletalMesh']
        if len(r) != 1: sys.exit('mesh %s not found' % n)
        return r[0]
    src = P.ex[mesh('sg1_crew_oneill')]; sb = d[src['off']:src['off'] + src['size']]
    sk = skeleton(sb, P)
    if not sk: sys.exit('sg1_crew_oneill skeleton not found')
    w = [b for b in sk[1] if b[1] == 'bone_weapon']
    if len(w) != 1 or sk[1][w[0][3]][1] != 'Bip01 R Hand': sys.exit('sg1_crew_oneill bone_weapon not found')
    nmw, q = read_ci(sb, w[0][0]); bone_data = sb[q:q + 48]                 # flags + BonePos (orientation, position, sizes)
    ARM = ['Bip01 %s Clavicle', 'bip01 %s Upperarm', 'Bip01 %s Forearm', 'Bip01 %s Hand', 'Bip01 %s ForeTwist', 'Bip01 %s ForeTwist1']
    ARM = [a % side for a in ARM for side in 'LR']
    osk = {x[1].lower(): x for x in sk[1]}
    def bpos(blob, entry):
        _, q = read_ci(blob, entry); return q + 4 + 16                      # name, flags, orientation -> position
    olen = {}
    for a in ARM:
        x = osk.get(a.lower())
        if not x: sys.exit('sg1_crew_oneill: no ' + a)
        v = struct.unpack_from('<3f', sb, bpos(sb, x[0])); olen[a.lower()] = math.sqrt(sum(c * c for c in v))
    def fit_arms(blob, bones):
        # O'Neill's arm bone lengths along the Tok'ra directions; None when already so
        out = bytearray(blob); changed = False
        for a in ARM:
            x = [y for y in bones if y[1].lower() == a.lower()]
            if len(x) != 1: sys.exit('no ' + a)
            pp = bpos(blob, x[0][0]); v = struct.unpack_from('<3f', blob, pp); L = math.sqrt(sum(c * c for c in v))
            if L < 1e-3: sys.exit('zero length ' + a)
            if abs(L - olen[a.lower()]) > 1e-3:
                k = olen[a.lower()] / L; struct.pack_into('<3f', out, pp, *[c * k for c in v]); changed = True
        return bytes(out) if changed else None
    new = {}
    for n in ('tokra_generic', 'tokra_selmak'):
        i = mesh(n); e = P.ex[i]; b = d[e['off']:e['off'] + e['size']]
        sk = skeleton(b, P)
        if not sk: sys.exit(n + ': skeleton not found')
        cpos, bones, end = sk
        if any(x[1].lower() == 'bone_weapon' for x in bones):              # bone already there (earlier version): arm lengths only
            fb = fit_arms(b, bones)
            if fb is not None:
                lz = lazy_arrays(b, e['off'])
                def move(at, fb=fb, lz=lz):
                    out = bytearray(fb)
                    for k, v in lz: struct.pack_into('<I', out, k, at + v)
                    return bytes(out)
                new[i] = move
            continue
        hand = [k for k, x in enumerate(bones) if x[1] == 'Bip01 R Hand']
        if len(hand) != 1 or len(bones) + 1 >= 64: sys.exit(n + ': unexpected skeleton')
        entry = write_ci(nmw) + bone_data + struct.pack('<ii', 0, hand[0])
        lz = lazy_arrays(b, e['off'])
        if not lz or any(k < end for k, v in lz): sys.exit(n + ': unexpected layout')
        nb = bytearray((fit_arms(b, bones) or b)[:end] + entry + b[end:])
        nb[cpos] = len(bones) + 1                                          # count (one byte below 64)
        nc = bones[hand[0]][2]; struct.pack_into('<i', nb, nc, struct.unpack_from('<i', nb, nc)[0] + 1)
        def make(at, nb=bytes(nb), lz=lz, ins=len(entry)):
            out = bytearray(nb)
            for k, v in lz: struct.pack_into('<I', out, k + ins, at + v + ins)
            return bytes(out)
        new[i] = make
    if not new: print('sg1_anim.ukx: Tok\'ra meshes already have bone_weapon and the human arm lengths'); return
    out = write_behind_table(d, P, new)
    Q = Pkg(bytes(out))
    for i in new:
        e = Q.ex[i]; b = out[e['off']:e['off'] + e['size']]; sk = skeleton(b, Q)
        if not sk or sk[1][-1][1] != 'bone_weapon' or fit_arms(b, sk[1]) is not None or len(lazy_arrays(b, e['off'])) != len(lazy_arrays(d[P.ex[i]['off']:P.ex[i]['off'] + P.ex[i]['size']], P.ex[i]['off'])):
            sys.exit('self check failed (%s)' % e['name'])
    bak = f + '.orig_mpweaponanims'
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(out))
    print('patched sg1_anim.ukx: bone_weapon / human arm lengths for %s' % ', '.join(P.ex[i]['name'] for i in new))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    files = [os.path.join(args[0], 'System', n) for n in ('StargateGame.u', 'StargateContent.u')] + [os.path.join(args[0], 'Animations', 'sg1_anim.ukx')]
    if '--revert' in sys.argv:
        for f in files:
            if os.path.exists(f + '.orig_mpweaponanims'): shutil.copyfile(f + '.orig_mpweaponanims', f); print('reverted', f)
        return
    patch_game(files[0]); patch_content(files[1]); patch_meshes(files[2])

main()
