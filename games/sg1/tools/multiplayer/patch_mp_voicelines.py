"""Fix 27: voice lines for Jacob / Selmak and the Jaffa in multiplayer (the V voice menu / Taunt MSGID_... keys).
Their voice packs have no lines for most of the menu's messages (Jacob has none at all), so ServerTaunt's SGVoicePack.Say() did nothing.
Now (StargateGame.u, UnrealPlayer.ServerTaunt, bytecode only) when Say() finds no line, the server plays one itself:
    if (!StargatePawn(Pawn).SGVoicePack.Say(AnimName))
        if (string(Pawn.Class) == "StargateContent.Jacob_Selmak")          a Jacob line (table JACOB)
        else if (InStr(string(Pawn.Class), "StargateContent.Jaffa") == 0)  a Jaffa line (table JAFFA)
    Pawn.PlaySound(Sound(DynamicLoadObject(<line>, class'Sound')), SLOT_Talk, 1.0, false, 300)   (= the voice packs' volume / radius)
The sound is played on the server and reaches every player like the other voice lines.
Jaffa lines: JaffaSounds (always loaded: StargateContent uses it).
Jacob lines: his M13 mission dialogue, Speech/M13_Final/*.wav (Xbox ADPCM, played as streams there). Streams are local only, so the
chosen files are put into a small sound package of their own, Sounds/SGMPVoices.uax (built here from those WAVs), and
UnrealEngine2.ini gets ServerPackages=SGMPVoices (a sound only reaches the clients from a package the server had loaded when the
game opened). Sound packages are not in System/Packages.md5, so a new one does not trip the join check.
Usage: python patch_mp_voicelines.py "<game folder>" [--revert]   (backups <file>.orig_mpvoicelines)
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

# message -> lines (one is picked at random). Jaffa: the light Jaffa ("lija") recordings of JaffaSounds.
VPKG = 'SGMPVoices'
SPEECH = 'M13_Final'
# Jacob: chosen by listening (Speech/M13_Final)
JACOB = {
    'MSGID_Taunt':            ['m13_07_f_jacob', 'm13_07_a_jacob'],   # "So what are you doing here?" / "What are you guys doing here?"
    'MSGID_NotOk':            ['m13_07_i_jacob'],                     # "What?"
    'MSGID_SpotEnemy':        ['m13_12_a_jacob'],                     # "They're in here already, we need to stop them"
    'MSGID_TakeCover':        ['m13_jacob_follow4'],                  # "Let's move!"
    'MSGID_AllEnemiesKilled': ['m13_jacob_follow5'],                  # "Let's move" (area clear)
    'MSGID_EnemyKilled':      ['m13_15_a_jacob'],                     # "There goes another one.. we're running out of time here"
}
J = 'JaffaSounds.'
JAFFA = {
    'MSGID_Taunt':            [J + 'Alert.lija_attack_ge_c_%02d' % n for n in (13, 14, 15, 16)],    # battle cries (the Alert set)
    'MSGID_Ok':               [J + 'Suspicious.lija_spotsomething_ge_c_%02d' % n for n in (9, 10, 11)],  # the "standing down" set
    'MSGID_NotOk':            [J + 'Suspicious.lija_spotsomething_ge_c_%02d' % n for n in (5, 6, 7, 8)], # the "suspicious" set
    'MSGID_Ready':            [J + 'Alert.lija_attack_ge_n_01', J + 'Alert.lija_attack_ge_n_03'],
    'MSGID_SpotEnemy':        [J + 'Suspicious.lija_spotenemy_ge_c_01a', J + 'Suspicious.lija_spotenemy_ge_c_01b', J + 'Suspicious.lija_spotenemy_ge_c_01c'],
    'MSGID_TakeCover':        [J + 'Tactical.lija_takecover_ge_c_01', J + 'Tactical.lija_takecover_ge_c_02'],
    'MSGID_EnemyKilled':      [J + 'Alert.lija_attack_ge_c_%02d' % n for n in (1, 3, 4)],
    'MSGID_AllEnemiesKilled': [J + 'Suspicious.lija_spotsomething_ge_c_%02d' % n for n in (9, 10, 11)],
    'MSGID_UnderFire':        [J + 'Tactical.lija_underfire_ge_c_01', J + 'Tactical.lija_underfire_ge_c_02'],
    'MSGID_TeamUnderFire':    [J + 'Tactical.lija_underfire_ge_c_01', J + 'Tactical.lija_underfire_ge_c_02'],
    'MSGID_ManDown':          [J + 'Suspicious.lija_spotdeadbody_ge_n_01'],
    'MSGID_InCoverPosition':  [J + 'Tactical.lija_takecover_ge_n_01'],
    'MSGID_HoldingFire':      [J + 'Tactical.lija_retreat_ge_n_01'],
    'MSGID_Firing':           [J + 'Alert.lija_attack_ge_c_%02d' % n for n in (5, 6, 8)],
    'MSGID_FriendlyFire':     [J + 'Pain.lija_wounded_ge_c_%02d' % n for n in (1, 2, 3)],
}
MARK = b'StargateContent.Jaffa\x00'
MARK2 = VPKG.encode() + b'.'
OLD = b'M13Sounds.'                          # first version (Jacob's two M13Sounds lines)

def patch_game(f):
    d = bytearray(open(f, 'rb').read()); P = Pkg(bytes(d)); top, imp, member, nm = finder(P)
    up = top('UnrealPlayer'); fn = member(up, 'ServerTaunt'); sc = get_script(d, P, fn)
    if OLD in sc or (MARK in sc and MARK2 not in sc):                     # an older version: redo from the backup
        bak = f + '.orig_mpvoicelines'
        if not os.path.exists(bak): sys.exit('first version of this patch found and no backup to redo it from')
        d = bytearray(open(bak, 'rb').read()); P = Pkg(bytes(d)); top, imp, member, nm = finder(P)
        up = top('UnrealPlayer'); fn = member(up, 'ServerTaunt'); sc = get_script(d, P, fn)
        if MARK in sc or OLD in sc: sys.exit('the backup %s is not the unpatched file' % bak)
        print('StargateGame.u: redoing the patch from', bak)
    elif MARK2 in sc: print('StargateGame.u: already patched'); return
    stm = statements(sc, [])
    if len(stm) != 3 or sc[stm[0][0]] != 0x19 or b'\x1b' + nm('Say') not in sc: sys.exit('ServerTaunt: run patch_coop_voicetaunt.py first')
    SAY = sc[stm[0][0]:stm[1][0]]
    arg = [i + 1 for i, x in enumerate(P.ex) if x['outer'] == fn + 1 and x['name'] == 'AnimName']
    if len(arg) != 1: sys.exit('AnimName not found')
    pawn = imp('ObjectProperty', 'Controller', 'Pawn'); clsprop = imp('ClassProperty', 'Object', 'Class')
    snd = imp('Class', None, 'Sound'); dlo = imp('Function', 'Object', 'DynamicLoadObject')
    PAWN = I(pawn)
    CLS = b'\x39\x56' + ctx(PAWN, I(clsprop), 4)                          # string(Pawn.Class)
    def s(t): return b'\x1f' + t.encode('latin1') + b'\x00'
    def f32(v): return b'\x1e' + struct.pack('<f', v)
    def play(path):                                                         # Pawn.PlaySound(Sound(DLO(path, class'Sound')), SLOT_Talk, 1.0, false, 300)
        call = (b'\x61\x08' + b'\x2e' + write_ci(snd) + b'\x1c' + write_ci(dlo) + s(path) + b'\x20' + write_ci(snd) + b'\x16'
                + b'\x24\x05' + f32(1.0) + b'\x28' + f32(300.0) + b'\x16')
        return ctx(PAWN, call, 0)
    def isid(msg): return b'\xfe\x00' + write_ci(arg[0]) + b'\x21' + nm(msg) + b'\x16'      # AnimName == 'MSGID_...'
    lab = [0]
    def L():
        lab[0] += 1; return 'l%d' % lab[0]
    def table(t):
        items = []
        for msg, lines in t.items():
            nxt = L(); items.append(('j', 7, nxt, isid(msg)))
            for k, path in enumerate(lines):                                 # Rand(n)==0 for n = left .. 1: each line equally likely
                left = len(lines) - k
                if left > 1:
                    skip = L(); items += [('j', 7, skip, b'\x9a\xa7\x2c' + bytes([left]) + b'\x16\x25\x16'), play(path), ('j', 6, 'out', None), ('L', skip)]
                else:
                    items += [play(path), ('j', 6, 'out', None)]
            items.append(('L', nxt))
        return items
    jaffa = L()
    jt = {m: [VPKG + '.' + n for n in v] for m, v in JACOB.items()}
    items = [('j', 7, 'out', b'\x81' + SAY + b'\x16'),
             ('j', 7, jaffa, b'\x7a' + CLS + s('StargateContent.Jacob_Selmak') + b'\x16')] + table(jt) + [('j', 6, 'out', None), ('L', jaffa),
             ('j', 7, 'out', b'\x9a\x7e' + CLS + s('StargateContent.Jaffa') + b'\x16\x25\x16')] + table(JAFFA) + [('L', 'out')]
    newscr = rebuild(sc, None, {stm[0][0]: Asm(items)})
    check(newscr)
    bak = f + '.orig_mpvoicelines'
    relocate(d, P, fn, newscr)
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(bytes(d))
    print('patched StargateGame.u: UnrealPlayer.ServerTaunt (Jacob %d, Jaffa %d messages)' % (len(JACOB), len(JAFFA)))

def riff_clean(w, name):
    """keep fmt + data only (like the game's own voice sounds); must be Xbox ADPCM"""
    if w[:4] != b'RIFF' or w[8:12] != b'WAVE': sys.exit(name + ': not a WAV')
    o = 12; fmt = data = None
    while o + 8 <= len(w):
        cid = w[o:o + 4]; sz = struct.unpack_from('<I', w, o + 4)[0]
        if cid == b'fmt ': fmt = w[o + 8:o + 8 + sz]
        elif cid == b'data': data = w[o + 8:o + 8 + sz]
        o += 8 + sz + (sz & 1)
    if not fmt or data is None or struct.unpack_from('<H', fmt, 0)[0] != 0x69: sys.exit(name + ': not Xbox ADPCM')
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(data)) + data
    return b'RIFF' + struct.pack('<I', len(body)) + body

