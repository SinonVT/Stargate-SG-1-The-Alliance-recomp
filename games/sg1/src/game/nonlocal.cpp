// setjmp / longjmp. The game's libjpeg (and a few other spots) catch errors with the CRT's _setjmp3 (0x3E9690) and
// longjmp (0x3E9614): a texture that will not decode longjmps back into the function that armed it. Recompiled, the
// longjmp's final  jmp [buf+0x14]  lands mid-function, which the dispatcher cannot call. Here longjmp does the CRT's
// SEH unwinding, puts the saved registers back and throws X86Resume; the function that called setjmp catches it on
// the host stack (unwinding the frames in between) and resumes at the return address after its setjmp call, which
// config/game.toml lists as a function.
#include <cstdint>

#include "cpu/x86_ops.h"
#include "core/log.h"
#include "kernel/kernel.h"

namespace {

constexpr uint32_t kVc20 = 0x56433230;  // MSVC's jmp_buf cookie

void CatchResume(X86Context& ctx, uint8_t* base, X86Func* fn, uint32_t resume) {
    const uint32_t frame = ctx.esp;
    X86Resume r{0, 0};
    bool resumed = false;
    for (;;) {
        try {
            if (resumed) x86_resume(ctx, base, r);
            else fn(ctx, base);
            return;
        } catch (const X86Resume& e) {
            if (e.target != resume || e.esp > frame) throw;
            r = e;
            resumed = true;
        }
    }
}

}  // namespace

#define SG1_SETJMP_SITE(fn, resume)                                                     \
    X86_EXTERN_FUNC(__imp__##fn);                                                       \
    X86_FUNC(fn) { CatchResume(ctx, base, __imp__##fn, resume); }

SG1_SETJMP_SITE(sub_003BADA0, 0x003BAE27u)
SG1_SETJMP_SITE(sub_003D6730, 0x003D674Cu)
SG1_SETJMP_SITE(sub_00468016, 0x0046805Cu)
SG1_SETJMP_SITE(sub_0046894A, 0x004689C1u)
SG1_SETJMP_SITE(sub_0046DF3C, 0x0046DF58u)

namespace {
bool IsResume(uint32_t t) {
    return t == 0x003BAE27u || t == 0x003D674Cu || t == 0x0046805Cu || t == 0x004689C1u || t == 0x0046DF58u;
}
}  // namespace

// longjmp(jmp_buf, value), cdecl
X86_EXTERN_FUNC(__imp__sub_003E9614);
X86_FUNC(sub_003E9614) {
    using namespace kernel;
    uint32_t buf = R32(ctx.esp + 4), val = R32(ctx.esp + 8);
    uint32_t target = R32(buf + 0x14);
    if (!IsResume(target)) {
        LOGE("longjmp to %08X: no setjmp site known there", target);
        __imp__sub_003E9614(ctx, base);
        return;
    }
    // the CRT's unwinding: SEH frames registered since the setjmp, then the setjmp frame's own try levels
    uint32_t reg = R32(buf + 0x18);
    ctx.ebx = buf;
    ctx.ebp = R32(buf);
    if (reg != R32(ctx.fs_base)) CallGuest(ctx, 0x003E58C8u, {reg});
    if (reg) {
        uint32_t ok = CallGuest(ctx, 0x003EF801u, {buf + 0x20});
        if (ok && R32(buf + 0x20) == kVc20) {
            if (uint32_t f = R32(buf + 0x24)) CallGuest(ctx, f, {buf});
        } else {
            CallGuest(ctx, 0x003E590Au, {reg, R32(buf + 0x1C)});
        }
    }
    ctx.ebp = R32(buf);
    ctx.ebx = R32(buf + 4);
    ctx.edi = R32(buf + 8);
    ctx.esi = R32(buf + 0xC);
    ctx.eax = val ? val : 1;
    uint32_t esp = R32(buf + 0x10) + 4;
    LOG_FIRST(16, "longjmp to %08X (value %u)", target, ctx.eax);
    throw X86Resume{target, esp};
}
