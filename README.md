# Octopus Energy Japan Integration v1.1.0

## 新增功能

### 1. Token 自动刷新机制
- 解决了 JWT token 过期问题（错误代码 KT-CT-1124）
- Token 在过期前自动刷新（50分钟）
- 智能错误检测和重试机制

### 2. 新增传感器

#### **当月累计用电量** (`current_month_consumption`)
- 显示本月从1号到现在的总用电量（kWh）
- 状态类型：`total_increasing`（随时间增加）
- 额外属性：
  - `days_so_far`：本月已过天数
  - `daily_average`：日均用电量

#### **当月累计电费** (`current_month_cost`)
- 显示本月到目前为止实际产生的电费（JPY）
- 包含阶梯电价计算、燃料调整费和基本费用
- 状态类型：`total_increasing`（随时间增加）
- 额外属性：
  - `total_kwh`：本月总用电量
  - `usage_cost`：用电费用（含燃料调整）
  - `standing_cost`：基本费用
  - `days_so_far`：本月已过天数

### 3. 改进的本月预计电费计算

#### **本月预计电费** (`monthly_estimate`) - 更新
- 新计算方式：**日平均电费 × 当月总天数**
- 基于实际使用模式预测整月费用
- 更准确的预测算法
- 额外属性：
  - `total_kwh_so_far`：本月已用电量
  - `daily_avg_kwh`：日均用电量
  - `estimated_month_kwh`：预计整月用电量
  - `estimated_usage_cost`：预计用电费用
  - `standing_cost`：整月基本费用
  - `days_so_far`：本月已过天数
  - `days_in_month`：当月总天数

## 传感器列表

| 传感器 | 描述 | 单位 | 状态类型 |
|--------|------|------|----------|
| `today_consumption` | 今日用电量 | kWh | total_increasing |
| `yesterday_consumption` | 昨日用电量 | kWh | total |
| **`current_month_consumption`** | **当月累计用电** | **kWh** | **total_increasing** |
| **`current_month_cost`** | **当月累计电费** | **JPY** | **total_increasing** |
| `last_month_consumption` | 上月用电量 | kWh | total |
| `monthly_estimate` | 本月预计电费 | JPY | total |
| `balance` | 账户余额 | JPY | - |
| `overdue_balance` | 逾期余额 | JPY | - |
| `last_bill` | 上月账单 | JPY | - |
| `product` | 电价套餐 | - | - |

## 安装方法

1. 停止 Home Assistant
2. 删除旧的 `custom_components/octopus_energy_jp` 文件夹
3. 将新的 `custom_components` 文件夹复制到 Home Assistant 配置目录
4. 重启 Home Assistant

## 能源仪表盘配置建议

### 实时监控卡片
```yaml
type: entities
title: 电力实时监控
entities:
  - entity: sensor.octopus_today_consumption_[账号]
    name: 今日用电
  - entity: sensor.octopus_current_month_consumption_[账号]
    name: 本月累计
  - entity: sensor.octopus_current_month_cost_[账号]
    name: 本月电费
```

### 预测分析卡片
```yaml
type: entities
title: 电费预测
entities:
  - entity: sensor.octopus_current_month_cost_[账号]
    name: 已产生费用
  - entity: sensor.octopus_monthly_estimate_[账号]
    name: 预计月度总费
```

### 统计图表
```yaml
type: statistics-graph
title: 用电趋势
entities:
  - sensor.octopus_current_month_consumption_[账号]
stat_types:
  - mean
  - max
  - min
```

## 更新日志

### v1.1.0 (2025-11-09)
- ✅ 修复 JWT token 过期问题
- ✅ 新增当月累计用电量传感器
- ✅ 新增当月累计电费传感器  
- ✅ 改进本月预计电费算法（基于日均）
- ✅ 优化错误处理和日志记录

### v1.0.1 (之前版本)
- 基础功能实现
- 今日/昨日/上月用电量
- 账户余额和账单查询

## 调试

如需查看详细日志，在 `configuration.yaml` 中添加：
```yaml
logger:
  default: info
  logs:
    custom_components.octopus_energy_jp: debug
```

## 注意事项

- 数据每30分钟更新一次
- 首次启动可能需要等待几分钟获取历史数据
- 所有时间基于日本东京时区（Asia/Tokyo）