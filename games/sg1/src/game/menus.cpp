// SG-1 overlays (ImGui, render thread): the Insert settings menu (mouse, FOV, display / resolution) and the V voice
// menu. Ported from the sp00nznet/xboxrecomp version (fb_present.c menus).
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <cstdio>
#include <utility>
#include <vector>

#include "imgui.h"

#include "app/app.h"
#include "game/sg1_input.h"
#include "gpu/ext.h"

namespace sg1kbm {

namespace {

std::vector<std::pair<uint32_t, uint32_t>> Modes() {
    static std::vector<std::pair<uint32_t, uint32_t>> modes;
    if (!modes.empty()) return modes;
    DEVMODEW dm{};
    dm.dmSize = sizeof dm;
    for (DWORD i = 0; EnumDisplaySettingsW(nullptr, i, &dm); i++) {
        if (dm.dmPelsWidth < 640 || dm.dmPelsHeight < 480) continue;
        std::pair<uint32_t, uint32_t> m{dm.dmPelsWidth, dm.dmPelsHeight};
        if (std::find(modes.begin(), modes.end(), m) == modes.end()) modes.push_back(m);
    }
    std::sort(modes.begin(), modes.end(), [](auto& a, auto& b) { return a.first * a.second > b.first * b.second; });
    return modes;
}

void Settings(double fps) {
    ImGuiIO& io = ImGui::GetIO();
    ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.5f), ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(520, 0), ImGuiCond_Appearing);
    bool open = true;
    if (!ImGui::Begin("SG-1 settings  (Insert closes)", &open, ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::End();
        if (!open) SetOverlay(false);
        return;
    }

    ImGui::SeparatorText("Mouse");
    float sens = float(g_opt_sens_x10) / 10.0f;
    if (ImGui::SliderFloat("Look sensitivity", &sens, 1.0f, 300.0f, "%.1f", ImGuiSliderFlags_Logarithmic))
        g_opt_sens_x10 = uint32_t(std::max(1.0f, sens * 10.0f + 0.5f));
    float menu = float(g_opt_menu_x100) / 100.0f;
    if (ImGui::SliderFloat("Menu cursor speed", &menu, 0.25f, 6.0f, "%.2f"))
        g_opt_menu_x100 = uint32_t(std::max(10.0f, menu * 100.0f + 0.5f));
    ImGui::Checkbox("Invert mouse Y", &g_opt_invert_y);
    ImGui::TextDisabled("PgUp / PgDn change the look sensitivity in game, F9 frees the mouse.");

    ImGui::SeparatorText("Widescreen / field of view");
    if (ImGui::Checkbox("Fill the window (16:9, ultrawide)", &g_opt_fill)) { gpu::g_fill_window = g_opt_fill; SendFov(); }
    ImGui::TextDisabled(g_opt_fill ? "The 3D view is drawn for the window's shape; menus and 2D are stretched to it."
                                   : "Off: the game's 4:3 picture, stretched to 16:9 on a wide screen.");
    int fov = g_opt_fov ? int(g_opt_fov) : 75;
    if (ImGui::SliderInt("FOV (at 4:3)", &fov, 60, 120)) g_opt_fov = uint32_t(fov);
    if (ImGui::Checkbox("Hor+ (wider view on a wide window)", &g_opt_hor_plus)) SendFov();
    ImGui::SameLine();
    if (ImGui::Button("Apply now")) SendFov();
    ImGui::TextDisabled("The game gets FOV %d, typed into its console once you are in a level.", FovTarget());

    ImGui::SeparatorText("Textures");
    if (ImGui::Checkbox("HD texture pack", &g_opt_hd_textures)) TexpackReload();
    ImGui::SameLine();
    if (ImGui::Checkbox("Custom textures", &g_opt_custom_textures)) TexpackReload();
    int ni = g_tex_index_count.load();
    if (ni > 0) ImGui::TextDisabled("Pack: %d textures, %u in use.", ni, g_tex_replaced.load());
    else ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.3f, 1.0f), "No HD pack yet: extract it from your game files.");
    static double extract_msg = 0;
    if (ImGui::Button("Extract HD textures")) extract_msg = TexpackExtract() ? ImGui::GetTime() : -ImGui::GetTime();
    ImGui::SameLine();
    if (ImGui::Button("Reload textures")) TexpackReload();
    if (extract_msg > 0 && ImGui::GetTime() - extract_msg < 8)
        ImGui::TextDisabled("Extracting in a new window; press Reload textures when it says DONE.");
    else if (extract_msg < 0 && ImGui::GetTime() + extract_msg < 8)
        ImGui::TextColored(ImVec4(1.0f, 0.5f, 0.4f, 1.0f), "make_texpack.bat not found (see the log).");
    ImGui::TextDisabled("Your own: PNGs in %s\\custom with the same name as in hd\\ (or f<fmt>_<w>x<h>_<hash>.png).",
                        TexpackFolder().c_str());

    ImGui::SeparatorText("Display");
    app::Settings& s = app::Get();
    bool display = false;
    static const char* kModeNames[] = {"Fullscreen", "Borderless", "Windowed"};
    int mode = int(s.display_mode);
    if (ImGui::Combo("Display mode", &mode, kModeNames, 3)) { s.display_mode = app::DisplayMode(mode); display = true; }
    auto modes = Modes();
    char cur[48];
    if (s.width && s.height) std::snprintf(cur, sizeof cur, "%ux%u", s.width, s.height);
    else std::snprintf(cur, sizeof cur, "Desktop");
    if (ImGui::BeginCombo("Resolution", cur)) {
        if (ImGui::Selectable("Desktop", !s.width)) { s.width = s.height = 0; display = true; }
        for (auto& m : modes) {
            char b[48];
            std::snprintf(b, sizeof b, "%ux%u", m.first, m.second);
            if (ImGui::Selectable(b, s.width == m.first && s.height == m.second)) { s.width = m.first; s.height = m.second; display = true; }
        }
        ImGui::EndCombo();
    }
    int rp = int(s.render_percent);
    if (ImGui::SliderInt("Render scale %", &rp, 50, 400)) s.render_percent = uint32_t(std::clamp(rp, 25, 400));
    ImGui::TextDisabled("Of the output height: 100 = native, 200 = supersampled.");
    static const uint32_t kCaps[] = {30, 60, 120, 144, 165, 240, app::kFpsCapRefresh, 0};
    static const char* kCapNames[] = {"30", "60", "120", "144", "165", "240", "Monitor refresh", "Unlimited"};
    int ci = 1;
    for (int i = 0; i < 8; i++) if (kCaps[i] == s.fps_cap) ci = i;
    if (ImGui::Combo("FPS cap", &ci, kCapNames, 8)) s.fps_cap = kCaps[ci];
    ImGui::Checkbox("VSync", &s.vsync);
    static const uint32_t kAniso[] = {0, 2, 4, 8, 16};
    static const char* kAnisoNames[] = {"As the game asks", "2x", "4x", "8x", "16x"};
    int ai = 0;
    for (int i = 0; i < 5; i++) if (kAniso[i] == s.aniso) ai = i;
    if (ImGui::Combo("Anisotropic filtering", &ai, kAnisoNames, 5)) s.aniso = kAniso[ai];
    if (display) { FitWindowed(); app::ApplyDisplay(); }

    ImGui::Separator();
    ImGui::Text("%.0f fps", fps);
    ImGui::SameLine(ImGui::GetWindowWidth() - 80);
    if (ImGui::Button("Close")) open = false;
    ImGui::End();
    if (!open) SetOverlay(false);
}

