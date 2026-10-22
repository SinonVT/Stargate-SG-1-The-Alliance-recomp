#!/usr/bin/env python3
"""OPTIONAL manual patch: put back the terrain grass that the Xbox build cut from the first mission level.
The dump's M02A (the map New Game -> No loads, as the stand-in Maps\\M01A.unr) has no terrain grass layers, but the engine still
supports them and the grass model is still in StaticMeshes\\M02Meshes.usx. This adds grass layers to Maps\\M01A.unr
(a backup is kept as M01A.unr.nograss; M02A.unr and all originals are never touched).

    python sg1_alliance\\tools\\install_grass.py "C:\\path\\to\\game folder"            add the grass
    python sg1_alliance\\tools\\install_grass.py "C:\\path\\to\\game folder" --undo     restore the plain copy
Options for the look: --scale 0.3 (grass size, default 0.3)  --dens 0.25 (density, default 0.25)
Close the game first (it locks the map file). Run make_standin_maps.py first if Maps\\M01A.unr does not exist.
"""
import os, shutil, subprocess, sys
a = [x for x in sys.argv[1:]]
if not a or a[0].startswith('--'): print(__doc__); sys.exit(1)
game = a[0].strip('"'); undo = '--undo' in a
def opt(n, d):
    return a[a.index(n) + 1] if n in a else d
maps = os.path.join(game, 'Maps'); m01 = os.path.join(maps, 'M01A.unr'); bak = m01 + '.nograss'; m02 = os.path.join(maps, 'M02A.unr')
if undo:
    if not os.path.isfile(bak): print('no backup (M01A.unr.nograss) found, nothing to undo'); sys.exit(1)
    shutil.copyfile(bak, m01); print('restored the plain Maps\\M01A.unr'); sys.exit(0)
if not os.path.isfile(m02): print('Maps\\M02A.unr not found in', maps); sys.exit(1)
# always start from the original M02A so running this twice does not stack layers
shutil.copyfile(m02, bak) if not os.path.exists(bak) else None
tmp = m01 + '.tmp'
r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'add_grass.py'), m02, tmp,
                    '--alpha', '--layers', '1,2', '--mesh', 'M02_deco_grass_03_clamp', '--dens', opt('--dens', '0.25'),
                    '--maxperquad', '32', '--fade', '2500,4000', '--scale', opt('--scale', '0.3') + ',' + opt('--scale', '0.3'), '--extent', '150'])
if r.returncode == 0 and os.path.isfile(tmp):
    os.replace(tmp, m01); print('grass added to Maps\\M01A.unr (New Game -> No). Undo with --undo.')
else:
    print('grass step failed; Maps\\M01A.unr unchanged'); sys.exit(1)
