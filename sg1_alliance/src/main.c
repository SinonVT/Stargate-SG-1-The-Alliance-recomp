/**
 * YOUR_GAME_NAME - Recompiled Game Entry Point
 *
 * This is the Windows executable that hosts the recompiled game code.
 * It performs the following initialization sequence:
 *
 * 1. Load the original XBE file from disk
 * 2. Initialize the Xbox memory layout (map data sections to original VAs)
 * 3. Initialize the Xbox kernel replacement layer
 * 4. Initialize the kernel bridge (thunk table in Xbox memory)
 * 5. Set up game file paths for I/O redirection
 * 6. Initialize the stack pointer
 * 7. Install VEH crash handler for diagnostics
 * 8. Call the game's original entry point (recompiled)
 *
 * Customize this file for your game:
 *   - Set YOUR_GAME_ENTRY_POINT to the XBE entry point address
 *   - Set YOUR_GAME_XBE_PATH to where the XBE file lives
 *   - Set YOUR_GAME_DIR to the game data directory
 *   - Add any CRT global pre-initialization your game needs
 *   - Customize the VEH handler for game-specific crash diagnosis
 *
 * XBE Details (fill in from xbe_parser output):
 *   Title:       YOUR_GAME_NAME
 *   Title ID:    0x00000000
 *   Base addr:   0x00010000
 *   Entry point: 0x00000000
 *   Code size:   ~??? KB (.text)
 *   Sections:    ?? (list them)
 *   Kernel imports: ??
 */

#include <windows.h>
#include <dbghelp.h>
#include <stdio.h>
#include <stdarg.h>
#include <share.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <math.h>

/* xboxrecomp runtime headers */
#include <xbox/xboxrecomp.h>
int g_sg1_mode_w = 640, g_sg1_mode_h = 480;   /* last display mode the game selected (set by the FindMode hook) */
int g_sg1_hud_off = -1, g_sg1_cam_off = -1; uint32_t g_sg1_hud_actor; float g_sg1_hud_save[3];   /* DrawActor hook: where AActor::Location sits, and the widget being moved */
void sg1_hud_log(int off, float f, float r, float u) { fprintf(stderr, "[HUDLOC] camera vector in the controller at +0x%X (widget fwd %.1f right %.1f up %.1f)\n", off, f, r, u); }
struct sg1_anch { uint32_t id; float x, y, ax; }; struct sg1_anch g_sg1_anch[96]; volatile int g_sg1_nanch;   /* HUD widget screen positions (fractions) for the 2D text/icon scaling in be_draw */
void sg1_hud_anchor(uint32_t id, float x, float y, float ax) { int i, n = g_sg1_nanch; for (i = 0; i < n; i++) if (g_sg1_anch[i].id == id) { g_sg1_anch[i].x = x; g_sg1_anch[i].y = y; g_sg1_anch[i].ax = ax; return; } if (n < 96) { g_sg1_anch[n].id = id; g_sg1_anch[n].x = x; g_sg1_anch[n].y = y; g_sg1_anch[n].ax = ax; g_sg1_nanch = n + 1; } }
/* Squad panel (Jackson/Carter/Teal'c): each row is four 3D widgets that slide in together - name (frame-0.034), frame, face (+0.055), "C" icon (+0.108).
 * The frame is rigid, so the other three keep their offset from it: return the frame's x (the second smallest x of the row) as the pivot. */
float sg1_hud_pivot(uint32_t id, float xf, float yf) {
    float xs[16]; int i, j, k = 0, n = g_sg1_nanch;
    sg1_hud_anchor(id, xf, yf, xf);
    if (!(xf < 0.4f && yf > 0.28f && yf < 0.62f)) return xf;
    for (i = 0; i < n && k < 16; i++) if (g_sg1_anch[i].x < 0.4f && fabsf(g_sg1_anch[i].y - yf) < 0.03f) xs[k++] = g_sg1_anch[i].x;
    if (k < 3) return xf;
    for (i = 0; i < k; i++) for (j = i + 1; j < k; j++) if (xs[j] < xs[i]) { float t = xs[i]; xs[i] = xs[j]; xs[j] = t; }
    return xs[1];
}
void sg1_hud_dbg(int tag, float a, float b, float c, float d) { static int n[8]; static int seen[512]; static int ns; if (tag == 3 || tag == 5) { int i, id = (int)d + (int)(a * 100.0f + 1000.0f) * 65536; for (i = 0; i < ns; i++) if (seen[i] == id + tag * 65536) return; if (ns < 512) seen[ns++] = id + tag * 65536; } if (tag >= 0 && tag < 8 && n[tag] < (tag == 3 ? 400 : 20)) { n[tag]++; fprintf(stderr, "[HUDDBG] %d: %.2f %.2f %.2f %.2f\n", tag, a, b, c, d); } }   /* 1 unused, 2 scan failed (best offset, fwd, right, up), 3 widget placed (fwd, right, up, stretch), 4 camera (x y z yaw) */

/*
 * If xboxrecomp.h is not an umbrella header in your setup, include
 * the individual headers directly:
 *
 * #include "kernel.h"
 * #include "xbox_memory_layout.h"
 * #include "d3d8_xbox.h"
 * #include "dsound_xbox.h"
 * #include "xinput_xbox.h"
 */

/* ── Global register state (defined in xbox_memory_layout.c) ── */

/* RECOMP_TLS is not optional here. The runtime defines these thread-local, and
 * a plain `extern` referencing a __declspec(thread) variable does not resolve
 * to the calling thread's copy -- it resolves to the image's TLS template. The
 * host side then writes g_esp somewhere the generated code never reads, so the
 * guest starts with every register at zero and faults immediately, having
 * apparently ignored the setup that visibly ran. */
extern RECOMP_TLS uint32_t g_eax, g_ecx, g_edx, g_esp;
extern RECOMP_TLS uint32_t g_ebx, g_esi, g_edi;
extern RECOMP_TLS uint32_t g_seh_ebp;
/* x87 and SSE state. Global for the same reason the volatile GPRs are: one
 * guest routine can lift to several C functions, so a value written in one
 * body is read in the next. Defined in xbox_memory_layout.c like the rest of
 * the register file. */
