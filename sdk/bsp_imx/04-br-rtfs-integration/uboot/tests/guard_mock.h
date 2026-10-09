/* Host-only adapters; exercise production guard logic without a board. */
#ifndef GUARD_MOCK_H
#define GUARD_MOCK_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <openssl/sha.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned int uint;
typedef unsigned long ulong;
#define ARCH_DMA_MINALIGN 64
#define ALLOC_CACHE_ALIGN_BUFFER(t, name, len) t name[len] __attribute__((aligned(64)))
#define min(a, b) ((a) < (b) ? (a) : (b))
#define DIV_ROUND_UP(a, b) (((a) + (b) - 1) / (b))
#define SHA256_SUM_LEN 32
#define CMD_RET_USAGE -1
#define CMD_RET_FAILURE 1
#define CMD_RET_SUCCESS 0
#define PART_TYPE_DOS 2
#define EXT_CSD_PART_CONF 179
#define IS_SD(mmc) ((mmc)->sd)
#define U_BOOT_CMD(...)
typedef SHA256_CTX sha256_context;
static void sha256_starts(sha256_context *c) { SHA256_Init(c); }
static void sha256_update(sha256_context *c, const u8 *p, uint n) { SHA256_Update(c, p, n); }
static void sha256_finish(sha256_context *c, u8 *p) { SHA256_Final(p, c); }
struct cmd_tbl { int unused; };
struct mmc { int sd; };
struct blk_desc { ulong lba; uint blksz, hwpart; int part_type; };
struct disk_partition { ulong start, size; };
static struct mmc mock_mmc;
static struct blk_desc mock_desc = { 5000000, 512, 0, 2 };
static u8 partconf = 0x48;
static bool bad_read, no_space, wrong_table;
static u8 pattern = 0x5a;
static char file_content[8] = "hello";
static struct mmc *find_mmc_device(int dev) { return dev == 1 ? &mock_mmc : NULL; }
static int mmc_init(struct mmc *mmc) { return 0; }
static int mmc_send_ext_csd(struct mmc *mmc, u8 *out) {
    memset(out, 0, 512); out[179] = partconf; return 0;
}
static int strict_strtoul(const char *s, int base, ulong *out) {
    char *end; *out = strtoul(s, &end, base); return !*s || *end;
}
static void *memalign(size_t alignment, size_t size) { return aligned_alloc(alignment, size); }
static void schedule(void) {}
static u32 get_unaligned_le32(const u8 *p) {
    return p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}
static uint get_unaligned_le16(const u8 *p) { return p[0] | p[1] << 8; }
static void put32(u8 *p, u32 v) { for (int i = 0; i < 4; ++i) p[i] = v >> (8 * i); }
static int blk_get_device_by_str(const char *interface, const char *name, struct blk_desc **out) {
    mock_desc.hwpart = name[2] - '0';
    mock_desc.lba = mock_desc.hwpart ? 8192 : 5000000;
    partconf = (partconf & 0xf8) | mock_desc.hwpart;
    *out = &mock_desc;
    return 1;
}
static void part_init(struct blk_desc *d) {}
static int part_get_info(struct blk_desc *d, int part, struct disk_partition *out) {
    out->start = part == 1 ? 2048 : 264192;
    out->size = part == 1 ? 262144 : 4194304;
    return part == 1 || part == 2 ? 0 : -1;
}
static ulong blk_dread(struct blk_desc *d, ulong start, ulong n, void *buffer) {
    u8 *p = buffer;
    memset(p, pattern, n * 512);
    if (bad_read) return n - 1;
    if (!d->hwpart && start == 0 && n == 1) {
        memset(p, 0, 512); p[510] = 0x55; p[511] = 0xaa;
        p[450] = wrong_table ? 0x83 : 0x0c; p[466] = 0x83;
        put32(p + 454, 2048); put32(p + 458, 262144);
        put32(p + 470, 264192); put32(p + 474, 4194304);
    } else if (!d->hwpart && start == 2048 && n == 1) {
        memset(p, 0, 512); p[12] = 2; p[13] = 1; p[14] = 32; p[16] = 2;
        put32(p + 32, 262144); put32(p + 36, 2048);
    } else if (!d->hwpart && start >= 2080 && start < 6176 && n == 1) {
        memset(p, no_space ? 0xff : 0, 512);
    }
    return n;
}
static int fat_register_device(struct blk_desc *d, int part) { return part == 1 ? 0 : -1; }
static int fat_size(const char *name, loff_t *size) { *size = strlen(file_content); return 0; }
static int fat_read_file(const char *name, void *buf, loff_t offset, loff_t n, loff_t *got) {
    memcpy(buf, file_content + offset, n); *got = n; return 0;
}
static void fat_close(void) {}
#endif
