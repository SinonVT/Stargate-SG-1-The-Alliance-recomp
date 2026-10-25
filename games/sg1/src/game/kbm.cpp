// Keyboard and mouse for Stargate SG-1: The Alliance, as Unreal Engine input events.
//
// The window's keyboard and mouse messages are queued here and handed to the engine at the start of the Xbox
// viewport's input update (0x32D370, this = the viewport): keys and mouse buttons through UEngine::InputEvent
// (0x120D10: viewport, key, action, delta), typed characters through UEngine::Key (0x120CE0: viewport, key, char),
// and raw mouse motion as IK_MouseX / IK_MouseY axis events. The game's System\User.ini binds them as on the PC.
// Ported from the sp00nznet/xboxrecomp version (recomp_0047_keyboard_mouse, recomp_0043_menu_mouse, mkb_input.c).
//
// Menus: while a game menu is drawn (0x2FDCF0 runs each menu frame) the mouse drives the menu's own cursor: the
// GUI controller (this of 0x2FD640, its InputEvent) gets IK_MouseX/Y, IK_LeftMouse and IK_Joy2 (back) for the right
// button, its cursor position is set directly and its windows-mouse bit (0x4000 at +0x168), which hides the
// software cursor, is cleared.
//
// Keys: F9 frees / captures the mouse, PgUp / PgDn mouse sensitivity, Insert the settings menu, V the voice menu.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <mutex>
#include <string>

#include "app/app.h"
#include "core/log.h"
#include "cpu/x86_ops.h"
#include "game/sg1_input.h"
#include "gpu/ext.h"
#include "kernel/kernel.h"

