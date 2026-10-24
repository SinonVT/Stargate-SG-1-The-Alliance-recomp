"""EXPERIMENTAL: players who join a network campaign get the character they chose (instead of everyone being O'Neill).

Two edits in StoryModeGame (System\\StargateGame.u), both same-length:
 1. Login: a joining player's character came from a "SG1Member" URL option that nothing sends, so every joiner got the next free
    roster slot and the first player's character. It now reads the "Class" option that the character-select screen does send
    (and no longer prepends "StargateContent." to it, because that option already holds the full class name).
 2. GetDefaultPlayerClass: returned the team's default class (O'Neill) for everybody. It now returns the class the player chose (the same\n    token layout as before, only the cast class and two property references change, so the script size the engine checks is unchanged).
The first player (host) is unchanged, and so is a joiner who sends no class (next free roster slot).
NOTE: step 2 also applies to single player (the class chosen at login); if a single-player level ever starts as the wrong character,
run this tool with --revert.

Usage:  python patch_coop_chars.py "<game folder>"            apply (backup System\\StargateGame.u.orig_coopchars)
        python patch_coop_chars.py "<game folder>" --revert   restore the original
"""
import sys, os, shutil, struct

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

def load(d):
    tag, ver, lic, flags, nn, no, ne, eo, ni, io = struct.unpack_from('<IHHIIIIIII', d, 0)
    if tag != 0x9E2A83C1: raise SystemExit('not an Unreal package')
    names = []; o = no
    for _ in range(nn):
        l, o = read_ci(d, o); names.append(d[o:o + l - 1].decode('latin1')); o += l + 4
    exports = []; o = eo
    for _ in range(ne):
        cls, o = read_ci(d, o); sup, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
        nm, o = read_ci(d, o); o += 4; sz, o = read_ci(d, o); off = 0
        if sz > 0: off, o = read_ci(d, o)
        exports.append((names[nm], outer, sz, off))
    imports = []; o = io
    for _ in range(ni):
        cp, o = read_ci(d, o); cn, o = read_ci(d, o); pk = struct.unpack_from('<i', d, o)[0]; o += 4; on, o = read_ci(d, o)
        imports.append((names[cn], pk, names[on]))
    return names, exports, imports

EMPTY = b'\x1f\x00'
def concat(a, b): return b'\x70' + a + b + b'\x16'
EMPTY18 = concat(concat(concat(concat(EMPTY, EMPTY), EMPTY), EMPTY), EMPTY)      # "" built from 4 concats = 18 bytes
assert len(EMPTY18) == 18
A_OLD = b'\x1f' + b'SG1Member' + b'\x00'
A_NEW = b'\x70\x1f' + b'Class' + b'\x00' + EMPTY + b'\x16'                       # ("Class" $ "") = 11 bytes
B_OLD = b'\x1f' + b'StargateContent.' + b'\x00'
B_NEW = EMPTY18

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u'); bak = f + '.orig_coopchars'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = bytearray(open(f, 'rb').read())
    names, exports, imports = load(bytes(d))
    smg = [i for i, e in enumerate(exports) if e[0] == 'StoryModeGame']
    if not smg: sys.exit('StoryModeGame not found')
    outer = smg[0] + 1
    login = [e for e in exports if e[0] == 'Login' and e[1] == outer and e[2]]
    gdpc = [e for e in exports if e[0] == 'GetDefaultPlayerClass' and e[1] == outer and e[2]]
    if len(login) != 1 or len(gdpc) != 1: sys.exit('functions not found')
    _, _, lsz, loff = login[0]; _, _, gsz, goff = gdpc[0]
    body = bytes(d[loff:loff + lsz])
    a_done = body.count(A_NEW) == 1 and body.count(A_OLD) == 0
    b_done = body.count(EMPTY18) >= 1 and body.count(B_OLD) == 0
    def imp(cls, name):
        r = [i for i, im in enumerate(imports) if im[2] == name and im[0] == cls]
        if len(r) != 1: sys.exit('import %s.%s not found/unique' % (cls, name))
        return -(r[0] + 1)
    def fit(v, n):
        b = bytearray(write_ci(v))
        if len(b) > n: sys.exit('reference does not fit')
        while len(b) < n: b[-1] |= 0x40; b.append(0)          # redundant continuation byte: same value, longer encoding
        return bytes(b)
    g = bytes(d[goff:goff + gsz])
    # Original:  return UnrealTeamInfo(C.PlayerReplicationInfo.Team).DefaultPlayerClass
    # New:       return Controller(C.PlayerReplicationInfo.Owner).PawnClass
    # Identical token layout (so the in-memory script size is unchanged); only the cast class and two property references change.
    head = bytes.fromhex('04192e')
    gi = g.find(head)
    tail = bytes.fromhex('191900')
    if gi < 0 or g[gi + 4:gi + 7] != tail: sys.exit('GetDefaultPlayerClass has an unexpected layout')
    cast_old = g[gi + 3:gi + 4]
    lref = g[gi + 7:gi + 9]
    p1 = gi + 9
    if g[p1:p1 + 5] != bytes.fromhex('05000401ad'): sys.exit('GetDefaultPlayerClass has an unexpected layout (1)')
    p2 = p1 + 5
    if g[p2:p2 + 4] != bytes.fromhex('05000401'): sys.exit('GetDefaultPlayerClass has an unexpected layout (2)')
    t_old = g[p2 + 4:p2 + 6]                                  # Team (2 bytes)
    p3 = p2 + 6
    if g[p3:p3 + 4] != bytes.fromhex('05000401'): sys.exit('GetDefaultPlayerClass has an unexpected layout (3)')
    r_old = g[p3 + 4:p3 + 6]                                  # DefaultPlayerClass (2 bytes)
    g_done = False
    if cast_old == fit(imp('Class', 'Controller'), len(cast_old)) and t_old == fit(imp('ObjectProperty', 'Owner'), len(t_old)): g_done = True
    elif cast_old != bytes([0x0b]): sys.exit('GetDefaultPlayerClass has an unexpected layout (cast)')
    if a_done and b_done and g_done: print('already patched'); return
    if body.count(A_OLD) != 1 or body.count(B_OLD) != 1:
        if not (a_done and b_done): sys.exit('Login has an unexpected layout (SG1Member x%d, StargateContent. x%d)' % (body.count(A_OLD), body.count(B_OLD)))
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    if not a_done:
        k = loff + body.index(A_OLD); d[k:k + len(A_OLD)] = A_NEW
    if not b_done:
        k = loff + body.index(B_OLD) if False else None
        body2 = bytes(d[loff:loff + lsz]); k = loff + body2.index(B_OLD); d[k:k + len(B_OLD)] = B_NEW
    if not g_done:
        k = goff + gi + 3; d[k:k + len(cast_old)] = fit(imp('Class', 'Controller'), len(cast_old))
        k = goff + p2 + 4; d[k:k + len(t_old)] = fit(imp('ObjectProperty', 'Owner'), len(t_old))
        k = goff + p3 + 4; d[k:k + len(r_old)] = fit(imp('ClassProperty', 'PawnClass'), len(r_old))
    open(f, 'wb').write(bytes(d))
    print('patched: joining players keep the chosen character')

main()