extern RECOMP_TLS double g_fp_stack[8];
extern RECOMP_TLS int g_fp_top;
extern RECOMP_TLS uint16_t g_fp_control_word;
extern RECOMP_TLS uint32_t g_mxcsr;
extern RECOMP_TLS int g_fp_cmp;
extern RECOMP_TLS RecompXmm g_xmm0, g_xmm1, g_xmm2, g_xmm3;
extern RECOMP_TLS RecompXmm g_xmm4, g_xmm5, g_xmm6, g_xmm7;
extern ptrdiff_t g_xbox_mem_offset;

/* ── XBE Constants ─────────────────────────────────────────── */

/*
 * TODO: Set these from your xbe_parser output.
 * Run: py -3 -m tools.xbe_parser game/default.xbe
 */
#define YOUR_GAME_ENTRY_POINT   0x0033F317  /* XBE entry point VA */
#define YOUR_GAME_XBE_PATH      "default.xbe"
#define YOUR_GAME_DIR            "."

/* ── Forward declarations ──────────────────────────────────── */

static BOOL load_xbe(const char *path, void **out_data, size_t *out_size);

/* Where the game lives: RECOMP_GAME_DIR, else the exe's folder or one of its parents
 * (also a "game" subfolder of each), else the path compiled in above. Lets the exe start
 * by double-click from anywhere inside / next to the game folder. */
