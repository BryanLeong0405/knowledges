[CmdletBinding()]
param(
    [string]$BusId = "",
    [string]$VidPid = "2ec7:6700",
    [string]$DeviceName = "IT6722A",
    [string[]]$Query = @(),
    [switch]$Status,
    [switch]$AllowMeasure,
    [switch]$RemoteProbe,
    [string]$WriteCommand = "",
    [ValidateRange(100, 30000)]
    [int]$TimeoutMs = 3000,
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BusId)) {
    throw "BusId is required: read the current bus id from 'usbipd list' and pass -BusId <x-x>. Never assume a previous value; BUSID changes with replug/report."
}

$script:SafeQueries = @("*IDN?", "SYST:ERR?", "SYST:VERS?", "*STB?", "VOLT?", "CURR?", "OUTP?", "OUTP:STAT?", "MEAS:VOLT?", "MEAS:CURR?", "MEAS:POW?")
$script:MeasureQueries = @("READ?")

function Test-SafeScpiQuery {
    param([Parameter(Mandatory = $true)][string]$Command)
    $key = $Command.Trim().ToUpperInvariant()
    return $script:SafeQueries -contains $key
}

function New-UsbtmcMessage {
    param(
        [Parameter(Mandatory = $true)][byte]$MessageId,
        [Parameter(Mandatory = $true)][byte]$Tag,
        [byte[]]$Payload = @(),
        [Parameter(Mandatory = $true)][uint32]$TransferSize,
        [byte]$Attributes = 0
    )

    $payloadLength = if ($null -eq $Payload) { 0 } else { $Payload.Length }
    $paddedLength = ($payloadLength + 3) -band (-4)
    $message = New-Object byte[] (12 + $paddedLength)
    $message[0] = $MessageId
    $message[1] = $Tag
    $message[2] = $Tag -bxor 0xFF
    [Array]::Copy([BitConverter]::GetBytes($TransferSize), 0, $message, 4, 4)
    $message[8] = $Attributes
    if ($payloadLength -gt 0) {
        [Array]::Copy($Payload, 0, $message, 12, $payloadLength)
    }
    return $message
}

function Parse-UsbtmcResponse {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][byte]$ExpectedTag
    )

    if ($Bytes.Length -lt 12) { throw "USBTMC response header is truncated: $($Bytes.Length) bytes" }
    if ($Bytes[0] -ne 2) { throw "Unexpected USBTMC response message id: $($Bytes[0])" }
    if ($Bytes[1] -ne $ExpectedTag -or $Bytes[2] -ne ($ExpectedTag -bxor 0xFF)) {
        throw "USBTMC response tag mismatch: got $($Bytes[1])/$($Bytes[2]), expected $ExpectedTag/$($ExpectedTag -bxor 0xFF)"
    }

    $payloadLength = [BitConverter]::ToUInt32($Bytes, 4)
    if ($payloadLength -gt ($Bytes.Length - 12)) {
        throw "USBTMC response payload is truncated: header=$payloadLength available=$($Bytes.Length - 12)"
    }
    $payload = New-Object byte[] ([int]$payloadLength)
    if ($payloadLength -gt 0) {
        [Array]::Copy($Bytes, 12, $payload, 0, [int]$payloadLength)
    }
    [pscustomobject]@{
        MessageId = $Bytes[0]
        Tag = $Bytes[1]
        TransferSize = $payloadLength
        PayloadBytes = $payload
        PayloadText = [Text.Encoding]::ASCII.GetString($payload)
    }
}

function ConvertFrom-UsbipdLine {
    param([Parameter(Mandatory = $true)][string]$Line)
    $pattern = '^\s*(\S+)\s+([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})\s+(.+?)\s+(Not shared|Shared|Attached)\s*$'
    if ($Line -notmatch $pattern) { return $null }
    return [pscustomobject]@{
        BusId = $Matches[1]
        VidPid = $Matches[2].ToLowerInvariant()
        Device = $Matches[3].Trim()
        State = $Matches[4].Trim()
    }
}

