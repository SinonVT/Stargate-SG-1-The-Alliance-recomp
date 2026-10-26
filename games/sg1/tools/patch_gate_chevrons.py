"""Light the stargate chevrons as the gate dials, as the PC build does.

GateChevrons (StargateContent.u) swaps a chevron's material when it locks: half lit when the lock sound starts, fully
lit when it ends, and back to unlit when the wormhole closes. Those lines are inside #ifdefPC in the script, so the
Xbox build compiled them out and its chevrons never change. This puts them back, using only names and imports the
package already has (a network client rejects a package with new ones):

    PlayChevronLock:   Log(...)   -> Skins[lastChevronLit] = Lit    (the chevron before this one is fully lit)
                       after lastChevronLit = ChevronSkinMap[i]:
                       Skins[lastChevronLit] = Material(DynamicLoadObject("Stargate_Gate_Tex.Gate_chev_Mid", class'Material'));
                       SetTimer(GetSoundDuration(LockSound) - 1.0, false) -> SetTimer(4.0, false)
                       (the lock sound is 4.98 s; the Xbox build's GetSoundDuration does not return it, so the timer
                       that tells the gate a chevron has locked never ran out and a DHD-dialled gate never opened)
    Timer:             Skins[lastChevronLit] = Material(DynamicLoadObject("Stargate_Gate_Tex.Gate_chev_Lit", class'Material'));
                       before Gate(Owner).ChevronLocked();
    UnlockAllChevrons: Log(...)   -> Skins.Length = 0; lastChevronLit = 0;   (every chevron back to unlit)

    Gate.WormholeOpen.Timer: when the stay-open time is up the gate shuts as the main menu's does: the unused
                       gate_close sound plays and the event horizon goes 2.3 s later (it used to vanish silently).

The longer functions no longer fit where they were: their new data is written after the other objects, the import
and export tables follow it, and the header points at their new places. Nothing else moves.

Usage: python patch_gate_chevrons.py "<game folder>"  [--revert]
A backup System\\StargateContent.u.orig_chevrons is written first. Re-running is harmless. Host and joining players must
use the same file.
"""
import os, shutil, struct, sys

PATCH_VERSION = b'\x14\x2d\x01\xed\x0b\x28\x0f\x01\xd9\x01'   # Spinning: bRotateToDesired = false: version 12



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
        self.no, self.eo, self.io = no, eo, io
        self.names = []; o = no
        for _ in range(nn):
            l, o = read_ci(d, o); self.names.append(d[o:o + l - 1].decode('latin1')); o += l + 4
        self.imports = []; o = io
        for _ in range(ni):
            cp, o = read_ci(d, o); cn, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
            on, o = read_ci(d, o)
            self.imports.append(dict(cls=self.names[cn], outer=outer, name=self.names[on]))
        self.import_end = o
        self.ex = []; o = eo
        for _ in range(ne):
            s = o
            cls, o = read_ci(d, o); sup, o = read_ci(d, o); outer = struct.unpack_from('<i', d, o)[0]; o += 4
            nm, o = read_ci(d, o); o += 4
            sz, o = read_ci(d, o); off = 0
            if sz > 0: off, o = read_ci(d, o)
            self.ex.append(dict(start=s, end=o, cls=cls, outer=outer, name=self.names[nm], size=sz, off=off))
        self.export_end = o

    def path(self, i):
        if i < 0:
            im = self.imports[-i - 1]
            return (self.path(im['outer']) + '.' if im['outer'] else '') + im['name']
        if i > 0:
            e = self.ex[i - 1]
            return (self.path(e['outer']) + '.' if e['outer'] else '') + e['name']
        return ''

    def find(self, path, imports=False):
        if imports:
            for i in range(len(self.imports)):
                if self.path(-i - 1) == path: return -i - 1
        else:
            for i in range(len(self.ex)):
                if self.path(i + 1) == path: return i + 1
        raise SystemExit('%s not found in the package' % path)


def ref(i):
    """An object reference in script: a compact index on disk, 4 bytes once loaded."""
    return write_ci(i), 4


class Code:
    """Script bytecode built with its loaded size: object references take 4 bytes in memory, whatever their disk size."""
    def __init__(self):
        self.disk = bytearray(); self.mem = 0

    def op(self, *parts):
        for p in parts:
            if isinstance(p, tuple):
                self.disk += p[0]; self.mem += p[1]
            else:
                b = bytes.fromhex(p) if isinstance(p, str) else bytes(p)
                self.disk += b; self.mem += len(b)
        return self


def cond_size(p, locked):
    return 1 + 1 + 4 + 1 + 4 + 1                                         # 9b 01 <ref> 1d <int> 16, once loaded


