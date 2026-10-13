// SPDX-License-Identifier: GPL-2.0+
/* Board-side I/O checks. Hex arguments, byte lengths, 512-byte LBAs. */
#include <command.h>
#include <env.h>
#include <fastboot.h>
#include <fastboot-internal.h>
#include <fs.h>
#include <ext4fs.h>
#include <malloc.h>
#include <memalign.h>
#include <mmc.h>
#include <part.h>
#include <stdlib.h>
#include <vsprintf.h>
#include <asm/unaligned.h>
#include <u-boot/sha256.h>
#include <linux/delay.h>

#define WINDOW (1024 * 1024)
#define MAX_EXPORT 8192
#define MAX_SLOTS 2048
#define MAX_PATH 201

struct saved {
	bool valid;
	uint hw, part;
	ulong start, bytes;
	char path[MAX_PATH];
	u8 digest[SHA256_SUM_LEN];
};
static struct saved saved[MAX_SLOTS];

static int number(const char *s, ulong *v)
{
	return strict_strtoul(s, 16, v);
}

static int device(uint hw, struct blk_desc **desc)
{
	struct mmc *m = find_mmc_device(1);
	char name[8];

	if (hw > 1 || !m || mmc_init(m) || IS_SD(m))
		return -1;
	snprintf(name, sizeof(name), "1.%u", hw);
	if (blk_get_device_by_str("mmc", name, desc) < 0 ||
	    (*desc)->blksz != 512)
		return -1;
	return 0;
}

static int range(uint hw, ulong start, ulong bytes, struct blk_desc **desc)
{
	ulong sectors = DIV_ROUND_UP(bytes, 512);

	if (device(hw, desc) || !bytes || start >= (*desc)->lba ||
	    sectors > (*desc)->lba - start)
		return -1;
	return 0;
}

static void hex(const u8 *in, uint n, char *out)
{
	uint i;

	for (i = 0; i < n; i++)
		sprintf(out + 2 * i, "%02x", in[i]);
}

static int matches(const u8 *digest, const char *expected)
{
	char value[65];

	hex(digest, 32, value);
	return strlen(expected) == 64 && !strcmp(value, expected);
}

static int export_data(const u8 *data, uint bytes)
{
	char name[32], value[49];
	uint i, n;

	if (bytes > MAX_EXPORT || env_set_hex("fastboot.uuf-size", bytes))
		return -1;
	/* getvar has only 60 response payload bytes; each field holds 24 bytes. */
	for (i = 0; i < bytes; i += 24) {
		n = min(24U, bytes - i);
		hex(data + i, n, value);
		snprintf(name, sizeof(name), "fastboot.uuf-data%u", i / 24);
		if (env_set(name, value))
			return -1;
	}
	return 0;
}

static int hash_range(uint hw, ulong start, ulong bytes, u8 *digest)
{
	struct blk_desc *d;
	sha256_context ctx;
	u8 *buf;
	ulong n;
	int ret = -1;

	if (range(hw, start, bytes, &d))
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, WINDOW);
	if (!buf)
		return -1;
	sha256_starts(&ctx);
	while (bytes) {
		n = min(bytes, (ulong)WINDOW);
		if (blk_dread(d, start, DIV_ROUND_UP(n, 512), buf) !=
		    DIV_ROUND_UP(n, 512))
			goto out;
		sha256_update(&ctx, buf, n);
		start += DIV_ROUND_UP(n, 512);
		bytes -= n;
		schedule();
	}
	sha256_finish(&ctx, digest);
	ret = 0;
out:
	free(buf);
	if (device(0, &d))
		ret = -1;
	return ret;
}

static int open_part(uint part)
{
	struct blk_desc *d;
	char name[16];

	if (part < 1 || part > 4 || device(0, &d))
		return -1;
	part_init(d);
	snprintf(name, sizeof(name), "1:%u", part);
	return fs_set_blk_dev("mmc", name, FS_TYPE_EXT);
}

static int hash_file(uint part, const char *path, ulong expected, u8 *digest)
{
	sha256_context ctx;
	loff_t bytes, got, offset = 0, n;
	u8 *buf;
	int ret = -1;

	if (open_part(part) || fs_size(path, &bytes) || ext4fs_io_error || bytes <= 0 ||
	    (expected && bytes != (loff_t)expected))
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, WINDOW);
	if (!buf)
		return -1;
	sha256_starts(&ctx);
	while (offset < bytes) {
		n = min(bytes - offset, (loff_t)WINDOW);
		if (open_part(part) || fs_read(path, (ulong)buf, offset, n, &got) || ext4fs_io_error || got != n)
			goto out;
		sha256_update(&ctx, buf, n);
		offset += n;
		schedule();
	}
	sha256_finish(&ctx, digest);
	ret = 0;
