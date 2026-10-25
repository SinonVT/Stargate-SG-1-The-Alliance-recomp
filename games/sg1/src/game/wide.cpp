// SG1 wide fill: the gun, the hands and the HUD widgets are drawn by UCanvas::DrawActor (0x101EA0, thiscall: actor, ?, ?,
// float DisplayFOV, ?) with a horizontal FOV meant for 4:3. On a wider window the renderer stretches perspective draws
// in clip y to the window's aspect, so DisplayFOV is widened the same way (Hor+): the vertical extent stays what 4:3
// gave and the HUD widgets keep their 4:3 layout in the middle. Ported from recomp_0019_drawactor_fov.
#include <cmath>

#include "cpu/x86_ops.h"
#include "gpu/ext.h"
#include "kernel/kernel.h"

X86_EXTERN_FUNC(__imp__sub_00101EA0);
X86_FUNC(sub_00101EA0) {
    if (gpu::g_fill_window.load()) {
        float a = gpu::g_display_aspect.load();
        float& f = kernel::G<float>(ctx.esp + 16);
        if (a > 1.34f && f > 1.0f && f < 170.0f) {
            float t = std::tan(f * 0.5f * 0.017453292f) * a * 0.75f;
            f = 2.0f * std::atan(t) * 57.29578f;
        }
    }
    __imp__sub_00101EA0(ctx, base);
}
