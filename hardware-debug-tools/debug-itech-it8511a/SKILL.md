---
name: debug-itech-it8511a
description: Generic serial-direct workflow for diagnosing, measuring, and safely controlling an ITECH IT8511A+ electronic load. Connect any USB-serial adapter (CH340 etc.) straight to the DB9 comm port and talk 26-byte binary frames or SCPI directly over the serial port with Python/pyserial - no HTTP controller or EXE service in between. Use when a task mentions IT8511A, IT8511A+, IT8500+, electronic load, CH340, DB9, serial port, SCPI, 26-byte binary frames, Short, Transient, load-input faults, 0x5F live values.
---

# 调试 ITECH IT8511A+(通用串口直连)

通过任意 USB 串口转换器(CH340 等)直连 IT8511A+ 的 DB9 通讯口,在宿主机上用 Python/pyserial 直接收发协议帧控制仪器。不依赖任何 HTTP 服务、总控台或 EXE 控制程序——协议是通用型的,脚本拿到任何一台带 USB 串口的机器上都能用。

> 默认先做状态和协议证据收集;任何输入开启、短路、动态响应、原始写命令或真实负载测试都必须有明确授权。

## 硬件和安全前提

1. 先确认 IT8511A+ 型号、外部电源、被测物、负载功率和接线安全。
2. DB9 通讯口按设备手册是 **TTL 电平**;必须使用 ITECH 原厂/兼容隔离转换线(如 CH340 转 DB9 隔离线),不要把标准 RS232 电平线直接接入。
3. 默认把输入保持关闭。设置模式/设定值时输入保持关闭,确认读回一致后再考虑是否开启。
4. 任何写入的 ACK 失败、校验失败、超时或读回不一致,立即停止后续写入并重新读取状态。
5. **串口独占**:同一时刻只允许一个进程打开 COM 口。直连脚本运行期间,不得再启动其他串口工具或 HTTP 服务连接同一端口。

## 连接识别(先确认串口)

1. 枚举 COM 口,记录设备描述、硬件 ID、USB 位置:

   ```python
   import serial.tools.list_ports as lp
   for p in lp.comports():
       print(p.device, p.description, p.hwid)
   ```

2. CH340 的 VID/PID 为 `1A86:7523`,hwid 形如 `USB VID:PID=1A86:7523 LOCATION=<x>`。
3. 多台 CH340 混插时,用设备管理器/注册表 `LocationInformation`(如 `Port_#0001.Hub_#xxxx` = BUSID <x-x>)与用户口述的物理位置核对,不要只认 COM 号。
4. 通讯参数:波特率 `4800 / 9600 / 19200 / 38400 / 115200`,默认 `115200`;设备地址 `0..31`,默认 `0`;协议默认 binary(SCPI 可选)。

## 协议:26 字节 binary 帧(主协议)

每帧固定 26 字节:

| 字节 | 含义 |
| --- | --- |
| 0 | 帧头 `0xAA` |
| 1 | 设备地址,默认 `0x00` |
| 2 | 命令字 |
| 3..24 | 数据区,最多 22 字节(不足补 `0x00`) |
| 25 | 校验和 = `sum(frame[0..24]) & 0xFF` |

- 写命令通常返回 `0x12` ACK 帧,成功码 `frame[3] == 0x80`。
- 读命令返回同命令字回显帧,数据区为读数。
- 任何长度 != 26、帧头非 `0xAA`、校验不符或 ACK 非 `0x80` 都不要继续写入。

常用命令表:

| 功能 | 写命令 | 读回命令 | 数据区编码 |
| --- | --- | --- | --- |
| 远程控制 | `0x20` | - | `1/0` |
| 输入 ON/OFF | `0x21` | `0x5F` 状态位 | `1/0` |
| 最大电压 | `0x22` | `0x23` | `V * 1000` u32 |
| 最大电流 | `0x24` | `0x25` | `A * 10000` u32 |
| 最大功率 | `0x26` | `0x27` | `W * 1000` u32 |
| 模式 | `0x28` | `0x29` | `0=CC 1=CV 2=CW 3=CR` |
| CC 电流 | `0x2A` | `0x2B` | `A * 10000` u32 |
| CV 电压 | `0x2C` | `0x2D` | `V * 1000` u32 |
| CW 功率 | `0x2E` | `0x2F` | `W * 1000` u32 |
| CR 电阻 | `0x30` | `0x31` | `Ohm * 10000` u32 |
| Sense 远端采样 | `0x52` | `0x53` | `1/0` |
| 功能模式 | `0x58` | `0x59` | `0=FIXED 1=SHORT 2=TRANSIENT 4=BATTERY 5=LIST` |
| Short 短路 | `0x5D` | `0x5E` | `1/0` |
| 实时值 | - | `0x5F` | 见下 |
| 产品信息 | - | `0x6A` | ASCII |
| 序列号 | - | `0x6B` | ASCII |

