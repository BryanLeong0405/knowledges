---
name: dslogic-logic-analyzer
description: DSLogic PLus 逻辑分析仪的 CLI 采样、解析与交叉验证技能。用于 dslogic-capture.sh 一键采样、.dsl 文件解析（位压缩）、退出码约定、与示波器交叉验证。当任务提到 DSLogic、逻辑分析仪、dslogic-capture.sh、.dsl、libsigrok4DSL、validate_dsl.py、usbipd 时使用。
---

# DSLogic PLus 逻辑分析仪 CLI

用于 DSLogic PLus 逻辑分析仪 CLI（本技能目录）这套知识。完整主文档（13 章调用说明与技术细节）随 CLI 交付包提供，不随本技能分发。

## 先确认环境

- 设备：DSLogic PLus（USB `2a0e:0030`），固件 2.2；WSL Ubuntu-24.04，WSL 普通用户（plugdev 组，无 sudo）。
- 设备节点：`/dev/bus/usb/001/055`（666/plugdev），需 `usbipd` 附加 + udev 规则；`--list` 应输出 `Demo Device` + `DSLogic PLus`。
- 一键脚本：`dslogic-capture.sh`（DSView 工具链）；产物在捕获目录（`--output` 可自定义）。

## 采样与触发

- 参数表 24 个；触发模式 `immediate`（默认）/ `edge` / `level` / `serial`（如 Start D0↑ / Clock D1↑ / Data D0=1）。
- 基准样本数（用于判断异常）：100ms@1MHz=**100,352**；10ms@100MHz=**1,000,448**；10s@1MHz=**10,000,384**。
- edge/level 报 `capture ended without usable logic data` = 窗口内无匹配信号，先 `immediate` 探测确认通道。

## 退出码约定（负向行为）

| 场景 | 退出码 |
|---|---|
| 串行无匹配 / 拒绝覆盖（无 `--overwrite`） | **3**（`pattern not found` / `refusing to overwrite`） |
| Ctrl+C 中断 | **130**（SIGINT） |

- 失败时**零文件残留**（无 `.dsl`/manifest/`.partial`）。
- 验证退出码不要走管道（`| tail` 会掩盖 `$?`）；用脚本文件方式规避 wsl.exe 参数转义。

## `.dsl` 格式（关键坑）

- ZIP 容器，关键点 `type=10000`；**逻辑数据位压缩：每字节 8 个样本，`bit0=D0`**——分析前必须按位解包，否则频率差 8 倍（实测曾算 63.7kHz 实为 8.04kHz）。

```python
import numpy as np
samples = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder='little')
ch0 = samples[::8]  # 其他通道依此类推
```

- 校验：`validate_dsl.py`（ZIP CRC/header/decoders/session/逻辑数据）+ SHA-256 与 manifest 比对。

## 交叉验证（与示波器）

CH0 与示波器 CH1 并接同一信号脚（**共地**）后对比：频率偏差 ~0.9%（在信号抖动内）、**占空比偏差 0.01%**（比例测量最可靠）。注意：共地、探头并联负载会拉缓边沿、两设备独立触发不能对齐绝对时间。

## 故障排查

- `LIBUSB_ERROR_ACCESS`：udev 规则缺失/不在 plugdev 组。
- 设备忙：先确认无其他进程占用。
- 边界：WSL-only、单设备、无解码器；采样数据路径 = DSLogic 硬件 + `libsigrok4DSL`，与 DSView GUI 同源。
