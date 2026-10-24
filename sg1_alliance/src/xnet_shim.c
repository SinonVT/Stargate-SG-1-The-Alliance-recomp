/*
 * xnet_shim.c -- Xbox XNet -> Winsock bridge for the SG-1 recomp.
 *
 * The game links Microsoft's XNet stack, which drives the console's NIC. There
 * is no NIC here, so the calls that move data are implemented on top of real
 * UDP sockets instead:
 *
 *   bind / getsockname / setsockopt / getsockopt / ioctlsocket
 *   recvfrom / sendto / closesocket / XNetGetTitleXnAddr
 *
 * Everything else still runs the original code (socket(), key registration, QOS
 * bookkeeping...) and is traced. A guest SOCKET is a pointer to XNet's own socket
 * object; the host SOCKET behind it is created on first use and kept in a table.
 *
 * Env: SG_NET_IP=a.b.c.d  address reported as this machine's (default: auto)
 *      SG_NET_LOG=0       silence per-call logging
 *      SG_NET_PEER=a.b.c.d[,e.f.g.h]  also send every broadcast (server discovery) straight to these hosts
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>

#ifdef _MSC_VER
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")
extern __declspec(thread) uint32_t g_esp, g_eax, g_fs_base;
#else
extern __thread uint32_t g_esp, g_eax, g_fs_base;
#endif
extern ptrdiff_t g_xbox_mem_offset;

#define H(a)   ((void *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))
#define M32(a) (*(volatile uint32_t *)H(a))
#define M16(a) (*(volatile uint16_t *)H(a))
#define M8(a)  (*(volatile uint8_t  *)H(a))
#define ARG(i) M32(g_esp + 4u + 4u * (i))

static int s_log = -1;
static int logging(void)
{
    if (s_log < 0) { const char *e = getenv("SG_NET_LOG"); s_log = !(e && e[0] == '0'); }
    return s_log;
}
#define NLOG(...) do { if (logging()) { fprintf(stderr, __VA_ARGS__); fflush(stderr); } } while (0)

/* ---- socket table ------------------------------------------------------- */
#define MAXS 32
static struct { uint32_t gs; SOCKET hs; } s_tab[MAXS];
static CRITICAL_SECTION s_cs;
static int s_inited;

static void net_init(void)
{
    WSADATA wd;
    if (s_inited) return;
    InitializeCriticalSection(&s_cs);
    WSAStartup(MAKEWORD(2, 2), &wd);
    s_inited = 1;
}

static void set_guest_error(int e)
{
    uint32_t tls = M32(g_fs_base + 4u);
    uint32_t idx = M32(0x7BD4ACu);
    uint32_t obj = M32(tls + idx * 4u);
    if (obj) M32(obj + 4u) = (uint32_t)e;
}

/* host socket for a guest SOCKET, created (UDP, non-blocking, broadcast) on first use */
static SOCKET host_sock(uint32_t gs, int create)
{
    int i, free_i = -1;
    SOCKET hs;
    net_init();
    EnterCriticalSection(&s_cs);
    for (i = 0; i < MAXS; i++) {
        if (s_tab[i].gs == gs && s_tab[i].hs) { hs = s_tab[i].hs; LeaveCriticalSection(&s_cs); return hs; }
        if (!s_tab[i].gs && free_i < 0) free_i = i;
    }
    if (!create || free_i < 0) { LeaveCriticalSection(&s_cs); return INVALID_SOCKET; }
    hs = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (hs != INVALID_SOCKET) {
        u_long nb = 1; BOOL one = TRUE;
        ioctlsocket(hs, FIONBIO, &nb);
        setsockopt(hs, SOL_SOCKET, SO_BROADCAST, (const char *)&one, sizeof one);
        s_tab[free_i].gs = gs; s_tab[free_i].hs = hs;
        NLOG("[NETHLE] host UDP socket created for guest socket %08X\n", gs);
    }
    LeaveCriticalSection(&s_cs);
    return hs;
}

static void drop_sock(uint32_t gs)
{
    int i;
    net_init();
    EnterCriticalSection(&s_cs);
    for (i = 0; i < MAXS; i++)
        if (s_tab[i].gs == gs && s_tab[i].hs) {
            closesocket(s_tab[i].hs);
            s_tab[i].gs = 0; s_tab[i].hs = 0;
        }
    LeaveCriticalSection(&s_cs);
}

