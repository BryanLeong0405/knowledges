---
name: fnb58-usb-power-meter
description: FNIRSI FNB58 USB 快充测试仪(电压电流表)的 HID 双端控制技能(Windows 原生 + WSL2)。免驱动读取 100Hz 电压/电流/功率/D+/D-/板温,CRC8 强校验,连续监测+CSV+HTTP 单文件控制台。覆盖 usbipd 所有权切换、WSL /dev/hidraw* 权限、hidapi 平台写帧差异(Windows 65B 报告ID前缀 vs Linux 裸 64B)。当任务提到 FNB58、USB 电压电流表、USB 测试仪、USB 功率计、快充测试仪、USB tester、HID 仪表、2e3c:5558、/dev/hidraw、usbipd attach 时使用。示例设备:FNIRSI FNB-58(VID 2e3c:5558)。
---

# FNIRSI FNB58 USB 电压电流表控制(Windows + WSL2)

FNB58 是 USB 快充测试仪:监测电压/电流/功率/D+/D−/板载温度,量程 4~28V / 7A / 140W,D+/D− 量程 0~3.3V(可据分压特征识别 Apple 2.4A / DCP / Samsung 等充电协议信号)。本技能用脚本经 **USB HID 接口**读数(协议为社区逆向,官方上位机协议不公开),Windows 与 WSL2 两条链路同一份脚本。核心约束:**设备同一时刻只能被一侧独占**(usbipd attach/detach 决定归属);**FNB58 必须插在 PC 联机端口(Micro-USB)上**取电+通信,拔掉即掉线。

## 一、先确认设备(每次操作前必做)

Windows 侧执行:

```bash
usbipd list          # WSL 内用 "/mnt/c/Program Files/usbipd-win/usbipd.exe" list
```

判别三件事:

1. **以 VID:PID 定位设备,绝不写死 BUSID**(随插拔/换口变化)。FNB58 = `2e3c:5558`。
   - 注意区分同门设备:FNB48 = `0483:003a`、FNB48S = `2e3c:0049`,协议近似但帧参数可能不同,本技能只在 FNB58 上验证过。
   - FNB58 枚举为**复合设备**:U 盘 + CDC 串口(COMx) + HID 接口 3 三个子设备挂在同一 BUSID 下,缺一个说明枚举异常。
2. **STATE 决定归属**:`Not shared`/`Shared` = 归 Windows;`Attached` = 被 WSL 独占,Windows 侧枚举不到 HID。
3. 找不到设备时先看 STATE,再检查 Micro-USB 线是否插在**PC 联机端口**(不是监控口)。

## 二、所有权切换(usbipd)

在 **Windows 管理员 PowerShell/CMD** 执行(bind 需管理员,一次性;attach/detach 普通权限即可):

```powershell
usbipd bind --busid <busid>           # 一次性登记;有不兼容 filter(如 hrdevmon)时加 --force
usbipd attach --wsl --busid <busid>   # 交给 WSL:出现 /dev/hidraw*(整个复合设备一起过去)
usbipd detach --busid <busid>         # 还给 Windows:COMx 与 HID 回到 Windows 侧
```

- attach 前确认 Windows 侧无程序占用(FNIRSI 官方上位机、本脚本 serve);**官方上位机与本脚本互斥**,都开 HID 句柄会抢流。
- detach 前确认 WSL 侧脚本已退出(读数线程占着节点会导致 detach 失败)。

## 三、依赖

```bash
# Windows
python -m pip install hidapi                      # 走 hid.dll,免驱动

# WSL2(Ubuntu 24.04 受 PEP 668 保护)
python3 -m pip install --user --break-system-packages hidapi
```

## 四、使用(两端同一条命令)

脚本见 `scripts/fnb58_control.py`(控制台页面 `scripts/fnb58.html` 须与脚本同目录):

```bash
python fnb58_control.py check                    # 在位+身份+快照+链路健康(每次先跑这个)
python fnb58_control.py once [--json]            # 单次读数
python fnb58_control.py monitor --seconds 10 --csv out.csv   # 连续监测+逐采样CSV,Ctrl+C出统计
python fnb58_control.py serve                    # HTTP 后端+控制台,默认 127.0.0.1:8423
```

- Windows 侧:设备归 Windows 后直接跑,**无需换驱动、无需 usbipd 操作**。
- WSL 侧:`/dev/hidraw*` 默认仅 root 可读写。临时 `sudo python3 fnb58_control.py ...`;要免 sudo 则装 udev 规则后重拔插:

  ```bash
  echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2e3c", ATTRS{idProduct}=="5558", MODE="0666"' | \
    sudo tee /etc/udev/rules.d/99-fnb58.rules
  ```

- WSL 里跑 serve 时,Windows 浏览器**仍开 `http://127.0.0.1:8423`**(WSL2 localhost 转发默认开启);打不开再用 `hostname -I` 的 WSL IP + `serve --host 0.0.0.0`。
- 控制台页面:V/I/P/T 大数字 + D+/D− 协议特征识别 + 双轴实时曲线(1/2/5 分钟窗) + 会话统计(Wh/mAh) + 一键导出 CSV(后端全速 100Hz,保留最近 70 秒) + 重置。

## 五、协议速查(已真机验证,改代码前先读这里)

64 字节帧,CRC8 = **poly 0x39 / init 0x42 / 无反射**(命令帧必带;应答帧 CRC 覆盖 data[1:-1],脚本默认强校验):

| 帧 | 内容 |
|---|---|
| 命令 | `AA 81`(init1) / `AA 82`(init2,**FNB58 固件要求连发两次**) / `AA 83`(poll,每 1s 保活) + 61×00 + CRC8 |
| 应答 | `AA 04` + 4 组×15 字节采样 + CRC8;约 100 采样/秒 |
| 采样 | V(u32le ÷1e5) · I(u32le ÷1e5) · D+(u16le ÷1e3) · D−(u16le ÷1e3) · 保留1B(恒 01) · 板温@偏移+13(u16le ÷10 °C) |
| 平台差异 | **Windows hidapi 写帧首字节=报告 ID 0x00(65B);Linux hidraw 写裸 64B**——脚本已按 `sys.platform` 分流,勿混用 |

## 六、实测注意(踩过的坑)

1. **初始化 AA 82 只发一次收不到数据**,必须连发两次(FNB58 固件怪癖,参考实现同款)。
2. **应答 CRC 实测 41/41 全过**,出现坏帧优先怀疑 USB 链路(usbip 转发/HUB),不要关校验掩盖。
3. Windows 上写帧**忘加 0x00 报告 ID 前缀会写入失败**(65 字节);Linux 加了反而失败,这是双端最大差异。
4. 温度字段在采样内**偏移 +13 不是 +12**(前 12 字节 = 4+4+2+2,第 12 字节是恒 01 保留位);社区转述两版本都有,以原始逆向仓库为准。
5. FNB58 掉线大多是**供电问题**:PC 联机口被拔/接触不良;监控口有无被测设备不影响通信。
6. 页面高频刷新(250ms)下,Playwright 原生 click 会动作性超时——自动化测试时改用页面内 `evaluate` 触发 click,真人操作不受影响。
7. 监控口量程 4~28V,**低于 4V 读数不可信**;快充触发/PD 监听等面板功能走设备按键,不经本 HID 通道。

## 参考

- 验证证据与来源见 `references/source-map.md`。
- 项目主副本(含开发记录)存于本地工作区 `fnb58_control/` 目录,不随技能分发;技能内 `scripts/` 为随行副本,改动请两边同步。
