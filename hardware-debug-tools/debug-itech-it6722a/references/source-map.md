# IT6722A source map

## Local evidence and implementation

- Probe: `scripts/it6722a_usbtmc_probe.ps1`（本技能目录）
- Current enumeration: `usbipd list`
- Current registry root: `HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_2EC7&PID_6700`（易变，运行时动态发现）

Current verified baseline:

```text
BUSID <x-x> / 2ec7:6700 / IT6722A / Not shared
Instance USB\VID_2EC7&PID_6700\<序列号>
Service WinUSB
Interface GUID {EF12D3B4-51BC-4726-88F9-0A30CDBC0835}
Bulk IN 0x82 / 64
Bulk OUT 0x01 / 64
Firmware 1.03-1.04
```

## Official sources

- [ITECH IT6700H product page](https://www.itechate.com/en/product/dc-power-supply/IT6700H.html)
- [ITECH IT6700 user manual](https://www.itechate.com/uploadfiles/%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C/user%20manual/it6700h/IT6700%20User%20Manual-EN.pdf)
- [ITECH IT6700 programming guide](https://www.itechate.com/uploadfiles/%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C/user%20manual/it6700h/IT6700%20Programming%20Guide-CN.pdf)
- [ITECH IT6722(A) product note](https://www.itechate.com/en/info_174.aspx?itemid=855&lcid=)

The official documentation identifies IT6722A as an 80 V / 20 A / 400 W supply with USB/RS232 communication, USB488/USBTMC support, and SCPI programming. The USB path in this skill is the verified Windows WinUSB path; the earlier CH340/COMx RS232 path is not part of this package.
