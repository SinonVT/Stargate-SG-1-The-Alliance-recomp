// Shared state between kbm.cpp (input, window thread + game thread) and menus.cpp (ImGui, render thread).
#pragma once
#include <atomic>
#include <cstdint>
#include <string>

namespace sg1kbm {

// settings kept in settings.toml (game_info.cpp lists them as options)
extern uint32_t g_opt_sens_x10;     // mouse look, x10 (500 = 50.0, the old build's default)
extern uint32_t g_opt_menu_x100;    // menu cursor speed, x100
extern bool g_opt_invert_y;
extern uint32_t g_opt_fov;          // 0 = leave the game's own
extern bool g_opt_hor_plus;         // widen the FOV for a wide window so the vertical view stays as at 4:3
extern bool g_opt_fill;             // the 3D view fills the window at its own aspect (16:9, ultrawide)

extern std::atomic<bool> g_overlay;     // Insert settings menu: the game gets no keyboard or mouse
extern std::atomic<bool> g_voice;       // V voice menu
extern std::atomic<int> g_voice_sel;
extern std::atomic<bool> g_in_menu;     // a game (GUI) menu is on screen

struct VoiceLine { const char* label; unsigned vk; };
extern const VoiceLine kVoice[];
extern const int kVoiceCount;

void TypeCommand(const char* cmd);  // typed into the game console once no menu is up
void SendFov();                     // types FOV <FovTarget()> again once a level is up
int FovTarget();
void SetOverlay(bool on);           // any thread
void SaveSettings();                // posts to the window thread
void FitWindowed();                 // windowed: a size whose title bar stays on screen
// texpack.cpp: HD texture pack and the player's own textures
extern bool g_opt_hd_textures, g_opt_custom_textures;
extern std::atomic<int> g_tex_index_count;
extern std::atomic<uint32_t> g_tex_replaced;
void TexpackInit();
void TexpackReload();
bool TexpackExtract();
std::string TexpackFolder();

}  // namespace sg1kbm
