# Game-script patches

Some bugs are in the game's own Unreal script (`System/*.u`), not in the
recompiled code. `sg1patch.py` fixes them in **your own extracted copy** of the
game. No game data is stored in this repository.

    python tools/patches/sg1patch.py "C:\path\to\game"            # apply
    python tools/patches/sg1patch.py "C:\path\to\game" --check    # status only
    python tools/patches/sg1patch.py "C:\path\to\game" --revert   # undo

`C:\path\to\game` is the folder that contains `System\` and `default.xbe`,
extracted from your own disc image. Every patched file is backed up next to
itself as `<name>.orig_sg1` first, and patches are located by function and call
name, so they apply to any build of the same package and are safe to re-run.

## Patches

| id | file | fix |
|----|------|-----|
| `teamsay-nonteam` | `Engine.u` | `TeamSay` was silently dropped in non-team games (e.g. Deathmatch) because the anti-spam check ran twice. |
| `gamemodes-last-man-standing` | `System\tweak\MP\GameModes.ini` | Enables the Last Man Standing game mode (the code is in `StargateGame.u`, only the menu entry was commented out). |
| `replicator-tweak-ini` | `System\Tweak\Pawns\Replicator.ini` | Creates the missing tweak file for the Replicator classes (new file, only if absent) so replicators spawned from the developer NPC menu get proper stats. |

To add a patch, append an entry to `PATCHES` in `sg1patch.py`.
