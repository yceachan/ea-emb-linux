#include "board_mock.h"
#include UUF_BOARD_SOURCE
#include <assert.h>
int main(void){
    u8 digest[32];char expected[65];
    memset(user,0x73,sizeof(user));memset(boot,0x5a,sizeof(boot));
    struct cmd_tbl cmd={0};
    char *match_args[]={"uuf","matchcid","00000001000000020000000300000004"};
    char *mismatch_args[]={"uuf","matchcid","00000001000000020000000300000005"};
    char *invalid_args[]={"uuf","matchcid","1234"};
    int writes_before=writes;
    assert(do_uuf(&cmd,0,3,match_args)==CMD_RET_SUCCESS);
    assert(do_uuf(&cmd,0,3,mismatch_args)==CMD_RET_FAILURE);
    assert(do_uuf(&cmd,0,3,invalid_args)==CMD_RET_FAILURE);
    assert(writes==writes_before);
    filesize=4097;for(uint i=0;i<filesize;i++)payload[i]=i%251;
    SHA256(payload,filesize,digest);hex(digest,32,expected);
    assert(!firmware(1,2,filesize,expected));assert(writes==1&&erases==0&&!strcmp(fw_result,"written"));
    assert(!memcmp(boot+1024,payload,filesize));
    for(uint i=0;i<1024;i++)assert(boot[i]==0x5a);
    for(uint i=1024+filesize;i<sizeof(boot);i++)assert(boot[i]==0x5a);
    for(uint i=0;i<sizeof(user);i++)assert(user[i]==0x73);
    assert(!firmware(1,2,filesize,expected));assert(writes==1&&erases==0&&!strcmp(fw_result,"skipped"));
    assert(firmware(0,2,filesize,expected));assert(firmware(1,0,filesize,expected));
    bad_read=1;assert(firmware(1,2,filesize,expected));bad_read=0;assert(writes==1);
    payload[0]^=1;SHA256(payload,filesize,digest);hex(digest,32,expected);
    bad_write=1;assert(firmware(1,2,filesize,expected));bad_write=0;assert(writes==2);
    assert(erase(1,2,0xffc00));assert(erases==0);
    assert(!erase(1,0,1024*1024));assert(erases==1);
    for(uint i=0;i<1024*1024;i++)assert(boot[i]==0xff);
    for(uint i=1024*1024;i<sizeof(boot);i++)assert(boot[i]==0x5a);
    assert(!bootconf(1,1));assert(partconf==0x48);
    writes=0;assert(!bootconf(1,1));assert(writes==0);
    file_enabled=true;assert(!file_target(1,"/kernel"));
    mock_file.inode.nlinks=2;assert(file_target(1,"/kernel"));
    mock_file.inode.nlinks=1;mock_file.inode.acl=7;assert(file_target(1,"/kernel"));
    puts("board CID match/reject, firmware hash gate, exact range/tail, I/O errors, erase alignment and boot config passed");
    return 0;
}
