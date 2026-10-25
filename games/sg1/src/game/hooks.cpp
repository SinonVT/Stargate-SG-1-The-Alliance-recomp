// Hooks for default.xbe (Stargate SG-1: The Alliance)
#include <cstring>

#include "core/log.h"
#include "cpu/x86_ops.h"
#include "kernel/kernel.h"

// The game's debug print (XAPI OutputDebugStringA, 0x33EEBB) ends in "int 2Dh; int 3". The Xbox kernel steps over
// the int 3; recompiled, the int 3 traps. Log the text and return (stdcall, one argument).
X86_FUNC(sub_0033EEBB) {
    (void)base;
    kernel::Args a{ctx};
    LOGI("game: %s", kernel::ReadCString(a[0], 512).c_str());
    kernel::Return(ctx, 0, 1);
}

// UE2 null-name loads (from the sp00nznet/xboxrecomp port, recomp_0008_null_workarounds): GameInfo::InitGame loads an
// empty class name; the engine then throws "Can't resolve package name" out of GetPackageLinker / StaticLoadObject and
// startup never comes back from it. Return NULL instead, as a failed load does. Both are cdecl: only the return
// address is popped.
X86_EXTERN_FUNC(__imp__sub_00072B70);
X86_FUNC(sub_00072B70) {                       // ULinkerLoad* GetPackageLinker(UObject* Outer, const TCHAR* File, ...)
    kernel::Args a{ctx};
    if (!a[0] && !a[1]) {
        LOG_FIRST(4, "SG1: GetPackageLinker(NULL, NULL) -> NULL");
        kernel::Return(ctx, 0, 0);
        return;
    }
    __imp__sub_00072B70(ctx, base);
}

X86_EXTERN_FUNC(__imp__sub_00073250);
X86_FUNC(sub_00073250) {                       // UObject* StaticLoadObject(UClass*, UObject* Outer, const TCHAR* Name, ...)
    kernel::Args a{ctx};
    uint32_t name = a[2];
    if (name && name < 0x08000000u) {
        uint16_t c;
        std::memcpy(&c, kernel::HostPtr(name), 2);
        if (c == 0) {
            LOG_FIRST(4, "SG1: StaticLoadObject(empty name) -> NULL");
            kernel::Return(ctx, 0, 0);
            return;
        }
    }
    __imp__sub_00073250(ctx, base);
}

// UUIXInteraction::RegisterPlayer (the Xbox Live UI player list) asks the UIX object for the player's entry
// (0x307F60), which comes back NULL here, and hands it to 0x308520 unchecked: [NULL + 0x20] on loading a map.
// Nothing to update without an entry: return (thiscall, one stack argument).
X86_EXTERN_FUNC(__imp__sub_00308520);
X86_FUNC(sub_00308520) {
    kernel::Args a{ctx};
    if (!a[0]) {
        LOG_FIRST(4, "SG1: UIX player entry missing, update skipped (0x308520)");
        kernel::Return(ctx, 0, 1);
        return;
    }
    __imp__sub_00308520(ctx, base);
}

// ---- instruction hooks ([[hook]] in config/game.toml), ported from the sp00nznet/xboxrecomp game_hooks ----

// GUIStyles.DrawText's optional OverrideColor (recomp_0043_drawtext_optcolor): when the script leaves it out, the
// stale stack local was taken as the colour (alpha 1/255), so the Tab objectives text was invisible. Clear it first.
X86_HOST_API void SG1_DrawTextColor(X86Context& ctx, uint8_t* base) {
    (void)base;
    kernel::W32(ctx.esp + 0x28, 0);
}

// Never strip lip-sync animations (recomp_0013_lipsync_keep_story_anims): the level prefix list drops the story lines
// of levels that list no prefix (m02_, m02int_, coda_, prol_ ...). The strip test's result is forced to "keep".
X86_HOST_API void SG1_LipsyncKeep(X86Context& ctx, uint8_t* base) {
    (void)base;
    ctx.eax = 0;
}

// DirectSound timeout path (recomp_0115_purecall_skip): the object is already being destroyed and its slot 0x18 is
// _purecall, which ends the game with R6025. Skip that call.
X86_HOST_API bool SG1_SkipPurecall(X86Context& ctx, uint8_t* base) {
    (void)base;
    if (kernel::R32(ctx.eax + 0x18) == 0x003E5501u) {
        LOG_FIRST(8, "SG1: skipped a pure virtual call on a dying DirectSound object %08X", ctx.esi);
        return true;
    }
    return false;
}

