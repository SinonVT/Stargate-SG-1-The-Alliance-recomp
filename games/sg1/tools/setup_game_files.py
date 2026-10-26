#!/usr/bin/env python3
"""Prepares YOUR copy of the game in assets\\ for this port (run it once, before build.bat):

    py tools\\setup_game_files.py              (uses the assets folder of this repository)
    py tools\\setup_game_files.py "D:\\path\\to\\game folder"
    add --no-multiplayer to skip the co-op / multiplayer script fixes,
        --mp-no-extras to leave out the joiner character / squadmate take-over / objectives extras

Every step only changes your own game files and keeps a backup beside each changed file (*.orig_*); each tool has a
--revert. Steps that are already applied are skipped, so running it again is safe. Needs Python 3.9+.
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))           # ...\tools
root = os.path.dirname(here)
args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
game = os.path.abspath(args[0].strip('"')) if args else os.path.join(root, 'assets')
if not os.path.isfile(os.path.join(game, 'default.xbe')):
    print('ERROR: default.xbe not found in', game)
    print('Copy your extracted game (default.xbe with System, Maps, Textures ... beside it) into the assets folder first.')
    sys.exit(1)
py = sys.executable
failed = []


def step(title, script, *extra):
    cmd = [py, os.path.join(here, *script.split('/'))] + list(extra)
    print('\n=== %s' % title, flush=True)
    r = subprocess.run(cmd, cwd=here)
    if r.returncode != 0:
        failed.append((title, script))


# the dump lacks the Tutorial / M01A maps and two music tracks: New Game freezes and deathmatch stutters without them
step('Stand-in tutorial maps and music', 'make_standin_maps.py', game)
# this port's key layout (B = third person, Ctrl = duck, voice binds ...): the dump has the PC prototype layout
step('Keyboard layout (User.ini)', 'controls_preset.py', game)
# plain stargates ignore their second trigger in the retail scripts, so the menu gate never closes
step('Stargate that never closes (StargateContent.u)', 'patch_gate_close.py', os.path.join(game, 'System', 'StargateContent.u'))
# the chevrons light as a gate dials only in the PC build's script (#ifdefPC); this puts it back
step('Chevrons light up as a stargate dials (StargateContent.u)', 'patch_gate_chevrons.py', game)
# non-team chat, the Last Man Standing menu entry and the missing Replicator.ini
step('Game script fixes (teamsay, Last Man Standing, Replicator.ini)', 'patches/sg1patch.py', game)
# the health / shield bar never moves in story mode in the retail script (the same on the Xbox)
step('Health bar in story mode (StargateGame.u)', 'patch_health_bar.py', game)
# the staff's right-click melee animation exists only in the Jaffa set: the SG-1 team, Walter, Jacob and the Tok'ra swung without one
step('Staff melee animation for everyone (StargateGame.u)', 'patch_staff_melee.py', game)
# the selected profile's name goes into the join URL, so the player is named after the profile
step('Player name from the selected profile (Engine.u)', 'patch_profile_name.py', game)
# texture detail High, weather and high detail actors on (only changes the Xbox defaults)
step('Graphics settings (UnrealEngine2.ini)', 'patch_gfx_ini.py', game)
if '--no-multiplayer' not in flags:
    # co-op campaign / multiplayer script fixes: network-only or menu-only changes, single player is not touched
    step('Multiplayer / co-op script fixes', 'multiplayer/setup_multiplayer.py', game,
         *(['--no-extras'] if '--mp-no-extras' in flags else []))

if failed:
    print('\nSome steps did not finish (see above); run them by hand:')
    for title, script in failed:
        print('  %s:  py tools\\%s "%s"' % (title, script.replace('/', '\\'), game))
    sys.exit(1)
print('\nGame files ready. Next: build.bat')