static char g_sg1_xbe_path[MAX_PATH], g_sg1_game_dir[MAX_PATH];
static int sg1_has_xbe(const char *dir)
{
    char p[MAX_PATH + 16];
    DWORD a;
    snprintf(p, sizeof p, "%s\\default.xbe", dir);
    a = GetFileAttributesA(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}
static void sg1_find_game(void)
{
    char d[MAX_PATH], sub[MAX_PATH + 8];
    const char *ev = getenv("RECOMP_GAME_DIR");
    int level;
    g_sg1_game_dir[0] = 0;
    if (ev && ev[0] && sg1_has_xbe(ev)) snprintf(g_sg1_game_dir, sizeof g_sg1_game_dir, "%s", ev);
    if (!g_sg1_game_dir[0] && GetModuleFileNameA(NULL, d, sizeof d)) {
        char *sl = strrchr(d, '\\');
        if (sl) *sl = 0;
        for (level = 0; level < 8 && !g_sg1_game_dir[0]; level++) {
            char *cut;
            if (sg1_has_xbe(d)) snprintf(g_sg1_game_dir, sizeof g_sg1_game_dir, "%s", d);
            else {
                snprintf(sub, sizeof sub, "%s\\game", d);
                if (sg1_has_xbe(sub)) snprintf(g_sg1_game_dir, sizeof g_sg1_game_dir, "%s", sub);
            }
            cut = strrchr(d, '\\');
            if (!cut || cut == d || d[strlen(d) - 1] == ':') break;
            *cut = 0;
        }
    }
    if (!g_sg1_game_dir[0]) snprintf(g_sg1_game_dir, sizeof g_sg1_game_dir, "%s", YOUR_GAME_DIR);
    snprintf(g_sg1_xbe_path, sizeof g_sg1_xbe_path, "%s\\default.xbe", g_sg1_game_dir);
}

/* Recompiled entry point (generated by recomp pipeline) */
volatile uint32_t g_sg1_isr_n, g_sg1_dpc_n, g_sg1_ists_or;   /* audio probe counters (bumped from the patched recomp_0114.c) */
extern void xbe_entry_point(void);
extern void sg1_gpu_backend_install(void);
extern void xbox_OhciInit(void);
extern void xbox_OhciReport(void);

/* ── VEH crash handler ─────────────────────────────────────── */

/*
 * Vectored Exception Handler for crash diagnostics.
 *
 * When the recompiled game hits an access violation, this handler prints
 * the faulting address, all Xbox register values, and a native stack trace.
 * This is your primary debugging tool during bring-up.
 *
 * Customize this for your game:
 *   - Add game-specific address checks (GPU register probes, etc.)
 *   - Add dumps of game-specific globals (heap handles, state flags)
 *   - Add SEH simulation if your game uses __try/__except
 */
/* Name the guest function a fault happened in, and recover the call chain.
 *
 * Recompiled code faults as ordinary native code, so the exception record
 * carries a host RIP and nothing else -- there is no guest program counter to
 * report, and the host address changes every build. Two things recover the
 * guest view:
 *
 *   - every generated function is a real symbol in the image (sub_005A03C0
 *     and so on), so the linker's PDB already maps host address back to guest
 *     function. dbghelp turns an anonymous RIP into that name.
 *
 *   - every lifted call pushes its guest return address onto the guest stack
 *     before jumping, so the stack still holds the chain. Scanning up from esp
 *     for values inside the code sections recovers it.
 *
 * ponytail: the stack scan is a scan, not a frame walk -- these are FPO frames
 * with no reliable ebp chain, so there is nothing to walk. It over-reports,
 * since addresses from returned-from calls linger below esp, but naming the
 * guest function is the whole question at a fault.
 *
 * Requires linking dbghelp and keeping the .pdb beside the .exe.
 */
static void print_guest_context(void *rip)
{
    /* SYMBOL_INFO is variable-length: the name is written past the struct, so
     * it must be over-allocated with MaxNameLen set to the slack. */
    char buf[sizeof(SYMBOL_INFO) + 256];
    SYMBOL_INFO *sym = (SYMBOL_INFO *)buf;
    DWORD64 disp = 0;

    memset(buf, 0, sizeof(buf));
    sym->SizeOfStruct = sizeof(SYMBOL_INFO);
    sym->MaxNameLen = 255;
    if (SymFromAddr(GetCurrentProcess(), (DWORD64)(uintptr_t)rip, &disp, sym))
        fprintf(stderr, "  in %s+0x%llX\n",
                sym->Name, (unsigned long long)disp);

    if (g_xbox_mem_offset && g_esp) {
        const uint32_t *sp =
            (const uint32_t *)((uintptr_t)g_xbox_mem_offset + g_esp);
        int shown = 0, i;
        fprintf(stderr, "  guest stack (return addresses, innermost first):\n");
        for (i = 0; i < 256 && shown < 24; i++) {
            uint32_t v = sp[i];
            if (v > g_xbox_code_lo && v < g_xbox_code_hi) {
                fprintf(stderr, "    [esp+%-4d] 0x%08X\n", i * 4, v);
                shown++;
            }
        }
        /* When the frame is gone, say so, and fall back on what is left.
         *
         * A fault inside a block copy leaves no return address in range: the
         * copy is a host memmove and its caller's frame is further up than
         * this reaches. Worse, a copy that ran past its buffer overwrites the
         * stack itself, so the list comes out empty exactly when it is most
         * needed -- and an empty list under a promising heading reads like
         * "nothing to see" rather than "the evidence is destroyed". */
        if (!shown)
            fprintf(stderr, "    (no return addresses in range)\n");

        /* Everything below only pays for itself when the scan came back
         * empty. A crash where the chain was recovered already says what
         * happened, and burying that under another twenty lines makes the
         * common report worse to read. */
        if (!shown) {
            uint32_t k;

            /* The indirect-call history, which the stack cannot overwrite.
             * recomp_manual.c prints this too, but only from
             * recomp_icall_fail_log -- a page fault inside a block copy
             * never reaches that path, and this is the same information by
             * the route the fault actually took.
             *
             * Declared here rather than included: main.c does not pull in
             * recomp_types.h, and recomp_manual.c spells it the same way. */
            extern volatile uint32_t g_icall_trace[16];
            extern volatile uint32_t g_icall_trace_idx;

            fprintf(stderr, "  recent ICALL targets:");
            for (k = 0; k < 16; k++)
                fprintf(stderr, " %08X",
                        g_icall_trace[(g_icall_trace_idx + k) & 15]);
            fprintf(stderr, "\n");

            /* The frame unfiltered. The pointers and lengths handed to
             * whatever faulted live here and look nothing like code, so the
             * filter above drops exactly what is wanted. On the crash this
             * was written for, one of these words was the end of the mapped
             * RAM mirror -- which is what identified the fault as a copy
             * running off its buffer rather than a stray pointer. */
            for (i = 0; i < 20; i++)
                fprintf(stderr, "    raw[esp+%-4d] 0x%08X\n", i * 4, sp[i]);
        }
    }
}

/* LOCAL PATCH (sg1 bring-up): called by RECOMP_WATCH to name the writer. */
void recomp_watch_sym_dump(void *rip)
{
    char buf[sizeof(SYMBOL_INFO) + 256];
    SYMBOL_INFO *sym = (SYMBOL_INFO *)buf;
    void *frames[24];
    USHORT n, i;
    n = CaptureStackBackTrace(0, 24, frames, NULL);
    for (i = 0; i <= n; i++) {
        void *pc = (i == 0) ? rip : frames[i - 1];
        DWORD64 disp = 0;
        memset(buf, 0, sizeof(buf));
        sym->SizeOfStruct = sizeof(SYMBOL_INFO);
        sym->MaxNameLen = 255;
        if (SymFromAddr(GetCurrentProcess(), (DWORD64)(uintptr_t)pc, &disp, sym))
            fprintf(stderr, "         W%-2d %s+0x%llX\n", i, sym->Name,
                    (unsigned long long)disp);
        else
            fprintf(stderr, "         W%-2d %p\n", i, pc);
    }
}

/* The emulated APU.
 *
 * Two entry points that had no callers anywhere in the tree. apu_mmio_hook.c
 * documents apu_hook_handle_mmio as "called from VEH in main.c" and no main.c
 * called it; apu_decode_and_handle's first line is `if (!g_apu_state) return
 * false` and nothing assigned g_apu_state. So with RECOMP_AC97_READY set the
 * APU's registers were unmapped to be trapped, and every trap was then
 * declined and surfaced as an access violation on the first register
 * DirectSound touched. The VEH below now reaches apu_hook_handle_mmio
 * through the toolkit's xbox_VehMmioFault.
 *
 * Declared rather than included so this does not depend on src/apu being on
 * the include path. */
typedef struct MCPXAPUState MCPXAPUState;
extern MCPXAPUState *mcpx_apu_init_standalone(uint8_t *ram_ptr);
extern MCPXAPUState *g_apu_state;




/* LOCAL (sg1): tell the pushbuffer executor where this game's GPU semaphore is.
 *
 * XDK D3D keeps a pointer to the GPU's progress word at device+0x30 and waits
 * for it to reach each fence (sub_00457C20 spins on it). The executor writes
 * the value for method 0x1D70 (semaphore release) to the address it was told
 * with nv2a_pb_set_semaphore_target(); nothing told it, so the semaphore never
 * moved and the first fence wait hung. The D3D device pointer for this title is
 * the guest global at 0x00460EE8. D3D rewrites the field on a device reset, so
 * the thread re-applies it whenever it changes. */
extern void nv2a_pb_set_semaphore_target(uint32_t guest_va);
static uint32_t sg_rd32(uint32_t va)
{
    return *(volatile uint32_t *)((uintptr_t)va + (uintptr_t)g_xbox_mem_offset);
}
static DWORD WINAPI sg_semaphore_thread(LPVOID unused)
{
    uint32_t last = 0;
    (void)unused;
    for (;;) {
        uint32_t dev = sg_rd32(0x00460EE8u);
        if (dev >= 0x00010000u && dev < 0x04000000u) {
            uint32_t sem = sg_rd32(dev + 0x30u);
            if (sem && sem != last &&
                ((sem >= 0x00010000u && sem < 0x04000000u) ||
                 (sem >= 0x80000000u && sem < 0x84000000u))) {
                nv2a_pb_set_semaphore_target(sem);
                fprintf(stderr, "[SG1] GPU semaphore for executor set to guest 0x%08X (device 0x%08X)\n", sem, dev);
                fflush(stderr);
                last = sem;
            }
        }
        Sleep(1);
    }
    return 0;
}

/* LOCAL (sg1): a trace file that does not share stderr's handle. The run ends
 * with the console log cut mid-line and no exit hook firing, so this records
 * what the process was doing from a separate file, flushed on every line. */
static FILE *sg_trace_fp;
static CRITICAL_SECTION sg_trace_cs;
extern volatile uint64_t g_icall_count;
static void sg_log(const char *fmt, ...)
{
    va_list ap;
    if (!sg_trace_fp) return;
    EnterCriticalSection(&sg_trace_cs);
    fprintf(sg_trace_fp, "[%8lu] ", (unsigned long)GetTickCount());
    va_start(ap, fmt);
    vfprintf(sg_trace_fp, fmt, ap);
    va_end(ap);
    fputc('\n', sg_trace_fp);
    fflush(sg_trace_fp);
    LeaveCriticalSection(&sg_trace_cs);
}

#include <tlhelp32.h>
/* SG1 freeze diagnosis: suspend every other thread for a moment, read where it is (an offset into the exe, which
 * build\Release\sg1_alliance_recomp.map names) plus the return addresses found on its stack, then log it. The text is
 * built into a local buffer while the threads are stopped, with no CRT locks or heap, and written after they resume. */
static void sg_dump_threads(const char *why)
{
    static char out[8192];
    int n = 0;
    unsigned char *base = (unsigned char *)GetModuleHandleA(NULL);
    unsigned long long lo = (unsigned long long)base, hi = lo;
    HANDLE snap;
    THREADENTRY32 te;
    DWORD me = GetCurrentThreadId(), pid = GetCurrentProcessId();
    if (base) {
        IMAGE_DOS_HEADER *dh = (IMAGE_DOS_HEADER *)base;
        IMAGE_NT_HEADERS *nh = (IMAGE_NT_HEADERS *)(base + dh->e_lfanew);
        hi = lo + nh->OptionalHeader.SizeOfImage;
    }
    out[0] = 0;
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return;
    te.dwSize = sizeof(te);
    if (Thread32First(snap, &te)) {
        do {
            HANDLE h;
            CONTEXT c;
            if (te.th32OwnerProcessID != pid || te.th32ThreadID == me) continue;
            h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, te.th32ThreadID);
            if (!h) continue;
            memset(&c, 0, sizeof(c));
            c.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
            if (SuspendThread(h) != (DWORD)-1) {
                if (GetThreadContext(h, &c)) {
                    int found = 0;
                    unsigned long long *sp = (unsigned long long *)c.Rsp;
                    int i;
                    if (c.Rip >= lo && c.Rip < hi) n += _snprintf(out + n, sizeof(out) - n - 1, "\n  tid %lu RIP=+%llX bt:", (unsigned long)te.th32ThreadID, c.Rip - lo);
                    else n += _snprintf(out + n, sizeof(out) - n - 1, "\n  tid %lu RIP=ext(%llX) bt:", (unsigned long)te.th32ThreadID, c.Rip);
                    __try {
                        for (i = 0; i < 400 && found < 14 && n < (int)sizeof(out) - 64; i++)
                            if (sp[i] >= lo && sp[i] < hi) { n += _snprintf(out + n, sizeof(out) - n - 1, " +%llX", sp[i] - lo); found++; }
                    } __except (EXCEPTION_EXECUTE_HANDLER) { }
                }
                ResumeThread(h);
            }
            CloseHandle(h);
        } while (n < (int)sizeof(out) - 128 && Thread32Next(snap, &te));
    }
    CloseHandle(snap);
    out[sizeof(out) - 1] = 0;
    sg_log("THREADS (%s):%s", why, out);
}

