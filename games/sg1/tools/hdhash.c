#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define HD_EXPORT __declspec(dllexport)
#else
#define HD_EXPORT
#endif
#include <stddef.h>
/* identical to hash_bytes() in d3d11_backend.c */
HD_EXPORT uint64_t hd_hash(const uint8_t *p, size_t n)
{
    uint64_t h = 1469598103934665603ull; size_t i = 0;
    for (; i + 8 <= n; i += 8) { uint64_t w; memcpy(&w, p + i, 8); h = (h ^ w) * 1099511628211ull; h ^= h >> 29; }
    for (; i < n; i++) h = (h ^ p[i]) * 1099511628211ull;
    return h;
}