def build_voices(game):
    """Sounds/SGMPVoices.uax: one Sound per chosen WAV, laid out like the game's own sound packages (version 127)"""
    import hashlib
    sounds = sorted({n for v in JACOB.values() for n in v})
    waves = []
    for n in sounds:
        src = os.path.join(game, 'Speech', SPEECH, n + '.wav')
        if not os.path.exists(src): sys.exit('missing ' + src)
        waves.append(riff_clean(open(src, 'rb').read(), n))
    names = ['WAV', 'None', 'Package', 'Class', 'Sound', 'Engine', 'Core'] + sounds + [VPKG]
    nt = b''.join(write_ci(len(n) + 1) + n.encode('latin1') + b'\0' + struct.pack('<I', 0x00070010) for n in names)
    imports = (write_ci(6) + write_ci(3) + struct.pack('<i', -2) + write_ci(4)          # Core.Class Engine.Sound
               + write_ci(6) + write_ci(2) + struct.pack('<i', 0) + write_ci(5))        # Core.Package Engine
    guid = hashlib.md5(b''.join(waves) + VPKG.encode()).digest()
    head = 64; at = head + len(nt); blobs = []
    for w in waves:                                                    # None, FileType 'WAV', 1.0, [end offset][count][data]
        pre = write_ci(1) + write_ci(0) + struct.pack('<f', 1.0)
        body = write_ci(len(w)) + w
        blobs.append(pre + struct.pack('<i', at + len(pre) + 4 + len(body)) + body); at += len(blobs[-1])
    io = at; eo = io + len(imports); exp = b''; off = head + len(nt)
    for i, b in enumerate(blobs):
        exp += write_ci(-1) + write_ci(0) + struct.pack('<i', 0) + write_ci(7 + i) + struct.pack('<I', 0x000F0004) + write_ci(len(b)) + write_ci(off)
        off += len(b)
    hdr = struct.pack('<IHHIIIIIII', 0x9E2A83C1, 127, 2, 1, len(names), head, len(blobs), eo, 2, io) + guid + struct.pack('<iii', 1, len(blobs), len(names))
    out = hdr + b'\0' * (head - len(hdr)) + nt + b''.join(blobs) + imports + exp
    Q = Pkg(out)
    if Q.names != names or [e['name'] for e in Q.ex] != sounds: sys.exit('self check failed (voice package)')
    for e in Q.ex:
        b = out[e['off']:e['off'] + e['size']]
        if struct.unpack_from('<i', b, 6)[0] != e['off'] + e['size']: sys.exit('self check failed (voice package)')
    f = os.path.join(game, 'Sounds', VPKG + '.uax')
    if os.path.exists(f) and open(f, 'rb').read() == out: print(VPKG + '.uax: up to date'); return
    open(f, 'wb').write(out); print('%s.uax: %d Jacob lines' % (VPKG, len(sounds)))

def patch_ini(f):
    if not os.path.exists(f): sys.exit('no ' + f)
    raw = open(f, 'rb').read(); nl = b'\r\n' if b'\r\n' in raw else b'\n'
    lines = raw.split(nl); want = b'ServerPackages=' + VPKG.encode()
    if any(l.strip().lower() == want.lower() for l in lines): print('UnrealEngine2.ini: already has', want.decode()); return
    at = [i for i, l in enumerate(lines) if l.strip().lower().startswith(b'serverpackages=')]
    if not at: sys.exit('no ServerPackages lines in ' + f)
    if not os.path.exists(f + '.orig_mpvoicelines'): shutil.copyfile(f, f + '.orig_mpvoicelines')
    lines.insert(at[-1] + 1, want)
    open(f, 'wb').write(nl.join(lines)); print('UnrealEngine2.ini: added', want.decode())

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u'); ini = os.path.join(args[0], 'System', 'UnrealEngine2.ini')
    if '--revert' in sys.argv:
        for x in (f, ini):
            if os.path.exists(x + '.orig_mpvoicelines'): shutil.copyfile(x + '.orig_mpvoicelines', x); print('reverted', x)
        return
    build_voices(args[0]); patch_ini(ini); patch_game(f)

main()