namespace sg1kbm {

uint32_t g_opt_sens_x10 = 500;
uint32_t g_opt_menu_x100 = 100;
bool g_opt_invert_y = false;
uint32_t g_opt_fov = 0;
bool g_opt_hor_plus = true;
bool g_opt_fill = true;
bool g_opt_maximized = false;

std::atomic<bool> g_overlay{false};
std::atomic<bool> g_voice{false};
std::atomic<int> g_voice_sel{0};
std::atomic<bool> g_in_menu{false};

// each row presses a key whose User.ini binding is  Taunt <MSGID>  (NumPad7 opens the console, so F18 for that one)
const VoiceLine kVoice[] = {
    {"Taunt", 0x61},           {"OK / affirmative", 0x62}, {"Negative", 0x63},        {"Ready", 0x64},
    {"Enemy spotted", 0x65},   {"Take cover", 0x66},       {"Enemy killed", 0x81},    {"Area clear", 0x68},
    {"Under fire", 0x69},      {"Team under fire", 0x60},  {"Man down", 0x7C},        {"In cover", 0x7D},
    {"Holding fire", 0x7E},    {"Firing", 0x7F},           {"Friendly fire!", 0x80},
};
const int kVoiceCount = int(sizeof kVoice / sizeof *kVoice);

namespace {

enum : int { kPress = 1, kRepeat = 2, kRelease = 3, kAxis = 4 };   // EInputAction
enum : int { kMouseX = 0xE4, kMouseY = 0xE5, kWheelUp = 0xEC, kWheelDown = 0xED, kJoy2 = 0xC9 };
enum : UINT { kMsgCapture = WM_APP + 0x51, kMsgSave = WM_APP + 0x52, kMsgMaximize = WM_APP + 0x53 };
bool g_max_ready = false;   // the saved maximized state was put back: size changes from here on are the player's

struct Ev {
    int vk;
    int action;     // kPress / kRepeat / kRelease, 0 = a typed character
    int ch;
};

std::mutex g_lock;
std::deque<Ev> g_q;
long g_mx = 0, g_my = 0;
bool g_capture = true;
bool g_active = false;
HWND g_hwnd = nullptr;
int g_last_down_vk = 0;
bool g_typing = false;        // chat or console line open: V and the rest are letters
bool g_lb_suppress = false;   // the voice menu took a left press: its release stays away from the game too
std::string g_cmd;            // console command waiting to be typed
bool g_cmd_pending = false;

std::atomic<uint32_t> g_menu_tick{0};
std::atomic<uint32_t> g_gui{0};   // the GUI controller, this of its InputEvent (0x2FD640)

float Sens() { return float(g_opt_sens_x10) / 10.0f; }

void Push(int vk, int action, int ch = 0) {
    std::lock_guard<std::mutex> l(g_lock);
    if (g_q.size() < 512) g_q.push_back({vk, action, ch});
}

void ReleaseHeld() {
    std::lock_guard<std::mutex> l(g_lock);
    for (int vk = 1; vk < 0xE0; vk++)
        if (GetAsyncKeyState(vk) & 0x8000) g_q.push_back({vk, kRelease, 0});
}

// window thread only: the cursor's show count belongs to the thread
void ApplyCapture() {
    if (!g_hwnd) return;
    if (g_capture && g_active && !g_overlay.load()) {
        RECT r;
        GetClientRect(g_hwnd, &r);
        MapWindowPoints(g_hwnd, nullptr, reinterpret_cast<POINT*>(&r), 2);
        ClipCursor(&r);
        while (ShowCursor(FALSE) >= 0) {}
    } else {
        ClipCursor(nullptr);
        while (ShowCursor(TRUE) < 0) {}
    }
}

void VoiceSay() {
    int s = g_voice_sel.load();
    if (s < 0 || s >= kVoiceCount) return;
    Push(int(kVoice[s].vk), kPress);
    Push(int(kVoice[s].vk), kRelease);
}

}  // namespace

void SetOverlay(bool on) {
    bool was = g_overlay.exchange(on);
    if (was == on) return;
    if (on) {
        g_voice = false;
        ReleaseHeld();
        std::lock_guard<std::mutex> l(g_lock);
        g_mx = g_my = 0;
    } else {
        SaveSettings();
    }
    if (g_hwnd) PostMessageW(g_hwnd, kMsgCapture, 0, 0);
}

void SaveSettings() {
    if (g_hwnd) PostMessageW(g_hwnd, kMsgSave, 0, 0);
}

void TypeCommand(const char* cmd) {
    std::lock_guard<std::mutex> l(g_lock);
    g_cmd = cmd;
    g_cmd_pending = true;
}

// the FOV the game should have: the menu's (75, the game's own, when unset), widened for a wide window (Hor+: the
// vertical view stays what 4:3 gave)
int FovTarget() {
    double fov = g_opt_fov ? double(g_opt_fov) : 75.0;
    double a = gpu::g_fill_window.load() ? double(gpu::g_display_aspect.load()) : 4.0 / 3.0;
    if (g_opt_hor_plus && a > 1.34) {
        double h = std::tan(fov * 0.5 * 3.14159265358979 / 180.0) * (a * 0.75);
        fov = 2.0 * std::atan(h) * 180.0 / 3.14159265358979;
        if (fov > 150.0) fov = 150.0;
    }
    return int(fov + 0.5);
}

namespace {
std::atomic<int> g_fov_sent{0};   // this session's, 0 = not yet
}

void SendFov() { g_fov_sent = 0; }   // the viewport update types it once a level is up

namespace {
// in a level with no menu for 3 s: type FOV when it differs from what this session last typed
void FovTick(uint32_t now, uint32_t menu_free_since) {
    static int last_t = 0;
    static uint32_t since = 0;
    if (!g_opt_fov && !gpu::g_fill_window.load()) return;
    if (!menu_free_since || now - menu_free_since < 3000 || g_overlay.load()) return;
    int t = FovTarget();
    if (t != last_t) { last_t = t; since = now; return; }   // a window being resized: wait until it settles
    if (now - since < 1000 || t == g_fov_sent.load()) return;
    g_fov_sent = t;
    char b[32];
    std::snprintf(b, sizeof b, "FOV %d", t);
    TypeCommand(b);
    LOGI("kbm: %s", b);
}
}  // namespace

void OnWindow(void* hwnd) {
    g_hwnd = static_cast<HWND>(hwnd);
    if (const char* e = std::getenv("SG1_MOUSE_SENS")) {
        float f = float(std::atof(e));
        if (f > 0.0f) g_opt_sens_x10 = uint32_t(f * 10.0f + 0.5f);
    }
    if (g_opt_sens_x10 < 1) g_opt_sens_x10 = 500;
    if (g_opt_menu_x100 < 10) g_opt_menu_x100 = 100;
    gpu::g_fill_window = g_opt_fill;
    TexpackInit();
    RAWINPUTDEVICE rid{};
    rid.usUsagePage = 0x01;
    rid.usUsage = 0x02;          // mouse
    rid.dwFlags = 0;
    rid.hwndTarget = g_hwnd;
    if (!RegisterRawInputDevices(&rid, 1, sizeof rid)) LOGE("kbm: raw mouse input not available (%lu)", GetLastError());
    g_active = GetForegroundWindow() == g_hwnd;
    ApplyCapture();
    if (IsWindowVisible(g_hwnd)) PostMessageW(g_hwnd, kMsgMaximize, 0, 0);
    LOGI("kbm: keyboard and mouse on (F9 frees the mouse, Insert settings, V voice), sensitivity %.1f", Sens());
}

bool OnMessage(void* hwnd, uint32_t msg, uintptr_t wp, intptr_t lp, intptr_t* result) {
    (void)hwnd;
    const bool overlay = g_overlay.load();
    switch (msg) {
    case kMsgCapture:
        ApplyCapture();
        *result = 0;
        return true;
    case kMsgMaximize:   // windowed and maximized last time (also across Exit to main menu, which restarts the exe)
        if (!g_max_ready) {
            g_max_ready = true;
            if (g_opt_maximized && app::Get().display_mode == app::DisplayMode::Windowed && !IsZoomed(g_hwnd))
                ShowWindow(g_hwnd, SW_MAXIMIZE);
        }
        *result = 0;
        return true;
    case WM_SHOWWINDOW:
        if (wp && !g_max_ready) PostMessageW(g_hwnd, kMsgMaximize, 0, 0);
        break;
    case kMsgSave:
        app::Save();
        *result = 0;
        return true;
    case WM_ACTIVATE:
        g_active = LOWORD(wp) != WA_INACTIVE;
        ApplyCapture();
        if (!g_active) ReleaseHeld();   // let go of everything held, or it stays held in the game
        break;
    case WM_SIZE:
        if (g_max_ready && app::Get().display_mode == app::DisplayMode::Windowed && wp != SIZE_MINIMIZED) {
            bool m = wp == SIZE_MAXIMIZED;
            if (m != g_opt_maximized) { g_opt_maximized = m; SaveSettings(); }
        }
        ApplyCapture();
        break;
    case WM_MOVE:
        ApplyCapture();
        break;
    case WM_KEYDOWN:
    case WM_SYSKEYDOWN: {
        int vk = int(wp);
        bool rep = (lp & (1 << 30)) != 0;
        if (vk == VK_INSERT && !rep) { SetOverlay(!overlay); return false; }
        if (overlay) {
            if (vk == VK_ESCAPE && !rep) SetOverlay(false);
            return false;           // the settings menu has the keyboard
        }
        if (vk == VK_F9 && !rep) { g_capture = !g_capture; ApplyCapture(); return false; }
        if (vk == VK_PRIOR && !rep) { g_opt_sens_x10 = uint32_t(g_opt_sens_x10 * 1.25f + 0.5f); LOGI("kbm: mouse sensitivity %.1f", Sens()); SaveSettings(); }
        if (vk == VK_NEXT && !rep && g_opt_sens_x10 > 1) { g_opt_sens_x10 = uint32_t(g_opt_sens_x10 / 1.25f + 0.5f); LOGI("kbm: mouse sensitivity %.1f", Sens()); SaveSettings(); }
        bool menu = g_in_menu.load();
        if (!rep && !menu) {
            if (vk == 'V' && !g_typing) {   // the voice menu instead of CallForHelp
                bool v = !g_voice.load();
                g_voice = v;
                return false;
            }
            if (vk == 'T' || vk == 'Y' || vk == VK_OEM_3) { if (!g_typing) { g_typing = true; g_voice = false; } }
            else if (vk == VK_RETURN || vk == VK_ESCAPE) g_typing = false;
        }
        if (menu) g_typing = false;
        if (vk == VK_ESCAPE && g_voice.load()) g_voice = false;
        if (vk == VK_OEM_3) vk = VK_NUMPAD7;   // ` opens the console: the game's console listens for NumPad7
        g_last_down_vk = vk;
        Push(vk, rep ? kRepeat : kPress);
        if (msg == WM_SYSKEYDOWN && (vk == VK_MENU || vk == VK_F10)) { *result = 0; return true; }   // Alt / F10: no system menu
        break;
    }
    case WM_KEYUP:
    case WM_SYSKEYUP: {
        int vk = int(wp);
        if (vk == VK_OEM_3) vk = VK_NUMPAD7;
        if (vk == 'V' || vk == VK_INSERT) break;
        Push(vk, kRelease);     // releases go through even with the settings menu up
        if (msg == WM_SYSKEYUP && (vk == VK_MENU || vk == VK_F10)) { *result = 0; return true; }
        break;
    }
    case WM_CHAR:
        if (overlay) break;
        if (wp >= 32 && wp < 0x10000 && wp != '`') Push(g_last_down_vk, 0, int(wp));
        break;
    case WM_LBUTTONDOWN:
        if (overlay) break;
        if (g_voice.load()) { VoiceSay(); g_voice = false; g_lb_suppress = true; break; }
        Push(VK_LBUTTON, kPress);
        break;
    case WM_LBUTTONUP:
        if (g_lb_suppress) { g_lb_suppress = false; break; }
        Push(VK_LBUTTON, kRelease);
        break;
    case WM_RBUTTONDOWN: if (!overlay) Push(VK_RBUTTON, kPress); break;
    case WM_RBUTTONUP:   Push(VK_RBUTTON, kRelease); break;
    case WM_MBUTTONDOWN: if (!overlay) Push(VK_MBUTTON, kPress); break;
    case WM_MBUTTONUP:   Push(VK_MBUTTON, kRelease); break;
    case WM_MOUSEWHEEL: {
        if (overlay) break;
        int up = GET_WHEEL_DELTA_WPARAM(wp) > 0;
        if (g_voice.load()) {   // the wheel picks the line, no weapon switch
            int s = g_voice_sel.load() + (up ? -1 : 1);
            g_voice_sel = (s % kVoiceCount + kVoiceCount) % kVoiceCount;
            break;
        }
        int k = up ? kWheelUp : kWheelDown;
        Push(k, kPress);
        Push(k, kRelease);
        break;
    }
    case WM_INPUT: {
        RAWINPUT ri;
        UINT sz = sizeof ri;
        if (GetRawInputData(reinterpret_cast<HRAWINPUT>(lp), RID_INPUT, &ri, &sz, sizeof(RAWINPUTHEADER)) != UINT(-1)
            && ri.header.dwType == RIM_TYPEMOUSE && !(ri.data.mouse.usFlags & MOUSE_MOVE_ABSOLUTE) && g_active && g_capture
            && !overlay) {
            std::lock_guard<std::mutex> l(g_lock);
            g_mx += ri.data.mouse.lLastX;
            g_my += ri.data.mouse.lLastY;
        }
        break;
    }
    default:
        break;
    }
    return false;
}

}  // namespace sg1kbm