static DWORD WINAPI sg_heartbeat(LPVOID unused)
{
    DWORD flags = 0;
    unsigned long long prev = 0; int slow = 0, spin = 0;
    extern volatile uint32_t g_icall_trace[16];
    extern volatile uint32_t g_icall_trace_idx;
    (void)unused;
    for (;;) {
        HANDLE e = GetStdHandle(STD_ERROR_HANDLE);
        BOOL ok = e && e != INVALID_HANDLE_VALUE && GetHandleInformation(e, &flags);
        sg_log("HB icalls=%llu stderr_handle=%p valid=%d", (unsigned long long)g_icall_count, (void *)e, (int)ok);
        /* SG1 stall watchdog: the guest normally makes millions of indirect calls a second. A few hundred a second for
         * three seconds is a freeze; name the last indirect-call targets so the loop can be found. */
        {
            unsigned long long now = (unsigned long long)g_icall_count;
            if (now - prev < 3000ull) slow++; else slow = 0;
            prev = now;
            { /* SG1: a spin shows as the same few targets over and over */
              int d = 0, a, b; for (a = 0; a < 16; a++) { for (b = 0; b < a; b++) if (g_icall_trace[a] == g_icall_trace[b]) break; if (b == a) d++; }
              if (d <= 4) spin++; else spin = 0;
              if (spin == 20 || (spin > 20 && (spin % 100) == 0)) { char sb[256]; int k2, n2 = 0; for (k2 = 0; k2 < 16; k2++) n2 += _snprintf(sb + n2, sizeof(sb) - n2, " %08X", g_icall_trace[(g_icall_trace_idx + k2) & 15]); sb[sizeof(sb) - 1] = 0; sg_log("SPIN guest repeating %d beats; ICALL targets:%s", spin, sb); if (spin == 20 || (spin % 300) == 0) sg_dump_threads("spin"); }
            }
            if (slow == 30 || (slow > 30 && (slow % 100) == 0)) {
                char b[256]; int k, n = 0;
                for (k = 0; k < 16; k++) n += _snprintf(b + n, sizeof(b) - n, " %08X", g_icall_trace[(g_icall_trace_idx + k) & 15]);
                b[sizeof(b) - 1] = 0;
                sg_log("STALL guest slow for %d beats; recent ICALL targets:%s", slow, b);
                if (slow == 30 || (slow % 300) == 0) sg_dump_threads("stall");
            }
        }
        Sleep(100);
    }
    return 0;
}
static void sg_trace_start(void)
{
    InitializeCriticalSection(&sg_trace_cs);
    sg_trace_fp = _fsopen("sg1_trace.txt", "w", _SH_DENYNO);
    sg_log("trace start pid=%lu", (unsigned long)GetCurrentProcessId());
    CloseHandle(CreateThread(NULL, 0, sg_heartbeat, NULL, 0, NULL));
}
/* LOCAL (sg1): find out who ends the process. Patches the first 12 bytes of
 * a few exit functions with a jump to a reporter that prints a host stack
 * trace, then restores the original bytes and calls the real function. */