/* ---- this machine's IPv4 ------------------------------------------------ */
static uint32_t local_ip(void)   /* network byte order */
{
    static uint32_t ip;
    if (ip) return ip;
    {
        const char *e = getenv("SG_NET_IP");
        if (e && *e) { ip = inet_addr(e); if (ip != INADDR_NONE) return ip; ip = 0; }
    }
    net_init();
    {   /* route-based: connect() a UDP socket (sends nothing) and read its address */
        SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (s != INVALID_SOCKET) {
            struct sockaddr_in to, me; int ml = sizeof me;
            memset(&to, 0, sizeof to); to.sin_family = AF_INET; to.sin_port = htons(53);
            to.sin_addr.s_addr = inet_addr("8.8.8.8");
            if (connect(s, (struct sockaddr *)&to, sizeof to) == 0 &&
                getsockname(s, (struct sockaddr *)&me, &ml) == 0)
                ip = me.sin_addr.s_addr;
            closesocket(s);
        }
    }
    if (!ip) ip = inet_addr("127.0.0.1");
    NLOG("[NETHLE] local address %u.%u.%u.%u\n", ip & 255, (ip >> 8) & 255, (ip >> 16) & 255, ip >> 24);
    return ip;
}

/* ---- tracing of calls that still run the original code ------------------ */
static int looks_ptr(uint32_t v) { return v >= 0x10000u && v < 0x08000000u; }
static void trace_call(uint32_t va)
{
    static unsigned counts[0x2000];
    static LONG total;
    unsigned idx = (va - 0x419100u) & 0x1FFFu;
    uint32_t a[6]; int i;
    unsigned n = counts[idx]++;
    if (n >= 12 && (n & (n - 1)) != 0) return;
    if (InterlockedIncrement(&total) > 3000) return;
    for (i = 0; i < 6; i++) a[i] = ARG(i);
    NLOG("[XNET] %08X #%u ret=%08X args: %08X %08X %08X %08X %08X %08X\n",
         va, n, M32(g_esp), a[0], a[1], a[2], a[3], a[4], a[5]);
    for (i = 0; i < 6; i++)
        if (looks_ptr(a[i])) {
            int k;
            NLOG("[XNET]    arg%d -> ", i);
            for (k = 0; k < 24; k++) NLOG("%02X ", M8(a[i] + k));
            NLOG("\n");
        }
}

/* Discovery is sent to 255.255.255.255, which Windows only puts on ONE adapter (often a virtual/link-local one), so a server on
 * another PC never sees it. Also send it to the directed broadcast of every adapter, and to the hosts in SG_NET_PEER. */
static void send_extra_broadcasts(SOCKET hs, const char *buf, int len, int fl, const struct sockaddr_in *to)
{
    static unsigned nx;
    struct sockaddr_in d = *to;
    const char *peer = getenv("SG_NET_PEER");
    if (to->sin_addr.s_addr != INADDR_BROADCAST) return;
    {   /* directed broadcast on every adapter: opt-in (SG_NET_BCAST=1); the copies leave with each adapter's own source address, which shows up as extra servers */
        ULONG sz = 0; MIB_IPADDRTABLE *t; const char *ob = getenv("SG_NET_BCAST");
        if (!(ob && ob[0] == '1')) goto peers;
        GetIpAddrTable(NULL, &sz, FALSE);
        t = sz ? (MIB_IPADDRTABLE *)malloc(sz) : NULL;
        if (t && GetIpAddrTable(t, &sz, FALSE) == NO_ERROR) {
            DWORD i;
            for (i = 0; i < t->dwNumEntries; i++) {
                DWORD a = t->table[i].dwAddr, m = t->table[i].dwMask;
                if (!a || (a & 255) == 127) continue;
                d.sin_addr.s_addr = a | ~m;
                if (d.sin_addr.s_addr == INADDR_BROADCAST) continue;
                sendto(hs, buf, len, fl, (const struct sockaddr *)&d, sizeof d);
                if (nx++ < 30) NLOG("[NETHLE] discovery also to %u.%u.%u.%u\n", d.sin_addr.s_addr & 255, (d.sin_addr.s_addr >> 8) & 255, (d.sin_addr.s_addr >> 16) & 255, d.sin_addr.s_addr >> 24);
            }
        }
        free(t);
    }
peers:
    if (peer && *peer) {
        char tmp[160], *tok, *ctx = NULL;
        strncpy(tmp, peer, sizeof tmp - 1); tmp[sizeof tmp - 1] = 0;
        for (tok = strtok_s(tmp, ", ;", &ctx); tok; tok = strtok_s(NULL, ", ;", &ctx)) {
            unsigned long ip = inet_addr(tok);
            if (ip == INADDR_NONE) continue;
            d.sin_addr.s_addr = ip;
            sendto(hs, buf, len, fl, (const struct sockaddr *)&d, sizeof d);
            if (nx++ < 30) NLOG("[NETHLE] discovery also to peer %s\n", tok);
        }
    }
}

