"""Make the HUD health/shield bar follow the player's health in story mode.

Retail GameHud.SetHealth does nothing in story mode:

    if (P.Level.GRI.GameClass != "StoryModeGame") { ... UpdateStatusBar(ShieldBar, MaxHealth, health); }

so the bar only moves for a shield, and a player without one sees a bar that never changes
(same on the Xbox).  This changes the string the class name is compared with to one that never
matches ("StoryModeGamX"), so the bar is updated in story mode too.  Same length, nothing else touched.

Usage:  python patch_health_bar.py "<game folder>"            apply (backup System\\StargateGame.u.orig_hb)
        python patch_health_bar.py "<game folder>" --revert   restore the original
Re-running is harmless.
"""
import sys, os, shutil

OLD = bytes.fromhex('01f10e1f') + b'StoryModeGame\x00' + bytes.fromhex('16')
NEW = bytes.fromhex('01f10e1f') + b'StoryModeGamX\x00' + bytes.fromhex('16')

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateGame.u')
    bak = f + '.orig_hb'
    if '--revert' in sys.argv:
        if not os.path.exists(bak):
            sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = open(f, 'rb').read()
    if d.count(OLD) == 1:
        if not os.path.exists(bak):
            shutil.copyfile(f, bak)
        open(f, 'wb').write(d.replace(OLD, NEW)); print('patched: health bar now follows health in story mode')
    elif d.count(NEW) == 1:
        print('already patched')
    else:
        sys.exit('pattern not found (different StargateGame.u?)')

main()
