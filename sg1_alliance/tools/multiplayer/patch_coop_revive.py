"""EXPERIMENTAL: in the campaign co-op mode (StoryModeGame, network game only) a player who reaches 0 health is knocked down like the AI
squadmates instead of dying, and another player can revive them.

What changes (System\\StargateGame.u, class StargatePawn):
 1. Died(): the "go unconscious instead of dying" branch, which only existed for AI bots, now also applies to a human player when the
    game is a network StoryModeGame. Deathmatch, single player and everything else are untouched.
 2. Trigger(): when another player finishes the "administer first aid" action on a downed player, the player gets up (Health 1,
    state PlayerWalking), the same way the AI squadmates do.
 3. UpdateUnconscious(): a downed player nobody revives within fShockTime seconds (60 by default) is lost: the game is ended
    with GameInfo.EndGame (the normal "mission failed" path: every player gets the game-ended fade and the Restart Level menu).
The three functions grow, so (like patch_coop_takeover.py) their new bodies are written into the unused ScriptText buffer of StoryModeGame;
jump targets, script sizes and export entries are fixed up and the file keeps its exact size.

Usage:  python patch_coop_revive.py "<game folder>"            apply (backup System\\StargateGame.u.orig_cooprevive)
        python patch_coop_revive.py "<game folder>" --revert   restore the backup
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
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_cooprevive'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    P = Pkg(bytes(d))
    def cls_ref(name):
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
    def imp(cls, name):
        r = [i for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name]
        if len(r) != 1: sys.exit('import %s.%s not found/unique' % (cls, name))
        return -(r[0] + 1)
    c_pawn = cls_ref('StargatePawn'); c_player = cls_ref('StargatePlayer'); c_smg = cls_ref('StoryModeGame')
    # the new bodies go into the unused source-text buffer of StoryModeGame (its offset is small enough for the 3-byte table entries;
    # the first 4 KB are left to patch_coop_takeover.py)
    tbuf = [i for i, e in enumerate(P.ex) if e['name'] == 'ScriptText' and e['outer'] == c_smg and e['size']]
    if len(tbuf) != 1: sys.exit('ScriptText of StoryModeGame not found')
    text = P.ex[tbuf[0]]
    names = P.names
    if 'PlayerWalking' not in names: sys.exit('name PlayerWalking not in package')
    n_walk = names.index('PlayerWalking')
    for nm_ in ('PlayerUnconscious', 'EndGame'):
        if nm_ not in names: sys.exit('name %s not in package' % nm_)
    n_unc = names.index('PlayerUnconscious'); n_endgame = names.index('EndGame')

    I = lambda r: b'\x01' + write_ci(r)
    L = lambda r: b'\x00' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    def AND(a, b): return b'\x82' + a + b'\x18' + struct.pack('<H', memlen(b) + 1) + b + b'\x16'   # Skip word = size + 1

    # ---- load the three functions
    fi = {n: func(n, c_pawn) for n in ('Died', 'Trigger', 'UpdateUnconscious')}
    info = {}
    for n, i in fi.items():
        e = P.ex[i]; szp, st, ssz, en = locate_script(bytes(d), e['off'], e['size'])
        fix = []; script = bytes(d[st:en]); stm = statements(script, fix)
        info[n] = dict(e=e, szp=szp, st=st, ssz=ssz, en=en, fix=fix, script=bytearray(script), stm=stm)
    died = info['Died']; trig = info['Trigger']; upd = info['UpdateUnconscious']
    if b'\x84\x77' in bytes(died['script'][:60]): print('already patched'); return

    # ---- references taken from existing code
    s0 = bytes(died['script'][died['stm'][0][0]:died['stm'][1][0]])
    k = s0.find(b'\x77\x2e')
    if k < 3 or s0[k - 3] != 0x18: sys.exit('Died has an unexpected layout')
    r_botenemy, o = read_ci(s0, k + 2)
    if s0[o] != 0x01: sys.exit('Died has an unexpected layout (2)')
    r_ctrl, o = read_ci(s0, o + 1)
    old_expr = s0[k:o + 2]
    if old_expr != b'\x77\x2e' + write_ci(r_botenemy) + b'\x01' + write_ci(r_ctrl) + b'\x2a\x16': sys.exit('Died has an unexpected layout (3)')
    if struct.unpack_from('<H', s0, k - 2)[0] != memlen(old_expr) + 1: sys.exit('Died has an unexpected layout (4)')
    # Level / NetMode from an existing  NetMode != x  test in StoryModeGame.Login
    c = [i for i, e in enumerate(P.ex) if e['name'] == 'Login' and e['outer'] == c_smg and e['size']]
    le = P.ex[c[0]]; _, lst, _, len_ = locate_script(bytes(d), le['off'], le['size']); lsc = bytes(d[lst:len_])
    m = lsc.find(b'\x9b\x39\x3a\x19\x01')
    if m < 0: sys.exit('NetMode test not found')
    r_level, o = read_ci(lsc, m + 5)
    if lsc[o:o + 4] != b'\x05\x00\x01\x01': sys.exit('NetMode test has an unexpected layout')
    r_netmode, o = read_ci(lsc, o + 4)
    r_game = imp('ObjectProperty', 'Game')
    r_pri = [-(i + 1) for i, im in enumerate(P.imports) if im[0] == 'ObjectProperty' and im[2] == 'PlayerReplicationInfo' and P.imports[-im[1] - 1][2] == 'Controller']
    if len(r_pri) != 1: sys.exit('Controller.PlayerReplicationInfo import not found')
    r_pri = r_pri[0]
    r_health = None
    tsc = bytes(trig['script']); m = tsc.find(b'\x98\x01')
    r_health, o = read_ci(tsc, m + 2)
    if tsc[o:o + 2] != b'\x25\x16': sys.exit('Trigger has an unexpected layout (health)')
    r_kd = member('KnockedDamage', c_pawn); r_shock = member('fShockTime', c_pawn)
    dt = [i + 1 for i, e in enumerate(P.ex) if e['name'] == 'DeltaTime' and e['outer'] == fi['UpdateUnconscious'] + 1]
    if len(dt) != 1: sys.exit('DeltaTime not found')

    SPCAST = b'\x2e' + write_ci(c_player) + I(r_ctrl)
    SPNN = b'\x77' + SPCAST + b'\x2a\x16'                                           # StargatePlayer(Controller) != None
    NETNE = b'\x9b\x39\x3a' + ctx(I(r_level), I(r_netmode), 1) + b'\x39\x3a\x24\x00\x16'   # Level.NetMode != NM_Standalone
    GAMEIS = b'\x77\x2e' + write_ci(c_smg) + ctx(I(r_level), I(r_game), 4) + b'\x2a\x16'      # StoryModeGame(Level.Game) != None
    GOTO = b'\x71\x21' + write_ci(n_walk) + b'\x16'                                  # GotoState('PlayerWalking')
    S_GOTO = ctx(SPCAST, GOTO, 0)

    def splice(info_, i, j, make, keep=()):
        """replace top-level statements [i, j) of a function by make(fixed old bytes); returns the memory growth"""
        script = info_['script']; stm = info_['stm']
        mems = []; mm = 0
        for s, a in stm: mems.append(mm); mm += a
        mend = mems[j] if j < len(stm) else mm
        old_s = stm[i][0]; old_e = stm[j][0]
        old_mem = mend - mems[i]
        # fix targets first (on the old bytes), so that replaced statements carry corrected words
        for fp in info_['fix']:
            if fp in keep: continue
            t = struct.unpack_from('<H', script, fp)[0]
            if t >= mend and t != 0xffff: struct.pack_into('<H', script, fp, t + GROW[0])
        new = make(bytes(script[old_s:old_e]), mems[i])
        info_['script'] = script[:old_s] + new + script[old_e:]
        return memlen(new) - old_mem

    # sizes must be known before targets are fixed: do a dry run of the builders to learn the growth
    # ---- 1. Died: widen the condition of the first statement
    new_expr = b'\x84' + old_expr + b'\x18'
    cond_h = AND(SPNN, AND(NETNE, GAMEIS))
    new_expr += struct.pack('<H', memlen(cond_h) + 1) + cond_h + b'\x16'
    grow_died = memlen(new_expr) - memlen(old_expr)
    def mk_died(old, mem0):
        k = old.find(old_expr)
        w = struct.pack('<H', memlen(new_expr) + 1)
        return old[:k - 2] + w + new_expr + old[k + len(old_expr):]
    GROW = [grow_died]
    d1 = splice(died, 0, 1, mk_died)
    assert d1 == grow_died, (d1, grow_died)

    # ---- 2. Trigger: after the bot branch, revive a player
    stm = trig['stm']; script = bytes(trig['script'])
    n = len(stm)
    if script[stm[-1][0]] != 0x47 or script[stm[-2][0]] != 0x04: sys.exit('Trigger has an unexpected layout')
    end_unc = bytes(script[stm[-3][0]:stm[-2][0]])
    if end_unc[0] not in (0x1b, 0x1c) or end_unc[-1] != 0x16 or len(end_unc) > 8: sys.exit('Trigger has an unexpected layout (EndUnconscious)')
    mems = []; mm = 0
    for s, a in stm: mems.append(mm); mm += a
    P_ins = mems[n - 2]                                   # memory position of the final "return"
    blk_len = 1 + 2 + memlen(SPNN) + memlen(end_unc) + memlen(S_GOTO)
    new_t = b'\x07' + struct.pack('<H', P_ins + blk_len) + SPNN + end_unc + S_GOTO
    assert memlen(new_t) == blk_len
    # the jump of  "if BotBase(Controller) != None" must now land on the new block (= keep its target), all others skip it
    keep = []
    for fp in trig['fix']:
        t = struct.unpack_from('<H', script, fp)[0]
        if t == P_ins:
            # statement that owns this word
            own = [s for s, a in stm if s <= fp][-1]
            if script[own] == 0x07 and b'\x77\x2e' in script[own:own + 12]: keep.append(fp)
    if len(keep) != 1: sys.exit('Trigger has an unexpected layout (bot branch)')
    GROW[0] = blk_len
    g2 = splice(trig, n - 2, n - 2, lambda old, m: new_t, keep=keep)
    assert g2 == blk_len

    # ---- 3. UpdateUnconscious: nobody revived the player within fShockTime -> the player is lost, the mission fails
    stm = upd['stm']; script = bytes(upd['script']); n = len(stm)
    if script[stm[-1][0]] != 0x47 or script[stm[-2][0]] != 0x04: sys.exit('UpdateUnconscious has an unexpected layout')
    mems = []; mm = 0
    for s, a in stm: mems.append(mm); mm += a
    P_ins = mems[n - 2]
    T1 = b'\xb9' + I(r_kd) + L(dt[0]) + b'\x16'                                        # KnockedDamage += DeltaTime
    ISIN = ctx(I(r_ctrl), b'\x61\x19\x21' + write_ci(n_unc) + b'\x16', 4)             # Controller.IsInState('PlayerUnconscious')
    COND = AND(AND(AND(SPNN, NETNE), b'\xb1' + I(r_kd) + I(r_shock) + b'\x16'), ISIN)  # player && netgame && KnockedDamage > fShockTime && still down
    msg = b'\x1f' + b'A squad member was lost.' + b'\x00'
    ENDG = ctx(ctx(I(r_level), I(r_game), 4),
               b'\x1b' + write_ci(n_endgame) + ctx(I(r_ctrl), I(r_pri), 4) + msg + b'\x16', 0)   # Level.Game.EndGame(Controller.PlayerReplicationInfo, "...")
    base = P_ins + memlen(T1)
    t_end = base + 1 + 2 + memlen(COND) + memlen(ENDG)
    new_u = T1 + b'\x07' + struct.pack('<H', t_end) + COND + ENDG
    GROW[0] = memlen(new_u)
    g3 = splice(upd, n - 2, n - 2, lambda old, m: new_u)
    assert g3 == memlen(new_u)

    # ---- write the new bodies into the ScriptText buffer, re-point the export entries
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    cur = text['off'] + 4096
    for nme in ('Died', 'Trigger', 'UpdateUnconscious'):
        inf = info[nme]; e = inf['e']
        blob = bytearray(d[e['off']:e['off'] + e['size']])
        q = inf['szp'] - e['off']; s0_ = inf['st'] - e['off']; e0_ = inf['en'] - e['off']
        newscr = bytes(inf['script'])
        nblob = bytes(blob[:q]) + struct.pack('<i', memlen(newscr)) + bytes(blob[q + 4:s0_]) + newscr + bytes(blob[e0_:])
        if cur + len(nblob) > text['off'] + text['size']: sys.exit('source-text buffer too small')
        szc = fit(len(nblob), e['offp'] - e['szp']); offc = fit(cur, e['end'] - e['offp'])
        d[cur:cur + len(nblob)] = nblob
        d[e['szp']:e['offp']] = szc; d[e['offp']:e['end']] = offc
        inf['new_off'] = cur; inf['new_size'] = len(nblob); inf['new_mem'] = memlen(newscr)
        cur += len(nblob) + 8
    # ---- verify
    P2 = Pkg(bytes(d))
    for nme in ('Died', 'Trigger', 'UpdateUnconscious'):
        e2 = P2.ex[fi[nme]]; inf = info[nme]
        assert e2['off'] == inf['new_off'] and e2['size'] == inf['new_size'] and len(d) == os.path.getsize(f)
        a, b, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
        assert c_ == inf['new_mem']
    open(f, 'wb').write(bytes(d))
    print('patched: players are knocked down (not killed) in network StoryModeGame and can be revived (60 s to revive them, otherwise the mission fails)')

main()
