#!/usr/bin/env python3
"""
sg1patch.py - apply small, reversible fixes to YOUR OWN copy of the game's files.

Stargate SG-1: The Alliance ships its game logic as Unreal packages (*.u).
A few bugs live in that script code, so they cannot be fixed in the recompiled
exe. This tool patches them in place. Nothing from the game is distributed
here: you point the tool at the System folder you extracted from your own disc
image and it edits those files (after saving a .orig_sg1 backup next to each).

    python sg1patch.py "C:\\SG-1 The_Alliance"            apply every patch
    python sg1patch.py "C:\\SG-1 The_Alliance" --check    only report status
    python sg1patch.py "C:\\SG-1 The_Alliance" --revert   restore the backups

Each patch is found by NAME (package -> function -> call), not by file offset,
so it works on any build of the same package. A patch only touches bytes that
match the expected original exactly; anything else is reported and skipped.
"""
import argparse, os, shutil, struct, sys

# --------------------------------------------------------------------------
# minimal Unreal package reader (UE2, version 130): names + exports
# --------------------------------------------------------------------------
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
    """Compact index encoding, as used for names inside script bytecode."""
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

def parse(d):
    tag, ver, lic, flags, nn, no, ne, eo, ni, io = struct.unpack_from('<IHHIIIIIII', d, 0)
    if tag != 0x9E2A83C1: raise ValueError('not an Unreal package')
    names = []; o = no
    for _ in range(nn):
        l, o = read_ci(d, o)
        names.append(d[o:o + l - 1].decode('latin1')); o += l + 4
    exports = []; o = eo
    for _ in range(ne):
        cls, o = read_ci(d, o); sup, o = read_ci(d, o)
        o += 4                                  # package
        nm, o = read_ci(d, o); o += 4           # object name, flags
        sz, o = read_ci(d, o); off = 0
        if sz > 0: off, o = read_ci(d, o)
        exports.append((names[nm], sz, off))
    return names, exports

# --------------------------------------------------------------------------
# the patches
# --------------------------------------------------------------------------
# Each patch: swap the callee of one script call. The calling instruction is
# 0x1B (virtual call) followed by the callee name as a compact index, then the
# argument list, which we match too so only the intended call is touched.
PATCHES = [
    dict(
        id="teamsay-nonteam",
        package="Engine.u",
        function="ServerTeamSay",
        old_call="Say",
        new_call="ServerSay",
        why=("In non-team games ServerTeamSay called Say(), which runs the "
             "anti-spam check a second time right after TeamSay already did, "
             "so the message was always dropped. Calling ServerSay() skips "
             "the repeat check; team games are unaffected."),
    ),
]

def find_patch(d, p):
    names, exports = parse(d)
    old = names.index(p['old_call']); new = names.index(p['new_call'])
    oc = b'\x1b' + write_ci(old); nc = b'\x1b' + write_ci(new)
    if len(oc) != len(nc): return None, 'size differs (not supported)'
    for nm, sz, off in exports:
        if nm == p['function'] and sz:
            body = d[off:off + sz]
            hits_old = [i for i in range(len(body)) if body.startswith(oc, i) and body[i+len(oc):i+len(oc)+1] == b'\x00']
            hits_new = [i for i in range(len(body)) if body.startswith(nc, i) and body[i+len(nc):i+len(nc)+1] == b'\x00']
            return (off, oc, nc, hits_old, hits_new), None
    return None, 'function %s not found' % p['function']

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('gamedir', help='folder that contains System\\ (your extracted game files)')
    ap.add_argument('--check', action='store_true'); ap.add_argument('--revert', action='store_true')
    a = ap.parse_args()
    sysdir = os.path.join(a.gamedir, 'System')
    if not os.path.isdir(sysdir): sys.exit('no System folder in ' + a.gamedir)
    rc = 0
    for p in PATCHES:
        path = os.path.join(sysdir, p['package']); bak = path + '.orig_sg1'
        print('[%s] %s' % (p['id'], p['package']))
        if a.revert:
            if os.path.exists(bak): shutil.copyfile(bak, path); print('  restored from backup')
            else: print('  no backup, nothing to do')
            continue
        if not os.path.exists(path): print('  missing file, skipped'); rc = 1; continue
        d = bytearray(open(path, 'rb').read())
        r, err = find_patch(d, p)
        if err: print('  skipped:', err); rc = 1; continue
        off, oc, nc, ho, hn = r
        if hn and not ho: print('  already applied'); continue
        if len(ho) != 1: print('  skipped: expected exactly one matching call, found %d' % len(ho)); rc = 1; continue
        print('  needs patch (%s)' % p['why'])
        if a.check: continue
        if not os.path.exists(bak): shutil.copyfile(path, bak)
        at = off + ho[0]; d[at:at + len(nc)] = nc
        open(path, 'wb').write(d); print('  patched, backup at', bak)
    sys.exit(rc)

if __name__ == '__main__':
    main()
