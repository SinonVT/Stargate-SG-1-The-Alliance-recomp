"""EXPERIMENTAL: the System Link server list always showed "0 / 16" for campaign (StoryModeGame) servers.

Cause: StoryModeGame has a state MatchInProgress that overrides GetServerInfo() with a body that only sets AdditionalInfo="GameStarted"
and never calls the real one, so the answer to a browser ping carried no player count / max players (the list then shows its defaults 0 / 16).
Since the campaign mode starts the match immediately (patch_coop_start.py) the server is always in that state.

Fix: the state's GetServerInfo now first calls the global (normal) GetServerInfo(ServerState) and then sets AdditionalInfo as before.
The new body is written into the unused ScriptText buffer of StoryModeGame (+12288); the file keeps its exact size.

Usage:  python patch_coop_listinfo.py "<game folder>"            apply (backup System\\StargateGame.u.orig_cooplistinfo)
        python patch_coop_listinfo.py "<game folder>" --revert   restore the backup
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
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_cooplistinfo'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    P = Pkg(bytes(d))
    smg = [i + 1 for i, e in enumerate(P.ex) if e['name'] == 'StoryModeGame' and e['outer'] == 0 and P.clsname(e) == 'Class']
    if len(smg) != 1: sys.exit('StoryModeGame not found')
    smg = smg[0]
    st = [i + 1 for i, e in enumerate(P.ex) if e['name'] == 'MatchInProgress' and e['outer'] == smg]
    if len(st) != 1: sys.exit('state MatchInProgress not found')
    fn = [i for i, e in enumerate(P.ex) if e['name'] == 'GetServerInfo' and e['outer'] == st[0] and e['size']]
    if len(fn) != 1: sys.exit('state GetServerInfo not found')
    e = P.ex[fn[0]]
    tb = [i for i, x in enumerate(P.ex) if x['name'] == 'ScriptText' and x['outer'] == smg and x['size']]
    if len(tb) != 1: sys.exit('ScriptText of StoryModeGame not found')
    text = P.ex[tb[0]]
    n_gsi = P.names.index('GetServerInfo')
    szp, st0, ssz, en = locate_script(bytes(d), e['off'], e['size'])
    script = bytes(d[st0:en])
    if script[0] == 0x38: print('already patched'); return
    if script[:2] != b'\x0f\x36': sys.exit('GetServerInfo (state) has an unexpected layout')
    r_member, o = read_ci(script, 2)
    if script[o] != 0x00: sys.exit('GetServerInfo (state) has an unexpected layout (2)')
    r_local, o = read_ci(script, o + 1)
    call = b'\x38' + write_ci(n_gsi) + b'\x00' + write_ci(r_local) + b'\x16'        # Global.GetServerInfo(ServerState)
    newscr = call + script
    blob = bytes(d[e['off']:e['off'] + e['size']])
    q = szp - e['off']; s0_ = st0 - e['off']; e0_ = en - e['off']
    nblob = blob[:q] + struct.pack('<i', memlen(newscr)) + blob[q + 4:s0_] + newscr + blob[e0_:]
    cur = text['off'] + 12288
    if cur + len(nblob) > text['off'] + text['size']: sys.exit('source-text buffer too small')
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    szc = fit(len(nblob), e['offp'] - e['szp']); offc = fit(cur, e['end'] - e['offp'])
    d[cur:cur + len(nblob)] = nblob
    d[e['szp']:e['offp']] = szc; d[e['offp']:e['end']] = offc
    P2 = Pkg(bytes(d)); e2 = P2.ex[fn[0]]
    assert e2['off'] == cur and e2['size'] == len(nblob) and len(d) == os.path.getsize(f)
    a, b, c_, e_ = locate_script(bytes(d), e2['off'], e2['size'])
    assert c_ == memlen(newscr)
    open(f, 'wb').write(bytes(d))
    print('patched: campaign servers now report their player count and max players to the server list')

main()
