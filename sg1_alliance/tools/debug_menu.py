#!/usr/bin/env python3
"""Experimental: turn the game's leftover PC debug menu (UDebugMenu.u) on/off.

usage: python debug_menu.py <game dir> on|off|status

'on' edits System\\UnrealEngine2.ini (backup UnrealEngine2.ini.orig_dbgmenu):
  Console=UWindow.WindowConsole          (UWindow console instead of Engine.Console)
  [UWindow.WindowConsole] RootWindow=UDebugMenu.UDebugRootWindow
  [UDebugMenu.UDebugRootWindow] DebugMenuKey=117   (F6)
In game press F6 for the menu bar (map list, stats graphs, video options).
Esc / the console key also open the UWindow desktop while it is on.
Close the game first: it rewrites the ini on exit.
"""
import os, re, shutil, sys

def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ("on", "off", "status"):
        print(__doc__); return 1
    ini = os.path.join(sys.argv[1], "System", "UnrealEngine2.ini")
    bak = ini + ".orig_dbgmenu"
    raw = open(ini, "rb").read()
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    txt = raw.decode("latin-1")
    on = re.search(r"^Console=UWindow\.WindowConsole", txt, re.M) is not None
    if sys.argv[2] == "status":
        print("debug menu is", "ON" if on else "OFF"); return 0
    if sys.argv[2] == "off":
        if os.path.exists(bak):
            shutil.copy2(bak, ini); print("restored", ini)
        else:
            print("no backup, nothing to do")
        return 0
    if on:
        print("already on"); return 0
    if not os.path.exists(bak):
        shutil.copy2(ini, bak)
    nlc = nl.decode()
    txt, n = re.subn(r"^Console=Engine\.Console", "Console=UWindow.WindowConsole", txt, count=1, flags=re.M)
    if n != 1:
        print("Console= line not found"); return 1
    txt = txt.rstrip() + nlc + nlc + "[UWindow.WindowConsole]" + nlc + "RootWindow=UDebugMenu.UDebugRootWindow" + nlc + nlc + \
          "[UDebugMenu.UDebugRootWindow]" + nlc + "DebugMenuKey=117" + nlc
    open(ini, "wb").write(txt.encode("latin-1"))
    print("debug menu ON: press F6 in game. Undo with: debug_menu.py <game dir> off")
    return 0

sys.exit(main())
