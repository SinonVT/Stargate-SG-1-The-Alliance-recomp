# Stargate SG-1: The Alliance - Xbox static recompilation

A work-in-progress native Windows port of the unreleased Xbox game *Stargate SG-1: The Alliance* (Unreal Engine 2, XDK 5849), built with [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) v0.15.0. The game's x86 code is translated to C and compiled with MSVC; the NV2A GPU is translated to Direct3D 11.

**No game files, no generated game code and no executables are in this repository.** You need your own copy of the game, and you generate the recompiled code yourself from your own `default.xbe`.

## Status
Boots Unreal Engine 2, shows the animated main menu, has audio, keyboard and mouse input, profile creation, and loads levels (Deathmatch maps are walkable). Menu speed is about 25-35 fps on a GTX 750. Known gaps: some maps are missing from the dump, black windows in room meshes, heat-haze effects are not emulated, game-mode editing screens are incomplete.

## Layout
- Repository root (`src/`, `include/`, `docs/` ...) - the xboxrecomp toolkit with our changes (kernel/NV2A executor, input, video). The original toolkit README is kept as `README-xboxrecomp.md`.
- `sg1_alliance/` - the game project: `src/main.c`, `src/d3d11_backend.c` (D3D11 back end), `src/recomp_manual.c`, `src/xnet_shim.c`, `CMakeLists.txt`, `tools/dbglaunch.c`.
- `sg1_alliance/game_hooks/` - small patches to the *generated* code (mouse hook in `recomp_0047.c`, D3D kickoff in `recomp_0109.c`; the kickoff one is off by default).
- `sg1_alliance/tools/patches/sg1patch.py` - fixes a bug in the game's own script files in your copy of the game (see its README).

## Building
1. Extract the game from your own disc image so you have `default.xbe` and `System/`.
2. Run the xboxrecomp pipeline on `default.xbe` to generate `sg1_alliance/src/recomp/gen/` (see the xboxrecomp docs). Apply the patches in `game_hooks/` to the generated `recomp_0047.c` and `recomp_0109.c`.
3. Set the game paths near the top of `sg1_alliance/src/main.c`.
4. In a VS 2022 x64 Native Tools prompt:

```
cd sg1_alliance
cmake -S . -B build -DXBOXRECOMP_DIR=..
cmake --build build --config Release
```

## Running
From `sg1_alliance\build\Release`:

```
dbglaunch.exe sg1_alliance_recomp.exe
```

Useful environment variables (some are set by default in `main.c`): `RECOMP_PB_EXEC=1`, `RECOMP_GPU=1`, `RECOMP_FB_WINDOW=1`, `RECOMP_VBLANK=paced`, `RECOMP_MKB=1` (mouse and keyboard). Variables set with `set` stay in a command window, so use a fresh prompt when measuring performance.

## In-game settings (Insert)
Mouse sensitivity, Invert Y, Resolution (480p to 2160p), Anisotropic filter, Mipmaps and Texture upscale (off / 2x / 4x / 8x). Settings are saved to `sg1_settings.txt` next to the exe. PgUp/PgDn change mouse sensitivity live; Home/End change the resolution.

## What we changed in xboxrecomp
Performance
- Vertex cache and multithreaded vertex transform (`RECOMP_XF_THREADS=n`, `RECOMP_XF_CACHE=0`).
- The D3D11 back end runs on its own render thread (`RECOMP_RENDER_THREAD=0/1`, `RECOMP_RT_AHEAD`).
- Pipelined framebuffer readback (`RECOMP_ASYNC_RESOLVE=0` restores blocking).
- Profiling: `RECOMP_FLIP_LOG=1`, `RECOMP_PROF=1`, `RECOMP_SAMPLE=1`.
- Known limit: the D3D kickoff waits for the GPU emulation after every kick. Skipping that wait (`RECOMP_KICK_INSTANT=1`) corrupts vertices, so it stays off until a safe version exists.

Rendering
- D3D11 back end with register-combiner HLSL, render-target and texture caches, resolution scaling, mipmaps, anisotropic filtering.
- Live texture upscale (Catmull-Rom plus light sharpen), up to 8x, capped at 2048x2048 per texture (`RECOMP_UPSCALE`).
- COLOR_MATERIAL lighting fix; unsupported texture-shader modes are skipped instead of drawn black.

Input
- Native mouse look, mouse buttons, keyboard mapping, hidden and clipped cursor, USB gamepad thread fixes.

## Caveats
- Tested on one machine (GTX 750, many cores). Threading is disabled below 4 cores.
- Some debug logging is still in: `[HUDDRAW]`, `[TEXFMT]`, and a `texdump` folder written next to the exe. Delete the dump folders before sharing a build directory.
- This is not an official project and has no affiliation with the game's rights holders.

## Credits
Built on [sp00nznet/xboxrecomp](https://github.com/sp00nznet/xboxrecomp) (see `LICENSE`).
