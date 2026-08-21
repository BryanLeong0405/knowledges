---
name: debug-siglent-sdm3055xe
description: Windows WinUSB/USBTMC/SCPI workflow for diagnosing the Siglent SDM3055X-E. Use when a task mentions SDM3055X-E, VID:PID f4ec:1202, usbipd, WinUSB, USBTMC, *IDN?, SYST:ERR?, CONF?, FUNC?, or READ?.
---

# 调试 Siglent SDM3055X-E

用于当前 Windows 侧的 `SDM3055X-E` 只读枚举、WinUSB 接口发现、USBTMC 传输和 SCPI 状态查询。当前设备由 Windows WinUSB 控制，默认不应通过 `usbipd attach` 转交 WSL。

## 当前链路和证据边界

```text
Windows usbipd list
  -> BUSID <x-x> / f4ec:1202 / SDM3055X-E / Not shared
  -> PnP/Registry WinUSB interface
  -> USBTMC bulk OUT/IN
  -> SCPI
```

- `BUSID` 不是永久编号；每次运行先重新读取 `usbipd list`，并同时核对 VID/PID、设备名和状态。
- `Not shared` 表示设备仍由 Windows 侧控制；不要为了“让脚本能用”自动 attach/detach。
- 设备实例、序列号、接口 GUID 和固件版本都是易变事实；探针会动态解析并记录，不应硬编码成判断依据。
- `*IDN?`、状态查询和一次 `READ?` 只能证明通信/测量响应，不能证明探头接线、精度、校准或 HIL PASS。

## 推荐只读流程

先确认目标设备和工具路径，再运行包内探针：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sdm3055x_e_probe.ps1 -Status
```

探针会：

1. 解析当前 `usbipd list`，要求 `6-4 / f4ec:1202 / SDM3055X-E / Not shared`。
2. 从 Windows USB 注册表动态发现 `WinUSB` 服务、实例和 `DeviceInterfaceGUIDs`。
3. 打开设备接口，查询 USB 接口并寻找 bulk IN/OUT 端点。
4. 串行发送 USBTMC `DEV_DEP_MSG_OUT` 和查询用 `REQUEST_DEV_DEP_MSG_IN`。
5. 校验 USBTMC response message id、tag/inverse-tag、长度和 ASCII SCPI 响应。
6. 默认查询 `*IDN?`、`SYST:ERR?`、`CONF?`、`FUNC?`、`*STB?`，输出带时间戳的 JSON 证据。
7. 每条命令完成后释放 WinUSB 句柄；不使用并发进程。

## 允许的查询

默认只允许：

```text
*IDN?
SYST:ERR?
CONF?
FUNC?
*STB?
```

明确需要一次测量时才加：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sdm3055x_e_probe.ps1 -Query 'READ?' -AllowMeasure
```

`READ?` 会启动一次测量并影响仪器读数缓存，因此不属于默认只读状态集。其结果必须带上当前功能、量程、接线和时间戳解释。

探针会拒绝 `*RST`、`*CLS`、配置写入、量程写入、触发写入和未列入白名单的 raw SCPI；不要通过参数绕过白名单。

## 错误处理

- 当前 `usbipd` 输出可能带 `hrdevmon` 警告；探针只忽略不匹配的警告行，仍要求目标设备行有效。
- BUSID/VID/PID/型号不匹配、设备已 Shared/Attached、驱动不是 WinUSB、接口 GUID 缺失或 bulk 端点缺失时立即停止。
- `WinUsb_ReadPipe`/写入超时、USBTMC header/tag/长度错误时关闭句柄并停止，不进行重试风暴。
- 设备被其他 VISA/PowerShell/厂商软件占用时，不结束用户进程、不抢占接口；报告占用证据。
- `SYST:ERR?` 返回非零错误时保存原始响应，停止后续危险动作。

## 不能做的事

- 不执行 `usbipd attach/detach`、驱动安装/切换或 `libwdi` 重绑定。
- 不复用 RIGOL DHO914S/MSO5072 的硬编码 VID/PID、序列号或接口 GUID。
- 不发送 `*RST`、`*CLS`、功能/量程/触发/存储配置写命令。
- 不把 WSL `lsusb` 不可见当作设备故障；当前设计是 Windows 侧 WinUSB。
- 不把一次 `READ?` 结果写成精度校准、模拟输入安全或产品验收结论。

## 证据报告

至少保留：

- `usbipd list` 目标行和时间。
- PnP/Registry 实例、WinUSB 服务和接口 GUID。
- bulk IN/OUT 端点发现结果。
- 每条 SCPI 命令、原始响应、响应长度、错误和时间戳。
- 当前连接归属（Windows `Not shared`）和是否执行过测量许可。

## 参考资料

设备来源、规格、官方编程手册和本次研究规格见 `references/source-map.md`。先读来源，再按本技能的只读边界操作。