function Get-UsbipdTarget {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedBusId,
        [Parameter(Mandatory = $true)][string]$ExpectedVidPid,
        [Parameter(Mandatory = $true)][string]$ExpectedName
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $lines = @(usbipd list 2>&1 | ForEach-Object { [string]$_ })
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $row = $null
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $candidate = ConvertFrom-UsbipdLine $line
        if ($null -ne $candidate -and $candidate.BusId -eq $ExpectedBusId -and $candidate.VidPid -eq $ExpectedVidPid.ToLowerInvariant()) {
            $row = $candidate
            break
        }
    }
    if ($null -eq $row) {
        throw "Current usbipd list has no matching $ExpectedBusId / $ExpectedVidPid device. Do not guess or attach another BUSID."
    }
    if ($row.Device -notlike "*$ExpectedName*") {
        throw "BUSID $ExpectedBusId has unexpected device name '$($row.Device)'; expected '$ExpectedName'."
    }
    if ($row.State -ne "Not shared") {
        throw "BUSID $ExpectedBusId is '$($row.State)'. Stop to avoid changing Windows/WSL control ownership."
    }
    return $row
}

function Resolve-SdmWinUsbInterface {
    param([Parameter(Mandatory = $true)][string]$ExpectedName)

    $root = "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_2EC7&PID_6700"
    if (-not (Test-Path -LiteralPath $root)) { throw "USB registry root not found: $root" }
    foreach ($instanceKey in @(Get-ChildItem -LiteralPath $root -ErrorAction Stop)) {
        $props = Get-ItemProperty -LiteralPath $instanceKey.PSPath -ErrorAction SilentlyContinue
        if ($null -eq $props) { continue }
        $friendly = [string]$props.FriendlyName
        $description = [string]$props.DeviceDesc
        if ($friendly -notlike "*$ExpectedName*" -and $description -notlike "*$ExpectedName*") { continue }
        if ([string]$props.Service -ne "WinUSB") { throw "Device $($instanceKey.PSChildName) is not using WinUSB." }

        $parametersPath = Join-Path $instanceKey.PSPath "Device Parameters"
        $parameters = Get-ItemProperty -LiteralPath $parametersPath -ErrorAction Stop
        $guidValues = @($parameters.DeviceInterfaceGUIDs)
        if ($guidValues.Count -eq 0) { throw "DeviceInterfaceGUIDs missing for $($instanceKey.PSChildName)." }
        $guid = ([string]$guidValues[0]).Trim()
        if (-not $guid.StartsWith("{")) { $guid = "{$guid}" }
        $instance = $instanceKey.PSChildName.ToLowerInvariant()
        $path = "\\?\usb#vid_2ec7&pid_6700#$instance#$guid"
        return [pscustomobject]@{
            InstanceId = "USB\VID_2EC7&PID_6700\$($instanceKey.PSChildName)"
            FriendlyName = $friendly
            Service = [string]$props.Service
            InterfaceGuid = $guid
            DevicePath = $path
        }
    }
    throw "No WinUSB IT6722A registry instance found."
}

