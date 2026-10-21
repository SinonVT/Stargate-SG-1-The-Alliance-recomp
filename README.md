# Stargate SG-1: The Alliance - Xbox static recompilation

A work-in-progress native Windows port of the unreleased Xbox game *Stargate SG-1: The Alliance* (Unreal Engine 2, XDK 5849), built with [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) v0.15.0. The game's x86 code is translated to C and compiled with MSVC; the NV2A GPU is translated to Direct3D 11.

**No game files, no generated game code and no executables are in this repository.** You need your own copy of the game, and you generate the recompiled code yourself from your own `default.xbe`.

## Status
Boots Unreal Engine 2, shows the animated main menu, has audio, keyboard, mouse and gamepad input, profile creation, and loads levels (Deathmatch maps are walkable). Player (projected) shadows render, the game's Brightness/Contrast/Gamma keys work, floor and wall textures sample correctly, and an optional HD texture pack swaps the game's reduced textures for the original full-size art from its own packages. Menu speed is about 25-35 fps on a GTX 750. Known gaps: some maps are missing from the dump, black windows in room meshes, levels can look dark in places (many static meshes have unbaked, zero vertex lighting in this unfinished build; the "Dark area lift" option compensates), fire and brazier emitters are frozen, anisotropic filtering or high resolutions can corrupt lighting, a rare crash in the object list, game-mode editing screens are incomplete.

## Layout
- Repository root (`src/`, `include/`, `docs/` ...) - the xboxrecomp toolkit with our changes (kernel/NV2A executor, input, video). The original toolkit README is kept as `README-xboxrecomp.md`.
- `sg1_alliance/` - the game project: `src/main.c`, `src/d3d11_backend.c` (D3D11 back end), `src/recomp_manual.c`, `src/xnet_shim.c`, `CMakeLists.txt`, `tools/dbglaunch.c`.
- `sg1_alliance/game_hooks/` - small patches to the *generated* code (mouse hook in `recomp_0047.c`, gamma ramp capture in `recomp_0108.c`, D3D kickoff in `recomp_0109.c`; the kickoff one is off by default) and `apply_hooks.py`, which applies them.
- `sg1_alliance/tools/make_hdpack.py` - builds the HD texture pack from your own game files (see HD texture pack below).
- `sg1_alliance/tools/patches/sg1patch.py` - fixes a bug in the game's own script files in your copy of the game (see its README).

## Building
1. Extract the game from your own disc image so you have `default.xbe` and `System/`.
2. Run the xboxrecomp pipeline on `default.xbe` to generate `sg1_alliance/src/recomp/gen/` (see the xboxrecomp docs). Then, from the `sg1_alliance` folder, apply our patches to the generated code with `python game_hooks/apply_hooks.py` (needs only Python 3; it patches `recomp_0047.c`, `recomp_0108.c` and `recomp_0109.c`, skips anything already applied, and `--check` just reports the state).
3. Nothing to edit for paths: the exe looks for `default.xbe` in its own folder and its parent folders (or in `RECOMP_GAME_DIR` if set).
4. In a VS 2022 x64 Native Tools prompt:

```
cd sg1_alliance
cmake -S . -B build -DXBOXRECOMP_DIR=..
cmake --build build --config Release
```

## HD texture pack
The pack is built from your own game files, so it is not in the repository (about 850 MB).

```
pip install numpy pillow
python sg1_alliance/tools/make_hdpack.py "C:\path\to\game" "sg1_alliance\build\Release\texpack"
```

This writes `texpack\hd\*.png` and `texpack\index.txt` next to the exe (a few minutes; you can run it again, it resumes). A C compiler makes it faster, otherwise a slower pure-Python hash is used. Turn it on or off with "HD texture pack" in the Insert menu (`hdpack` in `sg1_settings.txt`). The default size cap is 1024 px per texture; pass a third argument (for example `512`) if a level stutters or runs out of video memory.

Want your own AI-upscaled or hand-painted versions? Put a PNG with the **same file name** as one in `texpack\hd` into `texpack\custom` (`texpack\upscale_dump.bat` runs Real-ESRGAN over the whole `hd` folder into `custom` if you have it). Files in `custom` win over the shipped ones ("Custom textures" in the menu). Delete a file from `custom` to go back to the original.

## Running
From `sg1_alliance\build\Release`:

```
dbglaunch.exe sg1_alliance_recomp.exe
```

Useful environment variables (some are set by default in `main.c`): `RECOMP_PB_EXEC=1`, `RECOMP_GPU=1`, `RECOMP_FB_WINDOW=1`, `RECOMP_VBLANK=paced`, `RECOMP_MKB=1` (mouse and keyboard). Variables set with `set` stay in a command window, so use a fresh prompt when measuring performance.

## In-game settings (Insert)
Mouse sensitivity, Invert Y, Controllers on/off, Resolution (480p to 2160p), Anisotropic filter, Mipmaps, HD texture pack, Custom textures, Heat haze, Player shadows, Game gamma/brightness (applies the game's own gamma ramp), Dark area lift (off / low / medium / high / max) and a Debug page (texture dump, draw logs, hide draws, floor texgen fix, cube map lighting). Esc on the Debug page goes back. Settings are saved to `sg1_settings.txt` next to the exe. PgUp/PgDn change mouse sensitivity live; Home/End change the resolution.

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
- Debug logging is off unless you enable the debug items in the Insert menu; those can write logs, `texdump` folders and small `rt128_*.bmp` files next to the exe. Delete them before sharing a build directory.
- In-game gamma/brightness/contrast keys (F10/F11/F12) work, but F12 crashes when a debugger is attached (Windows reserves it). The original `UnrealEngine2.ini` values are Brightness 0.8, Contrast 0.7, Gamma 0.8.
- This is not an official project and has no affiliation with the game's rights holders.

## Credits
Built on [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) (see `LICENSE`).