typedef struct { void *target; unsigned char orig[12]; } SgHook;
static SgHook sg_h_rtlexit, sg_h_nterm, sg_h_term;

static void sg_hook_install(SgHook *h, void *target, void *detour)
{
    DWORD old;
    unsigned char jmp[12] = { 0x48, 0xB8, 0,0,0,0,0,0,0,0, 0xFF, 0xE0 };
    if (!target) return;
    h->target = target;
    memcpy(h->orig, target, 12);
    memcpy(jmp + 2, &detour, 8);
    if (VirtualProtect(target, 12, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(target, jmp, 12);
        VirtualProtect(target, 12, old, &old);
        FlushInstructionCache(GetCurrentProcess(), target, 12);
    }
}
static void sg_hook_remove(SgHook *h)
{
    DWORD old;
    if (!h->target) return;
    if (VirtualProtect(h->target, 12, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(h->target, h->orig, 12);
        VirtualProtect(h->target, 12, old, &old);
        FlushInstructionCache(GetCurrentProcess(), h->target, 12);
    }
}
static void sg_report_exit(const char *what, unsigned long code)
{
    sg_log("EXITHOOK %s code=%lu", what, code);
    fprintf(stderr, "[EXITHOOK] %s code=%lu thread=%lu exe_base=%p\n", what, code, GetCurrentThreadId(), (void *)GetModuleHandleA(NULL));
    recomp_watch_sym_dump(NULL);
    fflush(stderr);
}
typedef VOID (NTAPI *PFN_RtlExitUserProcess)(UINT);
typedef LONG (NTAPI *PFN_NtTerminateProcess)(HANDLE, LONG);
typedef BOOL (WINAPI *PFN_TerminateProcess)(HANDLE, UINT);
static VOID NTAPI sg_det_rtlexit(UINT code)
{
    sg_report_exit("RtlExitUserProcess", code);
    sg_hook_remove(&sg_h_rtlexit);
    ((PFN_RtlExitUserProcess)sg_h_rtlexit.target)(code);
}
static LONG NTAPI sg_det_nterm(HANDLE h, LONG code)
{
    if (h == NULL || h == GetCurrentProcess()) {
        /* NULL handle = "all other threads", used inside normal exit. */
        sg_report_exit(h ? "NtTerminateProcess(self)" : "NtTerminateProcess(NULL)", (unsigned long)code);
    }
    sg_hook_remove(&sg_h_nterm);
    return ((PFN_NtTerminateProcess)sg_h_nterm.target)(h, code);
}
static BOOL WINAPI sg_det_term(HANDLE h, UINT code)
{
    sg_report_exit("TerminateProcess", code);
    sg_hook_remove(&sg_h_term);
    return ((PFN_TerminateProcess)sg_h_term.target)(h, code);
}
static void sg_install_exit_hooks(void)
{
    HMODULE nt = GetModuleHandleA("ntdll.dll");
    HMODULE kb = GetModuleHandleA("kernelbase.dll");
    if (nt) {
        sg_hook_install(&sg_h_rtlexit, (void *)GetProcAddress(nt, "RtlExitUserProcess"), (void *)sg_det_rtlexit);
        sg_hook_install(&sg_h_nterm, (void *)GetProcAddress(nt, "NtTerminateProcess"), (void *)sg_det_nterm);
    }
    if (kb)
        sg_hook_install(&sg_h_term, (void *)GetProcAddress(kb, "TerminateProcess"), (void *)sg_det_term);
}

static void sg1_atexit_note(void)
{
    sg_log("atexit handler ran (exit() or main returned)");
    fprintf(stderr, "[EXIT] process exiting via atexit/exit()\n");
    fflush(stderr);
}

static LONG WINAPI sg1_unhandled(PEXCEPTION_POINTERS ep)
{
    sg_log("UNHANDLED code=0x%08lX rip=%llX", (unsigned long)ep->ExceptionRecord->ExceptionCode, (unsigned long long)ep->ContextRecord->Rip);
    {   /* SG1: enough in sg1_trace.txt to locate a crash without the console log: access type, address, rip as an offset into the exe */
        unsigned long long base = (unsigned long long)(uintptr_t)GetModuleHandleA(NULL);
        sg_log("  fault: %s addr=%llX  exe base=%llX rip offset=+%llX  xbox mem=%llX",
               ep->ExceptionRecord->NumberParameters > 0 ? (ep->ExceptionRecord->ExceptionInformation[0] == 0 ? "read" : ep->ExceptionRecord->ExceptionInformation[0] == 1 ? "write" : "exec") : "?",
               ep->ExceptionRecord->NumberParameters > 1 ? (unsigned long long)ep->ExceptionRecord->ExceptionInformation[1] : 0ull,
               base, (unsigned long long)ep->ContextRecord->Rip - base, (unsigned long long)(uintptr_t)g_xbox_mem_offset);
    }
    fprintf(stderr, "[UNHANDLED] code=0x%08lX RIP=0x%llX\n",
        (unsigned long)ep->ExceptionRecord->ExceptionCode,
        (unsigned long long)ep->ContextRecord->Rip);
    print_guest_context((void *)ep->ContextRecord->Rip);
    fflush(stderr);
    return EXCEPTION_CONTINUE_SEARCH;
}

/* SG1: write watch (RECOMP_WATCH=1): the executor arms one guest page read-only; the first write to it
 * is reported with the guest call stack, then the page is released. Used to find who fills the
 * vertex colour buffers. */
volatile uintptr_t g_sg1_watch_page;
volatile int g_sg1_watch_done;
void sg1_watch_arm(uint32_t guest_va)
{
    DWORD old;
    uintptr_t host = ((uintptr_t)g_xbox_mem_offset + guest_va) & ~(uintptr_t)0xFFF;
    if (g_sg1_watch_page || g_sg1_watch_done >= 14) return;
    if (VirtualProtect((LPVOID)host, 4096, PAGE_READONLY, &old)) g_sg1_watch_page = host;
}

static LONG CALLBACK veh_handler(PEXCEPTION_POINTERS ep)
{
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && g_sg1_watch_page
        && ep->ExceptionRecord->ExceptionInformation[0] == 1) {
        uintptr_t fa = ep->ExceptionRecord->ExceptionInformation[1];
        if (fa >= g_sg1_watch_page && fa < g_sg1_watch_page + 4096) {
            DWORD old;
            uintptr_t pg = g_sg1_watch_page;
            VirtualProtect((LPVOID)pg, 4096, PAGE_READWRITE, &old);
            g_sg1_watch_page = 0;
            g_sg1_watch_done++;
            fprintf(stderr, "[WATCH] write to guest %08X (page %08X) rip rva %llX thread %lu\n", (unsigned)(fa - (uintptr_t)g_xbox_mem_offset),
                    (unsigned)(pg - (uintptr_t)g_xbox_mem_offset),
                    (unsigned long long)ep->ContextRecord->Rip - (unsigned long long)(uintptr_t)GetModuleHandleA(NULL), (unsigned long)GetCurrentThreadId());
            print_guest_context((void *)ep->ContextRecord->Rip);
            fflush(stderr);
            return EXCEPTION_CONTINUE_EXECUTION;
        }
    }
    /* LOCAL (sg1): report every serious exception, not just access violations.
     * Anything else used to fall through silently and kill the process with no
     * message. 0x406D1388 (thread name), C++ throws (0xE06D7363) and the
     * debugger breakpoint-less cases are ignored. */
    {
        DWORD code = ep->ExceptionRecord->ExceptionCode;
        if (code != EXCEPTION_ACCESS_VIOLATION &&
            (code >= 0xC0000000u || code == EXCEPTION_BREAKPOINT) &&
            code != 0xE06D7363u) {
            sg_log("EXC code=0x%08lX rip=%llX", (unsigned long)code, (unsigned long long)ep->ContextRecord->Rip);
            fprintf(stderr, "[EXC] code=0x%08lX RIP=0x%llX esp=0x%08X eax=0x%08X ecx=0x%08X edx=0x%08X ebx=0x%08X esi=0x%08X edi=0x%08X\n",
                (unsigned long)code,
                (unsigned long long)ep->ContextRecord->Rip,
                g_esp, g_eax, g_ecx, g_edx, g_ebx, g_esi, g_edi);
            print_guest_context((void *)ep->ContextRecord->Rip);
        {   /* SG1: where in the exe -- look the rva up in sg1_alliance_recomp.map */
            unsigned long long mb = (unsigned long long)(uintptr_t)GetModuleHandleA(NULL);
            uintptr_t *sp2 = (uintptr_t *)ep->ContextRecord->Rsp; int q, shown = 0;
            fprintf(stderr, "  [CRASH] thread %lu, module base %llX, rip rva %llX\n", (unsigned long)GetCurrentThreadId(), mb,
                    (unsigned long long)ep->ContextRecord->Rip - mb);
            for (q = 0; q < 256 && shown < 16; q++) {
                unsigned long long v = (unsigned long long)sp2[q];
                if (v > mb && v < mb + 0x6000000ULL) { fprintf(stderr, "  [CRASH]   stack rva %llX\n", v - mb); shown++; }
            }
        }
            fflush(stderr);
        }
        if (code == EXCEPTION_ACCESS_VIOLATION) {
            uintptr_t fa = ep->ExceptionRecord->ExceptionInformation[1];
            if (fa >= 0xFD000000 && fa < 0xFE000000)
                fprintf(stderr, "[EXC] AV in NV2A range at RIP=0x%llX addr=0x%llX (%s)\n",
                    (unsigned long long)ep->ContextRecord->Rip,
                    (unsigned long long)fa,
                    ep->ExceptionRecord->ExceptionInformation[0] ? "write" : "read");
        }
    }
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {
        uintptr_t fault_addr = ep->ExceptionRecord->ExceptionInformation[1];

        /*
         * GPU register probe at 0xFD000000 range.
         * Some games probe NV2A registers directly. On real hardware this
         * returns GPU state; here we just skip the instruction.
         * TODO: Implement mini x86-64 decoder for instruction skipping,
         * or connect to the xbox_nv2a library for proper handling.
         */
        if (fault_addr >= 0xFD000000 && fault_addr < 0xFE000000) {
            return EXCEPTION_CONTINUE_SEARCH;
        }

        /* Trapped hardware registers (APU, USB OHCI) -> their models.
         *
         * The other half of RECOMP_AC97_READY: reporting the codec ready is
         * what lets DirectSoundCreate past its first gate, and from there it
         * drives the APU directly, so the registers have to fault to be seen.
         * "Handled" means the access was decoded and the instruction stepped
         * over, so execution resumes instead of unwinding. */
        if (xbox_VehMmioFault(ep))
            return EXCEPTION_CONTINUE_EXECUTION;

        fprintf(stderr, "[CRASH] Access violation at RIP=0x%llX, fault addr=0x%llX (%s)\n",
            (unsigned long long)ep->ContextRecord->Rip,
            (unsigned long long)fault_addr,
            ep->ExceptionRecord->ExceptionInformation[0] ? "write" : "read");
        fprintf(stderr, "  Xbox regs: eax=0x%08X ecx=0x%08X edx=0x%08X esp=0x%08X\n",
            g_eax, g_ecx, g_edx, g_esp);
        fprintf(stderr, "  Xbox regs: ebx=0x%08X esi=0x%08X edi=0x%08X\n",
            g_ebx, g_esi, g_edi);
        fprintf(stderr, "  Xbox VA of fault: 0x%08X\n",
            (uint32_t)(fault_addr - (uintptr_t)g_xbox_mem_offset));
        print_guest_context((void *)ep->ContextRecord->Rip);
        {   /* SG1: where in the exe -- look the rva up in sg1_alliance_recomp.map */
            unsigned long long mb = (unsigned long long)(uintptr_t)GetModuleHandleA(NULL);
            uintptr_t *sp2 = (uintptr_t *)ep->ContextRecord->Rsp; int q, shown = 0;
            fprintf(stderr, "  [CRASH] thread %lu, module base %llX, rip rva %llX\n", (unsigned long)GetCurrentThreadId(), mb,
                    (unsigned long long)ep->ContextRecord->Rip - mb);
            for (q = 0; q < 256 && shown < 16; q++) {
                unsigned long long v = (unsigned long long)sp2[q];
                if (v > mb && v < mb + 0x6000000ULL) { fprintf(stderr, "  [CRASH]   stack rva %llX\n", v - mb); shown++; }
            }
        }

        /*
         * TODO: Add game-specific diagnostics here. Examples:
         *
         * Dump CRT heap handle:
         *   uint32_t heap = *(uint32_t *)((uint8_t *)g_xbox_mem_offset + HEAP_HANDLE_VA);
         *   fprintf(stderr, "  CRT heap handle: 0x%08X\n", heap);
         *
         * Dump game state:
         *   uint32_t state = *(uint32_t *)((uint8_t *)g_xbox_mem_offset + GAME_STATE_VA);
         *   fprintf(stderr, "  Game state: %u\n", state);
         */

        /* Print native stack return addresses for debugging */
        {
            uintptr_t *sp = (uintptr_t *)ep->ContextRecord->Rsp;
            fprintf(stderr, "  Native stack (first 8 return addrs):\n");
            for (int i = 0; i < 64 && sp[i]; i++) {
                if (sp[i] >= 0x140000000ULL && sp[i] < 0x150000000ULL) {
                    fprintf(stderr, "    [%d] 0x%llX\n", i, (unsigned long long)sp[i]);
                }
            }
        }
        fflush(stderr);
    }

    return EXCEPTION_CONTINUE_SEARCH;
}

/* ── WinMain ───────────────────────────────────────────────── */

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow)
{
    void *xbe_data = NULL;
    size_t xbe_size = 0;

    (void)hInstance;
    (void)hPrevInstance;
    (void)lpCmdLine;

    /* Settings this port needs to run at all. They used to be typed into the
     * console by hand, so a fresh window hung during start-up. Anything already
     * set in the environment still wins. */
    {
        static const char *const defs[] = {
            "RECOMP_AC97_READY=1", "RECOMP_FB_WINDOW=1", "RECOMP_GPU=1",
            "RECOMP_HEAP_RECLAIM=1", "RECOMP_PB_EXEC=1", "RECOMP_RASTER_THREADS=1",
            "RECOMP_VBLANK=paced", "RECOMP_KEYBOARD=1", "RECOMP_MKB=1", "RECOMP_USB=1", "RECOMP_D3D_PRESENT=1",
        };
        size_t i;
        for (i = 0; i < sizeof defs / sizeof defs[0]; i++) {
            char name[64]; const char *eq = strchr(defs[i], '=');
            size_t n = (size_t)(eq - defs[i]);
            memcpy(name, defs[i], n); name[n] = 0;
            if (!getenv(name)) _putenv(defs[i]);
        }
    }
    (void)nCmdShow;

    /* Unbuffered output for immediate visibility during debugging */
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    printf("=== YOUR_GAME_NAME - Static Recompilation ===\n");
    printf("Loading XBE...\n");

    /* Install VEH handler (first handler in chain) */
    /* Load symbols up front rather than from inside the handler: at fault
     * time the process is already in a bad way, and SymInitialize
     * allocates. Failure is not fatal -- the handler prints no name. */
    SymSetOptions(SYMOPT_DEFERRED_LOADS | SYMOPT_UNDNAME);
    SymInitialize(GetCurrentProcess(), NULL, TRUE);
    AddVectoredExceptionHandler(1, veh_handler);
    SetUnhandledExceptionFilter(sg1_unhandled);

    /* Step 1: Load XBE */
    sg1_find_game();
    if (!load_xbe(g_sg1_xbe_path, &xbe_data, &xbe_size)) {
        char msg[MAX_PATH + 320];
        snprintf(msg, sizeof msg, "Failed to load default.xbe.\n\nLooked for:\n%s\n\n"
                 "Put the exe inside the game folder (or a folder below it), or set RECOMP_GAME_DIR to the folder that contains default.xbe.",
                 g_sg1_xbe_path);
        MessageBoxA(NULL, msg, "Recomp", MB_ICONERROR);
        return 1;
    }
    printf("XBE loaded: %zu bytes\n", xbe_size);

    /* Step 2: Initialize Xbox memory layout */
    printf("Initializing Xbox memory layout...\n");
    xbox_SetTotalRam(XBOX_DEVKIT_RAM);
    {   /* The 128 MB devkit's heap ran dry loading the tutorial (xbox_HeapAlloc:
         * out of memory at ~111 MB). Back more host memory behind the same guest
         * RAM size: the heap grows, what the title is told about memory does not.
         * RECOMP_MAP_MB overrides; 0 keeps the old size. */
        const char *mm = getenv("RECOMP_MAP_MB");
        unsigned mb = mm ? (unsigned)atoi(mm) : 256u;
        if (mb) xbox_SetMapSize((size_t)mb * 1024u * 1024u);
    }
    if (!xbox_MemoryLayoutInit(xbe_data, xbe_size)) {
        MessageBoxA(NULL, "Failed to initialize Xbox memory layout.\n"
                    "The required virtual address range may be unavailable.",
                    "Recomp", MB_ICONERROR);
        free(xbe_data);
        return 1;
    }

    g_xbox_mem_offset = xbox_GetMemoryOffset();
    printf("Xbox memory mapped. Offset: 0x%llX\n", (unsigned long long)g_xbox_mem_offset);

    {   /* SG1 ultrawide: the game's D3D library has a table of display modes (12-byte rows at 0x45F280, key /
         * size / flags). Only rows whose key matches the current video setup are offered, and the 720p row never matched,
         * so SETRES could not go above 720x480. RECOMP_MODE_ROW=WxH turns the 1280x720 row into a usable WxH mode by
         * giving it the key of the 480p rows (which do match). */
        if (getenv("RECOMP_AV_HDTV")) {
            /* FindMode requires key bit25 == request flag bit8; the engine sets bit8 for HD sizes. */
            uint32_t *t = (uint32_t *)((uint8_t *)g_xbox_mem_offset + 0x45F280u);
            for (int i = 0; i < 40; i++, t += 3) {
                unsigned w = t[1] & 0xFFFFu;
                if (w >= 1280 && w <= 4096 && (t[0] & 0xFFFFu) == 0x0104u) {
                    t[0] |= 0x02000000u;
                }
            }
        }
        const char *mr = getenv("RECOMP_MODE_ROW");
        unsigned mw = 0, mh = 0;
        if (mr && sscanf(mr, "%ux%u", &mw, &mh) == 2 && mw >= 640 && mw <= 4096 && mh >= 480 && mh <= 2160) {
            uint32_t *row = (uint32_t *)((uint8_t *)g_xbox_mem_offset + 0x45F2F8u);
            if (!getenv("RECOMP_AV_HDTV")) row[0] = 0x00480104u;   /* with HDTV bits the row keeps the working 720p key (bit25 set) */
            row[1] = (mh << 16) | mw;
        }
    }

    /* Bring up the emulated APU.
     *
     * Gated on the same variable that unmaps its registers, because the two
     * halves are useless apart: a trap with no model declines every access,
     * and a model nothing traps into never sees a register. The APU walks
     * Xbox physical RAM to find voice buffers, so it gets the guest RAM
     * base. */
    if (getenv("RECOMP_AC97_READY")) {
        g_apu_state = mcpx_apu_init_standalone((uint8_t *)xbox_GetMemoryBase());
        fprintf(stderr, "[BOOT] emulated APU %s\n",
                g_apu_state ? "up" : "FAILED to initialise");
    }

    /* Step 3: Initialize Xbox kernel */
    printf("Initializing Xbox kernel replacement...\n");
    xbox_kernel_init();

    /* Step 4: Set game directory for file I/O path translation */
    {
        extern void xbox_path_init(const char *game_dir, const char *save_dir);
        xbox_path_init(g_sg1_game_dir, NULL);
    }

    /* Step 5: Initialize kernel bridge (thunk table in Xbox memory) */
    printf("Initializing kernel bridge...\n");
    xbox_kernel_bridge_init();

    /* Step 6: Initialize stack */
    g_esp = XBOX_STACK_TOP;

    /*
     * TODO: Pre-initialize CRT globals if needed.
     *
     * Many Xbox games use the MSVC CRT. The CRT's __heap_init sets up a
     * heap descriptor at a game-specific address. You may need to
     * pre-initialize __active_heap to avoid small-block heap issues:
     *
     *   uint32_t *active_heap = (uint32_t *)((uint8_t *)g_xbox_mem_offset + ACTIVE_HEAP_VA);
     *   *active_heap = 1;  // 1 = system heap (HeapAlloc), avoids SBH init
     *
     * Find ACTIVE_HEAP_VA by searching the disassembly for __heap_init
     * or by looking for the CRT's __active_heap global in the data section.
     */

    printf("\n=== Initialization complete ===\n");
    printf("Entry point: 0x%08X\n", YOUR_GAME_ENTRY_POINT);
    printf("ESP: 0x%08X\n", g_esp);

    /* Build the flat dispatch table before the guest runs.
     *
     * Without this recomp_lookup falls back to a binary search over the
     * whole function table -- roughly log2(n) branches on *every*
     * indirect call, which for a 45,000-function C++ title is about 16
     * every time the game goes through a vtable. Half-Life 2 spent most
     * of its static initialisation inside recomp_lookup for exactly this
     * reason, and it read as a hang.
     *
     * Optional by design: if the allocation fails the search still works,
     * so a failure is worth one line and not a fatal error. */
    if (!recomp_dispatch_init())
        fprintf(stderr, "[BOOT] flat dispatch unavailable; "
                        "indirect calls will use the binary search\n");

    /* Arm the hang watchdog. Does nothing unless RECOMP_WATCHDOG_SECS is set,
     * and must be called from this thread -- the guest registers it samples are
     * thread-local, so it has to be handed the copies belonging to the thread
     * that runs guest code.
     *
     * Not optional boilerplate: without this call RECOMP_WATCHDOG_SECS is
     * silently inert, and the one diagnostic that tells a hang from slowness
     * does nothing while appearing to be set. */
    if (!getenv("RECOMP_TITLE_KEVENTS")) _putenv("RECOMP_TITLE_KEVENTS=1");   /* D3D waits on an event it initialised itself */
    if (!getenv("RECOMP_DISPATCH_GATE")) _putenv("RECOMP_DISPATCH_GATE=1");   /* the one-CPU gate DirectSound's IRQL locks rely on; set it to 0 to turn it off */
    if (!getenv("RECOMP_USB")) _putenv("RECOMP_USB=1");
    if (!getenv("RECOMP_KEYBOARD")) _putenv("RECOMP_KEYBOARD=1");
    if (!getenv("RECOMP_MKB")) _putenv("RECOMP_MKB=1");
    if (!getenv("RECOMP_USB_STATS")) _putenv("RECOMP_USB_STATS=1");
    atexit(xbox_OhciReport);
    xbox_OhciInit();   /* RECOMP_USB=1: emulated USB host + gamepad (keyboard via RECOMP_KEYBOARD=1) */
    xbox_WatchdogStart();

    /* Step 7: Call the recompiled entry point */
    printf("\nStarting game...\n");
    fflush(stdout);

    sg_trace_start();
    CloseHandle(CreateThread(NULL, 0, sg_semaphore_thread, NULL, 0, NULL));
    atexit(sg1_atexit_note);
    sg_install_exit_hooks();
    if (getenv("RECOMP_GPU")) { sg1_gpu_backend_install(); sg_log("GPU backend installed"); }
    sg_log("entering xbe_entry_point");
    xbe_entry_point();

    sg_log("xbe_entry_point RETURNED");
    printf("\nGame returned. Cleaning up...\n");

    /* Cleanup */
    xbox_kernel_shutdown();
    xbox_MemoryLayoutShutdown();
    free(xbe_data);

    return 0;
}

/* ── XBE Loading ───────────────────────────────────────────── */

static BOOL load_xbe(const char *path, void **out_data, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "Cannot open XBE: %s\n", path);
        return FALSE;
    }

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (size <= 0) {
        fclose(f);
        return FALSE;
    }

    void *data = malloc((size_t)size);
    if (!data) {
        fclose(f);
        return FALSE;
    }

    if (fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        fclose(f);
        return FALSE;
    }

    fclose(f);
    *out_data = data;
    *out_size = (size_t)size;
    return TRUE;
}

/* Console entry point (for debugging -- lets you see printf output) */
int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    return WinMain(GetModuleHandle(NULL), NULL, GetCommandLineA(), SW_SHOW);
}