/* The extra discovery sends above make the host receive the same search several times (once per route). Drop a datagram that is
 * byte-identical to one from the same sender in the last 150 ms, so the server answers once and the list shows one entry. */
static int is_discovery_port(SOCKET hs)   /* only the server-search socket (UDP 11777, plus SG_NET_PORT_OFFSET) is de-duplicated */
{
    struct sockaddr_in a; int l = sizeof a; unsigned p;
    if (getsockname(hs, (struct sockaddr *)&a, &l) != 0) return 0;
    p = ntohs(a.sin_port);
    return p >= 11777u && p <= 11793u;
}
static int is_dup_datagram(const char *buf, int len, const struct sockaddr_in *from)
{
    static struct { uint32_t h; DWORD t; } ring[32];
    static unsigned pos;
    uint32_t h = 2166136261u; int i; DWORD now = GetTickCount(); unsigned k;
    for (i = 0; i < len && i < 512; i++) { h ^= (unsigned char)buf[i]; h *= 16777619u; }
    h ^= (uint32_t)len;   /* the sender is NOT part of the key: copies that took different routes carry different source addresses */
    for (k = 0; k < 32; k++)
        if (ring[k].h == h && ring[k].t && (DWORD)(now - ring[k].t) < 150u) return 1;
    ring[pos++ & 31].h = h; ring[(pos - 1) & 31].t = now ? now : 1;
    return 0;
}

/* ---- the calls ---------------------------------------------------------- */
static int hle_calls;
#define HLOG(...) do { if (hle_calls < 400) { hle_calls++; NLOG(__VA_ARGS__); } } while (0)

static void to_host_addr(uint32_t ga, struct sockaddr_in *o)
{
    memset(o, 0, sizeof *o);
    o->sin_family = AF_INET;
    memcpy(&o->sin_port, H(ga + 2), 2);
    memcpy(&o->sin_addr, H(ga + 4), 4);
}
static void to_guest_addr(uint32_t ga, const struct sockaddr_in *a)
{
    memset(H(ga), 0, 16);
    M16(ga) = 2;
    memcpy(H(ga + 2), &a->sin_port, 2);
    memcpy(H(ga + 4), &a->sin_addr, 4);
}

