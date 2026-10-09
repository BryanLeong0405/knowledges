# SDM3055X-E source map

## Local evidence and implementation sources

- Current probe: `scripts/sdm3055x_e_probe.ps1`（本技能目录）
- Current device enumeration source: `usbipd list` and Windows registry `HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_F4EC&PID_1202`（易变，运行时动态发现）

A RIGOL WinUSB/USBTMC transport script exists elsewhere as reference only. Its hardcoded DHO914S path and MSO5072 identifiers must not be reused for SDM3055X-E.

## Official sources

- [Siglent SDM3055X-E product page](https://www.siglent.com/products-overview/sdm3055x-e/)
- [Siglent SDM Series Programming Guide](https://siglentna.com/wp-content/uploads/dlm_uploads/2017/10/SDM-Series-Digital-Multimeter_ProgrammingGuide_EN02A.pdf)
- [Siglent SDM3055X-E User Manual](https://www.siglent.com/wp-content/uploads/2024/08/SDM3055X-E_UserManual_UM06035E_C03A.pdf)

## Current verified baseline

```text
BUSID <x-x> / f4ec:1202 / SDM3055X-E / Not shared
Instance USB\VID_F4EC&PID_1202\<序列号>
Service WinUSB
DeviceInterfaceGUID {49F43DAA-6F59-4EC3-9807-89F318AA2763}
*IDN? -> Siglent Technologies,SDM3055X-E,<序列号>,2.02.01.15R1
SYST:ERR? -> 0,"No error"
CONF? -> "VOLT +2.00000000E-01"
FUNC? -> "VOLT"
*STB? -> 0
```

This baseline is a dated observation, not a permanent device identity. Re-enumerate before use.
