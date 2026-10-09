// SPDX-License-Identifier: GPL-2.0+
/* Read-only guards for the 04 host workflow. Every error propagates to UCmd. */
#include <command.h>
#include <fat.h>
#include <malloc.h>
#include <memalign.h>
#include <vsprintf.h>
#include <mmc.h>
#include <part.h>
#include <stdlib.h>
#include <asm/unaligned.h>
#include <u-boot/sha256.h>
#include <linux/delay.h>

#define IO_BYTES (1024 * 1024)
#define MAX_SAVED 1024
#define MAX_FILE (16 * 1024 * 1024)
#define SAVE_SECTORS (4 * 1024 * 1024 / 512)

struct saved_hash {
	bool valid;
	bool empty;
	uint hwpart;
	ulong start, count;
	char file[64];
	u8 digest[SHA256_SUM_LEN];
};
static struct saved_hash saved[MAX_SAVED];
static u8 saved_partconf;
static bool partconf_valid;
static bool loader_valid;
static ulong loader_user_sectors, loader_boot_sectors, loader_end;

static int read_partconf(u8 *value)
{
	struct mmc *mmc = find_mmc_device(1);
	ALLOC_CACHE_ALIGN_BUFFER(u8, ext_csd, 512);

	if (!mmc || mmc_init(mmc) || IS_SD(mmc) || mmc_send_ext_csd(mmc, ext_csd))
		return -1;
	*value = ext_csd[EXT_CSD_PART_CONF];
	return 0;
}

static int number(const char *s, ulong *v)
{
	return strict_strtoul(s, 16, v);
}

static int device(uint hwpart, struct blk_desc **desc)
{
	struct mmc *mmc = find_mmc_device(1);
	char name[8];

	if (hwpart > 1 || !mmc || mmc_init(mmc) || IS_SD(mmc))
		return -1;
	snprintf(name, sizeof(name), "1.%u", hwpart);
	if (blk_get_device_by_str("mmc", name, desc) < 0 ||
	    (*desc)->blksz != 512)
		return -1;
	return 0;
}

static int digest_range(uint hwpart, ulong start, ulong count, u8 *digest)
{
	struct blk_desc *desc;
	sha256_context ctx;
	u8 *buf;
	ulong n;

	if (device(hwpart, &desc))
		return -1;
	/* count=0 is reserved for snapshotting the complete boot0. */
	if (!count && hwpart == 1)
		count = desc->lba;
	if (!count || start >= desc->lba || count > desc->lba - start)
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, IO_BYTES);
	if (!buf)
		return -1;
	sha256_starts(&ctx);
	while (count) {
		n = min(count, (ulong)(IO_BYTES / 512));
		if (blk_dread(desc, start, n, buf) != n) {
			free(buf);
			return -1;
		}
		sha256_update(&ctx, buf, n * 512);
		start += n;
		count -= n;
		schedule();
	}
	sha256_finish(&ctx, digest);
	free(buf);
	/* Leave the shared MMC descriptor in user area for fastboot/FAT. */
	return device(0, &desc);
}

/* No partition-table assumption: a firmware-only update works on legacy media.
 * Every snapshot command hashes <= 4 MiB to bound a UUU USB command latency.
 */
static int loader_guard(ulong bytes)
{
    struct blk_desc *desc;

    loader_valid = false;
    partconf_valid = false;
    memset(saved, 0, sizeof(saved));
    if (bytes < 4096 || bytes > 0xffc00 || bytes % 512 ||
        device(1, &desc) || desc->lba < 2048 || desc->lba > SAVE_SECTORS)
        return -1;
    loader_boot_sectors = desc->lba;
    loader_end = 2 + bytes / 512;
    if (device(0, &desc) || !desc->lba ||
        desc->lba > (ulong)(MAX_SAVED - 2) * SAVE_SECTORS)
        return -1;
    loader_user_sectors = desc->lba;
    loader_valid = true;
    return 0;
}

static int loader_save(ulong slot)
{
    struct saved_hash *s;

    if (!loader_valid || slot >= MAX_SAVED)
        return -1;
    s = &saved[slot];
    memset(s, 0, sizeof(*s));
    if (slot < 2) {
        s->hwpart = 1;
        s->start = slot ? loader_end : 0;
        s->count = slot ? loader_boot_sectors - loader_end : 2;
    } else {
        s->start = (slot - 2) * SAVE_SECTORS;
        if (s->start < loader_user_sectors)
            s->count = min((ulong)SAVE_SECTORS, loader_user_sectors - s->start);
    }
    s->empty = !s->count;
    if (!s->empty && digest_range(s->hwpart, s->start, s->count, s->digest))
        return -1;
    s->valid = true;
    return 0;
}

