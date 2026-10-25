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
#include <cstring>
#include <mutex>
#include <utility>
#include <vector>

#include "imgui.h"

#include "app/app.h"
#include "core/input.h"
#include "game/sg1_input.h"
#include "gpu/backend.h"
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

    if (ImGui::CollapsingHeader("Mouse")) {
        float sens = float(g_opt_sens_x10) / 10.0f;
        if (ImGui::SliderFloat("Look sensitivity", &sens, 1.0f, 500.0f, "%.1f", ImGuiSliderFlags_Logarithmic))
            g_opt_sens_x10 = uint32_t(std::max(1.0f, sens * 10.0f + 0.5f));
        float menu = float(g_opt_menu_x100) / 100.0f;
        if (ImGui::SliderFloat("Menu cursor speed", &menu, 0.25f, 6.0f, "%.2f"))
            g_opt_menu_x100 = uint32_t(std::max(10.0f, menu * 100.0f + 0.5f));
        ImGui::Checkbox("Invert mouse Y", &g_opt_invert_y);
        ImGui::TextDisabled("PgUp / PgDn change the look sensitivity in game, F9 frees the mouse.");
    }

    if (ImGui::CollapsingHeader("Controllers")) {
        bool pads = !g_opt_no_controllers;
        if (ImGui::Checkbox("Detect controllers", &pads)) {
            g_opt_no_controllers = !pads;
            input::SetEnabled(pads);
            SaveSettings();
        }
        ImGui::TextDisabled(pads ? "Xbox, PlayStation and Switch controllers are read as the console's pads."
                                 : "Off: controllers are ignored; only the keyboard and mouse play.");
    }

    if (ImGui::CollapsingHeader("Widescreen / field of view", ImGuiTreeNodeFlags_DefaultOpen)) {
        if (ImGui::Checkbox("Fill the window (16:9, ultrawide)", &g_opt_fill)) { gpu::g_fill_window = g_opt_fill; SendFov(); }
        ImGui::TextDisabled(g_opt_fill ? "The 3D view is drawn for the window's shape; menus and 2D are stretched to it."
                                       : "Off: the game's 4:3 picture, stretched to 16:9 on a wide screen.");
        int fov = g_opt_fov ? int(g_opt_fov) : 75;
        if (ImGui::SliderInt("FOV (at 4:3)", &fov, 60, 120)) g_opt_fov = uint32_t(fov);
        if (ImGui::Checkbox("Hor+ (wider view on a wide window)", &g_opt_hor_plus)) SendFov();
        ImGui::SameLine();
        if (ImGui::Button("Apply now")) SendFov();
        ImGui::TextDisabled("The game gets FOV %d, typed into its console once you are in a level.", FovTarget());
    }

    if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
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
    }

    if (ImGui::CollapsingHeader("Textures")) {
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
    }

    if (ImGui::CollapsingHeader("GPU debug")) {
        if (ImGui::Button("Capture this frame now (saved in the captures folder)")) gpu::g_capture = true;
        static bool vb_snap = true;
        ImGui::Checkbox("Copy vertices when a draw is recorded (the flicker fix)", &vb_snap);
        gpu::g_vb_snapshot = vb_snap;
        static bool light_dedupe = true;
        ImGui::Checkbox("Drop duplicate muzzle flash lights (the P90 white-out fix)", &light_dedupe);
        gpu::g_light_dedupe = light_dedupe;
    }

    ImGui::Separator();
    ImGui::Text("%.0f fps", fps);
    ImGui::SameLine(ImGui::GetWindowWidth() - 80);
    if (ImGui::Button("Close")) open = false;
    ImGui::End();
    if (!open) SetOverlay(false);
}

