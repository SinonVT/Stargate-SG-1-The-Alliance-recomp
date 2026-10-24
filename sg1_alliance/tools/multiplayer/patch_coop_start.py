"""EXPERIMENTAL: let a network (co-op) campaign start without the cut "waiting for players" lobby.

Retail StoryModeGame.InitGame does `bWaitForNetPlayers = (Level.NetMode != NM_StandAlone); bDelayedStart = (Level.NetMode != NM_StandAlone);`.
In a network game the match then waits (world paused) for a lobby/ready screen that the shipped build no longer opens, so the
host sits frozen and joiners spectate an empty map.  This changes both comparisons to `Level.NetMode == 255` (always false), so the
campaign starts at once, exactly as in a single-player game.  Same length, standalone behaviour unchanged (both were already false there).

Usage:  python patch_coop_start.py "<game folder>"            apply (backup System\\StargateGame.u.orig_coopstart)
        python patch_coop_start.py "<game folder>" --revert   restore the original
"""
import sys, os, shutil

TAIL_OLD = bytes.fromhex('9b393a19019605000101dd01393a240016')
TAIL_NEW = bytes.fromhex('9a393a19019605000101dd01393a24ff16')
HEADS = [bytes.fromhex('142d01770e'), bytes.fromhex('142d01d713')]   # bWaitForNetPlayers, bDelayedStart

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u')
    bak = f + '.orig_coopstart'
    if '--revert' in sys.argv:
        if not os.path.exists(bak):
            sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = open(f, 'rb').read()
    n_old = sum(d.count(h + TAIL_OLD) for h in HEADS)
    n_new = sum(d.count(h + TAIL_NEW) for h in HEADS)
    if n_old == 3:
        if not os.path.exists(bak):
            shutil.copyfile(f, bak)
        for h in HEADS:
            d = d.replace(h + TAIL_OLD, h + TAIL_NEW)
        open(f, 'wb').write(d); print('patched: network campaign starts without the waiting lobby (%d places)' % n_old)
    elif n_new == 3 and n_old == 0:
        print('already patched')
    else:
        sys.exit('pattern not found (found %d unpatched / %d patched, expected 3) - different StargateGame.u?' % (n_old, n_new))

main()