static int digest_file(const char *name, ulong expected_size, u8 *digest)
{
	struct blk_desc *desc;
	sha256_context ctx;
	loff_t size, got, offset = 0, n;
	u8 *buf;
	int ret = -1;

	if (device(0, &desc) || fat_register_device(desc, 1) ||
	    fat_size(name, &size) || size <= 0 || size > MAX_FILE ||
	    (expected_size && (ulong)size != expected_size))
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, IO_BYTES);
	if (!buf)
		return -1;
	sha256_starts(&ctx);
	while (offset < size) {
		n = min(size - offset, (loff_t)IO_BYTES);
		if (fat_read_file(name, buf, offset, n, &got) || got != n)
			goto out;
		sha256_update(&ctx, buf, n);
		offset += n;
		schedule();
	}
	sha256_finish(&ctx, digest);
	ret = 0;
out:
	free(buf);
	fat_close();
	return ret;
}

static int matches(const u8 *digest, const char *hex)
{
	char actual[SHA256_SUM_LEN * 2 + 1];
	int i;

	for (i = 0; i < SHA256_SUM_LEN; ++i)
		sprintf(actual + 2 * i, "%02x", digest[i]);
	return strlen(hex) == SHA256_SUM_LEN * 2 && !strcmp(actual, hex);
}

static int guard(const char *mode, ulong *p)
{
	struct blk_desc *desc;
	struct disk_partition part;
	ALLOC_CACHE_ALIGN_BUFFER(u8, mbr, 512);
	int i;

	memset(saved, 0, sizeof(saved));
	loader_valid = false;
	partconf_valid = false;
	if (read_partconf(&saved_partconf))
		return -1;
	partconf_valid = true;
	if (p[0] < 8 || !p[1] || !p[3] || p[0] + p[1] < p[0] ||
	    p[2] < p[0] + p[1] || p[2] + p[3] < p[2])
		return -1;
	if (device(1, &desc) || desc->lba < 2048 ||
	    device(0, &desc) || p[2] + p[3] > desc->lba)
		return -1;
	if (!strcmp(mode, "all"))
		return 0;
	if (strcmp(mode, "kernel") && strcmp(mode, "dtb") && strcmp(mode, "rootfs"))
		return -1;
	/* Force a fresh partition scan; reject GPT, extended or extra partitions. */
	part_init(desc);
	if (desc->part_type != PART_TYPE_DOS || blk_dread(desc, 0, 1, mbr) != 1 ||
	    mbr[510] != 0x55 || mbr[511] != 0xaa)
		return -1;
	for (i = 0; i < 2; ++i) {
		u8 *entry = mbr + 446 + 16 * i;

		if (entry[4] != (i ? 0x83 : 0x0c) ||
		    part_get_info(desc, i + 1, &part) ||
		    part.start != p[2 * i] || part.size != p[2 * i + 1])
			return -1;
	}
	for (i = 478; i < 510; ++i)
		if (mbr[i])
			return -1;
	return 0;
}

/* Count real FAT entries, not the potentially stale FSInfo free count.
 * Require mirrored FAT32, an existing file and enough entirely free clusters
 * for the new file plus a directory cluster. This is deliberately conservative.
 */
static int space(const char *name, ulong bytes)
{
	struct blk_desc *desc;
	struct disk_partition part;
	ALLOC_CACHE_ALIGN_BUFFER(u8, sector, 512);
	ALLOC_CACHE_ALIGN_BUFFER(u8, mirror, 512);
	loff_t old_size;
	u32 reserved, fatsz, total, clusters, free_clusters = 0;
	u32 cluster_size, fat_sector, entry, i, needed;

	if (!bytes || bytes > MAX_FILE || device(0, &desc) ||
	    part_get_info(desc, 1, &part) || fat_register_device(desc, 1) ||
	    fat_size(name, &old_size) || blk_dread(desc, part.start, 1, sector) != 1)
		return -1;
	fat_close();
	cluster_size = sector[13];
	reserved = get_unaligned_le16(sector + 14);
	fatsz = get_unaligned_le32(sector + 36);
	total = get_unaligned_le32(sector + 32);
	if (get_unaligned_le16(sector + 11) != 512 || !cluster_size ||
	    (cluster_size & (cluster_size - 1)) || cluster_size > 128 ||
	    !reserved || sector[16] != 2 || !fatsz ||
	    get_unaligned_le16(sector + 17) || get_unaligned_le16(sector + 22) ||
	    get_unaligned_le16(sector + 40) || total > part.size ||
	    (u64)reserved + 2ULL * fatsz >= total)
		return -1;
	clusters = (total - reserved - 2 * fatsz) / cluster_size;
	if (clusters < 65525 || (u64)clusters + 2 > (u64)fatsz * 128)
		return -1;
	for (fat_sector = 0; fat_sector < fatsz; ++fat_sector) {
		if (blk_dread(desc, part.start + reserved + fat_sector, 1, sector) != 1 ||
		    blk_dread(desc, part.start + reserved + fatsz + fat_sector, 1, mirror) != 1 ||
		    memcmp(sector, mirror, 512))
			return -1;
		for (i = 0; i < 128; ++i) {
			entry = fat_sector * 128 + i;
			if (entry >= 2 && entry < clusters + 2 &&
			    !(get_unaligned_le32(sector + 4 * i) & 0x0fffffff))
				++free_clusters;
		}
		schedule();
	}
	needed = DIV_ROUND_UP(bytes, cluster_size * 512) + 1;
	printf("FAT free clusters %u; conservative need %u\n", free_clusters, needed);
	return free_clusters < needed ? -1 : 0;
}