// Del: the NPC spawner, ported from the old build (fb_present.c). It types console commands: summon StargateContent.<name>.
// Pawns spawned during play get no controller and no weapons (Pawn.PostBeginPlay / StargatePawn.PostBeginPlay only give
// them while Level.bStartup is set), so with AI on each spawn sets bStartup again and gives the class its controller
// class once. A NULL controller = no brain. The commands are typed once this window is closed.
struct NpcDef {
    const char* name;
    const char* ctrl;
};
const NpcDef kNpcs[] = {
    {"JaffaHorusL", "JaffaBotLight"},  {"JaffaHorusM", "JaffaBotMedium"},  {"JaffaHorusH", "JaffaBotHeavy"},
    {"JaffaSerpentL", "JaffaBotLight"}, {"JaffaSerpentM", "JaffaBotMedium"}, {"JaffaSerpentH", "JaffaBotHeavy"},
    {"JaffaJackalL", "JaffaBotLight"},  {"JaffaJackalM", "JaffaBotMedium"},  {"JaffaJackalH", "JaffaBotHeavy"},
    {"JaffaCaptain", "JaffaBotMedium"}, {"JaffaGrunt", "JaffaBotLight"},     {"GoauldFirstPrime", "JaffaBotHeavy"},
    {"HaakenGrunt", "HaakenBot"},       {"HaakenWarrior", "HaakenBot"},      {"HaakenLeader", "HaakenLeaderBot"},
    {"Goauld", "BotGoauld"},            {"Anubis", nullptr},
    {"Replicator", "BotEnemy"},         {"MediumGreenReplicator", "BotEnemy"}, {"MediumPurpleReplicator", "BotEnemy"},
    {"BigReplicator", "BotEnemy"},      {"ReplicatorQueen", "ReplicatorQueenBot"},
    {"Ptero", "PteroBot"},              {"PteroBoss", "PteroBossBot"},
};
constexpr int kNpcCount = int(sizeof kNpcs / sizeof *kNpcs);
// the replicator classes have no mesh in this build: summon one so the class loads, set the mesh, remove the bare one
struct MeshFix {
    const char* cls;
    const char* set_cmd;
    const char* skin;
};
const MeshFix kMeshFixes[] = {
    {"ReplicatorQueen", "set ReplicatorQueen Mesh SkeletalMesh'replicator_queen.replicator_queen'", nullptr},
    {"Replicator", "set Replicator Mesh SkeletalMesh'ReplicatorAnims.repmesh17'", nullptr},
    {"BigReplicator", "set BigReplicator Mesh SkeletalMesh'ReplicatorAnims.bigrep'", nullptr},
    // the medium mesh only references the green texture, so purple gets a skin
    {"MediumGreenReplicator", "set MediumGreenReplicator Mesh SkeletalMesh'ReplicatorAnims.repmesh18'", nullptr},
    {"MediumPurpleReplicator", "set MediumPurpleReplicator Mesh SkeletalMesh'ReplicatorAnims.repmesh18'",
     "set MediumPurpleReplicator Skins (Texture'ReplicatorTex.RepTexPink')"},
};
constexpr int kMeshFixCount = int(sizeof kMeshFixes / sizeof *kMeshFixes);
bool g_npc_ai = false;
bool g_mesh_done[kMeshFixCount] = {}, g_brain_done[kNpcCount] = {};

// redo: Shift held, the one-time steps are typed again (a new map forgets them)
void SpawnNpc(int i, bool redo) {
    const NpcDef& n = kNpcs[i];
    const char* ctrl = g_npc_ai ? n.ctrl : nullptr;
    char b[160];
    for (int k = 0; k < kMeshFixCount; k++) {
        if (std::strcmp(n.name, kMeshFixes[k].cls) != 0) continue;
        if (!g_mesh_done[k] || redo) {
            g_mesh_done[k] = true;
            if (g_npc_ai) TypeCommand("set LevelInfo bStartup false");  // the bare meshless pawn must not get a brain
            std::snprintf(b, sizeof b, "summon StargateContent.%s", n.name);
            TypeCommand(b);
            TypeCommand(kMeshFixes[k].set_cmd);
            if (kMeshFixes[k].skin) TypeCommand(kMeshFixes[k].skin);
            std::snprintf(b, sizeof b, "killall StargateContent.%s", n.name);
            TypeCommand(b);
        }
        break;
    }
    // bStartup does not stay true after the mesh setup: set it again right before every AI spawn
    if (g_npc_ai) TypeCommand("set LevelInfo bStartup true");
    if (ctrl && (!g_brain_done[i] || redo)) {
        g_brain_done[i] = true;
        // BotEnemy lives in StargateGame; the wrong package gives None, no brain at all
        std::snprintf(b, sizeof b, "set %s ControllerClass Class'%s.%s'", n.name,
                      std::strcmp(ctrl, "BotEnemy") ? "StargateContent" : "StargateGame", ctrl);
        TypeCommand(b);
    }
    std::snprintf(b, sizeof b, "summon StargateContent.%s", n.name);
    TypeCommand(b);
}

void Spawner() {
    ImGuiIO& io = ImGui::GetIO();
    ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x * 0.5f, io.DisplaySize.y * 0.5f), ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(420, 0), ImGuiCond_Appearing);
    bool open = true;
    if (!ImGui::Begin("NPC spawner  (Del closes)", &open, ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::End();
        if (!open) SetOverlay(false);
        return;
    }
    if (ImGui::Checkbox("AI: spawned NPCs get a controller and their weapons", &g_npc_ai)) {
        TypeCommand(g_npc_ai ? "set LevelInfo bStartup true" : "set LevelInfo bStartup false");
    }
    ImGui::TextDisabled("Click spawns in front of you (the menu closes, then the console types).");
    ImGui::TextDisabled("Shift+click also redoes the one-time setup (needed again after a new map).");
    ImGui::Separator();
    if (ImGui::BeginTable("##npcs", 2, ImGuiTableFlags_SizingFixedFit)) {
        for (int i = 0; i < kNpcCount; i++) {
            ImGui::TableNextColumn();
            char label[64];
            std::snprintf(label, sizeof label, "%s%s", kNpcs[i].name, kNpcs[i].ctrl ? "" : "  (no AI)");
            // a fixed width: the window sizes itself to its contents, so a fill width would be zero
            if (ImGui::Button(label, ImVec2(ImGui::GetFontSize() * 15.0f, 0))) {
                SpawnNpc(i, io.KeyShift);
                open = false;
            }
        }
        ImGui::EndTable();
    }
    ImGui::Separator();
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
    if (g_overlay.load()) {
        if (g_overlay_page.load() == kPageSpawner) Spawner();
        else Settings(fps);
    }
    else if (g_voice.load() && !g_in_menu.load()) Voice();
}

}  // namespace sg1kbm
