"""EXPERIMENTAL: adds "StoryModeGame" to the Multiplayer > Host game-mode list (StargateGame.StoryModeGame), so a co-op campaign can be hosted
from the menus instead of the console / coop_host.bat. Only edits System\\tweak\\MP\\GameModes.ini (one new line after Last Man Standing, plus GameName and MaxPlayers=8 in the [Stargategame.StoryModeGame] section).

Host:  Multiplayer > System Link > Host > "StoryModeGame" > pick a character > pick a story map (M01A, M02A, ...).
Joiners: Multiplayer > System Link > join the listed server (needs patch_coop_browser.py).
Usage:  python patch_coop_mode.py "<game folder>"            apply (backup GameModes.ini.orig_coopmode)
        python patch_coop_mode.py "<game folder>" --revert   restore
"""
import sys, os, shutil
LINE = 'GameModes=(Name="StoryModeGame",GameClass="StargateGame.StoryModeGame")'
args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not args: sys.exit(__doc__)
f = os.path.join(args[0], 'System', 'tweak', 'MP', 'GameModes.ini'); bak = f + '.orig_coopmode'
if '--revert' in sys.argv:
    if not os.path.exists(bak): sys.exit('no backup found, nothing to revert')
    shutil.copyfile(bak, f); print('reverted'); sys.exit()
raw = open(f, 'rb').read(); nl = b'\r\n' if b'\r\n' in raw else b'\n'
lines = raw.split(nl)
if not os.path.exists(bak): shutil.copyfile(f, bak)
# 1. menu entry (replace ours if present, else add after Last Man Standing)
mine = [i for i, l in enumerate(lines) if l.startswith(b'GameModes=') and b'StargateGame.StoryModeGame' in l]
if mine: lines[mine[0]] = LINE.encode()
else:
    at = [i for i, l in enumerate(lines) if l.lstrip(b'#').startswith(b'GameModes=') and b'LastManStandingGame' in l]
    if not at: sys.exit('Last Man Standing line not found; add this line under [StargateMenus.GameModeList] by hand:\n' + LINE)
    lines.insert(at[0] + 1, LINE.encode())
# 2. game name shown in the server list and max players (the default of 16 is too many for a squad campaign)
hd = [i for i, l in enumerate(lines) if l.strip().lower() == b'[stargategame.storymodegame]']
if not hd: sys.exit('[Stargategame.StoryModeGame] section not found')
i = hd[0] + 1
while i < len(lines) and not lines[i].startswith(b'['):
    if lines[i].split(b'=')[0].strip().lower() in (b'gamename', b'maxplayers'): del lines[i]
    else: i += 1
lines[hd[0] + 1:hd[0] + 1] = [b'GameName="StoryModeGame"', b'MaxPlayers=8']
open(f, 'wb').write(nl.join(lines)); print('patched: StoryModeGame added to the host game modes (max 8 players)')