void Voice() {
    ImGui::SetNextWindowPos(ImVec2(24, 24), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.75f);
    ImGuiWindowFlags f = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoInputs |
                         ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoSavedSettings;
    if (ImGui::Begin("##voice", nullptr, f)) {
        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f), "VOICE");
        ImGui::Separator();
        int sel = g_voice_sel.load();
        for (int i = 0; i < kVoiceCount; i++) {
            if (i == sel) ImGui::TextColored(ImVec4(1.0f, 1.0f, 0.45f, 1.0f), "> %s", kVoice[i].label);
            else ImGui::Text("  %s", kVoice[i].label);
        }
        ImGui::Separator();
        ImGui::TextDisabled("Wheel select, left click say, V close");
    }
    ImGui::End();
}

}  // namespace

// windowed at the desktop's size puts the title bar above the screen: use the biggest size that fits the work area
void FitWindowed() {
    app::Settings& s = app::Get();
    if (s.display_mode != app::DisplayMode::Windowed) return;
    RECT wa{0, 0, 1280, 720};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &wa, 0);
    RECT fr{0, 0, 0, 0};
    AdjustWindowRect(&fr, WS_OVERLAPPEDWINDOW, FALSE);
    uint32_t maxw = uint32_t(std::max<LONG>(640, (wa.right - wa.left) - (fr.right - fr.left)));
    uint32_t maxh = uint32_t(std::max<LONG>(480, (wa.bottom - wa.top) - (fr.bottom - fr.top)));
    app::Mode out = app::Output();
    if (s.width && s.height && out.width <= maxw && out.height <= maxh) return;
    static const uint32_t kSizes[][2] = {{2560, 1440}, {1920, 1080}, {1600, 900}, {1366, 768}, {1280, 720}, {1024, 576}, {800, 600}, {640, 480}};
    for (auto& z : kSizes)
        if (z[0] <= maxw && z[1] <= maxh) { s.width = z[0]; s.height = z[1]; return; }
    s.width = 640; s.height = 480;
}

void OnUi(double fps) {
    if (g_overlay.load()) Settings(fps);
    else if (g_voice.load() && !g_in_menu.load()) Voice();
}

}  // namespace sg1kbm