static int do_imx04(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	ulong v[5];
	u8 digest[SHA256_SUM_LEN];
	struct saved_hash *s;
	int i, ret = -1;

	if (argc < 2)
		return CMD_RET_USAGE;
	if (!strcmp(argv[1], "loaderguard") && argc == 3) {
		if (number(argv[2], &v[0]))
			return CMD_RET_USAGE;
		ret = loader_guard(v[0]);
	} else if (!strcmp(argv[1], "loadersave") && argc == 3) {
		if (number(argv[2], &v[0]))
			return CMD_RET_USAGE;
		ret = loader_save(v[0]);
	} else if (!strcmp(argv[1], "bootconf") && argc == 3) {
		u8 actual;

		if (number(argv[2], &v[0]) || v[0] > 255)
			return CMD_RET_USAGE;
		ret = read_partconf(&actual);
		if (!ret && actual != v[0])
			ret = -1;
	} else if (!strcmp(argv[1], "bootkeep") && argc == 2) {
		u8 actual;

		ret = partconf_valid ? read_partconf(&actual) : -1;
		/* Hardware partition ACCESS changes are transient, not boot policy. */
		if (!ret && (actual & 0xf8) != (saved_partconf & 0xf8))
			ret = -1;
	} else if (!strcmp(argv[1], "guard") && argc == 7) {
		for (i = 0; i < 4; ++i)
			if (number(argv[i + 3], &v[i]))
				return CMD_RET_USAGE;
		ret = guard(argv[2], v);
	} else if (!strcmp(argv[1], "space") && argc == 4) {
		if (number(argv[3], &v[0]))
			return CMD_RET_USAGE;
		ret = space(argv[2], v[0]);
	} else if (!strcmp(argv[1], "verify") && argc == 6) {
		for (i = 0; i < 3; ++i)
			if (number(argv[i + 2], &v[i]))
				return CMD_RET_USAGE;
		if (v[0] > 1)
			return CMD_RET_USAGE;
		ret = digest_range(v[0], v[1], v[2], digest);
		if (!ret && !matches(digest, argv[5]))
			ret = -1;
	} else if (!strcmp(argv[1], "file") && argc == 5) {
		if (number(argv[3], &v[0]))
			return CMD_RET_USAGE;
		ret = digest_file(argv[2], v[0], digest);
		if (!ret && !matches(digest, argv[4]))
			ret = -1;
	} else if ((!strcmp(argv[1], "save") && argc == 6) ||
		   (!strcmp(argv[1], "filesave") && argc == 4) ||
		   (!strcmp(argv[1], "keep") && argc == 3)) {
		if (number(argv[2], &v[0]) || v[0] >= MAX_SAVED)
			return CMD_RET_USAGE;
		s = &saved[v[0]];
		if (!strcmp(argv[1], "keep")) {
			if (!s->valid)
				return CMD_RET_FAILURE;
			if (s->empty)
				return CMD_RET_SUCCESS;
			ret = s->file[0] ? digest_file(s->file, 0, digest) :
				digest_range(s->hwpart, s->start, s->count, digest);
			if (!ret && memcmp(digest, s->digest, SHA256_SUM_LEN))
				ret = -1;
		} else {
			memset(s, 0, sizeof(*s));
			if (!strcmp(argv[1], "filesave")) {
				if (strlen(argv[3]) >= sizeof(s->file))
					return CMD_RET_USAGE;
				strcpy(s->file, argv[3]);
				ret = digest_file(s->file, 0, s->digest);
			} else {
				for (i = 1; i < 4; ++i)
					if (number(argv[i + 2], &v[i]))
						return CMD_RET_USAGE;
				if (v[1] > 1)
					return CMD_RET_USAGE;
				s->hwpart = v[1];
				s->start = v[2];
				s->count = v[3];
				ret = digest_range(s->hwpart, s->start, s->count, s->digest);
			}
			s->valid = !ret;
		}
	}
	if (ret)
		printf("imx04 %s: rejected or comparison failed\n", argv[1]);
	return ret ? CMD_RET_FAILURE : CMD_RET_SUCCESS;
}

U_BOOT_CMD(imx04, 7, 0, do_imx04, "04 read-only update guards (hex numbers)",
	"guard all|kernel|dtb|rootfs p1start p1size p2start p2size\n"
	"imx04 loaderguard image-bytes\n"
	"imx04 loadersave slot\n"
	"imx04 space filename bytes\n"
	"imx04 verify hwpart start sectors sha256\n"
	"imx04 file filename bytes sha256\n"
	"imx04 save slot hwpart start sectors\n"
	"imx04 filesave slot filename\n"
	"imx04 keep slot\n"
	"imx04 bootconf expected-byte\n"
	"imx04 bootkeep");
