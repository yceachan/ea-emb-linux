/* Compile the production command with host-only storage/FAT/SHA adapters. */
#include "guard_mock.h"
#include IMX04_SOURCE
#define EXPECT(cond) do { if (!(cond)) { fprintf(stderr, "line %d: %s\n", __LINE__, #cond); return 1; } } while (0)

static int invoke(int argc, char **argv) { return do_imx04(NULL, 0, argc, argv); }
int main(void)
{
    ulong good[] = { 2048, 262144, 264192, 4194304 };
    ulong too_big[] = { 2048, 262144, 264192, 5000000 };
    u8 digest[32];
    EXPECT(!guard("all", good));
    EXPECT(guard("all", too_big));
    mock_mmc.sd = 1;
    EXPECT(guard("all", good));
    mock_mmc.sd = 0;
    EXPECT(!guard("rootfs", good));
    wrong_table = true;
    EXPECT(guard("rootfs", good));
    wrong_table = false;
    EXPECT(!guard("kernel", good));
    char *save_args[] = { "imx04", "save", "0", "1", "0", "0" };
    EXPECT(!invoke(6, save_args));
    EXPECT(mock_desc.hwpart == 0); /* Must restore user area. */
    char *keep_args[] = { "imx04", "keep", "0" };
    EXPECT(!invoke(3, keep_args));
    pattern ^= 1;
    EXPECT(invoke(3, keep_args) == CMD_RET_FAILURE);
    pattern ^= 1;
    bad_read = true;
    EXPECT(digest_range(0, 100, 8, digest));
    bad_read = false;
    EXPECT(digest_range(0, 5000000, 8, digest)); /* Reject out-of-bounds. */
    EXPECT(!digest_range(0, 100, 8, digest));
    EXPECT(!matches(digest, "0000000000000000000000000000000000000000000000000000000000000000"));
    char *file_save[] = { "imx04", "filesave", "1", "extlinux/extlinux.conf" };
    char *file_keep[] = { "imx04", "keep", "1" };
    EXPECT(!invoke(4, file_save));
    EXPECT(!invoke(3, file_keep));
    strcpy(file_content, "wrong");
    EXPECT(invoke(3, file_keep) == CMD_RET_FAILURE);
    EXPECT(!space("zImage", 4096));
    no_space = true;
    EXPECT(space("zImage", 4096));
    no_space = false;
    EXPECT(!guard("dtb", good));
    char *boot_keep[] = { "imx04", "bootkeep" };
    EXPECT(!invoke(2, boot_keep));
    partconf = 0x50;
    EXPECT(invoke(2, boot_keep) == CMD_RET_FAILURE);
    partconf = 0x48;
    char *boot_conf[] = { "imx04", "bootconf", "48" };
    EXPECT(!invoke(3, boot_conf));
    partconf = 0;
    EXPECT(invoke(3, boot_conf) == CMD_RET_FAILURE);
    /* Firmware-only operation must accept legacy partition tables and protect
     * the full actual user capacity, not just the new product's partitions. */
    wrong_table = true;
    EXPECT(!loader_guard(4096));
    EXPECT(!loader_save(0));
    EXPECT(saved[0].hwpart == 1 && saved[0].start == 0 && saved[0].count == 2);
    EXPECT(!loader_save(1));
    EXPECT(saved[1].start == 10 && saved[1].count == 8192 - 10);
    EXPECT(!loader_save(2));
    char *user_keep[] = { "imx04", "keep", "2" };
    EXPECT(!invoke(3, user_keep));
    pattern ^= 1;
    EXPECT(invoke(3, user_keep) == CMD_RET_FAILURE);
    pattern ^= 1;
    ulong last = (loader_user_sectors - 1) / SAVE_SECTORS + 2;
    EXPECT(!loader_save(last));
    EXPECT(saved[last].start + saved[last].count == loader_user_sectors);
    EXPECT(!loader_save(1023));
    EXPECT(saved[1023].empty);
    char *empty_keep[] = { "imx04", "keep", "3ff" };
    EXPECT(!invoke(3, empty_keep));
    EXPECT(loader_guard(4097));
    EXPECT(loader_save(0)); /* failed guard must invalidate previous planning */
    EXPECT(loader_guard(0x100000));
    mock_mmc.sd = 1;
    EXPECT(loader_guard(4096));
    puts("production guard safety cases: passed (mock storage only)");
    return 0;
}
