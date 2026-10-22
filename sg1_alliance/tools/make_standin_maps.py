#!/usr/bin/env python3
"""The Dec 2005 Xbox dump is missing some single-player maps. Choosing New Game -> Yes (tutorial) asks for the map
"Tutorial " (with a trailing space) and No asks for M01A; when the file is absent the game freezes on "Failed to read file".
This makes stand-in copies of Maps\\M00.unr (the tutorial level) under those names. "Tutorial .unr" is then the real tutorial; M01A is a copy of M02A (the real first mission is missing from the dump). Originals are never touched and
existing files are never overwritten. The cut terrain grass is an optional manual patch: tools\\install_grass.py. Delete the two copies to undo.

    python sg1_alliance\\tools\\make_standin_maps.py "C:\\path\\to\\game folder"
"""
import os, shutil, subprocess, sys
if len(sys.argv) < 2: print(__doc__); sys.exit(1)
maps = os.path.join(sys.argv[1].strip('"'), 'Maps')
src = os.path.join(maps, 'M00.unr')
if not os.path.isfile(src): print('Maps\\M00.unr not found in', maps); sys.exit(1)
m02a = os.path.join(maps, 'M02A.unr')   # No to the tutorial starts M02A (the first mission that is in the dump)
for name, source in (('Tutorial .unr', src), ('M01A.unr', m02a if os.path.isfile(m02a) else src)):
    dst = os.path.join(maps, name)
    if os.path.exists(dst): print('exists, left alone:', name)
    else:
        shutil.copyfile(source, dst); print('created stand-in:', name, '<-', os.path.basename(source))

note = os.path.join(sys.argv[1].strip('"'), 'STANDIN_MAPS.txt')
if not os.path.exists(note):
    open(note, 'w').write('Stand-in maps (the dump is missing these maps).\nMaps\\Tutorial .unr and Maps\\M01A.unr are copies of Maps\\M00.unr. Delete them to undo.\n')
