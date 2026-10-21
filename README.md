# Stargate SG-1: The Alliance - Xbox static recompilation

A work-in-progress native Windows port of the unreleased Xbox game *Stargate SG-1: The Alliance* (Unreal Engine 2, XDK 5849), built with [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) v0.15.0. The game's x86 code is translated to C and compiled with MSVC; the NV2A GPU is translated to Direct3D 11.

**No game files, no generated game code and no executables are in this repository.** You need your own copy of the game, and you generate the recompiled code yourself from your own `default.xbe`.

![Stargate SG-1: The Alliance running natively on Windows](docs/screenshots/sg1_alliance_recomp.png)

*In-game screenshot: DM map with player shadow, cube-map lighting and the HD texture pack.*

## Status
Boots Unreal Engine 2, shows the animated main menu, has audio, keyboard, mouse and gamepad input, profile creation, and loads levels (Deathmatch maps are walkable). Player (projected) shadows render, the game's Brightness/Contrast/Gamma keys work, floor and wall textures sample correctly, and an optional HD texture pack swaps the game's reduced textures for the original full-size art from its own packages. Menu speed is about 25-35 fps on a GTX 750. Known gaps: some maps are missing from the dump, black windows in room meshes, levels can look dark in places (many static meshes have unbaked, zero vertex lighting in this unfinished build; the "Dark area lift" option compensates), fire and brazier emitters are frozen, anisotropic filtering or high resolutions can corrupt lighting, a rare crash in the object list, game-mode editing screens are incomplete.

## Layout
- Repository root (`src/`, `include/`, `docs/` ...) - the xboxrecomp toolkit with our changes (kernel/NV2A executor, input, video). The original toolkit README is kept as `README-xboxrecomp.md`.
- `sg1_alliance/` - the game project: `src/main.c`, `src/d3d11_backend.c` (D3D11 back end), `src/recomp_manual.c`, `src/xnet_shim.c`, `CMakeLists.txt`, `tools/dbglaunch.c`.
- `sg1_alliance/setup_sg1.py` / `setup_sg1.bat` - one-step setup (generate, patch, build).
- `sg1_alliance/game_hooks/` - patches to the *generated* code (keyboard and mouse look in `recomp_0047.c`, menu mouse in `recomp_0043.c`, gamma ramp in `recomp_0108.c`, XNet shim hooks in `recomp_0103.c`, two crash workarounds in `recomp_0008.c`, a missing FPU entry in `recomp_dispatch.c`, D3D kickoff in `recomp_0109.c` which is off by default) and `apply_hooks.py`, which applies them.
- `sg1_alliance/tools/make_hdpack.py` - builds the HD texture pack from your own game files (see HD texture pack below).
- `sg1_alliance/tools/patches/sg1patch.py` - fixes a bug in the game's own script files in your copy of the game (see its README).

