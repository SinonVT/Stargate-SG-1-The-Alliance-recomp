// SG-1 HD texture pack. The game uploads reduced copies of its textures; the original full-size art is still in
// Textures\*.utx. tools\make_hdpack.py (make_texpack.bat) writes it as texpack\hd\*.png beside the exe, with
// texpack\index.txt mapping "f<format>_<w>x<h>_<hash of the texture's level 0 bytes>" to a file. Here the renderer's
// g_texture_replace hook looks every uploaded texture up there:
//   texpack\custom\<same file name as in hd>  the player's own version (custom textures on)
//   texpack\custom\<id>.png                   own versions of textures the pack does not cover (custom textures on)
//   texpack\<index file>                      the HD pack (HD textures on)
// Ported from the sp00nznet/xboxrecomp version (d3d11_backend.c hd_*).
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <objbase.h>
#include <wincodec.h>

#include <atomic>
#include <cctype>
#include <condition_variable>
#include <deque>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "app/app.h"
#include "core/log.h"
#include "game/sg1_input.h"
#include "gpu/ext.h"

namespace sg1kbm {

bool g_opt_hd_textures = true;
bool g_opt_custom_textures = true;
std::atomic<int> g_tex_index_count{-1};   // -1 not read yet
std::atomic<uint32_t> g_tex_replaced{0};

namespace {

struct Entry {
    uint32_t code, w, h;
    std::string file;
};
std::mutex g_lock;
std::unordered_map<uint64_t, std::vector<Entry>> g_index;   // by hash
bool g_loaded = false;

std::filesystem::path Pack() { return app::ExeDir() / "texpack"; }

// the same hash make_hdpack.py writes (hdhash.c)
uint64_t HdHash(const uint8_t* p, size_t n) {
    uint64_t h = 1469598103934665603ull;
    size_t i = 0;
    for (; i + 8 <= n; i += 8) {
        uint64_t w;
        std::memcpy(&w, p + i, 8);
        h = (h ^ w) * 1099511628211ull;
        h ^= h >> 29;
    }
    for (; i < n; i++) h = (h ^ p[i]) * 1099511628211ull;
    return h;
}

std::unordered_set<std::string> g_custom;   // texpack\custom file names, lower case

std::string Lower(std::string v) {
    for (char& c : v) c = char(std::tolower(uint8_t(c)));
    return v;
}

void LoadIndex() {
    g_loaded = true;
    g_index.clear();
    g_custom.clear();
    int n = 0;
    FILE* f = _wfopen((Pack() / "index.txt").c_str(), L"r");
    if (f) {
        char line[400];
        while (std::fgets(line, sizeof line, f)) {
            unsigned code, w, h;
            unsigned long long hs;
            char fn[300];
            if (std::sscanf(line, "f%X_%ux%u_%llX %299s", &code, &w, &h, &hs, fn) != 5) continue;
            g_index[hs].push_back({code, w, h, fn});
            n++;
        }
        std::fclose(f);
    }
    std::error_code ec;
    for (auto& e : std::filesystem::directory_iterator(Pack() / "custom", ec))
        if (e.is_regular_file(ec)) g_custom.insert(Lower(e.path().filename().string()));
    g_tex_index_count = n;
    LOGI("texpack: %d HD textures, %d custom in %s", n, int(g_custom.size()), Pack().string().c_str());
}

bool LoadPng(const std::filesystem::path& path, std::vector<uint8_t>& out, uint32_t& w, uint32_t& h) {
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) return false;
    // CLSID_WICImagingFactory, kept here so no extra import library is needed
    static const GUID kWicFactory = {0xcacaf262, 0x9370, 0x4615, {0xa1, 0x3b, 0x9f, 0x55, 0x39, 0xda, 0x4c, 0x0a}};
    static thread_local IWICImagingFactory* fac = nullptr;
    if (!fac) {
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(CoCreateInstance(kWicFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&fac)))) { fac = nullptr; return false; }
    }
    IWICBitmapDecoder* dec = nullptr;
    IWICBitmapFrameDecode* fr = nullptr;
    IWICFormatConverter* cv = nullptr;
    UINT uw = 0, uh = 0;
    bool ok = false;
    if (SUCCEEDED(fac->CreateDecoderFromFilename(path.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec)) &&
        SUCCEEDED(dec->GetFrame(0, &fr)) && SUCCEEDED(fac->CreateFormatConverter(&cv)) &&
        SUCCEEDED(cv->Initialize(fr, GUID_WICPixelFormat32bppBGRA, WICBitmapDitherTypeNone, nullptr, 0.0, WICBitmapPaletteTypeCustom)) &&
        SUCCEEDED(cv->GetSize(&uw, &uh)) && uw >= 1 && uh >= 1 && uw <= 8192 && uh <= 8192) {
        out.resize(size_t(uw) * uh * 4);
        ok = SUCCEEDED(cv->CopyPixels(nullptr, uw * 4, UINT(out.size()), out.data()));
    }
    if (cv) cv->Release();
    if (fr) fr->Release();
    if (dec) dec->Release();
    if (!ok) return false;
    w = uw;
    h = uh;
    return true;
}

// level 0 bytes as make_hdpack.py hashes them: DXT1 / DXT3 / DXT5 blocks, swizzled A8R8G8B8
size_t Level0Bytes(const gpu::TextureDesc& d) {
    switch (d.format) {
    case 0x0C: return size_t((d.width + 3) / 4) * ((d.height + 3) / 4) * 8;
    case 0x0E:
    case 0x0F: return size_t((d.width + 3) / 4) * ((d.height + 3) / 4) * 16;
    case 0x06: return size_t(d.width) * d.height * 4;
    default: return 0;
    }
}

