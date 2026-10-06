// SPDX-License-Identifier: GPL-2.0+

#include <init.h>
#include <asm/arch/clock.h>
#include <asm/arch/crm_regs.h>
#include <asm/arch/sys_proto.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <config.h>
#include <linux/errno.h>

DECLARE_GLOBAL_DATA_PTR;

int board_early_init_f(void)
{
	struct mxc_ccm_reg *ccm = (struct mxc_ccm_reg *)CCM_BASE_ADDR;

	/* ROM SDP enables PLL3. Select PLL3 / 6, then UART_PODF / 1. */
	clrbits_le32(&ccm->cscdr1, MXC_CCM_CSCDR1_UART_CLK_SEL |
		     MXC_CCM_CSCDR1_UART_CLK_PODF_MASK);
	if (imx_get_uartclk() != 80000000)
		return -EINVAL;

	return 0;
}

int dram_init(void)
{
	gd->ram_size = imx_ddr_size();
	return 0;
}

int board_init(void)
{
	gd->bd->bi_boot_params = PHYS_SDRAM + 0x100;
	return 0;
}

int checkboard(void)
{
	puts("Board: 100ask i.MX6ULL Pro (UART1 / eMMC)\n");
	return 0;
}