def set_skin(code, skins, lit, material, dlo, name):
    # Skins[lastChevronLit] = Material(DynamicLoadObject(name, class'Material'));
    code.op('0f', '10', '01', ref(lit), '01', ref(skins), '2e', ref(material), '1c', ref(dlo),
            '1f', name.encode('latin1') + b'\0', '20', ref(material), '16')


def function_parts(d, e):
    """Header (up to and including ScriptSize), bytecode, trailer of a function export."""
    blob = bytes(d[e['off']:e['off'] + e['size']])
    end = blob.rfind(b'\x04\x0b\x47')          # return; end of script
    if end < 0: raise SystemExit('unexpected bytecode in ' + e['name'])
    end += 3
    return blob, end


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1: sys.exit(__doc__)
    path = os.path.join(args[0], 'System', 'StargateContent.u')
    bak = path + '.orig_chevrons'
    if '--revert' in sys.argv:
        if os.path.exists(bak): shutil.copyfile(bak, path); print('restored', path)
        else: print('no backup, nothing to do')
        return
    d = bytearray(open(path, 'rb').read())
    if PATCH_VERSION in d and b'SymbolRing stop\0' not in d and Pkg(d).export_end != len(d):   # this version
        print('already patched'); return
    if b'Stargate_Gate_Tex.Gate_chev_Lit\0' in d:                       # an earlier version of this patch
        if not os.path.exists(bak): sys.exit('patched by an earlier version and no backup to start from')
        d = bytearray(open(bak, 'rb').read())
    p = Pkg(d)
    if p.export_end != len(d) or p.import_end != p.eo:
        sys.exit('unexpected layout: the import and export tables are not at the end of the file')

    lock = p.find('GateChevrons.PlayChevronLock'); timer = p.find('GateChevrons.Timer')
    unlock = p.find('GateChevrons.UnlockAllChevrons')
    lit = p.find('GateChevrons.lastChevronLit')
    skins = p.find('Engine.Actor.Skins', True); material = p.find('Engine.Material', True)
    dlo = p.find('Core.Object.DynamicLoadObject', True)

    new = {}
    # PlayChevronLock, rebuilt whole. It also runs on every joining player's machine (see GateChevrons.Trigger below),
    # so it counts with its own lockedChevronCount instead of the argument, and only the server plays the lock sound
    # (the server's sound already reaches everyone):
    #     Skins[lastChevronLit] = Lit;                 (the chevron before is fully lit)
    #     lockedChevronCount++;
    #     lastLockedChevron = ChevronMap[lockedChevronCount - 1];
    #     lastChevronLit = ChevronSkinMap[lockedChevronCount - 1];
    #     Skins[lastChevronLit] = Mid;
    #     AnimName = "Chevron"@lastLockedChevron@"Lock"; PlayAnim(Name(AnimName));
    #     if (Role == ROLE_Authority) PlaySound(LockSound, SLOT_None, 1.0);
    #     SetTimer(4.0, false);
    # (4.0: GetSoundDuration(LockSound) - 1.0 never ran out on the Xbox build, so a DHD-dialled gate never opened)
    e = p.ex[lock - 1]; blob, end = function_parts(d, e)
    log = blob.find(b'\xe7\x70\x1fChevrons are inside of playchevronlock ')
    if log < 0: sys.exit('PlayChevronLock is not the expected code')
    size_at = log - 4
    if struct.unpack_from('<i', blob, size_at)[0] != 175: sys.exit('PlayChevronLock is not the expected code')
    count = write_ci(p.find('GateChevrons.lockedChevronCount')); i_ref = write_ci(p.find('GateChevrons.PlayChevronLock.i'))
    last_locked = write_ci(p.find('GateChevrons.lastLockedChevron')); chev_map = write_ci(p.find('GateChevrons.ChevronMap'))
    skin_map = write_ci(p.find('GateChevrons.ChevronSkinMap')); anim = write_ci(p.find('GateChevrons.PlayChevronLock.AnimName'))
    lock_sound = write_ci(p.find('GateChevrons.LockSound')); role = write_ci(p.find('Engine.Actor.Role', True))
    body = (b'\xa5\x01' + count + b'\x16' +
            b'\x0f\x01' + last_locked + b'\x1a\x00' + i_ref + b'\x01' + chev_map +
            b'\x0f\x01' + write_ci(lit) + b'\x1a\x00' + i_ref + b'\x01' + skin_map)
    anim_part = (b'\x0f\x00' + anim + b'\xa8\xa8\x1fChevron\x00\x39\x53\x01' + last_locked + b'\x16\x1fLock\x00\x16' +
                 b'\x61\x03\x39\x5a\x00' + anim + b'\x16')
    sound_part = b'\x61\x08\x01' + lock_sound + b'\x24\x00\x1e' + struct.pack('<f', 1.0) + b'\x16'
    timer_part = b'\x61\x18\xaf\x1c'
    o = blob.index(b'\0', log + 3) + 1
    if blob[o:o + 3] != b'\x39\x53\x00': sys.exit('PlayChevronLock is not the expected code')
    _, o = read_ci(blob, o + 3)
    if blob[o:o + 2] != b'\x16\x16' or blob[o + 2:o + 2 + len(body)] != body: sys.exit('PlayChevronLock is not the expected code')
    o += 2 + len(body)
    if blob[o:o + len(anim_part) + len(sound_part)] != anim_part + sound_part or \
            blob[o + len(anim_part) + len(sound_part):][:4] != timer_part:
        sys.exit('PlayChevronLock is not the expected code')
    tail = blob[blob.index(b'\x04\x0b\x47', o):]                         # return, end, function trailer
    minus1 = lambda: Code().op('93', '01', ref(p.find('GateChevrons.lockedChevronCount')), '26', '16')
    code = Code()
    set_skin(code, skins, lit, material, dlo, 'Stargate_Gate_Tex.Gate_chev_Lit')
    code.op('a5', '01', ref(p.find('GateChevrons.lockedChevronCount')), '16')
    idx = minus1(); code.op('0f', '01', ref(p.find('GateChevrons.lastLockedChevron')), '1a', (idx.disk, idx.mem), '01', ref(p.find('GateChevrons.ChevronMap')))
    idx = minus1(); code.op('0f', '01', ref(lit), '1a', (idx.disk, idx.mem), '01', ref(p.find('GateChevrons.ChevronSkinMap')))
    set_skin(code, skins, lit, material, dlo, 'Stargate_Gate_Tex.Gate_chev_Mid')
    code.op((anim_part, 32 + 10))                                         # 3 references in it, 4 bytes each once loaded
    test = Code().op('9a', '39', '3a', '01', ref(p.find('Engine.Actor.Role', True)), '39', '3a', '24 04', '16')
    sound = Code().op('61', '08', '01', ref(p.find('GateChevrons.LockSound')), '24 00', '1e', struct.pack('<f', 1.0), '16')
    code.op('07', struct.pack('<H', code.mem + 3 + test.mem + sound.mem), (test.disk, test.mem), (sound.disk, sound.mem))
    code.op('61', '18', '1e', struct.pack('<f', 4.0), '28', '16')
    code.op('04', '0b', '47')
    new[lock] = blob[:size_at] + struct.pack('<i', code.mem) + bytes(code.disk) + tail[3:]

    # GateChevrons.Trigger / UnTrigger run only on the server, and PlayChevronLock / UnlockAllChevrons (replicated
    # functions) reach only the actor's owning player: the gate owns the chevrons, so no joining player ever saw them.
    # They are now called once per player with each player made the owner for the call, which sends the call to that
    # player (and runs it here for the host's own player), then the gate is made the owner again:
    #     Other = Owner;
    #     ForEach AllActors(class'PlayerController', <Instigator>) { Owner = <Instigator>; PlayChevronLock(0); }
    #     Owner = Other;
    owner = p.find('Engine.Actor.Owner', True); pc = p.find('Engine.PlayerController', True)
    def per_player(fn, prefix_text, param_other, param_pawn, call, after=None):
        e = p.ex[fn - 1]; blob, end = function_parts(d, e)
        log = blob.find(prefix_text)
        if log < 0: sys.exit(p.path(fn) + ' is not the expected code')
        size_at = log - 4
        c = Code()
        c.op('0f', '00', ref(param_other), '01', ref(owner))
        it = Code().op('2f', '61', '30', '20', ref(pc), '00', ref(param_pawn), '16')
        loop = Code().op('0f', '01', ref(owner), '00', ref(param_pawn), (call.disk, call.mem))
        end_at = c.mem + it.mem + 2 + loop.mem + 1                        # IteratorPop: the loop ends at the one after it
        c.op((it.disk, it.mem), struct.pack('<H', end_at), (loop.disk, loop.mem), '31', '30')
        c.op('0f', '01', ref(owner), '00', ref(param_other))
        if after: after(c)
        c.op('04', '0b', '47')
        return blob[:size_at] + struct.pack('<i', c.mem) + bytes(c.disk) + blob[end:]
    lock_name = (write_ci(p.names.index('PlayChevronLock')), 4)
    unlock_name = (write_ci(p.names.index('UnlockAllChevrons')), 4)
    trig = p.find('GateChevrons.Trigger'); untr = p.find('GateChevrons.UnTrigger')
    # and the gate's symbol ring turns to the next address symbol, at both ends of a wormhole (the dialling gate's own
    # SpinTo from SpeedDialing then finds the ring already turning and does nothing):
    #     if (lockedChevronCount < 7) Gate(Owner).SymbolRing.SpinTo(Gate(Owner).GateAddress[lockedChevronCount]);
    gate_cls = p.find('Gate'); cnt = p.find('GateChevrons.lockedChevronCount')
    def ring_stop():
        # Gate(Owner).SymbolRing.StopSpinning();
        ring = p.find('Gate.SymbolRing')
        ring_ctx = Code().op('19', '2e', ref(gate_cls), '01', ref(owner), struct.pack('<H', 5), '04', '01', ref(ring))
        call = Code().op('1b', (write_ci(p.names.index('StopSpinning')), 4), '16')
        return Code().op('19', (ring_ctx.disk, ring_ctx.mem), struct.pack('<H', call.mem), '00', (call.disk, call.mem))
    def ring_turn(c):
        ring = p.find('Gate.SymbolRing'); address = p.find('Gate.GateAddress')
        spin_name = (write_ci(p.names.index('SpinTo')), 4)
        def gate_ctx(prop, size):
            return Code().op('19', '2e', ref(gate_cls), '01', ref(owner), struct.pack('<H', 5), struct.pack('<B', size),
                             '01', ref(prop))
        ring_ctx = gate_ctx(ring, 4); addr_ctx = gate_ctx(address, 12)
        spin_call = Code().op('1b', spin_name, '10', '01', ref(cnt), (addr_ctx.disk, addr_ctx.mem), '16')
        turn = Code().op('19', (ring_ctx.disk, ring_ctx.mem), struct.pack('<H', spin_call.mem), '00',
                         (spin_call.disk, spin_call.mem))
        test = Code().op('96', '01', ref(cnt), '2c', '07', '16')
        stop = ring_stop()
        a_else = c.mem + 3 + test.mem + turn.mem + 3
        c.op('07', struct.pack('<H', a_else), (test.disk, test.mem), (turn.disk, turn.mem))
        c.op('06', struct.pack('<H', a_else + stop.mem), (stop.disk, stop.mem))
    new[trig] = per_player(trig, b'\xe7\x70\x1fChevrons were triggered', p.find('GateChevrons.Trigger.Other'),
                           p.find('GateChevrons.Trigger.Instigator'), Code().op('1b', lock_name, '25', '16'), ring_turn)
    def stop_after(c):
        stop = ring_stop(); c.op((stop.disk, stop.mem))
    new[untr] = per_player(untr, b'\xe7\x1fChevrons were untriggered', p.find('GateChevrons.UnTrigger.Other'),
                           p.find('GateChevrons.UnTrigger.EventInstigator'), Code().op('1b', unlock_name, '16'), stop_after)

    # Timer: set the fully lit material first
    e = p.ex[timer - 1]; blob, end = function_parts(d, e)
    start = blob.find(b'\x19\x2e')                                        # Gate(Owner).ChevronLocked()
    if start < 0: sys.exit('Timer is not the expected code')
    size_at = start - 4; old_mem = struct.unpack_from('<i', blob, size_at)[0]
    code = Code(); set_skin(code, skins, lit, material, dlo, 'Stargate_Gate_Tex.Gate_chev_Lit')
    new[timer] = blob[:size_at] + struct.pack('<i', old_mem + code.mem) + code.disk + blob[start:]

    # UnlockAllChevrons: the Log becomes Skins.Length = 0
    e = p.ex[unlock - 1]; blob, end = function_parts(d, e)
    text = b'\xe7\x1fChevrons are inside of unlock all chevrons\x00\x16'
    log = blob.find(text)
    if log < 0: sys.exit('UnlockAllChevrons is not the expected code')
    size_at = log - 4; old_mem = struct.unpack_from('<i', blob, size_at)[0]
    code = Code().op('0f', '37', '01', ref(skins), '25', '0f', '01', ref(lit), '25')   # and lastChevronLit = 0
    new[unlock] = blob[:size_at] + struct.pack('<i', old_mem - len(text) + code.mem) + code.disk + blob[log + len(text):]

    # Gate.WormholeOpen.Timer (the gate's stay-open time is up): the gate shuts as the main menu's does, with the
    # gate_close sound first and the event horizon gone 2.3 s later. ChevronsLocked = -1 marks the sound as played.
    #     if (ChevronsLocked != -1) { ChevronsLocked = -1; PlaySound(Sound(DynamicLoadObject(
    #         "SGC_Sounds.Stargate.gate_close", class'Sound')), SLOT_None, 1.0); SetTimer(2.3, false); return; }
    #     ChevronsLocked = 0; ShutdownEventHorizon(); GotoState('Inactive');
    wt = p.find('Gate.WormholeOpen.Timer'); locked = p.find('Gate.ChevronsLocked')
    sound = p.find('Engine.Sound', True)
    e = p.ex[wt - 1]; blob, end = function_parts(d, e)
    body = blob.find(b'\x1b')                                           # ShutdownEventHorizon()
    size_at = body - 4; old_mem = struct.unpack_from('<i', blob, size_at)[0]
    if old_mem != 16 or blob[end - 3:end] != b'\x04\x0b\x47': sys.exit('Gate.WormholeOpen.Timer is not the expected code')
    minus1 = b'\x1d' + struct.pack('<i', -1)
    rest = Code()
    rest.op('0f', '01', ref(locked), minus1)
    rest.op('61', '08', '2e', ref(sound), '1c', ref(dlo), '1f', b'SGC_Sounds.Stargate.gate_close\0', '20', ref(sound), '16',
            '24 00', '1e', struct.pack('<f', 1.0), '16')
    # a linked gate's other end starts its closing sound now too (and shuts when this one does, as before):
    #     if (IsA('LinkedGate')) LinkedGate(Self).SiblingGate.Trigger(Self, None);
    linked = p.find('LinkedGate'); sibling = p.find('LinkedGate.SiblingGate')
    isa = Code().op('61', '2f', '21', (write_ci(p.names.index('LinkedGate')), 4), '16')
    inner = Code().op('19', '2e', ref(linked), '17', struct.pack('<H', 5), '04', '01', ref(sibling))
    call = Code().op('1b', (write_ci(p.names.index('Trigger')), 4), '17', '2a', '16')
    notify = Code().op('19', (inner.disk, inner.mem), struct.pack('<H', call.mem), '00', (call.disk, call.mem))
    pre = 3 + cond_size(p, locked) + rest.mem                         # where the IsA test starts
    rest.op('07', struct.pack('<H', pre + 3 + isa.mem + notify.mem), (isa.disk, isa.mem), (notify.disk, notify.mem))
    rest.op('61', '18', '1e', struct.pack('<f', 2.3), '28', '16')
    rest.op('04', '0b')
    cond = Code().op('9b', '01', ref(locked), minus1, '16')            # ChevronsLocked != -1
    assert cond.mem == cond_size(p, locked)
    target = 3 + cond.mem + rest.mem                                     # JumpIfNot: 07 + 2 byte offset + condition
    head = Code().op('07', struct.pack('<H', target)); head.op((cond.disk, cond.mem))
    tail = Code().op('0f', '01', ref(locked), '25')                      # ChevronsLocked = 0
    code = bytes(head.disk + rest.disk + tail.disk)
    new[wt] = blob[:size_at] + struct.pack('<i', old_mem + head.mem + rest.mem + tail.mem) + code + blob[body:]

    # Gate.WormholeOpen.Trigger from the other end of a linked pair (as patched by patch_gate_close.py):
    #     if (Other.IsA('LinkedGate')) {
    #         if (ChevronsLocked != -1) { ChevronsLocked = -1; PlaySound(gate_close ...); }   (the far end, as it starts)
    #         else { ChevronsLocked = 0; ShutdownEventHorizon(); GotoState('Inactive'); }      (when the near end shuts)
    #     } else if (!IsA('LinkedGate')) { ShutdownEventHorizon(); GotoState('Inactive'); }
    tr = p.find('Gate.WormholeOpen.Trigger')
    e = p.ex[tr - 1]; blob, end = function_parts(d, e)
    other = write_ci(p.find('Gate.WormholeOpen.Trigger.Other'))
    isa_other = b'\x19\x00' + other + b'\x08\x00\x04\x61\x2f\x21' + write_ci(p.names.index('LinkedGate')) + b'\x16'
    shut = b'\x1b' + write_ci(p.names.index('ShutdownEventHorizon')) + b'\x16\x71\x21' + write_ci(p.names.index('Inactive')) + b'\x16'
    not_linked = b'\x81\x61\x2f\x21' + write_ci(p.names.index('LinkedGate')) + b'\x16\x16'
    start = blob.find(b'\x07\x24\x00' + isa_other)
    expect = (b'\x07\x24\x00' + isa_other + shut + b'\x06\x3e\x00\x07\x3e\x00' + not_linked + shut + b'\x04\x0b\x47')
    if start < 0 or blob[start:start + len(expect)] != expect:
        sys.exit('Gate.WormholeOpen.Trigger is not the expected code (run patch_gate_close.py first)')
    size_at = start - 4
    m_isa, m_shut, m_not = 17, 13, 10                                    # their sizes once loaded
    play = Code().op('0f', '01', ref(locked), minus1,
                     '61', '08', '2e', ref(sound), '1c', ref(dlo), '1f', b'SGC_Sounds.Stargate.gate_close\0', '20',
                     ref(sound), '16', '24 00', '1e', struct.pack('<f', 1.0), '16')
    closing = Code().op('0f', '01', ref(locked), '25', (shut, m_shut))
    # offsets once loaded
    a_inner = 3 + m_isa                                                  # if (ChevronsLocked != -1)
    a_else_inner = a_inner + 3 + cond.mem + play.mem + 3                 # ChevronsLocked = 0 ...
    a_outer_else = a_else_inner + closing.mem + 3                        # else if (!IsA('LinkedGate'))
    a_end = a_outer_else + 3 + m_not + m_shut                            # return
    code = Code()
    code.op('07', struct.pack('<H', a_outer_else), (isa_other, m_isa))
    code.op('07', struct.pack('<H', a_else_inner), (cond.disk, cond.mem), (play.disk, play.mem), '06', struct.pack('<H', a_end))
    code.op((closing.disk, closing.mem), '06', struct.pack('<H', a_end))
    code.op('07', struct.pack('<H', a_end), (not_linked, m_not), (shut, m_shut))
    code.op('04', '0b', '47')
    assert code.mem == a_end + 3
    new[tr] = blob[:size_at] + struct.pack('<i', code.mem) + bytes(code.disk) + blob[start + len(expect):]

    # The symbol ring turns while a DHD dials (the Xbox script only turns it in the full dialling sequence, which no
    # map uses): after each chevron locks it spins to the next address symbol,
    #     SpeedDialing.BeginState: Log(...) -> SymbolRing.SpinTo(GateAddress[ChevronsLocked]);
    #     SpeedDialing.Trigger:    after TriggerEvent('chevrontag', ...):
    #                              if (ChevronsLocked < RequiredChevrons) SymbolRing.SpinTo(GateAddress[ChevronsLocked]);
    # and turns 6 times as fast (RotationRate.Roll 4096 -> 24576: half a turn in 1.3 s, a DHD chevron every 1.4 s).
    ring = p.find('Gate.SymbolRing'); address = p.find('Gate.GateAddress'); required = p.find('Gate.RequiredChevrons')
    spin_name = (write_ci(p.names.index('SpinTo')), 4)
    call = Code().op('1b', spin_name, '10', '01', ref(locked), '01', ref(address), '16')
    spin = Code().op('19', '01', ref(ring), struct.pack('<H', call.mem), '00', (call.disk, call.mem))

    sb = p.find('Gate.SpeedDialing.BeginState')
    e = p.ex[sb - 1]; blob, end = function_parts(d, e)
    text = b'\xe7\x1fGate is in speeddialing state, locking 1st chevron, triggereing the event\x00\x16'
    log = blob.find(text)
    if log < 0: sys.exit('Gate.SpeedDialing.BeginState is not the expected code')
    first = blob.find(b'\x0f\x01' + write_ci(locked) + b'\x25')
    size_at = first - 4; old_mem = struct.unpack_from('<i', blob, size_at)[0]
    new[sb] = (blob[:size_at] + struct.pack('<i', old_mem - len(text) + spin.mem) + blob[first:log] + spin.disk +
               blob[log + len(text):])

    st = p.find('Gate.SpeedDialing.Trigger')
    e = p.ex[st - 1]; blob, end = function_parts(d, e)
    other = write_ci(p.find('Gate.SpeedDialing.Trigger.Other'))
    isa = lambda n: b'\x19\x00' + other + b'\x08\x00\x04\x61\x2f\x21' + write_ci(p.names.index(n)) + b'\x16'
    trig = b'\x1b' + write_ci(p.names.index('TriggerEvent')) + b'\x21' + write_ci(p.names.index('chevrontag')) + b'\x17\x2a\x16'
    incr = b'\xa5\x01' + write_ci(locked) + b'\x16'
    inact = b'\x71\x21' + write_ci(p.names.index('Inactive')) + b'\x16'
    expect = (b'\x07\x2b\x00' + isa('DialHomeDevice') + incr + trig + b'\x06\x48\x00\x07\x48\x00\x81' +
              isa('LinkedGate') + b'\x16' + inact + b'\x04\x0b\x47')
    start = blob.find(expect)
    if start < 0: sys.exit('Gate.SpeedDialing.Trigger is not the expected code')
    m_isa, m_incr, m_trig, m_inact = 17, 7, 13, 7
    test = Code().op('96', '01', ref(locked), '01', ref(required), '16')   # ChevronsLocked < RequiredChevrons
    # a DHD dial that starts again (its first chevron) after one was given up, walking away from the DHD, starts the
    # count again: the gate stayed in SpeedDialing with the old count, ran past 7 and never opened
    #     if (DialHomeDevice(Other).NumChevrons == 1) { ChevronsLocked = 0; UnTriggerEvent('chevrontag', Self, None); }
    dhd = p.find('DialHomeDevice'); numchev = p.find('DialHomeDevice.NumChevrons')
    untrig_name = write_ci(p.names.index('UnTriggerEvent' if 'UnTriggerEvent' in p.names else 'UntriggerEvent'))
    untrig = Code().op('1b', (untrig_name, 4), '21', (write_ci(p.names.index('chevrontag')), 4), '17', '2a', '16')
    cast = Code().op('2e', ref(dhd), '00', (other, 4))
    count = Code().op('19', (cast.disk, cast.mem), struct.pack('<H', 5), '04', '01', ref(numchev))
    fresh = Code().op('9a', (count.disk, count.mem), '26', '16')         # == 1
    reset = Code().op('0f', '01', ref(locked), '25', (untrig.disk, untrig.mem))
    a_reset_end = 3 + m_isa + 3 + fresh.mem + reset.mem
    a_if = a_reset_end + m_incr + m_trig
    a_after = a_if + 3 + test.mem + spin.mem
    a_else = a_after + 3
    a_end = a_else + 3 + 1 + m_isa + 1 + m_inact
    code = Code()
    code.op('07', struct.pack('<H', a_else), (isa('DialHomeDevice'), m_isa))
    code.op('07', struct.pack('<H', a_reset_end), (fresh.disk, fresh.mem), (reset.disk, reset.mem))
    code.op((incr, m_incr), (trig, m_trig))
    code.op('07', struct.pack('<H', a_after), (test.disk, test.mem), (spin.disk, spin.mem))
    code.op('06', struct.pack('<H', a_end))
    code.op('07', struct.pack('<H', a_end), '81', (isa('LinkedGate'), m_isa), '16', (inact, m_inact))
    code.op('04', '0b', '47')
    assert code.mem == a_end + 3
    old_mem = struct.unpack_from('<i', blob, start - 4)[0]
    if old_mem != 0x4b: sys.exit('Gate.SpeedDialing.Trigger is not the expected code')
    new[st] = blob[:start - 4] + struct.pack('<i', code.mem) + bytes(code.disk) + blob[start + len(expect):]

    # DialHomeDevice.Dialling.UnTrigger (the dial given up): the chevrons go dark too
    #     after UnTriggerEvent(DialCompleteEvent, Self, Dialler):  UnTriggerEvent('chevrontag', Self, None);
    du = p.find('DialHomeDevice.Dialling.UnTrigger')
    e = p.ex[du - 1]; blob, end = function_parts(d, e)
    dial_untrig = (b'\x1b' + untrig_name + b'\x01' + write_ci(p.find('DialHomeDevice.DialCompleteEvent')) + b'\x17\x01' +
                   write_ci(p.find('DialHomeDevice.Dialler')) + b'\x16')
    at = blob.find(dial_untrig)
    if at < 0 or blob.count(dial_untrig) != 1: sys.exit('DialHomeDevice.Dialling.UnTrigger is not the expected code')
    first = blob.find(b'\x07\x4a\x00\x77')                                # if (Text != None)
    size_at = first - 4; old_mem = struct.unpack_from('<i', blob, size_at)[0]
    if first < 0 or old_mem != 0x6e: sys.exit('DialHomeDevice.Dialling.UnTrigger is not the expected code')
    at += len(dial_untrig)
    new[du] = blob[:size_at] + struct.pack('<i', old_mem + untrig.mem) + blob[first:at] + untrig.disk + blob[at:]

    # GateSymbolRing.Idle.SpinTo: DesiredRotation = Rotation copies the gate's pitch and yaw as placed, which can be
    # negative (DM-Tomb's first gate has pitch -1). The physics keeps a turned rotation in 0..65535, so the ring then
    # never equals its DesiredRotation: it stopped at its first symbol, stayed in Spinning (its sound on for good) and
    # ignored every later SpinTo. After DesiredRotation = Rotation:
    #     DesiredRotation.Pitch = DesiredRotation.Pitch & 65535;  DesiredRotation.Yaw = DesiredRotation.Yaw & 65535;
    sp = p.find('GateSymbolRing.Idle.SpinTo')
    e = p.ex[sp - 1]; blob, end = function_parts(d, e)
    desired = p.find('Engine.Actor.DesiredRotation', True)
    copy = b'\x0f\x01' + write_ci(desired) + b'\x01' + write_ci(p.find('Engine.Actor.Rotation', True))
    at = blob.find(copy)
    first = blob.find(b'\x0f\x01' + write_ci(p.find('GateSymbolRing.targetSymbol')))
    if at < 0 or first < 0 or struct.unpack_from('<i', blob, first - 4)[0] != 0x4e:
        sys.exit('GateSymbolRing.Idle.SpinTo is not the expected code')
    mask = Code()
    for member in ('Core.Object.Rotator.Pitch', 'Core.Object.Rotator.Yaw'):
        m = p.find(member, True)
        mask.op('0f', '36', ref(m), '01', ref(desired), '9c', '36', ref(m), '01', ref(desired), '1d', struct.pack('<i', 65535), '16')
    at += len(copy)
    new[sp] = blob[:first - 4] + struct.pack('<i', 0x4e + mask.mem) + blob[first:at] + mask.disk + blob[at:]

    # GateSymbolRing.Spinning.BeginState: bRotateToDesired = true -> false. The ring now turns steadily (its default
    # bFixedRotationDir) from the first chevron until GateChevrons stops it at the 7th (or the dial is given up / the
    # gate shuts): the turn to a symbol never reported it was there on one of DM-Tomb's gates, which kept it in
    # Spinning with its sound on and every later SpinTo ignored.
    sb2 = p.find('GateSymbolRing.Spinning.BeginState')
    e = p.ex[sb2 - 1]
    rot_true = b'\x14\x2d\x01' + write_ci(p.find('Engine.Actor.bRotateToDesired', True)) + b'\x27'
    at = bytes(d[e['off']:e['off'] + e['size']]).find(rot_true)
    if at < 0: sys.exit('GateSymbolRing.Spinning.BeginState is not the expected code')
    d[e['off'] + at + len(rot_true) - 1] = 0x28

    # GateSymbolRing's default RotationRate (Rotator, Roll 4096), changed where it is
    e = p.ex[p.find('GateSymbolRing') - 1]
    rate_old = b'\x3a' + write_ci(p.names.index('Rotator')) + struct.pack('<iii', 0, 0, 4096)
    at = bytes(d[e['off']:e['off'] + e['size']]).find(rate_old)
    if at < 0: sys.exit('GateSymbolRing defaults are not the expected ones')
    d[e['off'] + at:e['off'] + at + len(rate_old)] = rate_old[:-12] + struct.pack('<iii', 0, 0, 24576)

    # Everything stays where it was, the tables too: the header's table offsets are part of the package's quick MD5,
    # which a server checks against System\\Packages.md5 and kicks a joining player on a mismatch. The new function data
    # goes after the export table; only those exports' size and offset fields change (not part of that MD5).
    head = bytes(d[:p.eo])
    def table(place):
        t = bytearray()
        for i, e in enumerate(p.ex):
            raw = d[e['start']:e['end']]
            if i + 1 in place:
                _, o = read_ci(raw, 0); _, o = read_ci(raw, o); o += 4; _, o = read_ci(raw, o); o += 4
                off, size = place[i + 1]
                raw = raw[:o] + write_ci(size) + write_ci(off)
            t += raw
        return t
    place = {idx: (0, len(data)) for idx, data in new.items()}
    for _ in range(8):                                                   # the offsets' sizes move the data: settle
        at = len(head) + len(table(place))
        moved = {}
        for idx, data in new.items():
            moved[idx] = (at, len(data)); at += len(data)
        if moved == place: break
        place = moved
    out = bytearray(head) + table(place)
    for idx, data in new.items():
        if len(out) != place[idx][0]: sys.exit('layout did not settle')
        out += data

    # check: the rewritten package reads back with the new functions where they should be
    q = Pkg(out)
    for idx, (off, size) in place.items():
        e = q.ex[idx - 1]
        if (e['off'], e['size']) != (off, size) or out[off:off + size] != new[idx]: sys.exit('self check failed')
    if len(q.ex) != len(p.ex) or len(q.imports) != len(p.imports) or q.names != p.names: sys.exit('self check failed')

    if not os.path.exists(bak): shutil.copyfile(path, bak)
    open(path, 'wb').write(out)
    print('patched', path, '(backup', bak + ')')


if __name__ == '__main__':
    main()
