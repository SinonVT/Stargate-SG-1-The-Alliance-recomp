"""EXPERIMENTAL: co-op campaign (StoryModeGame) fixes, all same-length byte edits:
 1. "Restart level" in a hosted game no longer ends the server. PlayerController.RestartLevel (System\\Engine.u) used to send
    "?restart" to every client as an ABSOLUTE travel (the client just loaded the map by itself = single player) and to the host as a
    relative travel that dropped the "Listen" option (the host kept playing, but no longer hosting). Now clients travel relatively (they
    reconnect to the host) and the host reloads its map with "?Listen=" so it keeps hosting.
 2. StoryModeGame.PostBeginPlay hard-coded MaxPlayers=4; now 8 (System\\StargateGame.u). GameModes.ini [Stargategame.StoryModeGame] is
    set to MaxPlayers=8 by patch_coop_mode.py.
Usage:  python patch_coop_restart.py "<game folder>"            apply (backups Engine.u.orig_cooprestart / StargateGame.u.orig_cooprestart)
        python patch_coop_restart.py "<game folder>" --revert   restore both
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

def exports(d):
    tag, ver, lic, flags, nn, no, ne, eo, ni, io = struct.unpack_from('<IHHIIIIIII', d, 0)
    if tag != 0x9E2A83C1: raise SystemExit('not an Unreal package')
    names = []; o = no
    for _ in range(nn):
        l, o = read_ci(d, o); names.append(d[o:o + l - 1].decode('latin1')); o += l + 4
    ex = []; o = eo
    for _ in range(ne):
        cls, o = read_ci(d, o); sup, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
        nm, o = read_ci(d, o); o += 4; sz, o = read_ci(d, o); off = 0
        if sz > 0: off, o = read_ci(d, o)
        ex.append((names[nm], outer, sz, off))
    return ex

def func(d, cls, name):
    ex = exports(d)
    c = [i for i, e in enumerate(ex) if e[0] == cls and e[1] == 0]
    if len(c) != 1: sys.exit('class %s not found' % cls)
    f = [e for e in ex if e[0] == name and e[1] == c[0] + 1 and e[2]]
    if len(f) != 1: sys.exit('%s.%s not found' % (cls, name))
    return f[0][3], f[0][2]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    fe = os.path.join(args[0], 'System', 'Engine.u'); fg = os.path.join(args[0], 'System', 'StargateGame.u')
    if '--revert' in sys.argv:
        for f in (fe, fg):
            if os.path.exists(f + '.orig_cooprestart'): shutil.copyfile(f + '.orig_cooprestart', f); print('reverted', os.path.basename(f))
        return
    # ---- Engine.u
    d = bytearray(open(fe, 'rb').read()); off, sz = func(bytes(d), 'PlayerController', 'RestartLevel')
    body = bytes(d[off:off + sz]); S = b'\x1f?restart\x00'
    hits = []; k = body.find(S)
    while k >= 0: hits.append(k); k = body.find(S, k + 1)
    done_e = False
    if len(hits) == 3 and body[hits[1] + len(S):hits[1] + len(S) + 3] == b'\x24\x00\x28' and body[hits[2] + len(S):hits[2] + len(S) + 3] == b'\x24\x02\x28':
        if not os.path.exists(fe + '.orig_cooprestart'): shutil.copyfile(fe, fe + '.orig_cooprestart')
        a = off + hits[1] + len(S) + 1; d[a] = 2                                  # clients: TRAVEL_Absolute -> TRAVEL_Relative
        a = off + hits[2] + 1; d[a:a + 8] = b'?Listen='                           # host: keep listening
        open(fe, 'wb').write(bytes(d)); print('Engine.u: RestartLevel keeps the hosted game running')
    elif len(hits) == 2 and b'\x1f?Listen=\x00' in body: print('Engine.u: already patched'); done_e = True
    else: sys.exit('RestartLevel has an unexpected layout')
    # ---- StargateGame.u
    d = bytearray(open(fg, 'rb').read()); off, sz = func(bytes(d), 'StoryModeGame', 'PostBeginPlay')
    body = bytes(d[off:off + sz])
    i = body.find(b'\x0f\x01')
    if i < 0 or body[i + 4] != 0x2c: sys.exit('PostBeginPlay has an unexpected layout')
    if body[i + 5] == 8: print('StargateGame.u: already patched'); return
    if body[i + 5] != 4: sys.exit('PostBeginPlay has an unexpected layout')
    j = i + 4
    if not os.path.exists(fg + '.orig_cooprestart'): shutil.copyfile(fg, fg + '.orig_cooprestart')
    d[off + j + 1] = 8; open(fg, 'wb').write(bytes(d)); print('StargateGame.u: StoryModeGame MaxPlayers 4 -> 8')

main()
