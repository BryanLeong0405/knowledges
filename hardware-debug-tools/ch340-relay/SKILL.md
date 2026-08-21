---
name: ch340-relay
description: CH340 四路继电器(LCUS 兼容模块)控制技能。用于经 USB 串口(CH340, VID 1A86:7523)控制 4 路继电器:本项目 CH1=主板供电、CH2=BOOT 键、CH3/CH4 空闲(可接 NRST 等扩展)。命令:`ch340_4relay_control.sh -p <port> --channel N --cmd on/off/toggle/query [--read-feedback]`。当任务提到 ch340_4relay、四路继电器、继电器上下电、CH1/CH2/BOOT 控制、断电重启、NRST 控制时使用。
---

# CH340 四路继电器控制(LCUS 兼容)

通过 CH340 USB 串口控制 LCUS 兼容的四路继电器模块。脚本为 `ch340_4relay_control.{sh,py}`(`.sh` 是 wrapper,实际执行同目录 `.py`),随工程提供;也可按本技能用法直接调用。

## 调用与参数

```bash
./ch340_4relay_control.sh -p /dev/ttyUSB0 --channel 1 --cmd on
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `-p` / `--port` | ✅ | 串口设备,如 `/dev/ttyUSB0` |
| `--channel` | ✅ | `1..4` |
| `--cmd` | ✅ | `on` / `off` / `toggle` / `query` / `on-feedback` / `off-feedback` |
| `--read-feedback` | ❌ | 发送命令后主动等待并解析 4 字节反馈帧 |
| `--timeout-ms` | ❌ | 反馈超时,默认 1000(合法范围 50..60000) |

**退出码**:`0`=成功;`1`=串口/反馈解析错误(帧长度、起始字节、校验和、状态字节非法);`2`=用法错误(channel 不在 1..4、cmd 非法、timeout 越界、缺参数)。

## 线协议(排障参考)

模块为 LCUS-1 兼容协议,串口固定 **9600 8N1 无流控**。

- 命令帧(4 字节):`[0xA0, channel, opcode, checksum]`,`checksum` = 前 3 字节求和 & 0xFF。
- opcode 表:0x00 `off` / 0x01 `on` / 0x02 `off-feedback` / 0x03 `on-feedback` / 0x04 `toggle` / 0x05 `query`。
- 反馈帧(4 字节):`[0xA0, channel, state, checksum]`,`state` 0x00=off、0x01=on。

**语义澄清**:`on-feedback`/`off-feedback` 是**命令内嵌反馈语义**(opcode 0x03/0x02),与独立的 `--read-feedback` 标志互不排斥;`--read-feedback` 表示"发送后主动读一帧",可与任意 `--cmd` 组合。若只发命令不读反馈,触点状态以 `query --read-feedback` 为准。

## 本项目通道定义

| 通道 | 用途 | 说明 |
|---|---|---|
| CH1 | 主板供电 | on=上电,off=断电 |
| CH2 | BOOT 键 | on=拉高(BOOT 按下,CPU 进 bootloader),off=释放 |
| CH3/CH4 | 空闲 | 可接 NRST 等扩展(connect-under-reset 方案) |

烧录前提(配合 jlink-flash 技能):CH2(BOOT)=off、CH1(供电)=on。

## 实测注意(踩过的坑)

1. **反馈帧可能错位/超时(实测复现率高)**:`--read-feedback` 偶尔报 `feedback frame must be exactly 4 bytes`,或读到上一个通道/上一条命令的**残留反馈**(帧格式与校验和均合法但状态过期,如发 `off` 却读到 `on`)——命令帧已正确发出(输出 `sent ...` 即已入串口),**以实际状态为准**,用 `query --read-feedback` 重试确认。
2. **CH1 断电不彻底(本项目实测)**:CH1 off 后 J-Link `VTref` 仍 ≈3.26V——主板有反向供电/其他电源路径,CH1 off/on **不是完整 POR**,不要依赖它做"真断电重启"(详见 jlink-flash / 调用JLink.md §9)。
3. **`query` 默认不读反馈**:不带 `--read-feedback` 只发查询帧,不返回状态。
4. **继电器重启(拔插 USB)后默认全部 off**;且 usbipd 附加可能丢失(`/dev/ttyUSB0` 消失),需在 Windows 侧重新 `usbipd attach`。
5. **串口独占**:同一时刻只允许一个进程打开该串口。
6. **旧版脚本勿用**:`tools/ch340_relay_control.sh`(LCUS-1 固定地址 0x01,仅 ON/OFF、不读反馈)已被 `ch340_4relay_control.{sh,py}` 取代;命令写法(`--CMD ON` 等)与新版不兼容,误用旧脚本只会操作 CH1。

## 与 J-Link 烧录配合

- 烧录前状态:CH2 off + CH1 on。
- 若要硬件级复位替代 `noreset`:用空闲通道(CH3/CH4)接 MCU `NRST`——NRST 低电平期间连接 SWD(connect-under-reset),释放后立即 halt;原理与条件详见 `jlink-flash` 技能(RAMCode 恢复章节)。

## 参考

- 继电器供电/BOOT 控制与 `jlink-flash` 技能交叉引用:烧录前提 CH2(BOOT)=off、CH1(供电)=on,详见该技能"安全与硬件前提"。