function Initialize-SdmUsbtmcNative {
    if ("Sdm3055XUsbTmc" -as [type]) { return }
    $source = @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class Sdm3055XUsbTmc
{
    public static string LastEndpointInfo { get; private set; }
    const uint GENERIC_READ = 0x80000000;
    const uint GENERIC_WRITE = 0x40000000;
    const uint FILE_SHARE_READ = 0x00000001;
    const uint FILE_SHARE_WRITE = 0x00000002;
    const uint OPEN_EXISTING = 3;
    const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    const uint FILE_FLAG_OVERLAPPED = 0x40000000;

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr handle);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_Initialize(IntPtr device, out IntPtr iface);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_Free(IntPtr iface);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_QueryInterfaceSettings(IntPtr iface, byte alt, out USB_INTERFACE_DESCRIPTOR desc);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_QueryPipe(IntPtr iface, byte alt, byte index, out WINUSB_PIPE_INFORMATION pipe);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_WritePipe(IntPtr iface, byte pipe, byte[] buffer, uint length, out uint transferred, IntPtr overlapped);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_ReadPipe(IntPtr iface, byte pipe, byte[] buffer, uint length, out uint transferred, IntPtr overlapped);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_ResetPipe(IntPtr iface, byte pipe);
    [DllImport("winusb.dll", SetLastError = true)]
    static extern bool WinUsb_SetPipePolicy(IntPtr iface, byte pipe, uint policy, uint valueLength, ref uint value);

    [StructLayout(LayoutKind.Sequential)]
    struct USB_INTERFACE_DESCRIPTOR { public byte length, type, number, alt, endpoints, cls, subcls, protocol, index; }
    [StructLayout(LayoutKind.Sequential)]
    struct WINUSB_PIPE_INFORMATION { public int PipeType; public byte PipeId; public ushort MaximumPacketSize; public byte Interval; }

    static void Fail(string what) { throw new Win32Exception(Marshal.GetLastWin32Error(), what); }

    static byte[] Message(byte id, byte tag, byte[] payload, uint transferSize, byte attributes)
    {
        int length = payload == null ? 0 : payload.Length;
        int padded = (length + 3) & ~3;
        byte[] result = new byte[12 + padded];
        result[0] = id; result[1] = tag; result[2] = (byte)(tag ^ 0xFF);
        Array.Copy(BitConverter.GetBytes(transferSize), 0, result, 4, 4);
        result[8] = attributes;
        if (length > 0) Array.Copy(payload, 0, result, 12, length);
        return result;
    }

    public static byte[] Transfer(string path, string command, int timeoutMs, int maxRead, bool query)
    {
        IntPtr handle = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, IntPtr.Zero);
        if (handle == new IntPtr(-1)) Fail("CreateFile failed for " + path);
        IntPtr iface = IntPtr.Zero;
        try
        {
            if (!WinUsb_Initialize(handle, out iface)) Fail("WinUsb_Initialize failed");
            USB_INTERFACE_DESCRIPTOR desc;
            if (!WinUsb_QueryInterfaceSettings(iface, 0, out desc)) Fail("WinUsb_QueryInterfaceSettings failed");
            byte bulkIn = 0, bulkOut = 0;
            ushort bulkInMax = 0, bulkOutMax = 0;
            for (byte i = 0; i < desc.endpoints; i++)
            {
                WINUSB_PIPE_INFORMATION pipe;
                if (!WinUsb_QueryPipe(iface, 0, i, out pipe)) Fail("WinUsb_QueryPipe failed");
                if (pipe.PipeType == 2) {
                    if ((pipe.PipeId & 0x80) != 0) { bulkIn = pipe.PipeId; bulkInMax = pipe.MaximumPacketSize; }
                    else { bulkOut = pipe.PipeId; bulkOutMax = pipe.MaximumPacketSize; }
                }
            }
            if (bulkIn == 0 || bulkOut == 0) throw new Exception("USBTMC bulk IN/OUT endpoints were not found.");
            LastEndpointInfo = String.Format("interface={0} bulkIn=0x{1:X2} maxIn={2} bulkOut=0x{3:X2} maxOut={4}", desc.number, bulkIn, bulkInMax, bulkOut, bulkOutMax);
            uint timeout = (uint)timeoutMs;
            WinUsb_SetPipePolicy(iface, bulkIn, 0x03, 4, ref timeout);
            WinUsb_SetPipePolicy(iface, bulkOut, 0x03, 4, ref timeout);
            WinUsb_ResetPipe(iface, bulkIn); WinUsb_ResetPipe(iface, bulkOut);

            if (!command.EndsWith("\n")) command += "\n";
            byte[] commandBytes = Encoding.ASCII.GetBytes(command);
            byte[] outMessage = Message(1, 1, commandBytes, (uint)commandBytes.Length, 1);
            uint transferred;
            if (!WinUsb_WritePipe(iface, bulkOut, outMessage, (uint)outMessage.Length, out transferred, IntPtr.Zero)) Fail("USBTMC command write failed");

            if (!query) return new byte[0];

            byte[] readRequest = Message(2, 2, null, (uint)maxRead, 0);
            if (!WinUsb_WritePipe(iface, bulkOut, readRequest, (uint)readRequest.Length, out transferred, IntPtr.Zero)) Fail("USBTMC read request failed");
            byte[] buffer = new byte[maxRead + 12];
            uint read;
            if (!WinUsb_ReadPipe(iface, bulkIn, buffer, (uint)buffer.Length, out read, IntPtr.Zero)) Fail("USBTMC bulk read failed");
            if (read < 12) throw new Exception("USBTMC response header is truncated.");
            if (buffer[0] != 2 || buffer[1] != 2 || buffer[2] != 0xFD) throw new Exception("USBTMC response tag/header mismatch.");
            uint payloadLength = BitConverter.ToUInt32(buffer, 4);
            if (payloadLength > read - 12) throw new Exception("USBTMC response payload is truncated.");
            byte[] payload = new byte[payloadLength];
            if (payloadLength > 0) Array.Copy(buffer, 12, payload, 0, (int)payloadLength);
            return payload;
        }
        finally
        {
            if (iface != IntPtr.Zero) WinUsb_Free(iface);
            CloseHandle(handle);
        }
    }
}
"@
    Add-Type -TypeDefinition $source
}