namespace {

// the GUI controller's InputEvent (thiscall: key*, state*, float delta)
void GuiEvent(X86Context& ctx, uint32_t gui, int key, int state, float delta) {
    uint32_t save_esp = ctx.esp;
    ctx.esp -= 16;
    uint32_t kp = ctx.esp, sp = ctx.esp + 4;
    kernel::W32(kp, 0);
    kernel::W32(sp, 0);
    kernel::G<uint8_t>(kp) = uint8_t(key);
    kernel::G<uint8_t>(sp) = uint8_t(state);
    uint32_t fb;
    std::memcpy(&fb, &delta, 4);
    ctx.ecx = gui;
    kernel::CallGuest(ctx, 0x002FD640u, {kp, sp, fb});
    ctx.esp = save_esp;
}

struct MenuMouse {
    float x = 320.0f, y = 240.0f;
    bool lb = false, rb = false;
};
MenuMouse g_mm;

void MenuFrame(X86Context& ctx, uint32_t gui, long mx, long my, int lb, int rb) {
    using namespace kernel;
    float scale = float(sg1kbm::g_opt_menu_x100) / 100.0f;
    float dx = float(mx) * scale, dy = float(my) * scale;
    float wmax = float(int32_t(R32(gui + 0x218))) - 1.0f, hmax = float(int32_t(R32(gui + 0x21C))) - 1.0f;
    g_mm.x += dx;
    g_mm.y += dy;
    if (g_mm.x < 0) g_mm.x = 0;
    if (wmax > 0 && g_mm.x > wmax) g_mm.x = wmax;
    if (g_mm.y < 0) g_mm.y = 0;
    if (hmax > 0 && g_mm.y > hmax) g_mm.y = hmax;
    auto place = [&] {
        uint32_t vp = R32(gui + 0x2C);
        if (vp) { G<float>(vp + 0x3C) = g_mm.x; G<float>(vp + 0x40) = g_mm.y; }
        G<float>(gui + 0x200) = g_mm.x;
        G<float>(gui + 0x204) = g_mm.y;
    };
    // the software cursor is drawn only while the windows-mouse bit is clear
    uint32_t fl = R32(gui + 0x168);
    if (fl & 0x4000u) W32(gui + 0x168, (fl & ~0x4000u) | 0x2000u);
    place();
    if (dx != 0.0f) GuiEvent(ctx, gui, 0xE4, 4, dx);
    if (dy != 0.0f) GuiEvent(ctx, gui, 0xE5, 4, -dy);
    if (lb >= 0 && bool(lb) != g_mm.lb) { g_mm.lb = lb; place(); GuiEvent(ctx, gui, 0x01, lb ? 1 : 3, 0.0f); }
    if (rb >= 0 && bool(rb) != g_mm.rb) { g_mm.rb = rb; GuiEvent(ctx, gui, 0xC9, rb ? 1 : 3, 0.0f); }
    place();
}

int CharVk(unsigned c) {
    if (c >= 'a' && c <= 'z') return int(c - 32);
    if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) return int(c);
    switch (c) {
    case ' ': return 0x20;
    case '.': return 0xBE;
    case '=': return 0xBB;
    case '-': return 0xBD;
    case '/': case '?': return 0xBF;
    case '\\': return 0xDC;
    case '\'': return 0xDE;
    default: return 0x20;
    }
}

}  // namespace

