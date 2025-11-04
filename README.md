# Home Assistant - Octopus Energy Japan (Kraken)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

这是一个用于 Home Assistant 的自定义集成，用于连接到 Octopus Energy Japan 的 Kraken API。

## 功能
- 跟踪**今日**用电量 (kWh)，兼容能源仪表盘。
- 跟踪**本月预估**电费 (JPY)，基于你的阶梯电价。
- 显示**上个月**的账单总额 (JPY)。
- 显示你的账户余额和电价套餐详情。

## HACS 安装
1.  打开 HACS > 集成 > (点击右上角三个点)。
2.  选择 "自定义仓库" (Custom repositories)。
3.  在 URL 处粘贴 `https://github.com/你的用户名/ha-octopus-energy-jp`。
4.  类别选择 "集成" (Integration)。
5.  点击 "添加" (Add)。
6.  在 HACS 中找到 "Octopus Energy Japan" 并安装它。

## HA 配置
1.  重启 Home Assistant。
2.  转到 **设置** > **设备与服务** > **添加集成**。
3.  搜索 "Octopus Energy Japan"。
4.  输入你的 Octopus Energy 邮箱、密码和 API URL。