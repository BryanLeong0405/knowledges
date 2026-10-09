---
name: ch340-rst-boot
description: CH340_RST_BOOT 下载模式控制器(BOOT/RESET 硬线控制)技能。CH340 只用 DTR→BOOT(GPIO0)、RTS→RESET(EN) 两根 Modem 线控复位与进 ROM 下载模式,不带数据线;由 uart_boot_control.py 驱动,双系统可用(WSL /dev/ttyUSBx、Windows COMx)。命令:`uart_boot_control.py -p <port> bootloader/app/status`。当任务提到 ch340_rst_boot、CH340_RST_BOOT、uart_boot_control、BOOT/RESET 控制、进下载模式、退出下载模式、BOT/RST/STA 快捷指令时使用。
---

# CH340_RST_BOOT 下载模式控制器

一颗 CH340 USB 串口充当"盲控"复位控制器:**DTR→BOOT(GPIO0)、RTS→RESET(EN),TX/RX 不接芯片**——从该口收不到任何数据,进没进下载模式必须到芯片的数据口验证。控制器为单文件 `uart_boot_control.py`,仅依赖 pyserial,双系统直接可用;本技能 `scripts/uart_boot_control.py` 即该控制器(宿主工程如有自己的 wrapper,语义相同)。

## 调用与参数

**控制口一律显式传入**(`-p/--port`),本技能脚本不设默认端口。宿主工程自带的 wrapper 若有默认值,以显式传参为准。

WSL/Linux:

```bash
python3 uart_boot_control.py -p <port> bootloader   # 进 ROM 下载模式(快捷别名 BOT)
python3 uart_boot_control.py -p <port> app          # 释放 BOOT 并复位,正常启动(快捷别名 RST)
python3 uart_boot_control.py -p <port> status       # 打印 DTR/RTS 逻辑状态(快捷别名 STA)
```

Windows(PowerShell,同样的参数):

```powershell
python scripts\uart_boot_control.py -p <port> bootloader
python scripts\uart_boot_control.py -p <port> app
python scripts\uart_boot_control.py -p <port> status
```

`.py` 全部子命令:`status` / `lines`(手动置 DTR/RTS 验接线) / `release`(双线释放) / `reset`(只打复位脉冲) / `bootloader` / `app` / `run <bootloader|app|reset> -- <外部命令>`(做完序列后关口再执行命令,如 esptool/idf.py)。

| 参数 | 默认 | 说明 |
|---|---|---|
| `-p` / `--port` | (必填) | 控制口,WSL 如 `/dev/ttyUSBx`,Windows 如 `COMx` |
| `--boot-line` / `--reset-line` | `dtr` / `rts` | Modem 线到 BOOT/RESET 的分配 |
| `--boot-asserted` / `--reset-asserted` | `1` / `1` | 断言极性;电路反相改 `0`,无需改脚本 |
| `--pulse-ms` / `--after-ms` | 120 / 250 | RESET 保持时长 / 释放后延时 |

## BOT/RST 时序(做了什么)

- **BOT(bootloader)**:拉 BOOT → 拉 RESET 120ms → 放 RESET(芯片采样 BOOT=低,ROM 报 `boot:0x21 (DOWNLOAD(USB/UART0))`、打印一次 `waiting for download`)→ 250ms 后放 BOOT。之后一直停在下载模式,直到烧录或 RST。
- **RST(app)**:BOOT 保持释放,打一个 120ms 复位脉冲 → 正常启动应用。
- 判定"已进下载模式"的标准做法:在**数据口**上 `esptool --before no_reset --after no_reset flash_id` 能 sync 出芯片信息即算(不要用默认 `--before default_reset`,它自己会打复位,验证不了本控制器)。

## 双系统用法

| | WSL/Linux | Windows |
|---|---|---|
| 端口名 | `/dev/ttyUSB0..N` | `COMx` |
| 调用 | `python3 scripts/uart_boot_control.py`(或工程内 .sh wrapper) | `python scripts\uart_boot_control.py` |
| 依赖 | python3 + pyserial | Python + `pip install pyserial` |
| 端口枚举 | `ls /dev/ttyUSB*` | `usbipd list`、`Get-PnpDevice -Class Ports`、`mode` |

两端可能是同一批物理设备(经 usbipd share/attach):**attach 顺序变化会导致 /dev/ttyUSBx 重新编号**,Windows COM 号则跟随物理口相对固定。换口/重连后先判别再操作(见下节),不要依赖记忆中的端口号。

## 端口判别(不绑定端口,操作前必做)

同一颗 CH340 身份(VID `1a86:7523`)可能被多类模块共用(本控制器、继电器模块等),且无序列号,**不能只凭 VID/端口号猜**:

1. **RTS 静默法**(推荐):目标芯片在跑日志时,对候选口 `lines --rts 1 --hold-ms 1200` 按住 RTS 1.2 秒,同时观察目标数据口——日志流精确静默同时长 → 该口 RTS 接的就是目标 EN,即控制口。
2. **esptool 旁证**:先对候选控制口执行 `bootloader`,再到目标数据口 `esptool --before no_reset flash_id`;sync 成功即证明控制口选对了。
3. 极性若反(按住 RTS 目标不静默、或 BOT 后仍正常启动),换 `--boot-asserted 0` / `--reset-asserted 0` 重试,不改脚本。
4. 控制口发的是电平不是协议字节:误把继电器类模块当控制口会毫无反应;反向对继电器口发协议字节则有误触发风险。

## 实测注意(坑)

1. **status/STA 有副作用**:打开 CH340 控制口瞬间可能扰动 DTR/RTS 造成一次意外复位,"只查状态"也要在允许复位的场合用;判断应用是否活着看数据口日志,别靠 STA。
2. **验证必须走数据口**:控制口收不到数据,`waiting for download`、boot banner、esptool 全在数据口看。
3. **数据口自身的 DTR/RTS 通常没接芯片**(才需要独立控制口),所以烧录流程是:先 BOT,再 `esptool --before no_reset`。
4. Ubuntu 系统包 esptool 4.x 缺 `stub_flasher_<chip>.json`:带 stub 的写/擦会崩;加 `--no-stub` 或改用 ESP-IDF 自带 esptool。
5. 部分模组 eFuse 标注的内置 flash 大小与实测 flash ID 不一致,配 flash size 参数前以 flash_id 实测为准。
6. 串口独占:同一时刻只允许一个进程打开控制口。

## 与 ch340-relay 技能的区别

ch340-relay 走 **LCUS 字节协议**(9600 8N1,控制继电器触点);本控制器走 **Modem 线电平**(DTR/RTS,无协议、无波特率要求)。二者物理上是不同的 CH340,端口判别规则见上节。
