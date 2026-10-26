"""Adds Jacob / Selmak to the multiplayer character list (System/tweak/MP/Characters.ini), between Walter and the Tok'ra:
    Characters=(Name="Jacob / Selmak",PawnClass="StargateContent.Jacob_Selmak",Picture="SG1_MainMenuTex.MM_main_menu_players_Grey")
An existing Jacob line is replaced (a hand-added one with a ')' after PawnClass lost its picture). Other lines are not touched.
Usage: python patch_mp_characters.py "<game folder>" [--revert]   (backup Characters.ini.orig_mpchars)
"""
import sys, os, shutil

LINE = b'Characters=(Name="Jacob / Selmak",PawnClass="StargateContent.Jacob_Selmak",Picture="SG1_MainMenuTex.MM_main_menu_players_Grey")'

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: sys.exit(__doc__)
    f = os.path.join(args[0], 'System', 'tweak', 'MP', 'Characters.ini'); bak = f + '.orig_mpchars'
    if '--revert' in sys.argv:
        if os.path.exists(bak): shutil.copyfile(bak, f); print('reverted', f)
        return
    if not os.path.exists(f): sys.exit('no ' + f)
    raw = open(f, 'rb').read(); nl = b'\r\n' if b'\r\n' in raw else b'\n'
    lines = raw.split(nl)
    def cls(l):
        l = l.strip().lower()
        return l.startswith(b'characters=') and b'pawnclass="stargatecontent.' in l and l.split(b'pawnclass="stargatecontent.')[1].split(b'"')[0]
    if [l.strip() for l in lines].count(LINE) == 1 and sum(1 for l in lines if cls(l) == b'jacob_selmak') == 1:
        print('Characters.ini: Jacob / Selmak already listed'); return
    lines = [l for l in lines if cls(l) != b'jacob_selmak']
    at = next((i + 1 for i, l in enumerate(lines) if cls(l) == b'sgcwalter'), None)
    if at is None: at = next((i for i, l in enumerate(lines) if cls(l) == b'tokra'), None)
    if at is None: at = max([i + 1 for i, l in enumerate(lines) if cls(l)] or [len(lines)])
    lines.insert(at, LINE)
    if not os.path.exists(bak): shutil.copyfile(f, bak)
    open(f, 'wb').write(nl.join(lines))
    print('Characters.ini: Jacob / Selmak added after Walter')

main()