out:
	free(buf);
	fs_close();
	return ret;
}

static int info(void)
{
	struct mmc *m;
	struct blk_desc *d;
	char cid[33];
	ALLOC_CACHE_ALIGN_BUFFER(u8, csd, 512);

	if (device(0, &d))
		return -1;
	m = find_mmc_device(1);
	if (mmc_send_ext_csd(m, csd))
		return -1;
	snprintf(cid, sizeof(cid), "%08x%08x%08x%08x",
		 m->cid[0], m->cid[1], m->cid[2], m->cid[3]);
	if (env_set("fastboot.uuf-abi", "1") ||
	    env_set("fastboot.uuf-cid", cid) ||
	    env_set_hex("fastboot.uuf-user", m->capacity_user / 512) ||
	    env_set_hex("fastboot.uuf-boot", m->capacity_boot / 512) ||
	    env_set_hex("fastboot.uuf-erase", m->erase_grp_size) ||
	    env_set_hex("fastboot.uuf-erased", csd[181] & 1 ? 0xff : 0) ||
	    env_set_hex("fastboot.uuf-partconf", csd[EXT_CSD_PART_CONF] & 0xf8))
		return -1;
	return 0;
}

static int match_cid(const char *expected)
{
	struct blk_desc *d;
	struct mmc *m;
	char cid[33];

	if (strlen(expected) != 32 || device(0, &d))
		return -1;
	m = find_mmc_device(1);
	snprintf(cid, sizeof(cid), "%08x%08x%08x%08x",
		 m->cid[0], m->cid[1], m->cid[2], m->cid[3]);
	return strcmp(cid, expected) ? -1 : 0;
}

static int export_range(uint hw, ulong start, ulong bytes)
{
	struct blk_desc *d;
	u8 *buf;
	int ret = -1;

	if (bytes > MAX_EXPORT || range(hw, start, bytes, &d))
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, DIV_ROUND_UP(bytes, 512) * 512);
	if (!buf)
		return -1;
	if (blk_dread(d, start, DIV_ROUND_UP(bytes, 512), buf) == DIV_ROUND_UP(bytes, 512))
		ret = export_data(buf, bytes);
	free(buf);
	if (device(0, &d))
		ret = -1;
	return ret;
}

static int export_file(uint part, const char *path)
{
	loff_t bytes, got;
	u8 *buf;
	int ret = -1;

	if (open_part(part) || fs_size(path, &bytes) || ext4fs_io_error || bytes <= 0 || bytes > MAX_EXPORT)
		return -1;
	buf = memalign(ARCH_DMA_MINALIGN, MAX_EXPORT);
	if (!buf)
		return -1;
	if (!open_part(part) && !fs_read(path, (ulong)buf, 0, bytes, &got) && !ext4fs_io_error && got == bytes)
		ret = export_data(buf, bytes);
	free(buf);
	fs_close();
	return ret;
}

static int locate(uint explicit_part)
{
	struct blk_desc *d;
	struct disk_partition p;
	uint i, found = 0;
	bool exists;

	if (device(0, &d))
		return -1;
	part_init(d);
	for (i = 1; i <= 4; i++) {
		if (explicit_part && explicit_part != i)
			continue;
		if (part_get_info(d, i, &p))
			continue; /* absent MBR entry */
		if (open_part(i))
			return -1;
		exists = fs_exists("/extlinux/extlinux.conf");
		if (ext4fs_io_error)
			return -1;
		if (!exists)
			continue;
		if (found) {
			puts("uuf: multiple extlinux partitions; choose --kernel-part\n");
			return -1;
		}
		found = i;
	}
	if (!found)
		return -1;
	return env_set_hex("fastboot.uuf-kernel-part", found);
}

