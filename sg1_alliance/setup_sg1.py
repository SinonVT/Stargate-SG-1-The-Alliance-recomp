#!/usr/bin/env python3
"""One-step setup for the SG-1 recomp: generates the recompiled code from YOUR default.xbe,
applies our hooks, and (optionally) builds.

    python sg1_alliance\\setup_sg1.py "C:\\path\\to\\game folder"          (folder that contains default.xbe)
    python sg1_alliance\\setup_sg1.py "C:\\path\\to\\game folder" --build   (also run cmake + build)
    add --redo to regenerate even if sg1_alliance\\src\\recomp\\gen already exists

Run it from anywhere; needs Python 3.9+ (pip installs 'capstone' for you). The pipeline takes several minutes.
"""
import os, sys, subprocess, shutil
here = os.path.dirname(os.path.abspath(__file__))          # .../sg1_alliance
root = os.path.dirname(here)                                # repo root (the toolkit)
args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
if not args:
    print(__doc__); sys.exit(1)
game = args[0].strip('"')
xbe = game if game.lower().endswith('.xbe') else os.path.join(game, 'default.xbe')
if not os.path.isfile(xbe):
    print('ERROR: default.xbe not found at', xbe); sys.exit(1)
gen = os.path.join(here, 'src', 'recomp', 'gen')
py = sys.executable

def run(title, cmd, cwd=root):
    print('\n=== %s\n    %s' % (title, ' '.join(cmd)), flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        print('\nERROR: step failed (%s). Fix the message above and run this script again.' % title); sys.exit(r.returncode)

try:
    import capstone  # noqa
except ImportError:
    run('Installing capstone (disassembler library)', [py, '-m', 'pip', 'install', 'capstone'])

done = os.path.exists(os.path.join(gen, 'recomp_dispatch.c')) and '--redo' not in flags
if done:
    print('Generated code already exists in', gen, '(use --redo to regenerate).')
else:
    os.makedirs(gen, exist_ok=True)
    os.makedirs(os.path.join(root, 'tools', 'xbe_parser', 'output'), exist_ok=True)
    aj = os.path.join(root, 'tools', 'xbe_parser', 'output', 'default_analysis.json')
    run('1/5 Parse the XBE', [py, '-m', 'tools.xbe_parser', xbe, '--json', aj])
    run('2/5 Disassemble (slow: 30-60+ minutes, one CPU core)', [py, '-m', 'tools.disasm', xbe, '--analysis-json', aj])
    run('3/5 Identify library functions', [py, '-m', 'tools.func_id', xbe, '-v'])
    run('4/5 ABI analysis', [py, '-m', 'tools.abi_analysis', xbe, '-v'])
    run('5/5 Recompile to C (several minutes)', [py, '-m', 'tools.recomp', xbe, '--all', '--split', '250', '--gen-dir', gen])

run('Applying our hooks to the generated code', [py, os.path.join(here, 'game_hooks', 'apply_hooks.py')], cwd=here)
if '--build' in flags:
    if not shutil.which('cmake'):
        print('cmake not found: open a "x64 Native Tools Command Prompt for VS 2022" and run this script again, or build by hand (below).')
    else:
        run('Configure', ['cmake', '-S', '.', '-B', 'build', '-DXBOXRECOMP_DIR=..'], cwd=here)
        run('Build (Release)', ['cmake', '--build', 'build', '--config', 'Release'], cwd=here)
print('''
Setup finished.''' + ('' if '--build' in flags else '''
To build, in a "x64 Native Tools Command Prompt for VS 2022":
    cd sg1_alliance
    cmake -S . -B build -DXBOXRECOMP_DIR=..
    cmake --build build --config Release'''))
print('''Then run  sg1_alliance\\build\\Release\\dbglaunch.exe sg1_alliance_recomp.exe  (it finds default.xbe in its own or a parent folder; or set RECOMP_GAME_DIR).
Optional next steps: HD pack (tools\\make_hdpack.py) and the script fix (tools\\patches\\sg1patch.py) - see README.''')