/* returns bytes of arguments to pop (stdcall), or -1 to run the original */
int sg_xnet_hle(uint32_t va)
{
    switch (va) {
    case 0x4192AEu: {           /* bind(s, addr, len) */
        uint32_t gs = ARG(0), ga = ARG(1);
        struct sockaddr_in a; SOCKET hs; BOOL one = TRUE; int r;
        hs = host_sock(gs, 1);
        if (hs == INVALID_SOCKET) { set_guest_error(WSAENOTSOCK); g_eax = (uint32_t)-1; return 12; }
        to_host_addr(ga, &a);
        a.sin_addr.s_addr = INADDR_ANY;
        {   /* second copy of the game on one PC: SG_NET_PORT_OFFSET=1 shifts every bound port */
            const char *po = getenv("SG_NET_PORT_OFFSET");
            if (po && a.sin_port) a.sin_port = htons((unsigned short)(ntohs(a.sin_port) + atoi(po)));
        }
        setsockopt(hs, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, sizeof one);
        r = bind(hs, (struct sockaddr *)&a, sizeof a);
        HLOG("[NETHLE] bind(%08X port %u) -> %d (wsa %d)\n", gs, ntohs(a.sin_port), r, r ? WSAGetLastError() : 0);
        if (r) { set_guest_error(WSAGetLastError()); g_eax = (uint32_t)-1; } else g_eax = 0;
        return 12;
    }
    case 0x4192A3u: {           /* getsockname(s, addr, len*) */
        uint32_t gs = ARG(0), ga = ARG(1), gl = ARG(2);
        SOCKET hs = host_sock(gs, 0);
        struct sockaddr_in a; int l = sizeof a;
        if (hs == INVALID_SOCKET || getsockname(hs, (struct sockaddr *)&a, &l)) { set_guest_error(WSAENOTSOCK); g_eax = (uint32_t)-1; return 12; }
        if (a.sin_addr.s_addr == 0) a.sin_addr.s_addr = local_ip();
        to_guest_addr(ga, &a);
        if (gl) M32(gl) = 16;
        g_eax = 0;
        return 12;
    }
    case 0x419285u: {           /* setsockopt(s, level, opt, val, len) */
        uint32_t gs = ARG(0), lvl = ARG(1), opt = ARG(2), gv = ARG(3), gl = ARG(4);
        SOCKET hs = host_sock(gs, 1);
        int r = -1;
        if (hs != INVALID_SOCKET) {
            char buf[16]; uint32_t n = gl > 16 ? 16 : gl;
            memcpy(buf, H(gv), n);
            r = setsockopt(hs, (int)lvl, (int)opt, buf, (int)n);
            if (r) set_guest_error(WSAGetLastError());
        } else set_guest_error(WSAENOTSOCK);
        HLOG("[NETHLE] setsockopt(%08X lvl %X opt %X) -> %d\n", gs, lvl, opt, r);
        g_eax = (uint32_t)r;
        return 20;
    }
    case 0x419294u: {           /* getsockopt(s, level, opt, val, len*) */
        uint32_t gs = ARG(0), lvl = ARG(1), opt = ARG(2), gv = ARG(3), gl = ARG(4);
        SOCKET hs = host_sock(gs, 1);
        int r = -1;
        if (hs != INVALID_SOCKET) {
            char buf[16]; int l = (int)M32(gl);
            if (l > 16) l = 16;
            r = getsockopt(hs, (int)lvl, (int)opt, buf, &l);
            if (r == 0) { memcpy(H(gv), buf, (size_t)l); M32(gl) = (uint32_t)l; }
            else set_guest_error(WSAGetLastError());
        } else set_guest_error(WSAENOTSOCK);
        HLOG("[NETHLE] getsockopt(%08X lvl %X opt %X) -> %d\n", gs, lvl, opt, r);
        g_eax = (uint32_t)r;
        return 20;
    }
    case 0x41927Au: {           /* ioctlsocket(s, cmd, argp*) */
        uint32_t gs = ARG(0), cmd = ARG(1), ga = ARG(2);
        SOCKET hs = host_sock(gs, 1);
        int r = 0;
        if (hs != INVALID_SOCKET) {
            if (cmd == 0x8004667Eu) { /* FIONBIO: the host socket always stays non-blocking */ }
            else if (cmd == 0x4004667Fu) { u_long n = 0; r = ioctlsocket(hs, FIONREAD, &n); M32(ga) = n; }
        } else { r = -1; set_guest_error(WSAENOTSOCK); }
        HLOG("[NETHLE] ioctlsocket(%08X cmd %08X) -> %d\n", gs, cmd, r);
        g_eax = (uint32_t)r;
        return 12;
    }
    case 0x41931Du: {           /* recvfrom(s, buf, len, flags, from, fromlen*) */
        uint32_t gs = ARG(0), gb = ARG(1), len = ARG(2), fl = ARG(3), gf = ARG(4), gfl = ARG(5);
        SOCKET hs = host_sock(gs, 0);
        struct sockaddr_in from; int fl2 = sizeof from; int r;
        static unsigned nrecv;
        if (hs == INVALID_SOCKET) { set_guest_error(WSAENOTSOCK); g_eax = (uint32_t)-1; return 24; }
        r = recvfrom(hs, (char *)H(gb), (int)len, (int)fl, (struct sockaddr *)&from, &fl2);
        if (r > 0 && !(fl & MSG_PEEK) && is_discovery_port(hs) && is_dup_datagram((const char *)H(gb), r, &from)) { WSASetLastError(WSAEWOULDBLOCK); r = -1; }
        if (r < 0) {
            int e = WSAGetLastError();
            set_guest_error(e);
            g_eax = (uint32_t)-1;
        } else {
            if (gf) to_guest_addr(gf, &from);
            if (gfl) M32(gfl) = 16;
            g_eax = (uint32_t)r;
            if (nrecv++ < 60)
                NLOG("[NETHLE] recvfrom(%08X) %d bytes from %u.%u.%u.%u:%u\n", gs, r,
                     from.sin_addr.s_addr & 255, (from.sin_addr.s_addr >> 8) & 255,
                     (from.sin_addr.s_addr >> 16) & 255, from.sin_addr.s_addr >> 24, ntohs(from.sin_port));
        }
        return 24;
    }
    case 0x419346u: {           /* sendto(s, buf, len, flags, to, tolen) */
        uint32_t gs = ARG(0), gb = ARG(1), len = ARG(2), fl = ARG(3), gt = ARG(4);
        SOCKET hs = host_sock(gs, 1);
        struct sockaddr_in to; int r;
        static unsigned nsend;
        if (hs == INVALID_SOCKET) { set_guest_error(WSAENOTSOCK); g_eax = (uint32_t)-1; return 24; }
        to_host_addr(gt, &to);
        r = sendto(hs, (const char *)H(gb), (int)len, (int)fl, (struct sockaddr *)&to, sizeof to);
        send_extra_broadcasts(hs, (const char *)H(gb), (int)len, (int)fl, &to);
        if (nsend++ < 60)
            NLOG("[NETHLE] sendto(%08X) %u bytes to %u.%u.%u.%u:%u -> %d (wsa %d)\n", gs, len,
                 to.sin_addr.s_addr & 255, (to.sin_addr.s_addr >> 8) & 255,
                 (to.sin_addr.s_addr >> 16) & 255, to.sin_addr.s_addr >> 24, ntohs(to.sin_port),
                 r, r < 0 ? WSAGetLastError() : 0);
        if (r < 0) { set_guest_error(WSAGetLastError()); g_eax = (uint32_t)-1; } else g_eax = (uint32_t)r;
        return 24;
    }
    case 0x419264u: {           /* closesocket(s) */
        uint32_t gs = ARG(0);
        drop_sock(gs);
        HLOG("[NETHLE] closesocket(%08X)\n", gs);
        return -1;               /* let XNet free its own socket object too */
    }
    case 0x41924Eu: {           /* XNetGetTitleXnAddr(XNADDR*) */
        uint32_t gp = ARG(0);
        uint32_t ip = local_ip();
        if (gp) {
            memset(H(gp), 0, 36);
            memcpy(H(gp), &ip, 4);                       /* ina       */
            M8(gp + 12) = 0x02; M8(gp + 13) = 0x00;      /* abEnet: locally administered */
            memcpy(H(gp + 14), &ip, 4);
        }
        HLOG("[NETHLE] XNetGetTitleXnAddr -> %u.%u.%u.%u\n", ip & 255, (ip >> 8) & 255, (ip >> 16) & 255, ip >> 24);
        g_eax = 0x06;            /* ETHERNET | STATIC */
        return 4;
    }
    case 0x4191FBu: {           /* XNetXnAddrToInAddr(pxna, pxnkid, pina): the "secure" address is just the real one here */
        uint32_t gx = ARG(0), gi = ARG(2);
        if (gx && gi) M32(gi) = M32(gx);
        HLOG("[NETHLE] XnAddrToInAddr -> %u.%u.%u.%u\n", gx ? M8(gx) : 0, gx ? M8(gx + 1) : 0, gx ? M8(gx + 2) : 0, gx ? M8(gx + 3) : 0);
        g_eax = 0;
        return 12;
    }
    case 0x419212u: {           /* XNetInAddrToXnAddr(ina, pxna, pxnkid) */
        uint32_t ina = ARG(0), gx = ARG(1), gk = ARG(2);
        if (gx) {
            memset(H(gx), 0, 36);
            memcpy(H(gx), &ina, 4);
            M8(gx + 12) = 0x02; memcpy(H(gx + 14), &ina, 4);
        }
        if (gk) memset(H(gk), 0, 8);
        HLOG("[NETHLE] InAddrToXnAddr %u.%u.%u.%u\n", ina & 255, (ina >> 8) & 255, (ina >> 16) & 255, ina >> 24);
        g_eax = 0;
        return 12;
    }
    case 0x4191E5u:             /* XNetRegisterKey(pxnkid, pxnkey) */
        HLOG("[NETHLE] XNetRegisterKey\n");
        g_eax = 0;
        return 8;
    case 0x4191F0u:             /* XNetUnregisterKey(pxnkid) */
        HLOG("[NETHLE] XNetUnregisterKey\n");
        g_eax = 0;
        return 4;
    default:
        trace_call(va);
        return -1;
    }
}
