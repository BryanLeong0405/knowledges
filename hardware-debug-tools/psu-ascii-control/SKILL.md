---
name: psu-ascii-control
description: 程控直流稳压电源(ASCII 串口协议, CP210x VID 10C4:EA60)的 WIN/WSL 双端控制技能。读电压电流/CV-CC、设定电压电流、输出开关、面板锁定(091/092 控制权)、软件方案槽 P1~P4、本地控制台页面。命令:`psu.py -p <port> status|setv|seti|on|off|lock|unlock|monitor|preset|serve`。当任务提到 psu-ascii-control、程控电源、可调电源、直流稳压电源、设定电压/电流、电源输出开关、CV/CC、形如 <01004580000> 的 ASCII 电源帧、psu.py/psu.html、bench 电源控制时使用。
---

# 程控直流稳压电源控制(ASCII 协议, WIN/WSL 双端)

通过 USB 串口(CP210x, VID:PID **10C4:EA60**)以 ASCII 协议控制程控直流稳压电源。工具脚本 `psu.py`(CLI+HTTP 后端)与控制台页面 `psu.html` 位于工作区 `psu_control/` 目录(主副本,不随本技能分发;技能内如有 `scripts/` 副本则以主副本为准)。

## 第一步: 端口判别(必做, 串口号会漂移)

**禁止凭记忆假设端口号**(同一设备历史出现过 COM5/COM6/COM143)。每次先实查:

```bash
usbipd list                    # Windows 侧执行; 找 VID:PID 10C4:EA60 那一行
```

| STATE | 含义 | 用哪个端口 |
|---|---|---|
| `Shared` | 设备归 Windows | Windows COM 口: `python psu.py list` 列出, 取 CP210x 对应项; 或 PowerShell `[System.IO.Ports.SerialPort]::GetPortNames()` |
| `Attached` | 已转发到 WSL | WSL 的 `/dev/ttyUSBn`(通常 0), Windows 侧该设备无 COM 口 |

设备在 WSL 与 Windows 之间迁移:

```bash
usbipd bind --hardware-id 10C4:EA60      # 首次(已做过)
usbipd attach --wsl --hardware-id 10C4:EA60   # Windows→WSL
usbipd detach --hardware-id 10C4:EA60         # 归还 Windows
```

WSL 前置: `python3 -m pip install pyserial`(已装则跳过)。

## 命令速查

```bash
# Windows(GitBash/PowerShell): python psu.py -p COMx ...
# WSL: python3 psu.py -p /dev/ttyUSBn ...(路径以 psu.py 实际存放位置为准)
python psu.py list              # 列串口(list 无需 -p)
python psu.py -p <port> status  # 读 U/I/P + CV/CC(只读, 安全)
python psu.py -p <port> setv 12.5        # 设电压(V)
python psu.py -p <port> seti 1.0         # 设电流(A)
python psu.py -p <port> on|off           # 开/关输出
python psu.py -p <port> lock|unlock      # 锁定/解锁面板(控制权)
python psu.py -p <port> monitor          # 周期刷新(Ctrl-C 退出)
python psu.py -p <port> preset list|save <1-4> <V> <A>|apply <1-4>   # 软件方案槽
python psu.py -p <port> raw <02000000000>                # 原始帧(调试用)
python psu.py -p <port> serve [--max-v 32 --max-i 11]    # HTTP 后端+控制台页面
```

`-p` 必填(list/preset list|save 除外)。通用参数: `-b`(波特率, 默认 9600), `-a`(RS485 地址, 串口固定 0), `--no-handshake`, `-v`(打印收发帧)。

**退出码**: `0`=成功; `1`=通信失败/未确认/超限; `2`=用法错误。

## 协议要点与固件怪癖(全部实测, 文档未写)

帧格式(ASCII, 9600 8N1, 帧间靠 ≥3.5 字符时间静默定界, 无换行): `<0 + 功能位 + 6位数据 + 3位地址>`, 数据=数值×1000 补零(12.10V→`012100`)。功能位: `1/2/3/4`=设/读电压电流, `7/8`=输出开/关, `9+数据首位1/2`=建立/断开连接。回包首位 `1`=CV、`C`=CC。

1. **必须先握手(`<091...>`, 回 `<19OK0000000>`)**: 不握手时 setv/seti/on/off **照样回 `<11OK...>` 但完全不生效**(假确认)。psu.py 打开串口默认自动握手, 关闭/退出自动发 `<092>` 归还面板——不要绕过。
2. **091/092 = 面板控制权锁**: 锁定=页面/PC 独占(面板按键让位, PC 命令生效); 解锁=控制权归面板(PC 控制类命令假 OK 忽略, 读命令正常)。锁状态无串口查询, 以读数与命令跟踪为准。
3. **功能 7/8 应答怪异**: 回读数帧而非 `<1?OK...>`, 不能按 OK 校验, 以 V/I 读数为准。
4. **设定电压为软斜坡**(约 1~2s 渐变), 非阶跃; 判断生效要等读数稳定。
5. **协议无输出状态查询、无设定值回读、无机内 M1~M4 存储帧**(面板 M 键纯面板功能, 串口读不到; 页面/CLI 的 P1~P4 方案槽是电脑侧 `presets.json`, 与面板 M 键无关不同步)。
6. **USB 重新插拔会杀死已打开的句柄**(Win32 错误 22): serve 模式已自动重开重握手; CLI 重跑即可。
7. **串口独占**: serve 运行时 CLI 打不开同一端口(先停 serve); 页面只开一个, 多页签会互踩锁状态。

## 安全规则

- serve/CLI 默认安全上限 `--max-v 32 --max-i 11`(0=不限), 超限设定直接拒绝; 按设备实际规格调整。
- 页面侧另有本地上限输入 + 相对当前读数跳变 >5V/2A 的确认框, 双重防护。
- **对带载设备设电压前先确认当前 V/I 读数与负载性质**; 未知负载时先 `status` 再小步调整。
- 输出 ON/OFF 后以读数验证; V=0 且 I=0 无法区分"输出关"与"0V 设定", 此时不要臆断。
- 解锁(面板控制)状态下 PC 控制命令不生效——若页面设定"成功但无效", 先查锁开关。

## 控制台页面(GUI)

`python psu.py -p <port> serve` 后浏览器开 `http://127.0.0.1:8422`(WSL 运行 serve 时 Windows 浏览器同地址可达)。双传输模式: HTTP 后端(通用)或 Web Serial 直连(Edge/Chrome, 设备须归 Windows)。页面含实时 V/I/P 读数、CV/CC 徽标、输出 ON/OFF、跳变确认、🔒面板锁定开关、方案槽 P1~P4(单击调用/双击存入)、滚动曲线、TX/RX 日志。

## 实测踩坑速查

1. "设定成功但输出没变" → 九成是锁在面板控制(未握手/已解锁), 看页头开关或发 `lock`。
2. 输出曾以面板预置 31V 意外起来过: 解锁/重上电后面板预置仍在, 带载前先 `status` 确认实际电压。
3. COM 口漂移: 每次 `usbipd list` + `psu.py list` 实查。
4. 后端端口 8422 被占: 已禁用重复绑定, 说明有旧实例, 先结束旧 python 进程。
