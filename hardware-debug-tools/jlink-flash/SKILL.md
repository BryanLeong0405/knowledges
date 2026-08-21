---
name: jlink-flash
description: J-Link 烧录与调试技能(通用 + N32H787/STM32H7 实测)。用于固件烧录/读回/复位/擦除、RTT 调试(JLinkRTTLogger/Client、环形缓冲原理)、J-Link Commander 常用命令、RAMCode did not respond 恢复。当任务提到 J-Link、JLinkExe、JLinkRTTLogger、loadfile、verifybin、erase、RAMCode timeout、N32H787、STM32H7、SWD 调试、SEGGER RTT 时使用。继电器供电/BOOT 控制见 ch340-relay 技能。
---

# J-Link 烧录与调试(JLinkExe / RTT / Commander)

> 主文档:工程内《JLink烧录流程与技术细节-20260818.md》(N32H787 详细);本技能为跨芯片速查 + 实测记录。

## 0. 环境与设备名

- J-Link 软件:`/usr/bin/JLinkExe`(V8.92),WSL 侧经 `usbipd` 附加(Windows `usbipd attach --wsl --busid <BUSID>`;丢失时报 `Cannot connect to J-Link`)。
- **多 J-Link 并存**:`selectprobe` 列出全部;`usb <SN>` 选机(实测两台 J-Link 同附加时按 SN 区分,SN 以 `selectprobe`/`showemulist` 实际输出为准)。
- **设备名**:
  - N32H787:`N32H787XI_M7` / `N32H787II_M7`(必须 `_M7`;`_M4` 不能烧 bank2)
  - STM32H7:具体型号如 `STM32H743ZI`(实测);**未知用 `CORTEX-M7` 只读探测**(读 `DBGMCU IDCODE` 0x5C001000 判型号:0x450=H743/753、0x483=H723/733 等)
- **VTref=0 排查**:目标未供电 / VTref 线未接板子 3.3V / 接触不良。实测:板子 3V3 有电但 J-Link VTref=0 → 换供电路径(5V)后 VTref=4.9V 恢复。

## 1. J-Link Commander 常用命令速查(V8.92,★=本轮实测)

### 连接与探测
| 命令 | 用途 |
|---|---|
| `connect` ★ | 连接(本身不 reset) |
| `device <Name>` / `-device` | 选设备名 |
| `si SWD` / `speed 4000` | 接口/速率(不稳时降 `400`) |
| `usb <SN>` / `selectprobe` ★ | 多机选机/列表 |
| `showfwinfo` / `showhwstatus` ★ | J-Link 固件/硬件状态 |
| `vtref` ★ | 目标电压(0 = 未供电) |

### 运行控制
| 命令 | 用途 |
|---|---|
| `halt` / `go` / `ishalted` / `moe` ★ | 停/跑/状态/halt 原因 |
| `reset` / `r` ★ | 复位(N32H78x 复位后 BPU 停核,必须 `go`) |
| `resetx <ms>` / `step [n]` / `waitHalt [ms]` | 复位+延时 / 单步 / 等待 |
| `regs` ★ / `rreg` / `wreg` / `setpc` | 寄存器 |
| `vcatch <val>` | 向量 catch |

### 内存与 Flash
| 命令 | 用途 |
|---|---|
| `mem`/`mem8`/`mem16`/`mem32 <addr>, <n>` ★ | 读内存(**计数十六进制**:`mem32 0x20000030 2` 读 2 个 u32) |
| `w1`/`w2`/`w4`/`w8 <addr>, <data>` ★ | 写内存(实测推进 RTT RdOff:`w4 0x20000034 0`) |
| `loadfile <file> <addr>` ★ | 烧录 bin/hex/elf(隐式 reset & halt) |
| `loadfile <file> <addr> noreset` | 跳过隐式复位(RAMCode 恢复,见 §3) |
| `verifybin <file>, <addr>` ★ | 烧后全量校验 |
| `erase [<S>, <E>]` ★ | 擦除(实测 H7 128KB 大扇区) |
| `savebin <file>, <addr>, <n>` ★ | 读回备份(**长度十六进制**) |
| `testcspeed`/`testrspeed`/`testwspeed` | 速度测量 |

### 断点/诊断/其他
| 命令 | 用途 |
|---|---|
| `setbp <addr> [A/T] [S/H]` / `clearbp <h>` | 断点 |
| `setwp <addr> [R/W] ...` / `clearwp <h>` | 观察点 |
| `readap`/`writeap`、`readdp`/`writedp` | CoreSight AP/DP(多核诊断) |
| `swostart`/`swostop`/`swoview` | SWO 跟踪(≠RTT) |
| `power on/off`、`vcom enable`、`reboot`、`sleep <ms>`、`log <file>` | 其他 |

## 2. RTT 调试(★ 本轮 STM32H7 全链路实测)

**RTT 不在 Commander 里**,由独立工具/协议提供;核心是目标 RAM 里的 **SEGGER RTT 控制块**。

### 控制块结构(目标侧,须与 SEGGER 布局一致)
```
偏移 字段                说明
0x00  acID[16]          "SEGGER RTT" + 零填充(魔数,host 靠它搜索)
0x10  MaxNumUpBuffers   = 1
0x14  MaxNumDownBuffers = 1
0x18  aUp[0].sName[16]  "Terminal"
0x28  aUp[0].pBuffer    环形缓冲指针
0x2C  aUp[0].SizeOfBuffer
0x30  aUp[0].WrOff      固件写位置
0x34  aUp[0].RdOff      host 读位置
0x38  aUp[0].Flags
0x3C  aDown[0]...       下行通道(host→target)
```
**环形缓冲**:host 推进 `RdOff`,固件才能继续写(留 1 字节区分满/空);host 不读则缓冲满,固件写丢弃(非阻塞)。

