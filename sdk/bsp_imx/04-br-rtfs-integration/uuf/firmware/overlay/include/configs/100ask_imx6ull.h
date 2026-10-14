/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __100ASK_IMX6ULL_CONFIG_H
#define __100ASK_IMX6ULL_CONFIG_H

#include "mx6_common.h"

#define PHYS_SDRAM		MMDC0_ARB_BASE_ADDR
#define PHYS_SDRAM_SIZE		SZ_512M
#define CFG_SYS_SDRAM_BASE	PHYS_SDRAM
#define CFG_SYS_INIT_RAM_ADDR	IRAM_BASE_ADDR
#define CFG_SYS_INIT_RAM_SIZE	IRAM_SIZE
#define CFG_MXC_UART_BASE	UART1_BASE
#define CFG_SYS_BAUDRATE_TABLE	{ 115200, 1500000 }
#define CFG_SYS_FSL_ESDHC_ADDR	USDHC2_BASE_ADDR
#define CFG_SYS_FSL_USDHC_NUM	1

/* Partition discovery keeps extlinux independent of host filenames. */
#define CFG_EXTRA_ENV_SETTINGS \
	"console=ttymxc0\0" \
	"mmcdev=1\0" \
	"kernel_addr_r=0x80800000\0" \
	"fdt_addr_r=0x88000000\0" \
	"pxefile_addr_r=0x8a000000\0" \
	"uuf_scan=part list mmc 1 -bootable uuf_parts; " \
		"for uuf_part in ${uuf_parts}; do " \
		"if test -e mmc 1:${uuf_part} /extlinux/extlinux.conf; then " \
		"sysboot mmc 1:${uuf_part} ext2 ${pxefile_addr_r} /extlinux/extlinux.conf; " \
		"fi; done\0"

#endif