## Quick start
You need: Windows 10/11, [Visual Studio 2022](https://visualstudio.microsoft.com/) (Desktop development with C++, which includes CMake), [Python 3](https://www.python.org/downloads/) (tick "Add to PATH"), Git, and your own copy of the game extracted from your disc image (a folder containing `default.xbe` and `System\`).

1. Clone this repo: `git clone https://github.com/SinonVT/Stargate-SG-1-The-Alliance-recomp` and open a **x64 Native Tools Command Prompt for VS 2022** in it.
2. Run one command (about 10-30 minutes the first time):

```
sg1_alliance\setup_sg1.bat "C:\path\to\your game folder" --build
```

It generates the recompiled code from your `default.xbe`, applies our fixes to it, then builds. If something fails it stops and says which step; fix that and run the same line again (finished steps are skipped).
3. Start the game: `sg1_alliance\build\Release\dbglaunch.exe sg1_alliance_recomp.exe`. The exe finds `default.xbe` in its own folder or a parent folder; if your game is elsewhere set `RECOMP_GAME_DIR` to its folder first.
4. Optional: the HD texture pack (below) and `sg1_alliance\tools\patches\sg1patch.py` (fixes a bug in the game's own script files). The Insert key opens the in-game settings.

Do not try to run the pieces by hand unless you have to: the generated code must be patched with `game_hooks\apply_hooks.py` (setup does this) or the keyboard, menu mouse, gamma and network pieces will be missing. `python sg1_alliance\game_hooks\apply_hooks.py --check` shows whether they are applied.

Common problems: "capstone not found" (setup installs it; if pip is blocked run `pip install capstone`), "cmake not found" (use the VS Native Tools prompt, not a normal one), mismatched Python (use `py -3`), and a black or empty window (the exe could not find `default.xbe`; see step 3).

## Building by hand
Only if you did not use the script: run the xboxrecomp pipeline on your `default.xbe` (`tools.xbe_parser --json`, `tools.disasm --text-only`, `tools.func_id`, `tools.abi_analysis`, then `python -m tools.recomp default.xbe --all --split 250 --gen-dir sg1_alliance/src/recomp/gen`), run `python sg1_alliance/game_hooks/apply_hooks.py`, then `cd sg1_alliance`, `cmake -S . -B build -DXBOXRECOMP_DIR=..`, `cmake --build build --config Release`.

## HD texture pack
The pack is built from your own game files, so it is not in the repository (about 850 MB).

```
pip install numpy pillow
python sg1_alliance/tools/make_hdpack.py "C:\path\to\game" "sg1_alliance\build\Release\texpack"
```

This writes `texpack\hd\*.png` and `texpack\index.txt` next to the exe (a few minutes; you can run it again, it resumes). A C compiler makes it faster, otherwise a slower pure-Python hash is used. Turn it on or off with "HD texture pack" in the Insert menu (`hdpack` in `sg1_settings.txt`). The default size cap is 1024 px per texture; pass a third argument (for example `512`) if a level stutters or runs out of video memory.

Want your own AI-upscaled or hand-painted versions? Put a PNG with the **same file name** as one in `texpack\hd` into `texpack\custom` (`texpack\upscale_dump.bat` runs Real-ESRGAN over the whole `hd` folder into `custom` if you have it). Files in `custom` win over the shipped ones once you turn on "Custom textures" in the Insert menu (it is off by default because the HD pack already covers the stock game). Delete a file from `custom` to go back to the original.

## Running
From `sg1_alliance\build\Release`:

```
dbglaunch.exe sg1_alliance_recomp.exe
```

Useful environment variables (some are set by default in `main.c`): `RECOMP_PB_EXEC=1`, `RECOMP_GPU=1`, `RECOMP_FB_WINDOW=1`, `RECOMP_VBLANK=paced`, `RECOMP_MKB=1` (mouse and keyboard). Variables set with `set` stay in a command window, so use a fresh prompt when measuring performance.

## In-game settings (Insert)
Mouse sensitivity, Invert Y, Controllers on/off, Field of view (60-120, typed into the game console for you, so use it in a map; the game saves it in `System\User.ini`), Resolution (480p to 2160p), Anisotropic filter, Mipmaps, HD texture pack, Custom textures, Heat haze, Player shadows, Game gamma/brightness (applies the game's own gamma ramp), Dark area lift (off / low / medium / high / max) and a Debug page (texture dump, draw logs, hide draws, floor texgen fix, cube map lighting). Esc on the Debug page goes back. Defaults on a fresh install: mouse sensitivity 50, controllers off, HD texture pack on, 720p, anisotropic off, mipmaps on, custom textures off, heat haze on, player shadows on, game gamma on, dark area lift low, floor texgen fix and cube map lighting on, debug items off. Settings are saved to `sg1_settings.txt` next to the exe. PgUp/PgDn change mouse sensitivity live; Home/End change the resolution.

## Controls
In a match the keyboard and mouse go to the game through its own bindings in `System\User.ini` (the PC prototype layout: WASD, Space jump, Ctrl/C duck, Shift walk, Z zoom, R reload, F use, number keys select weapons, mouse wheel cycles). The toolkit's keyboard-as-controller layer (Z/X/C/V = A/B/X/Y) is only active in the front-end menus, because the menus only listen to a pad; the recompiled build turns it off while a match is loaded (it follows the game's own log). Known issue: C may still jump in a match.

## Optional tools
- `sg1_alliance\tools\extract_scripts.py <game dir> <out dir>` writes the UnrealScript source that every `System\*.u` package carries (do not publish its output).
- `sg1_alliance\tools\debug_menu.py <game dir> on|off` is an experiment to open the game's leftover PC debug menu (F6); it replaces the console and breaks the console-typing the FOV and profile-name features use, so leave it off.
- `sg1patch.py` also has a game-mode patch that enables Last Man Standing in `System\tweak\MP\GameModes.ini`.

## What we changed in xboxrecomp
Performance
- Vertex cache and multithreaded vertex transform (`RECOMP_XF_THREADS=n`, `RECOMP_XF_CACHE=0`).
- The D3D11 back end runs on its own render thread (`RECOMP_RENDER_THREAD=0/1`, `RECOMP_RT_AHEAD`).
- Pipelined framebuffer readback (`RECOMP_ASYNC_RESOLVE=0` restores blocking).
- Profiling: `RECOMP_FLIP_LOG=1`, `RECOMP_PROF=1`, `RECOMP_SAMPLE=1`.
- Known limit: the D3D kickoff waits for the GPU emulation after every kick. Skipping that wait (`RECOMP_KICK_INSTANT=1`) corrupts vertices, so it stays off until a safe version exists.

Rendering
- D3D11 back end with register-combiner HLSL, render-target and texture caches, resolution scaling, mipmaps, anisotropic filtering.
- HD texture pack: the game only uploads reduced copies of its textures, but the original art (up to 1024 or 2048 px) is still in `Textures\*.utx`. `make_hdpack.py` finds it and the game swaps it in when a texture is uploaded (matched by a hash of the texture's bytes). Cube-map lighting on characters (fixes blown-out coats and skin).
- Player shadows: B8 shadow-map render targets are rasterised, and fixed-function texture-coordinate generation (eye/object linear planes, projective S/T/Q, normal map, reflection, sphere) is emulated in the vertex path. Toggle with Player shadows in the Insert menu (`shadows` in `sg1_settings.txt`).
- Fixed-function texgen wins over a stale vertex array (fixes blurry floors), texture matrices on array-fed stages.
- Gamma ramp capture and display.
- COLOR_MATERIAL lighting fix; unsupported texture-shader modes are skipped instead of drawn black.

Input
- Native mouse look, mouse buttons, keyboard mapping, hidden and clipped cursor, USB gamepad thread fixes, a Controllers on/off setting, and held keys now repeat correctly.

## Caveats
- Tested on one machine (GTX 750, many cores). Threading is disabled below 4 cores.
- Debug logging is off unless you enable the debug items in the Insert menu; those can write logs, `texdump` folders next to the exe (`rt128_*.bmp` shadow-map dumps only with `RECOMP_RT_DUMP=1`). Delete them before sharing a build directory.
- In-game gamma/brightness/contrast keys (F10/F11/F12) work, but F12 crashes when a debugger is attached (Windows reserves it). The original `UnrealEngine2.ini` values are Brightness 0.8, Contrast 0.7, Gamma 0.8.
- This is not an official project and has no affiliation with the game's rights holders.

## Credits
Built on [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) (see `LICENSE`).
