# fnb58-usb-power-meter source map

## Local evidence and implementation

- Entry: `SKILL.md`
- Scripts: `scripts/fnb58_control.py`(双端 CLI + serve 后端)、`scripts/fnb58.html`(单文件控制台,须与脚本同目录)
- 项目主副本(开发记录与回归): 工作区 `fnb58_control/` 目录(不随技能分发)
- 设备定位: `usbipd list` 动态核对 VID:PID/STATE,绝不写死 BUSID

Verified baseline(2026-10-09 真机,FNB-58 固件 v2.00):

```text
VID:PID = 2e3c:5558,复合设备 = U盘 + CDC串口(COMx) + HID(interface 3)
Windows 链路: hidapi(hid.dll) 免驱动直读,写帧 65B(0x00 报告ID前缀)
实测采样率 101.5 Hz(每包4采样);应答 CRC8(poly 0x39/init 0x42) 41/41 全过
读数样例: V=5.159V, I≈0.07mA, D+ 2.67/D− 2.59(Apple 2.4A 特征), 板温 34.7C
控制台: serve @127.0.0.1:8423,100Hz 后端/20点每秒曲线/4Hz 页面轮询,浏览器已验收
WSL 链路: hidapi 0.15.0(Ubuntu 24.04, pip --user --break-system-packages)安装通过,
py_compile/参数解析/未找到设备的分流提示已验证;实机 hidraw 读数待设备 attach 后按
SKILL.md 第四节清单回归
```

## Community/official sources

- [baryluk/fnirsi-usb-power-data-logger](https://github.com/baryluk/fnirsi-usb-power-data-logger):HID 协议原始逆向(命令帧/采样布局/CRC/温度偏移+13)
- [yeckel/OpenFNB58](https://github.com/yeckel/OpenFNB58):FNB58 hidraw/BLE 客户端,AA 82 连发两次与每秒 AA 83 保活的做法出处
- [f4inu/FNB58](https://github.com/f4inu/FNB58):USB 模式 100Hz 采样率的旁证
- [usbipd-win](https://github.com/dorssel/usbipd-win) / [Microsoft Learn: Connect USB devices in WSL](https://learn.microsoft.com/en-us/windows/wsl/connect-usb):bind(管理员)/attach/detach 语义
- 设备说明书(FNIRSI 随机 PDF):量程 4~28V/7A/140W、D± 0~3.3V、PC 联机口 Micro-USB 兼供电

## Skill scope

- 只管"读数":枚举、所有权切换、权限、CLI 采集、CSV、HTTP 控制台。
- 不涉及:快充触发/PD 监听/E-Marker(设备面板功能,不经 HID 通道)、固件升级、FNB48/FNB48S 适配(协议近似未验证)。
