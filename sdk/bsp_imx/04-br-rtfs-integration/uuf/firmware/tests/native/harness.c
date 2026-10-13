#include "uuf_host.h"
#include <ext4fs.h>
#include <ext_common.h>
#undef malloc
#undef calloc
#undef free
struct allocation { void *p; size_t n; };
static struct allocation allocations[4096];
static size_t used, peak;
static FILE *media;
static int fail_read, fail_write, writes, reads, stop_writes;
static int fail_alloc_once;
static const char *fault_mode;
void *uuf_memalign(size_t align, size_t n) {
    void *p;
    if(fail_alloc_once) { fail_alloc_once=0; return NULL; }
    if (used + n > 16 * 1024 * 1024 || posix_memalign(&p,align,n?n:1)) return NULL;
    for (int i=0;i<4096;i++) if(!allocations[i].p) {allocations[i]=(struct allocation){p,n};used+=n;if(used>peak)peak=used;return p;}
    abort();
}
void *uuf_malloc(size_t n) { return uuf_memalign(64,n); }
void *uuf_calloc(size_t a,size_t b) { void *p=uuf_malloc(a*b);if(p)memset(p,0,a*b);return p; }
void uuf_free(void *p) { if(!p)return;for(int i=0;i<4096;i++)if(allocations[i].p==p){used-=allocations[i].n;allocations[i].p=NULL;free(p);return;} free(p); }
ulong blk_dread(struct blk_desc*d,lbaint_t start,lbaint_t count,void*buf) {
    reads++; if(fail_read&&reads==fail_read)return count-1;
    if(start>d->lba||count>d->lba-start||fseeko(media,start*512,SEEK_SET))return 0;
    return fread(buf,512,count,media);
}
ulong blk_dwrite(struct blk_desc*d,lbaint_t start,lbaint_t count,const void*buf) {
    writes++; if(stop_writes) { fprintf(stderr,"WRITE AFTER FAILURE\n");abort(); }
    if(fail_write&&writes==fail_write){stop_writes=1;return count-1;}
    if(start>d->lba||count>d->lba-start||fseeko(media,start*512,SEEK_SET))return 0;
    ulong result=fwrite(buf,512,count,media);fflush(media);return result;
}
void uuf_native_deinit_begin(void) {
    if(!strcmp(fault_mode,"deinit-alloc")) fail_alloc_once=1;
    if(!strcmp(fault_mode,"deinit-inode-read")) fail_read=reads+1;
    if(!strcmp(fault_mode,"deinit-write")) fail_write=writes+1;
}
void uuf_native_jsb_read_begin(void) {
    if(!strcmp(fault_mode,"deinit-jsb-read")) {
        puts("fault=journal-superblock-data-read");
        fail_read=reads+1;
    }
}
static int recover_flag(void) {
    struct ext2_sblock sb;
    if(fseeko(media,1024,SEEK_SET)||fread(&sb,1,sizeof(sb),media)!=sizeof(sb)) return -1;
    return !!(le32_to_cpu(sb.feature_incompat)&0x0004);
}
void rtc_to_tm(unsigned long n,struct rtc_time*t) { memset(t,0,sizeof(*t)); }
uint16_t crc16(uint16_t crc,const u8*p,size_t n) { while(n--){crc^=*p++;for(int i=0;i<8;i++)crc=(crc>>1)^((crc&1)?0xa001:0);}return crc; }
int main(int argc,char**argv) {
    if(argc!=5)return 2;
    media=fopen(argv[1],"r+b");if(!media)return 2;
    fseeko(media,0,SEEK_END);size_t total=ftello(media);
    struct blk_desc desc={total/512,512,9};struct disk_partition part={0,total/512,512};
    FILE*source=fopen(argv[3],"rb");if(!source)return 2;
    fseeko(source,0,SEEK_END);size_t n=ftello(source);rewind(source);
    void *data=malloc(n);if(!data||fread(data,1,n,source)!=n)return 2;fclose(source);
    fault_mode=argv[4];
    if(!strcmp(fault_mode,"fs-devread-short")) {
        char buf[16]; fail_read=reads+1;
        int result=fs_devread(&desc,&part,0,0,sizeof(buf),buf);
        printf("fs_devread=%d reads=%d\n",result,reads);
        free(data);fclose(media);
        return result != 0 || reads != 1;
    }
    if(ext4fs_probe(&desc,&part))return 3;
    if(!strncmp(fault_mode,"short-write",11))fail_write=fault_mode[11]?atoi(fault_mode+12):1;
    if(!strncmp(fault_mode,"short-read",10))fail_read=reads+(fault_mode[10]?atoi(fault_mode+11):1);
    if (!strncmp(fault_mode, "writable-", 9)) {
        int result=ext4fs_file_writable(argv[2]);
        printf("writable=%d writes=%d io_error=%d\n",result,writes,ext4fs_io_error);
        free(data);fclose(media);
        return writes || (!strcmp(fault_mode,"writable-success") ? result != 0 : result == 0);
    }
    loff_t written=0;int result=ext4_write_file(argv[2],data,0,n,&written);
    int recover=recover_flag();
    printf("result=%d written=%lld peak_heap=%zu writes=%d reads=%d io_error=%d recover=%d\n",result,(long long)written,peak,writes,reads,ext4fs_io_error,recover);
    free(data);fclose(media);
    if(!strcmp(fault_mode,"success")) return result||written!=n||recover!=0;
    if(!strncmp(fault_mode,"deinit-",7)) return !result||written!=0||ext4fs_io_error==0||recover!=1;
    return !result||written!=0;
}