static int firmware(uint hw, ulong start, ulong bytes, const char *expected)
{
	struct blk_desc *d;
	u8 digest[32], sector_digest[32], actual_digest[32], *buf;
	ulong offset, n, sectors;
	int ret = -1;

	/* A firmware command cannot modify user area or ROM's leading 1 KiB. */
	if (hw != 1 || start != 2 || bytes > 0xffc00 || !bytes ||
	    env_get_hex("filesize", 0) != bytes || bytes > fastboot_buf_size ||
	    range(hw, start, bytes, &d))
		return -1;
	sha256_csum_wd((void *)fastboot_buf_addr, bytes, digest, WINDOW);
	if (!matches(digest, expected) || hash_range(hw, start, bytes, digest))
		return -1;
	if (matches(digest, expected)) {
		puts("uuf: firmware identical; no write/erase\n");
		return env_set("fastboot.uuf-fw-result", "skipped");
	}
	buf = memalign(ARCH_DMA_MINALIGN, WINDOW);
	if (!buf || device(hw, &d)) {
		free(buf);
		return -1;
	}
	for (offset = 0; offset < bytes; offset += n) {
		n = min(bytes - offset, (ulong)WINDOW);
		sectors = DIV_ROUND_UP(n, 512);
		/* Preserve the unused bytes in the last sector. */
		if (n % 512 && blk_dread(d, start + offset / 512, sectors, buf) != sectors)
			goto out;
		memcpy(buf, (void *)(fastboot_buf_addr + offset), n);
		sha256_csum_wd(buf, sectors * 512, sector_digest, WINDOW);
		if (blk_dwrite(d, start + offset / 512, sectors, buf) != sectors ||
		    hash_range(hw, start + offset / 512, sectors * 512, actual_digest) ||
		    memcmp(sector_digest, actual_digest, 32) || device(hw, &d))
			goto out;
		schedule();
	}
	if (hash_range(hw, start, bytes, digest) || !matches(digest, expected))
		goto out;
	ret = env_set("fastboot.uuf-fw-result", "written");
out:
	free(buf);
	if (device(0, &d))
		ret = -1;
	return ret;
}

static int file_target(uint part, const char *path)
{
	int ret;

	if (open_part(part))
		return -1;
	ret = ext4fs_file_writable(path);
	fs_close();
	return ret;
}

static int file_write(uint part, const char *path, ulong bytes, const char *expected)
{
	u8 digest[32];
	loff_t got;
	int ret;

	if (bytes != env_get_hex("filesize", 0) || !bytes || bytes > fastboot_buf_size)
		return -1;
	sha256_csum_wd((void *)fastboot_buf_addr, bytes, digest, WINDOW);
	if (!matches(digest, expected) || file_target(part, path) || open_part(part))
		return -1;
	/* Host checks the superblock; the write driver checks again before mutation. */
	ret = fs_write(path, (ulong)fastboot_buf_addr, 0, bytes, &got);
	if (ret || got != (loff_t)bytes || ext4fs_io_error ||
	    hash_file(part, path, bytes, digest) || !matches(digest, expected))
		return -1;
	return 0;
}

static int bootconf(ulong ack, ulong part)
{
	struct blk_desc *d;
	struct mmc *m;
	ALLOC_CACHE_ALIGN_BUFFER(u8, csd, 512);
	u8 expected = (ack << 6) | (part << 3);

	if (ack > 1 || part != 1 || device(0, &d))
		return -1;
	m = find_mmc_device(1);
	if (mmc_send_ext_csd(m, csd))
		return -1;
	if ((csd[EXT_CSD_PART_CONF] & 0xf8) != expected &&
	    mmc_set_part_conf(m, ack, part, 0))
		return -1;
	if (mmc_send_ext_csd(m, csd) || csd[EXT_CSD_PART_CONF] != expected)
		return -1;
	return 0;
}

static int erase(uint hw, ulong start, ulong bytes)
{
	struct blk_desc *d;
	struct mmc *m;
	ulong n, offset, sectors;
	u8 *buf, value;
	ALLOC_CACHE_ALIGN_BUFFER(u8, csd, 512);
	int ret = -1;

	if (bytes % 512 || range(hw, start, bytes, &d))
		return -1;
	m = find_mmc_device(1);
	sectors = bytes / 512;
	if (!m->erase_grp_size || start % m->erase_grp_size || sectors % m->erase_grp_size) {
		puts("uuf: erase range is not erase-group aligned; refusing expansion\n");
		return -1;
	}
	if (mmc_send_ext_csd(m, csd))
		return -1;
	value = csd[181] & 1 ? 0xff : 0;
	buf = memalign(ARCH_DMA_MINALIGN, WINDOW);
	if (!buf)
		return -1;
	if (blk_derase(d, start, sectors) != sectors)
		goto out;
	for (offset = 0; offset < bytes; offset += n) {
		n = min(bytes - offset, (ulong)WINDOW);
		if (blk_dread(d, start + offset / 512, n / 512, buf) != n / 512)
			goto out;
		while (n && buf[n - 1] == value)
			n--;
		if (n)
			goto out;
		n = min(bytes - offset, (ulong)WINDOW);
		schedule();
	}
	ret = 0;
out:
	free(buf);
	if (device(0, &d))
		ret = -1;
	return ret;
}

