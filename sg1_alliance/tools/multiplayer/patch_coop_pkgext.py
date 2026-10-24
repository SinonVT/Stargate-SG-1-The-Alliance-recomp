"""Package extension: rewrites the import/export tables of StargateGame.u (they sit behind the object data) so that patches can
  - reference more engine properties (IMPORTS list: Pawn.ViewPitch, Pawn.bDoTorsoTwist) and names,
  - grow any function: export size/offset fields are rewritten 4 bytes wide (no more 63-byte / 1 MB limits).
Object data is not moved. Works on System\\StargateGame.u.orig_coopmplog if it exists (then re-run patch_coop_mplog.py), else on System\\StargateGame.u.
Re-running is safe (missing imports are added, existing ones kept). Backup: <file>.orig_coopext (first run only).
Usage:  python patch_coop_pkgext.py "<game folder>"  [--revert]
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


# ----------------------------------------------------------------------------------------------- package extension
# Layout of StargateGame.u: header | names | object data | imports | exports (to the end of the file).  Nothing refers to the position of the
# imports/exports, so they can be rewritten after the data. The name table sits in front of the data (growing it would shift every export), so
# it is copied behind the data when names are added; the old one is left in place unused.
# NOTE (night 7d): the client rejects any change to the name table, import table or header ("CorruptConnect: StargateGame.u" on the first
# replicated object), so IMPORTS and NAMES must stay EMPTY. Only the export widening below is join-safe.
IMPORTS = []
NAMES = []
WIDTH = 4                                                    # export size / offset fields are rewritten this wide (27 bits)

def build(d, widen=True, add=True, names_on=True, imps_on=True, dup=False):
    tag, ver, lic, flags, nn, no, ne, eo, ni, io = struct.unpack_from('<IHHIIIIIII', d, 0)
    P = Pkg(bytes(d))
    # names (raw, to keep flags)
    o = no; ents = []
    for _ in range(nn):
        s = o; l, o = read_ci(d, o); o += l + 4; ents.append(bytes(d[s:o]))
    names = list(P.names); fl = ents[names.index('PlayWaiting')][-4:]
    def add_name(n):
        if n in names: return names.index(n)
        names.append(n); ents.append(write_ci(len(n) + 1) + n.encode('latin1') + b'\0' + fl); return len(names) - 1
    if add and names_on and NAMES:
        for n in NAMES: add_name(n)
    # imports (class package, class, outer, object)
    o = io; imps = []
    for _ in range(ni):
        cp, o = read_ci(d, o); cn, o = read_ci(d, o); pk = struct.unpack_from('<i', d, o)[0]; o += 4; on, o = read_ci(d, o); imps.append([cp, cn, pk, on])
    added = []
    for (kind, owner, name) in ((IMPORTS if imps_on else [('BoolProperty', 'Pawn', 'bIsTyping')]) if add else []):
        have = [i for i, im in enumerate(imps) if names[im[3]] == name and names[im[1]] == kind and names[imps[-im[2] - 1][3]] == owner]
        if have and not dup: continue
        ow = [i for i, im in enumerate(imps) if names[im[3]] == owner and names[im[1]] == 'Class']
        ref = [i for i, im in enumerate(imps) if names[im[1]] == kind]
        if len(ow) != 1 or not ref: sys.exit('cannot place import %s.%s' % (owner, name))
        imps.append([imps[ref[0]][0], imps[ref[0]][1], -(ow[0] + 1), add_name(name)]); added.append('%s.%s' % (owner, name))
    # exports: rewritten with wide size/offset fields
    exs = []
    o = eo; out = bytearray()
    for e in P.ex:
        s = o
        cls, o = read_ci(d, o); sup, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
        nm, o = read_ci(d, o); fl_ = d[o:o + 4]; o += 4
        sz_, o = read_ci(d, o)
        if sz_ > 0: _, o = read_ci(d, o)
        out += write_ci(cls) + write_ci(sup) + struct.pack('<i', outer) + write_ci(nm) + fl_
        if widen:
            out += fit(e['size'], WIDTH) if e['size'] else write_ci(0)
            if e['size']: out += fit(e['off'], WIDTH)
        else:
            out += d[e['szp']:e['end']]
    data = bytearray(d[:io])
    if add and names_on and NAMES:
        nofs = len(data); nt = b''.join(ents); data += nt
    else:
        nofs = no
    iofs = len(data)
    for im in imps: data += write_ci(im[0]) + write_ci(im[1]) + struct.pack('<i', im[2]) + write_ci(im[3])
    eofs = len(data); data += out
    struct.pack_into('<IIIIII', data, 12, len(names), nofs, ne, eofs, len(imps), iofs)
    # keep the generation record (last entry: export count, name count) consistent with the tables: the network package check compares them
    if add and names_on and NAMES:
        gc = struct.unpack_from('<I', data, 52)[0]; g = 56 + 8 * (gc - 1)
        struct.pack_into('<II', data, g, ne, len(names))
    return bytes(data), added

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    sysdir = os.path.join(args[0], 'System'); f = os.path.join(sysdir, 'StargateGame.u')
    base = f + '.orig_coopmplog'
    if os.path.exists(base): f = base
    bak = f + '.orig_coopext'
    if '--revert' in sys.argv:
        if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    if '--in' in sys.argv:                      # experiment: build a variant from an arbitrary file without touching the game folder
        src = sys.argv[sys.argv.index('--in') + 1]; dst = sys.argv[sys.argv.index('--out') + 1]
        d = open(src, 'rb').read()
        nd, added = build(d, widen='--no-widen' not in sys.argv, add='--no-add' not in sys.argv, names_on='--no-names' not in sys.argv, imps_on='--no-imports' not in sys.argv, dup='--dup' in sys.argv)
        Pkg(nd); open(dst, 'wb').write(nd); print('wrote', dst, len(nd), added); return
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    d = open(f, 'rb').read(); P0 = Pkg(d)
    nd, added = build(d)
    P1 = Pkg(nd)
    assert len(P1.ex) == len(P0.ex) and P1.names[:len(P0.names)] == P0.names and P1.imports[:len(P0.imports)] == P0.imports
    for a, b in zip(P0.ex, P1.ex):
        assert (a['cls'], a['sup'] if 'sup' in a else 0, a['outer'], a['name'], a['size'], a['off']) == (b['cls'], b['sup'] if 'sup' in b else 0, b['outer'], b['name'], b['size'], b['off'])
    io = struct.unpack_from('<I', d, 32)[0]
    assert nd[68:io] == d[68:io], 'data region changed'
    # every function script still parses
    n = 0
    for e in P1.ex:
        if P1.clsname(e) == 'Function' and e['size']:
            try: locate_script(nd, e['off'], e['size']); n += 1
            except SystemExit: pass
    open(f, 'wb').write(nd)
    print('extended %s: %d exports rewritten (size/offset fields %d bytes), imports added: %s, %d names, file %d -> %d bytes, %d function scripts parse' % (
        os.path.basename(f), len(P1.ex), WIDTH, added or 'none (already there)', len(P1.names), len(d), len(nd), n))

main()
