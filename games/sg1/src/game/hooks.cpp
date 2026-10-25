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
