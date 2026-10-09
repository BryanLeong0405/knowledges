---
name: debug-itech-it6722a
description: Windows WinUSB/USBTMC/SCPI workflow for the ITECH IT6722A programmable DC supply. Use when a task mentions IT6722A, VID:PID 2ec7:6700, USB488, USBTMC, WinUSB, *IDN?, VOLT?, CURR?, OUTP?, or MEAS:VOLT? and MEAS:CURR?.
---

# 调试 ITECH IT6722A

用于 Windows 侧 ITECH IT6722A 的 USB488/USBTMC/SCPI 发现、状态读取和受控远程模式验证。当前设备是 80 V / 20 A / 400 W 可编程直流电源；本技能默认只读，不负责设置输出电压、电流或开启输出。

## 先确认设备

```text
usbipd list
  -> BUSID <x-x> / 2ec7:6700 / IT6722A / Not shared
  -> Windows WinUSB
  -> USBTMC bulk OUT/IN
  -> SCPI
```

- `BUSID` 会因重新插拔变化；每次运行必须重新核对 VID/PID、型号和状态。
- 当前已验证设备接口 GUID 为 `{EF12D3B4-51BC-4726-88F9-0A30CDBC0835}`，但运行时必须从注册表动态发现。
- `Not shared` 表示设备仍由 Windows 控制；不要执行 `usbipd attach/detach`。
- USB 驱动缺失、Problem Code 非零、接口 GUID 缺失或端点无法发现时，先停在驱动/枚举层。

## 只读状态流程

在本技能目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\it6722a_usbtmc_probe.ps1 -BusId <x-x> -Status
```

探针会动态完成：

1. 校验 `BUSID <x-x> / 2ec7:6700 / IT6722A / Not shared`。
2. 解析 USB 注册表中的 WinUSB 服务、设备实例和 `DeviceInterfaceGUIDs`。
3. 打开接口，寻找 bulk IN/OUT 端点。
4. 发送 USBTMC `DEV_DEP_MSG_OUT` 和 `REQUEST_DEV_DEP_MSG_IN`。
5. 校验 response message id、tag/inverse-tag、长度和 ASCII SCPI 响应。
6. 串行查询身份、错误、版本、设定值、输出状态和实际测量值，并输出 JSON 证据。

## 默认只读查询

```text
*IDN?
SYST:ERR?
SYST:VERS?
*STB?
VOLT?
CURR?
OUTP?
OUTP:STAT?
MEAS:VOLT?
MEAS:CURR?
MEAS:POW?
```

当前实机已验证返回示例：

```text
*IDN?      -> ITECH Electronics,IT6722A,<序列号>,1.03-1.04
VOLT?      -> 24
CURR?      -> 1
OUTP?      -> 0
MEAS:VOLT? -> 0.001
MEAS:CURR? -> 0
MEAS:POW?  -> 0
```

`VOLT?`/`CURR?` 是当前设定查询，`MEAS:*?` 是实时读回；两者都不能替代电源输出安全确认。

## 受控远程模式探针

如果需要确认写路径，但不改变输出参数，可以显式执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\it6722a_usbtmc_probe.ps1 -BusId <x-x> -RemoteProbe -Query '*IDN?'
```

该模式严格执行：

```text
SYST:REM
*IDN? / 只读查询
SYST:LOC      # finally 恢复本地
```

如果恢复本地失败，立即停止后续操作并报告 `local_restore_error`；不得继续发送输出命令。

## 禁止的操作

- 不发送 `VOLT <value>`、`CURR <value>`、`OUTP ON`、`*RST`、`*CLS`。
- 不发送 OVP/OCP、LIST、触发、存储、校准或系统配置写命令。
- 不安装/切换/卸载驱动，不自动 `usbipd attach/detach`。
- 不把 USBTMC 设备当成 CH340 串口(COMx);RS232/CH340 是另一条物理接口路径。
- 不与 VISA、厂商软件或其他 Agent 并发访问；WinUSB 设备必须单进程串行使用。

## 错误处理和证据

- 读超时或 USBTMC header/tag/长度错误：关闭句柄并停止，不进行重试风暴。
- 不兼容的 SCPI 查询可能产生 `170, "Invalid command"`；记录查询来源，逐条读取错误队列后再判断设备健康。
- 至少保留：`usbipd list` 目标行、PnP/Registry 驱动证据、接口 GUID、端点、命令、RawHex、响应长度、时间戳和输出状态。
- 编程/通信成功不等于电气输出安全、精度合格或 HIL/产品 PASS。

## 参考资料

详细规格、已验证证据和官方手册见 `references/source-map.md`。先读取来源，再进行任何真实设备动作。
