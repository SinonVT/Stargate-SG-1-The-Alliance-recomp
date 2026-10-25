#include "app/app.h"

namespace sg1kbm {   // src/game/kbm.cpp
void OnWindow(void* hwnd);
bool OnMessage(void* hwnd, uint32_t msg, uintptr_t wp, intptr_t lp, intptr_t* result);
void OnUi(double fps);   // src/game/menus.cpp
extern uint32_t g_opt_sens_x10, g_opt_menu_x100, g_opt_fov;
extern bool g_opt_invert_y, g_opt_hor_plus, g_opt_fill, g_opt_hd_textures, g_opt_custom_textures, g_opt_maximized;
void FitWindowed();      // src/game/menus.cpp
bool g_windowed_once = false;
// first start: a window, not the whole screen; later starts keep what the menu set
void Init() {
    if (!g_windowed_once) {
        g_windowed_once = true;
        app::Get().display_mode = app::DisplayMode::Windowed;
        app::Get().width = app::Get().height = 0;
        FitWindowed();
        app::Save();
    }
    FitWindowed();
}
}

// what the runtime asks of the game; strings must be set, hooks may stay null
const app::GameInfo app::kGame = {
    .title = L"Stargate SG-1 The Alliance",               // window and splash
    .short_title = L"Game",               // message boxes
    .name = L"Game",                      // window classes, crash dumps, handover event
    .log = "game",                        // log file prefix
    .settings = "settings.toml",          // settings file beside the exe
    .splash = L"splash",                  // optional splash.png or splash.bmp beside the exe
    .missing = L"Put the game in the assets folder: its disc image (.iso), or default.xbe with its folders beside it.",
    .images = {{"default.xbe", "SG1"}},  // each recompiled xbe and its exe, for title launches
    .options = {{"mouse_sensitivity_x10", nullptr, &sg1kbm::g_opt_sens_x10},
                {"menu_cursor_speed_x100", nullptr, &sg1kbm::g_opt_menu_x100},
                {"invert_mouse_y", &sg1kbm::g_opt_invert_y, nullptr},
                {"fov", nullptr, &sg1kbm::g_opt_fov},
                {"fov_hor_plus", &sg1kbm::g_opt_hor_plus, nullptr},
                {"widescreen_fill", &sg1kbm::g_opt_fill, nullptr},
                {"hd_textures", &sg1kbm::g_opt_hd_textures, nullptr},
                {"custom_textures", &sg1kbm::g_opt_custom_textures, nullptr},
                {"window_maximized", &sg1kbm::g_opt_maximized, nullptr},
                {"sg1_windowed_default", &sg1kbm::g_windowed_once, nullptr}},   // game settings kept in the settings file
    .load = nullptr,                      // reads more from the settings file's toml::table
    .save = nullptr,                      // writes more into it
    .init = sg1kbm::Init,                 // after the settings load: start windowed
    .loaded = nullptr,                    // image in memory, before its entry point runs
    .window = sg1kbm::OnWindow,                    // the game window is up
    .message = sg1kbm::OnMessage,                   // window messages first; true takes one
    .ui = sg1kbm::OnUi,                   // ImGui drawing each frame: Insert settings, V voice
    .pad = nullptr,                       // changes a polled pad
    .rumble = nullptr,                    // changes a rumble before it is set
};
