/* dbglaunch.c - run a program under the Win32 debug API and log what happens.
 * Usage: dbglaunch.exe program.exe
 * Writes dbg_events.txt: counts of every exception code plus the last events
 * before the process ended. Exceptions are passed on to the program as-is. */
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

#define RING 400
static char ring[RING][220];
static unsigned long ring_n;
static DWORD codes[64];
static unsigned long counts[64];
static int ncodes;

static void note(const char *fmt, ...)
{
    va_list ap;
    char *slot = ring[ring_n % RING];
    va_start(ap, fmt);
    vsnprintf(slot, 219, fmt, ap);
    va_end(ap);
    ring_n++;
}

static void count_code(DWORD c)
{
    int i;
    for (i = 0; i < ncodes; i++)
        if (codes[i] == c) { counts[i]++; return; }
    if (ncodes < 64) { codes[ncodes] = c; counts[ncodes++] = 1; }
}

int main(int argc, char **argv)
{
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    DEBUG_EVENT ev;
    char cmd[1024];
    DWORD exit_code = 0;
    int first_bp = 1, done = 0;
    unsigned long t0 = GetTickCount();
    int i;
    unsigned long start;
    FILE *f;

    if (argc < 2) { fprintf(stderr, "usage: dbglaunch program.exe\n"); return 2; }
    snprintf(cmd, sizeof cmd, "\"%s\"", argv[1]);
    memset(&si, 0, sizeof si); si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    if (!CreateProcessA(NULL, cmd, NULL, NULL, TRUE, DEBUG_ONLY_THIS_PROCESS, NULL, NULL, &si, &pi)) {
        fprintf(stderr, "CreateProcess failed: %lu\n", GetLastError());
        return 3;
    }
    while (!done && WaitForDebugEvent(&ev, INFINITE)) {
        DWORD cont = DBG_CONTINUE;
        unsigned long t = GetTickCount() - t0;
        switch (ev.dwDebugEventCode) {
        case EXCEPTION_DEBUG_EVENT: {
            EXCEPTION_RECORD *r = &ev.u.Exception.ExceptionRecord;
            count_code(r->ExceptionCode);
            if (r->ExceptionCode == EXCEPTION_BREAKPOINT && first_bp) { first_bp = 0; break; }
            cont = DBG_EXCEPTION_NOT_HANDLED;
            note("%6lu ms  tid=%lu EXC %s code=%08lX addr=%p info0=%llX info1=%llX",
                 t, ev.dwThreadId, ev.u.Exception.dwFirstChance ? "first " : "SECOND",
                 r->ExceptionCode, r->ExceptionAddress,
                 r->NumberParameters > 0 ? (unsigned long long)r->ExceptionInformation[0] : 0ULL,
                 r->NumberParameters > 1 ? (unsigned long long)r->ExceptionInformation[1] : 0ULL);
            break; }
        case CREATE_THREAD_DEBUG_EVENT:
            note("%6lu ms  tid=%lu CREATE_THREAD", t, ev.dwThreadId); break;
        case EXIT_THREAD_DEBUG_EVENT:
            note("%6lu ms  tid=%lu EXIT_THREAD code=%lu", t, ev.dwThreadId, ev.u.ExitThread.dwExitCode); break;
        case CREATE_PROCESS_DEBUG_EVENT:
            note("%6lu ms  CREATE_PROCESS", t);
            if (ev.u.CreateProcessInfo.hFile) CloseHandle(ev.u.CreateProcessInfo.hFile);
            break;
        case EXIT_PROCESS_DEBUG_EVENT:
            exit_code = ev.u.ExitProcess.dwExitCode;
            note("%6lu ms  tid=%lu EXIT_PROCESS code=%lu (0x%08lX)", t, ev.dwThreadId, exit_code, exit_code);
            done = 1; break;
        case LOAD_DLL_DEBUG_EVENT:
            if (ev.u.LoadDll.hFile) CloseHandle(ev.u.LoadDll.hFile);
            note("%6lu ms  LOAD_DLL base=%p", t, ev.u.LoadDll.lpBaseOfDll); break;
        case UNLOAD_DLL_DEBUG_EVENT:
            note("%6lu ms  UNLOAD_DLL base=%p", t, ev.u.UnloadDll.lpBaseOfDll); break;
        case OUTPUT_DEBUG_STRING_EVENT:
            note("%6lu ms  OutputDebugString len=%u", t, ev.u.DebugString.nDebugStringLength); break;
        case RIP_EVENT:
            note("%6lu ms  RIP error=%lu", t, ev.u.RipInfo.dwError); break;
        }
        ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, cont);
    }
    f = fopen("dbg_events.txt", "w");
    if (f) {
        fprintf(f, "exit code: %lu (0x%08lX)\n\nexception counts:\n", exit_code, exit_code);
        for (i = 0; i < ncodes; i++)
            fprintf(f, "  %08lX : %lu\n", codes[i], counts[i]);
        fprintf(f, "\nlast events:\n");
        start = ring_n > RING ? ring_n - RING : 0;
        for (; start < ring_n; start++)
            fprintf(f, "%s\n", ring[start % RING]);
        fclose(f);
    }
    fprintf(stderr, "[dbglaunch] process ended, exit code %lu; see dbg_events.txt\n", exit_code);
    return (int)exit_code;
}