// a game menu frame
X86_EXTERN_FUNC(__imp__sub_002FDCF0);
X86_FUNC(sub_002FDCF0) {
    sg1kbm::g_menu_tick = GetTickCount();
    __imp__sub_002FDCF0(ctx, base);
}

// the GUI controller's InputEvent: keep its this for the menu mouse
X86_EXTERN_FUNC(__imp__sub_002FD640);
X86_FUNC(sub_002FD640) {
    if (ctx.ecx) sg1kbm::g_gui = ctx.ecx;
    __imp__sub_002FD640(ctx, base);
}

// UXboxViewport input update (thiscall, this = viewport): the queued keys and mouse motion go to the engine first.
X86_EXTERN_FUNC(__imp__sub_0032D370);
X86_FUNC(sub_0032D370) {
    using namespace sg1kbm;
    static thread_local bool busy = false;
    static uint32_t menu_free_since = 0;
    static int type_stage = -1, type_wait = 0;
    static std::string type_cmd;
    uint32_t view = ctx.ecx;
    uint32_t client = view ? kernel::R32(view + 0x18) : 0;
    uint32_t engine = client ? kernel::R32(client + 0x28) : 0;
    uint32_t now = GetTickCount();
    bool menu = g_menu_tick.load() && now - g_menu_tick.load() < 250;
    g_in_menu = menu;
    if (menu) menu_free_since = 0;
    else if (!menu_free_since) menu_free_since = now ? now : 1;
    FovTick(now, menu_free_since);
    if (engine && !busy) {
        std::deque<Ev> evs;
        long mx, my;
        {
            std::lock_guard<std::mutex> l(g_lock);
            evs.swap(g_q);
            mx = g_mx; my = g_my; g_mx = g_my = 0;
            if (g_cmd_pending && type_stage < 0) { type_cmd = g_cmd; g_cmd_pending = false; type_stage = 0; }
        }
        busy = true;
        uint32_t keep_ecx = ctx.ecx, keep_eax = ctx.eax, keep_edx = ctx.edx;
        auto input = [&](int vk, int action, float delta = 0.0f) {
            uint32_t fb;
            std::memcpy(&fb, &delta, 4);
            ctx.ecx = engine;
            kernel::CallGuest(ctx, 0x00120D10u, {view, uint32_t(vk), uint32_t(action), fb});
        };
        auto key = [&](int vk, int ch) {
            ctx.ecx = engine;
            kernel::CallGuest(ctx, 0x00120CE0u, {view, uint32_t(vk), uint32_t(ch)});
        };
        // a console command: open the console, a frame later type the line (its first character is swallowed)
        if (type_stage >= 0 && !menu && !g_overlay.load() && now - menu_free_since > 500) {
            if (type_stage == 0) {
                input(0x67, kPress);
                input(0x67, kRelease);
                type_stage = 1;
                type_wait = 3;
            } else if (--type_wait <= 0) {
                std::string line = " " + type_cmd;
                for (char c : line) {
                    int vk = CharVk(uint8_t(c));
                    input(vk, kPress);
                    key(vk, uint8_t(c));
                    input(vk, kRelease);
                }
                input(VK_RETURN, kPress);
                input(VK_RETURN, kRelease);
                type_stage = -1;
            }
        }
        uint32_t gui = g_gui.load();
        bool menu_mouse = menu && gui;
        int lb = -1, rb = -1;
        for (const Ev& e : evs) {
            if (menu_mouse && (e.vk == VK_LBUTTON || e.vk == VK_RBUTTON) && e.action) {
                if (e.action != kRepeat) (e.vk == VK_LBUTTON ? lb : rb) = e.action == kPress;
                continue;
            }
            if (e.action) input(e.vk, e.action);
            else key(e.vk, e.ch);
        }
        if (menu_mouse) {
            MenuFrame(ctx, gui, mx, my, lb, rb);   // every frame: keeps the cursor shown and placed
        } else {
            if (!menu) g_mm.lb = g_mm.rb = false;
            float s = Sens();
            if (mx) input(kMouseX, kAxis, float(mx) * s);
            if (my) input(kMouseY, kAxis, (g_opt_invert_y ? 1.0f : -1.0f) * float(my) * s);
        }
        ctx.ecx = keep_ecx; ctx.eax = keep_eax; ctx.edx = keep_edx;
        busy = false;
    }
    __imp__sub_0032D370(ctx, base);
}
