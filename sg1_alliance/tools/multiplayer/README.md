# Multiplayer / co-op script fixes

`setup_multiplayer.py "<game folder>"` applies them (setup_sg1.py does it for you; `--no-multiplayer` skips it, `--mp-extras` adds the extras).
Undo: `setup_multiplayer.py "<game folder>" --revert` (restores `*.orig_mp`).

Default set: only network-game code paths, multiplayer menus, or the "simulated" flag on animation functions, so single player behaves as before.
- start (no lobby wait in a network campaign), mode (StoryModeGame in the host list), browser + listinfo (campaign servers visible, real player count)
- restart (restart keeps the listen server), revive (network campaign: downed instead of dead, revive, mission failed if nobody revives)
- clientfx / clientfx2 / clientfx3 (other players drawn lying / revived correctly, revive bar), animfix (weapon pose + crouch of remote pawns)
- pkgext (widens export size fields only, no new names/imports: the client rejects those), simfuncs (leg animations of remote pawns), clientfx5 --marker (look up/down, needs game_hooks/recomp_0027_remote_player_look.patch)
- LanServerMaxTickRate 35 -> 60 in UnrealEngine2.ini (smoother remote players on a LAN)

`--extras` (not default, they also run in single player): chars (joiner gets the chosen character), takeover (joiner replaces the AI squadmate), objectives (host info screen rebuild).

Notes on how it works: see the project notes sg1-networking-notes / sg1-coop-notes-night7*.
