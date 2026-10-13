#ifndef UUF_BOARD_MOCK
#define UUF_BOARD_MOCK
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <openssl/sha.h>
typedef uint8_t u8;typedef uint32_t u32;typedef unsigned int uint;typedef unsigned long ulong;
#define ARCH_DMA_MINALIGN 64
#define ALLOC_CACHE_ALIGN_BUFFER(t,n,l) t n[l] __attribute__((aligned(64)))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
#define min(a,b) ((a)<(b)?(a):(b))
#define SHA256_SUM_LEN 32
#define EXT_CSD_PART_CONF 179
#define IS_SD(m) ((m)->sd)
#define FS_TYPE_EXT 2
#define le16_to_cpu(x) (x)
#define FILETYPE_INO_MASK 0170000
#define FILETYPE_INO_REG 0100000
struct mock_ext_node {struct {unsigned short nlinks,mode;unsigned int acl;} inode;};
static struct mock_ext_node mock_file={{1,0100644,0}};
static bool file_enabled;
static int ext4fs_file_writable(const char*p){return file_enabled && mock_file.inode.nlinks==1 && !mock_file.inode.acl ? 0 : -1;}
#define CMD_RET_USAGE -1
#define CMD_RET_FAILURE 1
#define CMD_RET_SUCCESS 0
#define U_BOOT_CMD(...)
struct cmd_tbl {int dummy;};
struct blk_desc {ulong lba;uint blksz,hwpart;};
struct disk_partition {ulong start,size;};
struct mmc {int sd;uint cid[4],erase_grp_size;uint64_t capacity_user,capacity_boot;};
static struct mmc mock_mmc={0,{1,2,3,4},2048,2*1024*1024,4*1024*1024};
static struct blk_desc mock_desc;
static u8 user[2*1024*1024],boot[4*1024*1024],payload[16384];
static void *fastboot_buf_addr=payload;
static u32 fastboot_buf_size=16*1024*1024;
static ulong filesize;
static int reads,writes,erases,bad_read,bad_write,ext4fs_io_error;
static u8 partconf;
static char fw_result[16];
typedef SHA256_CTX sha256_context;
static void sha256_starts(sha256_context*c){SHA256_Init(c);}
static void sha256_update(sha256_context*c,const u8*p,uint n){SHA256_Update(c,p,n);}
static void sha256_finish(sha256_context*c,u8*p){SHA256_Final(p,c);}
static void sha256_csum_wd(const void*p,uint n,u8*out,uint chunk){SHA256(p,n,out);}
static int strict_strtoul(const char*s,int base,ulong*out){char*end;*out=strtoul(s,&end,base);return !*s||*end;}
static void *memalign(size_t a,size_t n){void*p=NULL;return posix_memalign(&p,a,n)?NULL:p;}
static void schedule(void){}
static int env_set_hex(const char*n,ulong v){return 0;}
static int env_set(const char*n,const char*v){if(!strcmp(n,"fastboot.uuf-fw-result"))snprintf(fw_result,sizeof(fw_result),"%s",v);return 0;}
static ulong env_get_hex(const char*n,ulong fallback){return !strcmp(n,"filesize")?filesize:fallback;}
static struct mmc *find_mmc_device(uint n){return n==1?&mock_mmc:NULL;}
static int mmc_init(struct mmc*m){return 0;}
static int blk_get_device_by_str(const char*i,const char*n,struct blk_desc**out){
    mock_desc=(struct blk_desc){n[2]=='1'?sizeof(boot)/512:sizeof(user)/512,512,(uint)(n[2]-'0')};
    partconf=(partconf&0xf8)|mock_desc.hwpart;*out=&mock_desc;return 1;
}
static ulong blk_dread(struct blk_desc*d,ulong start,ulong n,void*out){reads++;if(bad_read)return n-1;memcpy(out,(d->hwpart?boot:user)+start*512,n*512);return n;}
static ulong blk_dwrite(struct blk_desc*d,ulong start,ulong n,const void*in){writes++;if(bad_write)return n-1;memcpy((d->hwpart?boot:user)+start*512,in,n*512);return n;}
static ulong blk_derase(struct blk_desc*d,ulong start,ulong n){erases++;memset((d->hwpart?boot:user)+start*512,0xff,n*512);return n;}
static int mmc_send_ext_csd(struct mmc*m,u8*p){memset(p,0,512);p[179]=partconf;p[181]=1;return 0;}
static int mmc_set_part_conf(struct mmc*m,u8 ack,u8 part,u8 access){partconf=ack<<6|part<<3|access;return 0;}
static void part_init(struct blk_desc*d){}
static int part_get_info(struct blk_desc*d,uint p,struct disk_partition*out){return -1;}
static int fs_set_blk_dev(const char*i,const char*d,int type){return file_enabled?0:-1;}
static int fs_size(const char*n,loff_t*p){return -1;}
static int fs_read(const char*n,ulong p,loff_t o,loff_t l,loff_t*got){return -1;}
static int fs_write(const char*n,ulong p,loff_t o,loff_t l,loff_t*got){return -1;}
static int fs_exists(const char*n){return 0;}
static void fs_close(void){}
#endif