static int do_uuf(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	ulong v[4];
	u8 digest[32];
	struct saved *s;
	int ret = -1, i;

	if (argc < 2)
		return CMD_RET_USAGE;
	if (!strcmp(argv[1], "info") && argc == 2) {
		ret = info();
	} else if (!strcmp(argv[1], "matchcid") && argc == 3) {
		ret = match_cid(argv[2]);
	} else if (!strcmp(argv[1], "locate") && argc == 3) {
		if (number(argv[2], v))
			return CMD_RET_USAGE;
		ret = locate(v[0]);
	} else if (!strcmp(argv[1], "writable") && argc == 4) {
		if (number(argv[2], v))
			return CMD_RET_USAGE;
		ret = file_target(v[0], argv[3]);
	} else if (!strcmp(argv[1], "exportfile") && argc == 4) {
		if (number(argv[2], v))
			return CMD_RET_USAGE;
		ret = export_file(v[0], argv[3]);
	} else if (!strcmp(argv[1], "export") && argc == 5) {
		for (i = 0; i < 3; i++)
			if (number(argv[2 + i], &v[i]))
				return CMD_RET_USAGE;
		ret = export_range(v[0], v[1], v[2]);
	} else if ((!strcmp(argv[1], "verify") || !strcmp(argv[1], "fw")) && argc == 6) {
		for (i = 0; i < 3; i++)
			if (number(argv[2 + i], &v[i]))
				return CMD_RET_USAGE;
		if (!strcmp(argv[1], "fw"))
			ret = firmware(v[0], v[1], v[2], argv[5]);
		else if (!hash_range(v[0], v[1], v[2], digest))
			ret = matches(digest, argv[5]) ? 0 : -1;
	} else if ((!strcmp(argv[1], "file") || !strcmp(argv[1], "writefile")) && argc == 6) {
		if (number(argv[2], v) || number(argv[4], &v[1]))
			return CMD_RET_USAGE;
		if (!strcmp(argv[1], "writefile"))
			ret = file_write(v[0], argv[3], v[1], argv[5]);
		else if (!hash_file(v[0], argv[3], v[1], digest))
			ret = matches(digest, argv[5]) ? 0 : -1;
	} else if (!strcmp(argv[1], "bootconf") && argc == 4) {
		if (number(argv[2], v) || number(argv[3], &v[1]))
			return CMD_RET_USAGE;
		ret = bootconf(v[0], v[1]);
	} else if (!strcmp(argv[1], "erase") && argc == 5) {
		for (i = 0; i < 3; i++)
			if (number(argv[2 + i], &v[i]))
				return CMD_RET_USAGE;
		ret = erase(v[0], v[1], v[2]);
	} else if ((!strcmp(argv[1], "save") && argc == 6) ||
		   (!strcmp(argv[1], "filesave") && argc == 5) ||
		   (!strcmp(argv[1], "keep") && argc == 3)) {
		if (number(argv[2], v) || v[0] >= MAX_SLOTS)
			return CMD_RET_USAGE;
		s = &saved[v[0]];
		if (!strcmp(argv[1], "keep")) {
			if (s->valid && !(s->path[0] ? hash_file(s->part, s->path, 0, digest) :
			    hash_range(s->hw, s->start, s->bytes, digest)))
				ret = memcmp(s->digest, digest, 32) ? -1 : 0;
		} else {
			memset(s, 0, sizeof(*s));
			if (!strcmp(argv[1], "filesave")) {
				if (number(argv[3], &v[1]) || strlen(argv[4]) >= MAX_PATH)
					return CMD_RET_USAGE;
				s->part = v[1];
				strcpy(s->path, argv[4]);
				ret = hash_file(s->part, s->path, 0, s->digest);
			} else {
				for (i = 0; i < 3; i++)
					if (number(argv[3 + i], &v[i]))
						return CMD_RET_USAGE;
				s->hw = v[0]; s->start = v[1]; s->bytes = v[2];
				ret = hash_range(s->hw, s->start, s->bytes, s->digest);
			}
			s->valid = !ret;
		}
	}
	if (ret) {
		printf("uuf: %s failed; stop operation\n", argv[1]);
		return CMD_RET_FAILURE;
	}
	return CMD_RET_SUCCESS;
}

U_BOOT_CMD(uuf, 6, 0, do_uuf, "uuf checked I/O (hex numbers)",
	"info | locate part(0=discover) | export hw start bytes\n"
	"uuf matchcid cid\n"
	"uuf exportfile part path | verify hw start bytes sha256\n"
	"uuf fw hw start bytes sha256 | file part path bytes sha256\n"
	"uuf writefile part path bytes sha256 | writable part path\n"
	"uuf bootconf ack partition\n"
	"uuf erase hw start bytes | save slot hw start bytes\n"
	"uuf filesave slot part path | keep slot");
