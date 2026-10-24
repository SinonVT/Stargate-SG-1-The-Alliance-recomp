"""EXPERIMENTAL: show campaign (StoryModeGame) servers in the System Link server browser, so a second player can join a co-op campaign.

Retail StargateMenus.MultiplayerServerPanel.isValidGameMode is `return !(GameType ~= "StoryModeGame");`, which hides every
campaign server from the browser (the console route `open <ip>` does not work: the Xbox connect needs the host's secure
address that only the browser's discovery provides).  This changes that string to one that never matches, so the filter
lets everything through.  Same length, nothing else touched.

Usage:  python patch_coop_browser.py "<game folder>"            apply (backup System\\StargateMenus.u.orig_coop)
        python patch_coop_browser.py "<game folder>" --revert   restore the original
"""
import sys, os, shutil

OLD = bytes.fromhex('0a1f') + b'StoryModeGame\x00' + bytes.fromhex('1616')
NEW = bytes.fromhex('0a1f') + b'StoryModeGamX\x00' + bytes.fromhex('1616')

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'StargateMenus.u')
    bak = f + '.orig_coop'
    if '--revert' in sys.argv:
        if not os.path.exists(bak):
            sys.exit('no backup found, nothing to revert')
        shutil.copyfile(bak, f); print('reverted'); return
    d = open(f, 'rb').read()
    if d.count(OLD) == 1:
        if not os.path.exists(bak):
            shutil.copyfile(f, bak)
        open(f, 'wb').write(d.replace(OLD, NEW)); print('patched: campaign servers now listed in the server browser')
    elif d.count(NEW) == 1:
        print('already patched')
    else:
        sys.exit('pattern not found (different StargateMenus.u?)')

main()