### 工具
| 工具 | 用途 | 实测 |
|---|---|---|
| `JLinkRTTLogger -Device X -if SWD -Speed 4000 -RTTChannel 0 <log>` | 连 J-Link 搜控制块+记录 | 能识别控制块(`OK. 1 up-channels found`),但 **V8.92 报 `Failed to get RTT Channel description` 且不落日志(工具 bug)** |
| `JLinkRTTClient` | 连 RTT Server(localhost:19021),不直接连 J-Link | 需先有 Server(Viewer/GDBServer 提供) |
| `JLinkRTTViewerExe` | GUI | WSL 无 GUI 不可用 |

### 自实现 host 读取(绕过工具 bug,原理通用)
```text
connect
w4 0x20000030 0          # 重置 WrOff
w4 0x20000034 0          # 重置 RdOff(空缓冲)
sleep 500
mem32 0x20000030 2       # 读 WrOff/RdOff → WrOff 推进 = 固件在写
mem8  0x20000080 64      # 读 Up 缓冲 → 数据 ASCII
```
实测(STM32H743ZI):重置后 500ms `WrOff=0xE8(232)` 持续推进,缓冲=`"STM32H7 RTT demo: tick=N"`;host 每轮读后推进 RdOff 即持续接收。

### 目标固件要求
- 含控制块(魔数 `"SEGGER RTT"`)+ 持续写 Up 通道;控制块放 RAM 起始(host 默认搜索前 1KB)或用 `-RTTAddr` 指定
- 参考固件:`references/stm32h7_rtt_demo/`(919B,arm-none-eabi-gcc,控制块并入 `.data` 段——**注意:控制块必须是已初始化数据由启动代码拷贝**,放独立段会漏拷导致 RAM 无魔数,实测踩过)

## 3. RAMCode did not respond(保护后恢复,N32H787 实测)

根因:检测到读写保护→自动 unsecure→ROM HardFault→普通 loadfile 隐式复位→启动固件停核前重配 MPU/I-D Cache→RAMCode 超时。恢复:

```text
connect
halt
r
halt
w4 0xE000ED94 0x00000000      # 禁 MPU
w4 0xE000ED14 0x00040200      # 清 I/D Cache
w4 0xE000EF50 0x00000000
w4 0xE000ED28 0xFFFFFFFF      # 清 CFSR
w4 0xE000ED2C 0xFFFFFFFF      # 清 HFSR
w4 0xE000ED30 0xFFFFFFFF
loadfile <固件.bin> <addr> noreset
verifybin <固件.bin> <addr>
r
go
```

## 4. N32H787 专用(双核)

- 地址:M7@`0x15000000`、M4@`0x15080000`;**先 M4 后 M7**;M4 固件用 M7 设备名烧
- 地址表:`_estack=0x2401E000`、fault=`0x2401E800`、阶段快照=`0xC0400000`(6×10×u32=240B)、A8=`0xC0300000/0x2000`
- 详见工程文档《JLink烧录流程与技术细节-20260818.md》与知识库 `调用JLink.md`

## 5. STM32H7 实测记录(2026-08-21)

| 项 | 实测 |
|---|---|
| 目标 | STM32H743ZI(DBGMCU IDCODE `0x20036450` → DEV_ID 0x450),CPUID `0x411FC271`(M7 r1p1) |
| 供电 | 5V 供电后 VTref=4.9V(3V3 排针有电但 J-Link VTref 检测不到,换供电路径解决) |
| 连接 | `CORTEX-M7`/`STM32H743ZI` 均可;Core found |
| 烧录 | demo.bin 919B → `Bank 0 @ 0x08000000: 131072 bytes`(H7 128KB 大扇区),`Verify successful.`,Program ~9-10 MB/s |
| verifybin | ✅ 全量通过 |
| erase | `erase 0x08000000 0x08020000` → 全 `0xFFFFFFFF`(128KB 扇区,走 RAMCode 正常) |
| RTT | ✅ 控制块 @0x20000000、WrOff 0→232→255 推进、数据 `"STM32H7 RTT demo: tick=N"`;Logger description bug(见 §2) |
| savebin | ✅ 备份 64KB 成功 |
| 结论 | 连接/烧录/擦除/RTT/Commands 全链路可用;`noreset` 恢复配方为 N32H787 保护场景专用,STM32H7 普通 loadfile 即可 |

## 6. 常见坑(跨芯片)

1. `VTref=0` = 目标未供电或 VTref 线未接 3.3V;多 J-Link 并存用 `selectprobe`/`usb <SN>` 选机
2. Commander 数值参数默认十六进制(loadfile 目标地址除外)
3. RTT 控制块必须是**已初始化数据**(由启动代码拷入 RAM),放独立段会漏拷(实测踩过)
4. RTT host 不推进 RdOff → 环形缓冲写满 → 固件写丢弃,读数停在旧位置
5. WSL bash `for`/`$()` 异常 —— 脚本写文件执行或逐条命令
6. usbipd 附加丢失 → Windows 侧重新 `usbipd attach`
