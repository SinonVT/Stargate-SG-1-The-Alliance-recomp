#pragma once
// A game's additions to the D3D12 renderer: hooks at fixed points of the console path, none of which run without one
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <vector>

#include "gpu/shaders.h"
#include "gpu/state.h"
#include "gpu/texture.h"

namespace gpu {

// a console surface the renderer draws into
struct Target {
    Microsoft::WRL::ComPtr<ID3D12Resource> res;
    bool depth = false;
    uint32_t gw = 0, gh = 0, w = 0, h = 0;
    uint32_t view = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    uint32_t data = 0, bytes = 0;
    uint64_t epoch = 0, sig = 0;  // last lock seen, guest memory as last matched
    bool drawn = false;           // the GPU wrote it since the last readback
    std::vector<uint8_t> read;    // what Sync left in guest memory
    Microsoft::WRL::ComPtr<ID3D12Resource> fb;  // copy read by draws that sample the target they render to
    D3D12_RESOURCE_STATES fb_state = D3D12_RESOURCE_STATE_COPY_DEST;
    DXGI_FORMAT fmt = DXGI_FORMAT_B8G8R8A8_UNORM;
    float range = 1;         // colour held divided by it until the extension resolves the target
    uint64_t tag = ~0ull;    // the extension's
};

// what the renderer lends an extension, on the render thread
class Context {
public:
    virtual ID3D12Device* Device() = 0;
    virtual ID3D12GraphicsCommandList* List() = 0;
    virtual void Transition(ID3D12Resource* r, D3D12_RESOURCE_STATES& cur, D3D12_RESOURCE_STATES want) = 0;
    virtual void Release(Microsoft::WRL::ComPtr<ID3D12Resource> r) = 0;  // once the GPU is past this frame
    virtual D3D12_CPU_DESCRIPTOR_HANDLE View(const Target& t) = 0;       // a colour target's RTV
    virtual void Unbind() = 0;                                           // the next draw binds its targets again
    virtual ID3D12Resource* Feedback(Target& t) = 0;                     // a copy of t to read while drawing to it
    // src over the bound viewport; taps per axis, colour times mul
    virtual void Blit(ID3D12Resource* src, DXGI_FORMAT fmt, const float uvrect[4], bool gamma, bool alpha, uint32_t taps, float mul,
                      DXGI_FORMAT rtv) = 0;
    // a full screen pass: hlsl holds vs and entry, src is t0 to t2, p is b1, blend >= 0 blends by that factor
    virtual void Pass(const char* hlsl, const char* entry, DXGI_FORMAT rtv, D3D12_CPU_DESCRIPTOR_HANDLE rh, uint32_t w, uint32_t h,
                      ID3D12Resource* const src[3], const DXGI_FORMAT fmt[3], const float p[8], float blend) = 0;
    virtual void Capture(Target& t, const char* tag, float mul) = 0;  // F3: saves t as NNNN_tag_data
    virtual float Scale() const = 0;                                  // render scale
    virtual void GuestSize(uint32_t& w, uint32_t& h) const = 0;       // the title's back buffer
    virtual uint64_t Presents() const = 0;
};

class Extension {
public:
    virtual ~Extension() = default;
    virtual const ShaderHooks* Shaders() const { return nullptr; }
    // settings at init and each present; true remakes every target
    virtual bool Settings() { return false; }
    // after Init, and after the targets were dropped for a remake
    virtual void Reset(Context&) {}
    // a surface looked up as a target: false leaves it unbound, key picks another copy of it
    virtual bool TargetKey(const Surface&, bool /*depth*/, uint64_t& /*key*/) { return true; }
    // a new target: scale from the render scale, fmt of a colour target
    virtual void MakeTarget(const Surface&, bool /*depth*/, uint32_t /*gw*/, uint32_t /*gh*/, float& /*scale*/, DXGI_FORMAT& /*fmt*/) {}
    virtual void BeginDraw(const State&) {}
    virtual void EndDraw() {}
    // targets bound for a draw; true binds them again
    virtual bool Bound(Context&, const State&, Target* /*rt*/, Target* /*ds*/, bool /*pretransformed*/) { return false; }
    // stage samples surface data: key picks the copy, k its texels per render scale texel, box allows the spread taps
    virtual void Sample(uint32_t /*data*/, bool /*depth*/, int /*stage*/, uint64_t& /*key*/, float& /*k*/, bool& /*box*/) {}
    // bound: the target, or a texture with the flags Decoded gave it
    virtual void Sampled(const TextureDesc&, const Target*, uint8_t /*flags*/, TexInfo&) {}
    // a texture level decoded for upload
    virtual void Decoded(const TextureDesc&, const FormatInfo&, uint32_t /*face*/, uint32_t /*level*/, const std::vector<uint8_t>& /*px*/,
                         uint32_t /*pitch*/, uint8_t& /*flags*/) {}
    // a draw's constants: the vertex registers as uploaded, DrawConstants::ext; src_blend 1 without blending
    virtual void Constants(float (*/*vsc*/)[4], float* /*ext*/, const Target* /*rt*/, uint32_t /*src_blend*/) {}
    // a target with range other than 1 is read, copied or presented
    virtual void Resolve(Context&, Target&) {}
};

inline std::unique_ptr<Extension> g_extension;

// SG1 wide fill: the 4:3 frame fills the window, perspective draws to the back buffer are stretched in clip y to
// match (the game widens its FOV to suit, Hor+); g_display_aspect is the window's, as the last present had it
inline std::atomic<bool> g_fill_window{false};
inline std::atomic<float> g_display_aspect{4.0f / 3.0f};

// SG1 texture pack: a guest 2D texture's level 0 (its bytes as in guest memory) may be swapped for a BGRA8 image of
// any size, which the renderer gives a full mip chain. Called on the render thread when the texture is made or its
// bytes change: 1 with w, h and w * h * 4 bytes of bgra, 0 for the game's own, 2 not ready yet (the game's own is
// drawn and it is asked again each frame it is used). g_texture_epoch: bumped, every texture asks again.
inline int (*g_texture_replace)(const TextureDesc& d, const uint8_t* guest, std::vector<uint8_t>& bgra, uint32_t& w,
                                 uint32_t& h) = nullptr;
inline std::atomic<uint32_t> g_texture_epoch{0};

// Debug (SG1 settings menu, "GPU debug"): draws that are not drawn, to find which one makes a glitch. While g_dbg_active
// the renderer counts the draws per pixel / vertex shader handle; an entry with skip set is not drawn.
struct DbgShader {
    uint32_t handle = 0, count = 0;
    bool skip = false;
};
// a kind of blended draw: shaders, blend, geometry size; stays the same while the camera moves
struct DbgSig {
    uint32_t vs = 0, ps = 0, src = 0, dst = 0, zwrite = 0, prim = 0, count = 0, n = 0;
    bool skip = false;
};
struct DbgDraws {
    std::vector<DbgSig> sig;
    std::mutex mu;
    std::vector<DbgShader> ps, vs, bl;  // bl: blend modes, handle = src << 16 | dst << 4 | depth write
};
inline DbgDraws g_dbg;
inline std::atomic<bool> g_dbg_active{false};      // the menu section is open: count the draws
inline std::atomic<bool> g_dbg_any_skip{false};    // some skip is on
inline std::atomic<bool> g_dbg_skip_add{false};    // additive draws that do not write depth
inline std::atomic<bool> g_dbg_skip_blend{false};  // every blended draw
inline std::atomic<bool> g_dbg_skip_alpha_test{false};
inline std::atomic<bool> g_dbg_hide_range{false};  // hide the draws numbered lo..hi of every frame
inline std::atomic<int> g_dbg_lo{0}, g_dbg_hi{0};
inline std::atomic<int> g_dbg_frame_draws{0};       // draws in the last frame
struct DbgProbe {  // the draw numbered g_dbg_lo
    bool valid = false;
    uint32_t prim = 0, count = 0, vs = 0, ps = 0, src = 0, dst = 0, zwrite = 0, blend = 0, tex0 = 0, tex1 = 0;
};
inline DbgProbe g_dbg_probe;
inline std::atomic<bool> g_dbg_no_fog{false};          // fog off for every draw
inline std::atomic<bool> g_dbg_black_fog_blend{false}; // fog colour black on blended draws

// before the backend is made
inline void SetExtension(std::unique_ptr<Extension> e) {
    g_extension = std::move(e);
    g_shader_hooks = g_extension ? g_extension->Shaders() : nullptr;
}

}  // namespace gpu