实时值 `0x5F` 响应数据区(小端):

| 偏移 | 含义 | 缩放 |
| --- | --- | --- |
| 3..6 | 电压 | `/1000` |
| 7..10 | 电流 | `/10000` |
| 11..14 | 功率 | `/1000` |
| 15 | 状态字节 | bit3 = 输入开启 |

数值均为 u32 小端;写设定值示例:`CC 1A` = `0x2A` + data `10 27 00 00`(`10000 = 1.0 * 10000`)。

## 直连脚本

`references/it8511a_direct.py` 是自包含直连工具(仅依赖 pyserial):

```
python it8511a_direct.py scan              # 只读探测:远程控制开+身份+模式+实时值
python it8511a_direct.py raw 0x5F          # 发任意读命令(如实时值)
python it8511a_direct.py raw 0x2A 10270000 # 发写命令+数据 hex(CC 电流 1A)
```

脚本自动做:26 字节组帧、校验和计算与验证、ACK 语义解析、实时值解码。需要自定义命令字时,先用 `raw` 验证响应再封装。

## 操作流程

### 只读诊断(无需授权)

1. 枚举 COM 口,确认转换线插入且驱动正常(pyserial 能列出)。
2. 打开串口(115200/地址 0),发 `0x20` 开启远程控制(会改变仪器远程状态,属受控动作),然后读 `0x6A`/`0x6B` 身份、`0x29` 模式、`0x5F` 实时值。
3. 记录型号、序列号、端口、波特率、地址、协议、额定值、设定值、实际读数、时间戳、错误和读回结果,保证可复现。

### 受控工作点设置(需明确授权)

```text
打开串口 -> 0x20 远程控制开 -> 0x28 设模式 -> 0x2A/2C/2E/30 设值 -> 读回校验 -> 0x5F 确认实际值
```

- 支持模式:`CC/CV/CW/CR`,单位 A/V/W/Ohm。
- 保守绝对边界:150 V、30 A、150 W;仍以设备身份和额定值读回为准。
- 写模式或设定值后必须读回校验(如 `0x2B` 读回 CC 电流),不能只看 ACK。
- 若需打开输入(`0x21`),先重新读取完整状态,确认设定值、外部电源和保护范围,再单独发 `0x21 01`,随后立即读 `0x5F` 确认 `status bit3`。

### 危险命令边界

默认禁止自动调用,除非用户给出明确目标和安全条件:

- `0x21` 输入 ON:真实加载外部电源。
- `0x5D` Short 短路模拟。
- `0x58` 的 `TRANSIENT/BATTERY/LIST` 功能切换。
- `0x20` 远程控制、`0x52` Sense、触发类命令:可能改变仪器工作状态,写前确认含义。
- 动态响应(transient)参数:单位边界(`us/ms/100us tick`)未经实机完全闭环,不用于未经实机确认的生产自动化。

## 协议故障排查

- 打开失败 / 拒绝访问:COM 口被其他进程占用(包括残留的 HTTP 服务连接),先释放串口再重试。
- 无响应 / 超时:确认 COM 口、波特率、地址、TTL 转换线和接线;降低调用频率并重新打开。
- 校验失败:帧长度、帧头、校验和或 ACK 不符时不要继续;对照命令表核对数据区编码(小端、缩放系数)。
- SCPI 无响应:确认设备确实支持 SCPI 且换行符正确;不要把 binary 响应当成文本解析。

## 测试和证据边界

- 真实负载行为(输入开启、Short、Transient)与只读查询分开报告;不能把串口能收发帧当成真实负载 PASS。
- 实机验证需记录:设备型号/序列号、端口、波特率、地址、协议、设定值、读回值、ACK 帧、时间戳。
- 需要全功能实机测试(切换 Sense/Short/触发/CC/CV/CW/CR/动态参数/输入)时,必须有人在现场确认外部电源与被测物安全,不得无人值守运行。

## 参考资料

协议手册、设备 PDF 与参考实现的精确位置见 `references/source-map.md`。使用时先读对应源文件,再执行任何真实设备动作。