// PNGs are read on worker threads: the renderer draws the game's own texture until the image is ready (no stutter)
struct Job {
    std::vector<std::filesystem::path> files;   // in order: the first that loads wins
    bool done = false, found = false;
    std::vector<uint8_t> px;
    uint32_t w = 0, h = 0;
};
std::unordered_map<std::string, Job> g_jobs;   // by texture id
std::deque<std::string> g_queue;
std::condition_variable g_cv;
uint32_t g_gen = 0;    // bumped by a reload: results of older jobs are dropped
bool g_workers = false;

void Worker() {
    for (;;) {
        std::string id;
        std::vector<std::filesystem::path> files;
        uint32_t gen;
        {
            std::unique_lock<std::mutex> l(g_lock);
            g_cv.wait(l, [] { return !g_queue.empty(); });
            id = g_queue.front();
            g_queue.pop_front();
            auto it = g_jobs.find(id);
            if (it == g_jobs.end()) continue;
            files = it->second.files;
            gen = g_gen;
        }
        std::vector<uint8_t> px;
        uint32_t w = 0, h = 0;
        bool found = false;
        for (auto& f : files)
            if (LoadPng(f, px, w, h)) { found = true; break; }
        std::lock_guard<std::mutex> l(g_lock);
        if (gen != g_gen) continue;
        auto it = g_jobs.find(id);
        if (it == g_jobs.end()) continue;
        it->second.done = true;
        it->second.found = found;
        if (found) { it->second.px.swap(px); it->second.w = w; it->second.h = h; }
    }
}

// 0 the game's own, 1 bgra holds the image, 2 still loading: asked again next frame
int Replace(const gpu::TextureDesc& d, const uint8_t* guest, std::vector<uint8_t>& bgra, uint32_t& w, uint32_t& h) {
    if (!g_opt_hd_textures && !g_opt_custom_textures) return 0;
    if (d.width < 16 || d.height < 16) return 0;
    size_t n = Level0Bytes(d);
    if (!n) return 0;
    uint64_t hash = HdHash(guest, n);
    char id[64];
    std::snprintf(id, sizeof id, "f%02X_%ux%u_%016llX", d.format, d.width, d.height, (unsigned long long)hash);
    std::lock_guard<std::mutex> l(g_lock);
    if (!g_loaded) LoadIndex();
    auto j = g_jobs.find(id);
    if (j != g_jobs.end()) {
        if (!j->second.done) return 2;
        if (!j->second.found) return 0;   // nothing for it: remembered until a reload
        bgra.swap(j->second.px);
        w = j->second.w;
        h = j->second.h;
        g_jobs.erase(j);                  // the GPU has it now; asked again only after the texture was dropped
        g_tex_replaced++;
        return 1;
    }
    std::string file;
    auto it = g_index.find(hash);
    if (it != g_index.end())
        for (const Entry& e : it->second)
            if (e.code == d.format && e.w == d.width && e.h == d.height) { file = e.file; break; }
    Job job;
    if (g_opt_custom_textures) {
        if (!file.empty()) {
            std::string base = file.substr(file.find_last_of("/\\") + 1);
            if (g_custom.count(Lower(base))) job.files.push_back(Pack() / "custom" / base);
        }
        std::string own = std::string(id) + ".png";
        if (g_custom.count(Lower(own))) job.files.push_back(Pack() / "custom" / own);
    }
    if (g_opt_hd_textures && !file.empty()) job.files.push_back(Pack() / file);
    if (job.files.empty()) return 0;
    if (!g_workers) {
        g_workers = true;
        for (int i = 0; i < 3; i++) std::thread(Worker).detach();
    }
    g_jobs.emplace(id, std::move(job));
    g_queue.push_back(id);
    g_cv.notify_one();
    return 2;
}

}  // namespace

void TexpackInit() {
    {
        std::lock_guard<std::mutex> l(g_lock);
        LoadIndex();
    }
    gpu::g_texture_replace = Replace;
}

// the index read again, every texture asked again (a new pack, the switches)
void TexpackReload() {
    {
        std::lock_guard<std::mutex> l(g_lock);
        g_loaded = false;
        g_gen++;
        g_jobs.clear();
        g_queue.clear();
    }
    g_tex_replaced = 0;
    gpu::g_texture_epoch++;
}

// make_texpack.bat in the project folder (three up from out\build\release) or beside the exe
bool TexpackExtract() {
    for (auto p : {app::ExeDir() / "make_texpack.bat", app::ExeDir().parent_path().parent_path().parent_path() / "make_texpack.bat"}) {
        if (!std::filesystem::exists(p)) continue;
        std::wstring dir = p.parent_path().wstring();
        std::wstring cmd = L"cmd.exe /c \"\"" + p.wstring() + L"\"\"";
        STARTUPINFOW si{};
        si.cb = sizeof si;
        PROCESS_INFORMATION pi{};
        if (!CreateProcessW(nullptr, cmd.data(), nullptr, nullptr, FALSE, CREATE_NEW_CONSOLE, nullptr, dir.c_str(), &si, &pi)) {
            LOGE("texpack: could not start %s (%lu)", p.string().c_str(), GetLastError());
            return false;
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        LOGI("texpack: started %s", p.string().c_str());
        return true;
    }
    LOGE("texpack: make_texpack.bat not found");
    return false;
}

std::string TexpackFolder() { return Pack().string(); }

}  // namespace sg1kbm
