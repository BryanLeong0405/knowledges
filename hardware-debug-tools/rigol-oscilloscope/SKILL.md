---
name: rigol-oscilloscope
description: RIGOL MSO5072 示波器的网络（SCPI/TCP）调用与测量技能。用于经 5555 端口远程读取测量值/波形、FREQ/占空比/延迟测量、与逻辑分析仪交叉验证。当任务提到 RIGOL、MSO5072、示波器、SCPI、*IDN?、:WAV:DATA?、scope_read.py 时使用。
---

# RIGOL MSO5072 示波器网络调用

用于 RIGOL MSO5072 示波器网络调用（本技能目录）这套知识。

## 先确认设备

- 型号：RIGOL MSO5072（2ch、70MHz、8GSa/s）；IP 按现场设备实际配置（`*IDN?` 与网络设置可查），网关为所在子网网关。
- `*IDN?` → `RIGOL TECHNOLOGIES,MSO5072,<序列号>,00.01.03.03.00`（序列号以设备实际返回为准）。
- 使用前先确认示波器空闲（5555 可连、`*IDN?` 有响应），避免打扰在忙的测量。

## 连接方式（按优先级）

| 方式 | 端口 | 状态 |
|---|---|---|
| **SCPI over TCP（raw socket）** | **5555** | ✅ 主用，纯文本 SCPI，socket 直连 |
| VXI-11 | 111 | 备选（需 vxi11/pyvisa） |
| Web 管理页 | 80 | 备选（查信息/升级固件） |
| USBTMC | — | ❌ WSL 无 usbtmc 模块 |

脚本载体：`scope_read.py`（Scope 类 cmd/ask/read_wave）、`scope_meas.py`（快速测量）、`scope_delay4.py`（延迟测量：0.5V/div + 阈值 `(min+max)/2` + 边沿配对）。

## 三条铁律（实测踩坑）

1. **`:WAV:MODE` 必须 `NORM`**——RAW 返回约 1 亿点，socket 读到超时。
2. **BYTE 字节值是电压映射，不是逻辑电平**——判高低用自适应阈值 `(min+max)/2`。
3. **用完 `s.close()`**——残留连接会占住示波器网口（曾清理 6 条 FIN-WAIT-2）。

标准序列：`*IDN?` → `:WAV:SOUR`/`:WAV:MODE NORM`/`:WAV:FORM BYTE`/`:WAV:POIN 1200` → `:WAV:DATA?` 解析 `#N<len>` 头。

## 实测踩坑补充

- **时基必须匹配信号频率**：1μs/div 时 8kHz 信号（周期 ~15.7μs）放不下，`FREQ` 返回 `9.9e37`；改 20–50μs/div。
- **`:MEAS:ITEM? DUTY,CHAN1` 返回空**（DUTY 项不可用）——用波形数据 + 阈值 `(min+max)/2` 计算占空比。
- **僵尸会话卡死 SCPI**：5555 可连但 `*IDN?` 无响应、VNC/Web 正常 → 设备侧服务卡死，重启示波器恢复。
- VNC(5900) 半响应（版本握手成功但安全协商超时），不可靠。

## 交叉验证

与逻辑分析仪同接信号脚（共地）：示波器读频率/占空比/波形与 CLI 统计对比；**占空比是比例测量、不受两设备时钟差影响，最可靠**（实测 14.00% vs 14.01%）。

## 安全

- 只读命令（`*IDN?`、`:WAV:DATA?`、`:MEAS:ITEM?`、`:TRIG:STAT?`）优先；写命令（`:WAV:...` 配置）确认无碍后再发。
- 不并发占用：一个脚本用完关闭连接再让给下一个。
