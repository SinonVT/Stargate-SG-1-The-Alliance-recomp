#!/usr/bin/env python3
"""Keyboard layout used by this port (edits [Engine.Input] in System\\User.ini and System\\DefUser.ini of YOUR game folder).
The dump's default layout is the PC prototype layout (Ctrl=Jump, Alt=Fire, Z=Strafe, Q=WeaponZoom, B unbound...). This sets:

    B = ToggleBehindView (third person)     Ctrl = Duck        CapsLock = toggleInvisibility
    Z = ZoomToggle                          Alt, Backspace, Q = unbound (Alt releases the mouse pointer)

    python sg1_alliance\\tools\\controls_preset.py "C:\\path\\to\\game folder"            apply
    python sg1_alliance\\tools\\controls_preset.py "C:\\path\\to\\game folder" --revert   restore the backups (*.orig_sg1)
Only those keys change; a backup is saved once as User.ini.orig_sg1 / DefUser.ini.orig_sg1. Close the game first.
"""
import os, shutil, sys
a = [x for x in sys.argv[1:]]
if not a or a[0].startswith('--'): print(__doc__); sys.exit(1)
sysdir = os.path.join(a[0].strip('"'), 'System'); revert = '--revert' in a
KEYS = [('Ctrl', 'Duck'), ('Alt', ''), ('CapsLock', 'toggleInvisibility'), ('Z', 'ZoomToggle'), ('Backspace', ''), ('B', 'ToggleBehindView'), ('Q', '')]
done = 0
for name in ('User.ini', 'DefUser.ini'):
    p = os.path.join(sysdir, name); bak = p + '.orig_sg1'
    if revert:
        if os.path.isfile(bak): shutil.copyfile(bak, p); print('restored', name); done += 1
        continue
    if not os.path.isfile(p): print('not found (skipped):', name); continue
    raw = open(p, 'rb').read(); crlf = b'\r\n' in raw
    lines = raw.decode('latin-1').replace('\r\n', '\n').split('\n')
    sec = None; first_in = None; last_in = None; seen = set(); changed = 0
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith('['): sec = s.lower()
        if sec == '[engine.input]':
            if first_in is None: first_in = i
            last_in = i
            if '=' in l and not s.startswith(';'):
                k = l.split('=', 1)[0].strip()
                for kk, vv in KEYS:
                    if k.lower() == kk.lower():
                        seen.add(kk)
                        if l.split('=', 1)[1].strip() != vv: lines[i] = kk + '=' + vv; changed += 1
    missing = [(k, v) for k, v in KEYS if k not in seen]
    if missing and last_in is not None:
        pos = last_in + 1
        while pos > first_in + 1 and lines[pos - 1].strip() == '': pos -= 1
        for k, v in reversed(missing): lines.insert(pos, k + '=' + v); changed += 1
    if not changed: print(name, 'already has this layout'); continue
    if not os.path.exists(bak): shutil.copyfile(p, bak)
    out = '\n'.join(lines)
    if crlf: out = out.replace('\n', '\r\n')
    open(p, 'wb').write(out.encode('latin-1')); print('updated', name, '(%d keys)' % changed); done += 1
if not done and not revert: print('nothing changed')
