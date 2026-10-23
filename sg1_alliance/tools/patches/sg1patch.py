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

# Text patches: replace one line of a game config file (found by its exact text).
TEXT_PATCHES = [
    dict(
        id="gamemodes-last-man-standing",
        file=os.path.join("System", "tweak", "MP", "GameModes.ini"),
        match='#GameModes=(Name="Last Man Standing",GameClass="StargateGame.LastManStandingGame")',
        new='GameModes=(Name="Last Man Standing",GameClass="StargateGame.LastManStandingGame")',
        why=("The Last Man Standing game mode is fully present in StargateGame.u "
             "but its menu entry was commented out. This enables it."),
    ),
]

def run_text_patches(a):
    rc = 0
    for p in TEXT_PATCHES:
        if a.only and p['id'] != a.only: continue
        path = os.path.join(a.gamedir, p['file']); bak = path + '.orig_sg1'
        print('[%s] %s' % (p['id'], p['file']))
        if a.revert:
            if os.path.exists(bak): shutil.copyfile(bak, path); print('  restored from backup')
            else: print('  no backup, nothing to do')
            continue
        if not os.path.exists(path): print('  missing file, skipped'); rc = 1; continue
        raw = open(path, 'rb').read(); nl = b'\r\n' if b'\r\n' in raw else b'\n'
        lines = raw.split(nl); hit = [i for i, l in enumerate(lines) if p['match'].encode() in l]
        if not hit:
            if p['new'].encode() in raw: print('  already applied')
            else: print('  skipped: line not found'); rc = 1
            continue
        print('  needs patch (%s)' % p['why'])
        if a.check: continue
        if not os.path.exists(bak): shutil.copyfile(path, bak)
        for i in hit: lines[i] = p['new'].encode()
        open(path, 'wb').write(nl.join(lines)); print('  patched, backup at', bak)
    return rc

# New-file patches: create a game config file that is missing from the disc image.
NEW_FILES = [
    dict(
        id="replicator-tweak-ini",
        file=os.path.join("System", "Tweak", "Pawns", "Replicator.ini"),
        why=("The game has no tweak file for the Replicator classes, so with the developer "
             "spawner they came out with default (not replicator) stats. This writes one with "
             "stats modelled on the other enemy pawn files. Only used by the NPC spawner menu."),
        text="""[Stargatecontent.Replicator]
Health=25
GroundSpeed=300
WalkingPct=0.50
CrouchedPct=0.50
WaterSpeed=300
JumpZ=250
AirControl=0.35
BaseEyeHeight=12
BaseCrouchEyeHeight=8
FearSpotReactionDelay=0.25
UnderWaterTime=5
DrowningDamageRate=100
BotSkill=3.0
MoraleDeathInc=0.1
AccelRate=500
PlayerAccelRate=2048
RotationRate=(Pitch=0,Yaw=20000,Roll=2048)

[Stargatecontent.MediumGreenReplicator]
Health=60
GroundSpeed=300
WalkingPct=0.50
CrouchedPct=0.50
WaterSpeed=300
JumpZ=250
AirControl=0.35
BaseEyeHeight=18
BaseCrouchEyeHeight=12
FearSpotReactionDelay=0.25
UnderWaterTime=5
DrowningDamageRate=100
BotSkill=3.0
MoraleDeathInc=0.1
AccelRate=500
PlayerAccelRate=2048
RotationRate=(Pitch=0,Yaw=20000,Roll=2048)

[Stargatecontent.MediumPurpleReplicator]
Health=60
GroundSpeed=300
WalkingPct=0.50
CrouchedPct=0.50
WaterSpeed=300
JumpZ=250
AirControl=0.35
BaseEyeHeight=18
BaseCrouchEyeHeight=12
FearSpotReactionDelay=0.25
UnderWaterTime=5
DrowningDamageRate=100
BotSkill=3.0
MoraleDeathInc=0.1
AccelRate=500
PlayerAccelRate=2048
RotationRate=(Pitch=0,Yaw=20000,Roll=2048)

[Stargatecontent.BigReplicator]
Health=250
GroundSpeed=350
WalkingPct=0.50
CrouchedPct=0.50
WaterSpeed=300
JumpZ=250
AirControl=0.35
BaseEyeHeight=40
BaseCrouchEyeHeight=28
FearSpotReactionDelay=0.25
UnderWaterTime=5
DrowningDamageRate=100
BotSkill=3.0
MoraleDeathInc=0.1
AccelRate=500
PlayerAccelRate=2048
RotationRate=(Pitch=0,Yaw=20000,Roll=2048)
""",
    ),
]

def run_new_files(a):
    rc = 0
    for p in NEW_FILES:
        if a.only and p['id'] != a.only: continue
        path = os.path.join(a.gamedir, p['file'])
        print('[%s] %s' % (p['id'], p['file']))
        if a.revert:
            if os.path.exists(path) and open(path, 'rb').read() == p['text'].replace('\n', '\r\n').encode():
                os.remove(path); print('  removed')
            else: print('  not ours or missing, left alone')
            continue
        if os.path.exists(path): print('  already present, left alone'); continue
        if not os.path.isdir(os.path.dirname(path)): print('  Tweak\\Pawns folder missing, skipped'); rc = 1; continue
        print('  needs file (%s)' % p['why'])
        if a.check: continue
        open(path, 'wb').write(p['text'].replace('\n', '\r\n').encode()); print('  created')
    return rc

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
    ap.add_argument('--only', metavar='ID', help='apply only the patch with this id (setup_sg1.py uses this for the always-safe file additions)')
    a = ap.parse_args()
    sysdir = os.path.join(a.gamedir, 'System')
    if not os.path.isdir(sysdir): sys.exit('no System folder in ' + a.gamedir)
    rc = 0
    for p in PATCHES:
        if a.only and p['id'] != a.only: continue
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
    rc |= run_text_patches(a)
    rc |= run_new_files(a)
    sys.exit(rc)

if __name__ == '__main__':
    main()
