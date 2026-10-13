/* Host storage/memory adapters; filesystem algorithms come from fixed U-Boot. */
#ifndef UUF_NATIVE_COMPAT
#define UUF_NATIVE_COMPAT
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <endian.h>
#include <time.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;
typedef uint8_t __u8; typedef uint16_t __u16; typedef uint32_t __u32; typedef uint16_t __le16; typedef uint32_t __le32; typedef uint64_t __le64;
typedef uint16_t __be16; typedef uint32_t __be32; typedef uint64_t __be64;
typedef unsigned int uint; typedef unsigned long ulong; typedef uint64_t lbaint_t;
#undef S_IFLNK
#define CONFIG_EXT4_WRITE 1
#define CONFIG_EXT4_MAX_JOURNAL_ENTRIES 128
#define ARCH_DMA_MINALIGN 64
#define __packed __attribute__((packed))
#define __aligned(x) __attribute__((aligned(x)))
#define ALLOC_CACHE_ALIGN_BUFFER(t,n,len) t n[len] __attribute__((aligned(64)))
#define le16_to_cpu le16toh
#define le32_to_cpu le32toh
#define __le32_to_cpu le32toh
#define le64_to_cpu le64toh
#define be16_to_cpu be16toh
#define be32_to_cpu be32toh
#define cpu_to_le16 htole16
#define cpu_to_le32 htole32
#define cpu_to_le64 htole64
#define cpu_to_be16 htobe16
#define cpu_to_be32 htobe32
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define ROUND(a,b) (((a)+(b)-1)/(b)*(b))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
#define do_div(n,b) ({uint32_t _r=(n)%(b); (n)/=(b); _r;})
#define lldiv(a,b) ((a)/(b))
#define debug(...) do {} while(0)
#define log_debug(...) do {} while(0)
#define log_err(...) fprintf(stderr,__VA_ARGS__)
#define log_warning(...) fprintf(stderr,__VA_ARGS__)
#define LBAFU "%llu"
#define LBAF "llx"
#define kzalloc(s,f) calloc(1,s)
struct blk_desc { lbaint_t lba; uint blksz, log2blksz; };
struct disk_partition { lbaint_t start, size; uint blksz; };
struct rtc_time { int dummy; };
struct fs_dir_stream { int dummy; };
#define FS_DIRENT_NAME_LEN 256
#define FS_DT_DIR 4
#define FS_DT_REG 8
#define FS_DT_LNK 10
struct fs_dirent { char name[FS_DIRENT_NAME_LEN]; int type; loff_t size; struct rtc_time access_time,create_time,change_time; };
void rtc_to_tm(unsigned long, struct rtc_time*);
ulong blk_dread(struct blk_desc*,lbaint_t,lbaint_t,void*);
ulong blk_dwrite(struct blk_desc*,lbaint_t,lbaint_t,const void*);
int fs_devread(struct blk_desc*,struct disk_partition*,lbaint_t,int,int,char*);
uint16_t crc16(uint16_t,const u8*,size_t);
void *uuf_malloc(size_t); void *uuf_calloc(size_t,size_t); void *uuf_memalign(size_t,size_t); void uuf_free(void*);
void uuf_native_jsb_read_begin(void);
#define malloc uuf_malloc
#define calloc uuf_calloc
#define memalign uuf_memalign
#define free uuf_free
#endif