function Get-QueryPlan {
    param([switch]$StatusMode, [switch]$AllowMeasurement, [string[]]$Requested)
    $plan = if ($StatusMode) { @("*IDN?", "SYST:ERR?", "SYST:VERS?", "*STB?", "VOLT?", "CURR?", "OUTP?", "MEAS:VOLT?", "MEAS:CURR?", "MEAS:POW?") } elseif ($Requested.Count -gt 0) { $Requested } else { @("*IDN?") }
    foreach ($command in $plan) {
        $key = $command.Trim().ToUpperInvariant()
        if (Test-SafeScpiQuery $key) { continue }
        if ($AllowMeasurement -and $script:MeasureQueries -contains $key) { continue }
        throw "Query '$command' is not in the read-only allowlist. Use -AllowMeasure explicitly for READ?."
    }
    return @($plan | ForEach-Object { $_.Trim() })
}

function Invoke-SdmScpiQuery {
    param(
        [Parameter(Mandatory = $true)][string]$DevicePath,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][int]$Timeout
    )
    Initialize-SdmUsbtmcNative
    $bytes = [Sdm3055XUsbTmc]::Transfer($DevicePath, $Command, $Timeout, 65536, $true)
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    [pscustomobject]@{
        Command = $Command
        Response = $text.TrimEnd([char]0, [char]13, [char]10)
        RawLength = $bytes.Length
        RawHex = ([BitConverter]::ToString($bytes) -replace '-', ' ')
        EndpointInfo = [Sdm3055XUsbTmc]::LastEndpointInfo
    }
}

function Invoke-ItechScpiWrite {
    param(
        [Parameter(Mandatory = $true)][string]$DevicePath,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][int]$Timeout
    )
    Initialize-SdmUsbtmcNative
    [void][Sdm3055XUsbTmc]::Transfer($DevicePath, $Command, $Timeout, 0, $false)
}

if ($NoRun) { return }

$report = [ordered]@{
    ok = $false
    tool = "debug-itech-it6722a"
    timestamp_utc = [DateTime]::UtcNow.ToString("o")
    protocol = "Windows WinUSB -> USBTMC -> SCPI"
    target = $null
    interface = $null
    endpoint = $null
    remote_sent = $false
    write_command = $null
    write_sent = $false
    local_restore_sent = $false
    local_restore_error = $null
    queries = @()
    error = $null
}

$remoteActive = $false
try {
    $target = Get-UsbipdTarget -ExpectedBusId $BusId -ExpectedVidPid $VidPid -ExpectedName $DeviceName
    $interface = Resolve-SdmWinUsbInterface -ExpectedName $DeviceName
    $report.target = $target
    $report.interface = $interface
    if ($RemoteProbe -or $WriteCommand) {
        Invoke-ItechScpiWrite -DevicePath $interface.DevicePath -Command "SYST:REM" -Timeout $TimeoutMs
        $remoteActive = $true
        $report.remote_sent = $true
    }
    if ($WriteCommand) {
        Invoke-ItechScpiWrite -DevicePath $interface.DevicePath -Command $WriteCommand -Timeout $TimeoutMs
        $report.write_command = $WriteCommand
        $report.write_sent = $true
    }
    $plan = Get-QueryPlan -StatusMode:$Status -AllowMeasurement:$AllowMeasure -Requested $Query
    $results = [System.Collections.Generic.List[object]]::new()
    foreach ($command in $plan) {
        $results.Add((Invoke-SdmScpiQuery -DevicePath $interface.DevicePath -Command $command -Timeout $TimeoutMs))
    }
    $report.queries = @($results)
    $report.endpoint = [Sdm3055XUsbTmc]::LastEndpointInfo
    $report.ok = $true
}
catch {
    $report.error = $_.Exception.Message
}
finally {
    if ($remoteActive) {
        try {
            Invoke-ItechScpiWrite -DevicePath $interface.DevicePath -Command "SYST:LOC" -Timeout $TimeoutMs
            $report.local_restore_sent = $true
        }
        catch {
            $report.local_restore_error = $_.Exception.Message
        }
    }
}

$report | ConvertTo-Json -Depth 8
if (-not $report.ok) { exit 1 }
