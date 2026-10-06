- codebase : 内核态，用户空间的源码树外开发工作区
- profile  : 放环境脚本与辅助函数
- notes    : 开发笔记
- sdk      : 多target/vendor 的sdk
  - `bsp*` ： 将上游sdk适配板卡的工作区
  - `vendor*` 上游SDK工具



## 构建规则：

sdk级别的耗时构建，先对齐需求目标，把命令流/脚本 交付给开发者，让开发者把关执行。