"""Make a plain stargate close on a second trigger (main menu and cutscene gates).

Retail Gate.WormholeOpen.Trigger closes an open gate only when the trigger comes
from a 'LinkedGate'; anything else just logs "what is triggering me?".  The main
menu (and some cutscenes) fire the gate event a second time to close it, so those
gates stay open forever.

This rewrites the else branch of that function in StargateContent.u:

    else Log("what is triggering me?");
 -> else if (!IsA('LinkedGate')) { ShutdownEventHorizon(); GotoState('Inactive'); }

Linked gates (multiplayer / CTF) take exactly the same path as before, and plain
gates keep ignoring nothing but their old behaviour for LinkedGate triggers.
The new code is shorter, so the function export shrinks by 6 bytes (the export
table entry is updated; 6 unused bytes are left after it).

Usage: python patch_gate_close.py "<game folder>\\System\\StargateContent.u"
A backup StargateContent.u.orig is written next to it.  Re-running is harmless.
"""
import sys, os, shutil, struct

def ci_read(d, p):
    x = d[p]; p += 1; neg = x & 0x80; v = x & 0x3f
    if x & 0x40:
        sh = 6
        while True:
            y = d[p]; p += 1; v |= (y & 0x7f) << sh; sh += 7
            if not y & 0x80: break
    return (-v if neg else v), p

def ci_write(v):
    out = []; neg = 0x80 if v < 0 else 0; v = abs(v)
    b = (v & 0x3f) | neg; v >>= 6
    if v: b |= 0x40
    out.append(b)
    while v:
        b = v & 0x7f; v >>= 7
        if v: b |= 0x80
        out.append(b)
    return bytes(out)

OLD_ELSE = bytes.fromhex('e71f') + b'what is triggering me?\x00' + bytes.fromhex('16')
# JumpIfNot->end, !IsA('LinkedGate'), ShutdownEventHorizon(), GotoState('Inactive')
NEW_ELSE = bytes.fromhex('073e00' '81612f2147091616' '1b520d16' '7121710716')
HEAD = bytes.fromhex('41000000' '07240019005e28080004612f21470916' '1b520d16')  # unique Gate.WormholeOpen.Trigger start
TAIL = bytes.fromhex('06' '3e00')

def main(f):
    d = bytearray(open(f, 'rb').read())
    tag, ver, lic, flags, nc, no, ec, eo, ic, io = struct.unpack('<IHHIIIIIII', d[:36])
    old = HEAD + bytes.fromhex('71210717' if False else '') 
    i = bytes(d).find(HEAD)
    if i < 0:
        sys.exit('Gate.WormholeOpen.Trigger not found (already patched or a different StargateContent.u).')
    if bytes(d).count(HEAD) != 1:
        sys.exit('pattern is not unique')
    j = bytes(d).find(TAIL + OLD_ELSE, i)
    if j < 0 or j - i > 80:
        if bytes(d).find(TAIL + NEW_ELSE, i) > 0:
            print('already patched'); return
        sys.exit('else branch not as expected')
    # find the export entry that contains this code
    p = eo; target = None
    for n in range(ec):
        _, p = ci_read(d, p); _, p = ci_read(d, p); p += 4; _, p = ci_read(d, p); p += 4
        szpos = p; sz, p = ci_read(d, p)
        if sz > 0:
            off, p2 = ci_read(d, p)
            if off <= i < off + sz:
                target = (szpos, sz, off, p, p2)
            p = p2
    if not target: sys.exit('export entry not found')
    szpos, sz, off, _, afterp = target
    newsz = sz - (len(OLD_ELSE) - len(NEW_ELSE))
    if len(ci_write(sz)) != len(ci_write(newsz)):
        sys.exit('size field changes length; not supported')
    start = j + len(TAIL)
    end_old = off + sz
    body = bytes(d[start + len(OLD_ELSE):end_old])          # 04 0b 47 + trailer
    new_region = NEW_ELSE + body + b'\x00' * (len(OLD_ELSE) - len(NEW_ELSE))
    assert len(new_region) == end_old - start
    if not os.path.exists(f + '.orig'):
        shutil.copy2(f, f + '.orig')
    d[start:end_old] = new_region
    d[szpos:szpos + len(ci_write(sz))] = ci_write(newsz)
    open(f, 'wb').write(d)
    print('patched: export size %d -> %d at file offset 0x%X' % (sz, newsz, j))

if __name__ == '__main__':
    if len(sys.argv) != 2: sys.exit(__doc__)
    main(sys.argv[1])
