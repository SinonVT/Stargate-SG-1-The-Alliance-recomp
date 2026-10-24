"""EXPERIMENTAL: a player who joins a campaign co-op game takes over the AI squadmate they picked, instead of appearing as an extra character.

When a joining player picks a character whose roster slot is already used by an AI squadmate (the host's match starts with the squad
filled up with AI), the old code only printed "Character is already taken!!!" and the player spawned as a duplicate. This patch replaces
that message with code that finds the AI controller+pawn of that same character, destroys them and gives its slot back to the game
(NumBots is reduced so the player count stays the same). The joiner then spawns at the normal player start as that character.

How: StoryModeGame.Login (System\\StargateGame.u) gets 3 more statements. They do not fit in the old function, so the new function body is
written into the (unused at run time) source-text buffer of the same class, the script-size field and all jump targets that follow the
insertion are corrected, and the export table entry of Login is re-pointed. The file keeps its exact size.

Usage:  python patch_coop_takeover.py "<game folder>"            apply (backup System\\StargateGame.u.orig_coopnpc)
        python patch_coop_takeover.py "<game folder>" --revert   restore the backup
Needs patch_coop_chars.py applied or not - the two are independent. Run on every PC that hosts or joins.
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
def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_coopnpc'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    P = Pkg(bytes(d))
    smg = [i for i, e in enumerate(P.ex) if e['name'] == 'StoryModeGame' and P.clsname(e) == 'Class']
    if len(smg) != 1: sys.exit('StoryModeGame not found')
    smg_ref = smg[0] + 1
    li = [i for i, e in enumerate(P.ex) if e['name'] == 'Login' and e['outer'] == smg_ref and e['size']]
    tb = [i for i, e in enumerate(P.ex) if e['name'] == 'ScriptText' and e['outer'] == smg_ref and e['size']]
    if len(li) != 1 or len(tb) != 1: sys.exit('Login / ScriptText not found')
    login = P.ex[li[0]]; text = P.ex[tb[0]]
    sz_pos, st, ssz, en = locate_script(bytes(d), login['off'], login['size'])

    def find_ex(name, outer):
        r = [i + 1 for i, e in enumerate(P.ex) if e['name'] == name and e['outer'] == outer]
        if len(r) != 1: sys.exit('%s not found' % name)
        return r[0]
    def find_imp(cls, name):
        r = [i for i, im in enumerate(P.imports) if im[0] == cls and im[2] == name]
        if len(r) != 1: sys.exit('import %s.%s not found/unique' % (cls, name))
        return -(r[0] + 1)
    login_ref = li[0] + 1
    r_testpawn = find_ex('TestPawn', login_ref); r_chosen = find_ex('ChosenRoster', login_ref)
    botbase = [i + 1 for i, e in enumerate(P.ex) if e['name'] == 'BotBase' and P.clsname(e) == 'Class']
    if len(botbase) != 1: sys.exit('BotBase not found')
    r_botbase = botbase[0]; r_initroster = find_ex('InitialRoster', r_botbase)
    r_pawncls = find_imp('Class', 'Pawn'); r_numbots = find_imp('IntProperty', 'NumBots')
    r_ctrl = find_imp('ObjectProperty', 'Controller')
    if P.imports[-find_imp('Class', 'Pawn') - 1][2] != 'Pawn': sys.exit('internal')

    # walk statements: find the Warn("Character is already taken!!!") statement and every jump word
    script = bytearray(d[st:en]); fix = []
    p = 0; stmts = []
    while True:
        s = p; a, p = tok(bytes(script), p, fix); stmts.append((s, a)); 
        if script[s] == 0x47: break
    mem = 0; warn = None; pos = []
    for s, a in stmts:
        pos.append(mem)
        if script[s] == 0xe8 and b'Character is already taken' in script[s:s + a + 10] and warn is None: warn = (s, a, mem)
        mem += a
    already_new = any(script[s] == 0x2f and b'\x2e' + write_ci(r_botbase) in script[s:s + 40] for s, a in stmts)
    if warn is None:
        if already_new: print('already patched'); return
        sys.exit('Login has an unexpected layout (Warn statement not found)')
    ws, wmem_len, wmem = warn
    # serial length of the Warn statement
    tmp = []; _a, wend_pos = tok(bytes(script), ws, tmp)
    old_ser = wend_pos - ws

    # ---- assemble the new statements
    L = lambda r: b'\x00' + write_ci(r)
    I = lambda r: b'\x01' + write_ci(r)
    def ctx(e1, e2, size): return b'\x19' + e1 + struct.pack('<H', memlen(e2)) + bytes([size]) + e2
    TP = L(r_testpawn); CH = L(r_chosen)
    CTRL = ctx(TP, I(r_ctrl), 4)
    CAST = b'\x2e' + write_ci(r_botbase) + CTRL
    c1 = b'\x77' + CAST + b'\x2a\x16'
    c2 = b'\x72' + ctx(CAST, I(r_initroster), 4) + CH + b'\x16'
    # (the Skip word is the size of the skipped expression + 1, as the compiler writes it)
    cond = b'\x82' + c1 + b'\x18' + struct.pack('<H', memlen(c2) + 1) + c2 + b'\x16'
    DESTROY = b'\x61\x17\x16'
    body = b'\xa6' + I(r_numbots) + b'\x16' + ctx(CTRL, DESTROY, 0) + ctx(TP, DESTROY, 0)
    enum = b'\x61\x39' + b'\x20' + write_ci(r_pawncls) + TP + b'\x16'
    hdr_mem = 1 + memlen(enum) + 2
    pos_if = wmem + hdr_mem
    pos_body = pos_if + 3 + memlen(cond)
    pos_next = pos_body + memlen(body)
    pos_pop = pos_next + 1
    new_end = pos_pop + 1
    new = (b'\x2f' + enum + struct.pack('<H', pos_pop) + b'\x07' + struct.pack('<H', pos_next) + cond + body + b'\x31\x30')
    assert memlen(new) == new_end - wmem
    delta = (new_end - wmem) - wmem_len
    old_end_mem = wmem + wmem_len

    # ---- correct jump targets behind the insertion
    for fp in fix:
        t = struct.unpack_from('<H', script, fp)[0]
        if t >= old_end_mem and t != 0xffff: struct.pack_into('<H', script, fp, t + delta)
    nscript = bytes(script[:ws]) + new + bytes(script[ws + old_ser:])
    assert memlen(nscript) == ssz + delta

    # ---- new function blob
    blob = bytearray(d[login['off']:login['off'] + login['size']])
    q = sz_pos - login['off']
    blob[q:q + 4] = struct.pack('<i', ssz + delta)
    s0 = st - login['off']; e0 = en - login['off']
    nblob = bytes(blob[:s0]) + nscript + bytes(blob[e0:])
    # the old (same-length) script may only be reused when nothing before had to change: recompute table entry
    toff = text['off'] + 64
    if len(nblob) + 64 > text['size']: sys.exit('source-text buffer too small')
    new_sz_ci = write_ci(len(nblob)); new_off_ci = write_ci(toff)
    if len(new_sz_ci) != login['offp'] - login['szp'] or len(new_off_ci) != login['end'] - login['offp']:
        sys.exit('table entry would change length')
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    d[toff:toff + len(nblob)] = nblob
    d[login['szp']:login['offp']] = new_sz_ci
    d[login['offp']:login['end']] = new_off_ci
    # ---- verify
    P2 = Pkg(bytes(d))
    l2 = P2.ex[li[0]]
    assert l2['off'] == toff and l2['size'] == len(nblob) and len(d) == os.path.getsize(f)
    a, b, c, e2 = locate_script(bytes(d), l2['off'], l2['size'])
    assert c == ssz + delta
    open(f, 'wb').write(bytes(d))
    print('patched: a joining player takes over the AI squadmate of the chosen character (Login grew by %d memory bytes)' % delta)

main()