// ---- co-op: look up / down of other players (ported from recomp_0027_remote_player_look) ----
// UpdateTwistLook (0x1A27D0, thiscall, this = pawn). The co-op script marks a downed / knocked-back remote player
// with LookTargetActor (+0x7B0) == Level (+0xA0). Treat it like the host's own pawn: clear the look target (the script
// sets the mark again every frame) and remember that it was marked, so the look pitch comes from the replicated ViewPitch.
static bool g_sg1_downmark = false;
X86_HOST_API void SG1_LookDownMark(X86Context& ctx, uint8_t* base) {   // before 0x1A27D6, esi = pawn
    (void)base;
    g_sg1_downmark = false;
    uint32_t lta = kernel::R32(ctx.esi + 0x7B0);
    if (lta != 0 && lta == kernel::R32(ctx.esi + 0xA0)) {
        kernel::W32(ctx.esi + 0x7B0, 0);
        g_sg1_downmark = true;
    }
}

// UpdateTwistLook only follows the real view pitch when the pawn has a Controller (branch at 0x1A2C22). On a client other
// players' pawns have none, so their look up / down never showed. The co-op script marks such a pawn with
// LookTargetActor == itself; take the Controller branch for it (and for a marked downed pawn): look = ViewPitch, which
// the server replicates. Runs before 0x1A2C4A (the no-Controller branch); true jumps to 0x1A2C22.
X86_HOST_API bool SG1_LookUseViewPitch(X86Context& ctx, uint8_t* base) {
    (void)base;
    if (kernel::R32(ctx.esi + 0x7B0) == ctx.esi) return true;
    return g_sg1_downmark;
}

// Smooth the replicated look pitch of other players' pawns (jitter fix).
// Runs at 0x001A2C38 in UpdateTwistLook, eax = signed pitch from ViewPitch.
#include <unordered_map>
X86_HOST_API void SG1_LookSmoothPitch(X86Context& ctx, uint8_t* base) {
    (void)base;
    static std::unordered_map<uint32_t, float> s_pitch;
    int32_t target = (int32_t)ctx.eax;
    auto it = s_pitch.find(ctx.esi);
    if (it == s_pitch.end() || target - it->second > 6000.f || it->second - target > 6000.f) {
        s_pitch[ctx.esi] = (float)target;
        return;
    }
    it->second += ((float)target - it->second) * 0.25f;
    ctx.eax = (uint32_t)(int32_t)it->second;
}

// ---- co-op: mouth of other players' characters while they speak (taunts etc.) ----
// The voice pack plays the sound on the server and starts the lip-sync animation there only; a client just gets the sound
// (APlayerController::execClientHearSound, 0x20C620) and the remote pawn's mouth stays shut. After the client has decided to
// play the sound (0x20C75A: [esp+0x10] = actor, [esp+0x44] = sound) start the lip-sync of a pawn that nobody on this machine
// controls, if it has an animation named like the sound. Uses the engine's own execHasLIPSincAnim (0x211470) and
// execPlayLIPSincAnim (0x211210) with a small fake script frame built below the stack.
namespace {
uint32_t RunLipExec(X86Context& ctx, uint32_t fn, uint32_t actor, uint32_t nameIdx, bool withOptionals, uint32_t scratch) {
    using namespace kernel;
    uint32_t frame = scratch, code = scratch + 0x40, result = scratch + 0x30;
    for (uint32_t i = 0; i < 0x60; i += 4) W32(scratch + i, 0);
    uint32_t p = code;
    G<uint8_t>(p++) = 0x21;                                    // EX_NameConst
    W32(p, nameIdx); p += 4;
    if (withOptionals) for (int i = 0; i < 3; i++) G<uint8_t>(p++) = 0x0B;   // EX_Nothing: default volume / radius / pitch
    G<uint8_t>(p++) = 0x16;                                    // EX_EndFunctionParms
    G<uint8_t>(p++) = 0x04;
    W32(frame + 0x08, actor);                                  // FFrame::Object
    W32(frame + 0x0C, code);                                   // FFrame::Code
    ctx.ecx = actor;
    CallGuest(ctx, fn, {frame, result});
    return R32(result);
}
}

X86_HOST_API void SG1_ClientVoiceLip(X86Context& ctx, uint8_t* base) {
    (void)base;
    using namespace kernel;
    uint32_t actor = R32(ctx.esp + 0x10), snd = R32(ctx.esp + 0x44);
    if (!actor || !snd) return;
    if (R32(actor + 0xC0) == 0) return;          // no lip-sync component
    if (R32(actor + 0x390) != 0) return;         // a pawn controlled on this machine does its own
    uint32_t nameIdx = R32(snd + 0x20);
    X86Context save = ctx;
    uint32_t scratch = (ctx.esp - 0x200) & ~15u;
    ctx.esp = scratch;
    if (RunLipExec(ctx, 0x00211470u, actor, nameIdx, false, scratch) & 1)
        RunLipExec(ctx, 0x00211210u, actor, nameIdx, true, scratch);
    ctx = save;
}
