"""EXPERIMENTAL: client-side fixes for the co-op revive (see patch_coop_revive.py). Needs patch_coop_revive.py applied first.

On a joining client:
 1. StargatePawn.PlayWaiting: a downed (bBeingUnconscious) pawn of another player was drawn standing, because the knock-down animation is only
    played on the server. The client now loops the unconscious animation for any downed pawn (the replicated flags bBeingUnconscious and
    bKnockedBackward decide which one) and blends out the torso layers.
 2. StargatePawn.EndUnconscious: the revive trigger was destroyed in the same tick the revive finished, so the client never received the
    "complete" state and the REVIVING progress bar stayed on the screen. The trigger now lives one more second (LifeSpan) so it replicates.
 3. ProgressTrigger.PostNetReceive: when a replicated progress state changes to anything but "progressing", the client hides the progress bar.
New function bodies go to the unused ScriptText buffer of StoryModeGame (+8192 and up); the file keeps its exact size.

Usage:  python patch_coop_clientfx.py "<game folder>"            apply (backup System\\StargateGame.u.orig_coopclientfx)
        python patch_coop_clientfx.py "<game folder>" --revert   restore the backup
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
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_coopclientfx'
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
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == outer]
        if len(r) != 1: sys.exit('%s not found' % name)
        return r[0]
    def func(name, outer):
        r = [i for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == outer and e['size']]
        if len(r) != 1: sys.exit('function %s not found' % name)
        return r[0]
    def imp(cls, name, owner):
        r = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name and P.imports[-im[1] - 1][2] == owner]
        if len(r) != 1: sys.exit('import %s.%s not found/unique' % (owner, name))
        return r[0]
    def nm(n):
        if n not in P.names: sys.exit('name %s not in package' % n)
        return P.names.index(n)
    c_pawn = top('StargatePawn'); c_prog = top('ProgressTrigger'); c_player = top('StargatePlayer'); c_smg = top('StoryModeGame')
    tbuf = [i for i, e in enumerate(P.ex) if e['name'] == 'ScriptText' and e['outer'] == c_smg and e['size']]
    if len(tbuf) != 1: sys.exit('ScriptText of StoryModeGame not found')
    text = P.ex[tbuf[0]]

    I = lambda r: b'\x01' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    def AND(a, b): return b'\x82' + a + b'\x18' + struct.pack('<H', memlen(b) + 1) + b + b'\x16'
    F1 = b'\x1e\x00\x00\x80\x3f'; F01 = b'\x1e\xcd\xcc\xcc\x3d'; F0 = b'\x1e\x00\x00\x00\x00'

    fns = {}
    for key, cls_, name in (('PW', c_pawn, 'PlayWaiting'), ('EU', c_pawn, 'EndUnconscious'), ('PN', c_prog, 'PostNetReceive')):
        e = P.ex[func(name, cls_)]; szp, st, ssz, en = locate_script(bytes(d), e['off'], e['size'])
        fix = []; script = bytes(d[st:en]); stm = statements(script, fix)
        fns[key] = dict(e=e, szp=szp, st=st, en=en, fix=fix, script=script, stm=stm)
    pw, eu, pn = fns['PW'], fns['EU'], fns['PN']
    if pw['script'][0] == 0x07 and pw['script'][3] == 0x82 and pw['script'][4] == 0x2d:
        print('already patched'); return

    def retarget(fn, mem_from, delta):
        sc = bytearray(fn['script'])
        for fp in fn['fix']:
            t = struct.unpack_from('<H', sc, fp)[0]
            if t != 0xffff and t >= mem_from: struct.pack_into('<H', sc, fp, t + delta)
        fn['script'] = bytes(sc)

    # ---- 1. PlayWaiting: prepend the client-side "lying down" block
    r_unc = member('bBeingUnconscious', c_pawn); r_back = member('bKnockedBackward', c_pawn)
    r_ab = member('UnconsciousAnimB', c_pawn); r_af = member('UnconsciousAnimF', c_pawn)
    r_role = imp('ByteProperty', 'Role', 'Actor')
    n_loop = nm('LoopIfNeeded')
    # AnimBlendToAlpha(channel, 0, 0.1): final function reference copied from AnimEnd
    ae = fns.get('AE')
    aeinfo = [i for i, e in enumerate(P.ex) if e['name'] == 'AnimEnd' and e['outer'] == c_pawn and e['size']]
    if len(aeinfo) != 1: sys.exit('AnimEnd not found')
    e_ = P.ex[aeinfo[0]]; _, s_, _, n_ = locate_script(bytes(d), e_['off'], e_['size']); aes = bytes(d[s_:n_])
    k = aes.find(b'\x1c')
    while k >= 0:
        r_ab2, o = read_ci(aes, k + 1)
        if aes[o:o + 2] == b'\x2c\x0f' and aes[o + 2:o + 7] == F0: break
        k = aes.find(b'\x1c', k + 1)
    if k < 0: sys.exit('AnimBlendToAlpha reference not found')
    r_blend = r_ab2
    def BLEND(ch): return b'\x1c' + write_ci(r_blend) + b'\x2c' + bytes([ch]) + F0 + F01 + b'\x16'
    ELEM = lambda r: b'\x10\x25' + I(r)                                           # Array[0]
    def LOOP(r): return b'\x1b' + write_ci(n_loop) + ELEM(r) + F1 + F01 + b'\x16'
    BOOL = lambda r: b'\x2d' + I(r)
    COND = AND(BOOL(r_unc), b'\x9b\x39\x3a' + I(r_role) + b'\x39\x3a\x24\x04\x16')   # bBeingUnconscious && Role != ROLE_Authority
    inner = BLEND(10) + BLEND(11)
    # block layout (memory offsets relative to the start of the function)
    h = 1 + 2 + memlen(COND)
    m_blend = memlen(inner)
    m_if = 1 + 2 + memlen(BOOL(r_back))
    m_l1 = memlen(LOOP(r_ab)); m_j = 3; m_l2 = memlen(LOOP(r_af)); m_ret = memlen(b'\x04\x0b')
    p_inner = h; p_if = p_inner + m_blend; p_l1 = p_if + m_if; p_j = p_l1 + m_l1; p_l2 = p_j + m_j; p_ret = p_l2 + m_l2; p_end = p_ret + m_ret
    blk = (b'\x07' + struct.pack('<H', p_end) + COND + inner
           + b'\x07' + struct.pack('<H', p_l2) + BOOL(r_back) + LOOP(r_ab)
           + b'\x06' + struct.pack('<H', p_ret) + LOOP(r_af) + b'\x04\x0b')
    # ^ the jump after the first LOOP skips the second one: target = p_ret (the return)
    assert memlen(blk) == p_end
    # the "jumpifnot" of the whole block must land after the block: p_end   (done above)
    retarget(pw, 0, p_end)
    pw['script'] = blk + pw['script']

    # ---- 2. EndUnconscious: ReviveTrigger.Destroy()  ->  ReviveTrigger.LifeSpan = 1.0
    sc = eu['script']
    r_rt = member('ReviveTrigger', c_pawn)
    r_life = imp('FloatProperty', 'LifeSpan', 'Actor')
    old = b'\x19' + I(r_rt) + struct.pack('<H', 3) + b'\x04' + b'\x61\x17\x16'
    pos = sc.find(old)
    if pos < 0 or sc.find(old, pos + 1) >= 0: sys.exit('EndUnconscious has an unexpected layout')
    new = old   # SG1: keep ReviveTrigger.Destroy(); the LifeSpan = 1.0 variant killed the revived player ~1 s later (the client hides the bar itself, clientfx3)
    mem_end = memlen(sc[:pos + len(old)])
    delta = memlen(new) - memlen(old)
    retarget(eu, mem_end, delta)
    eu['script'] = eu['script'][:pos] + new + eu['script'][pos + len(old):]

    # ---- 3. ProgressTrigger.PostNetReceive: hide the progress bar when progress is not running
    r_old = member('OldProgState', c_prog); r_ps = member('ProgState', c_prog); r_up = member('UserPawn', c_prog)
    r_ctrl = imp('ObjectProperty', 'Controller', 'Pawn')
    SPC = b'\x2e' + write_ci(c_player) + ctx(I(r_up), I(r_ctrl), 4)                 # StargatePlayer(UserPawn.Controller)
    NE = lambda a, b: b'\x9b\x39\x3a' + a + b'\x39\x3a' + b + b'\x16'
    HIDEC = AND(AND(AND(NE(I(r_old), I(r_ps)), NE(I(r_ps), b'\x24\x01')), b'\x77' + I(r_up) + b'\x2a\x16'), b'\x77' + SPC + b'\x2a\x16')
    r_hide = [i for i, e in enumerate(P.ex) if e['name'] == 'HideProgressBar' and e['outer'] == c_player and e['size']]
    if len(r_hide) != 1: sys.exit('HideProgressBar not found')
    n_hide = nm('HideProgressBar')
    HIDE = ctx(SPC, b'\x1b' + write_ci(n_hide) + b'\x16', 0)
    blk3 = b'\x07' + struct.pack('<H', 3 + memlen(HIDEC) + memlen(HIDE)) + HIDEC + HIDE
    retarget(pn, 0, memlen(blk3))
    pn['script'] = blk3 + pn['script']

    # ---- write the new bodies into the ScriptText buffer
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    cur = text['off'] + 8192
    for key in ('PW', 'EU', 'PN'):
        inf = fns[key]; e = inf['e']
        blob = bytearray(d[e['off']:e['off'] + e['size']])
        q = inf['szp'] - e['off']; s0_ = inf['st'] - e['off']; e0_ = inf['en'] - e['off']
        newscr = inf['script']
        nblob = bytes(blob[:q]) + struct.pack('<i', memlen(newscr)) + bytes(blob[q + 4:s0_]) + newscr + bytes(blob[e0_:])
        if cur + len(nblob) > text['off'] + text['size']: sys.exit('source-text buffer too small')
        szc = fit(len(nblob), e['offp'] - e['szp']); offc = fit(cur, e['end'] - e['offp'])
        d[cur:cur + len(nblob)] = nblob
        d[e['szp']:e['offp']] = szc; d[e['offp']:e['end']] = offc
        inf['new_off'] = cur; inf['new_size'] = len(nblob); inf['new_mem'] = memlen(newscr)
        cur += len(nblob) + 8
    P2 = Pkg(bytes(d))
    for key, (cls_, name) in (('PW', (c_pawn, 'PlayWaiting')), ('EU', (c_pawn, 'EndUnconscious')), ('PN', (c_prog, 'PostNetReceive'))):
        e2 = P2.ex[func(name, cls_)]; inf = fns[key]
        assert e2['off'] == inf['new_off'] and e2['size'] == inf['new_size'] and len(d) == os.path.getsize(f)
        a, b, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
        assert c_ == inf['new_mem']
    open(f, 'wb').write(bytes(d))
    print('patched: downed players are drawn lying on the client, and the revive bar is cleared')

main()
