# -*- coding: utf-8 -*-
"""IT8511A+ 通用串口直连调试工具(不依赖任何 HTTP 控制服务)。

通过 USB 串口转换器(CH340 等)直连 IT8511A+ 的 DB9 通讯口,
按 26 字节 binary 帧协议直接收发命令。仅依赖 pyserial。

帧结构: AA + addr(1) + cmd(1) + data(22) + checksum(1)
checksum = sum(frame[0..24]) & 0xFF
写命令 ACK: 0x12 帧, frame[3] == 0x80 表示成功

用法:
  python it8511a_direct.py ports                # 仅枚举串口
  python it8511a_direct.py scan [PORT]          # 只读探测:远程控制开+身份+模式+实时值
  python it8511a_direct.py raw <CMD> [DATAHEX]  # 发任意命令(CMD 为 0x5F 等,DATAHEX 为 hex 字符串)
"""
import sys
import time
import struct

import serial
import serial.tools.list_ports as lp

BAUD = 115200
ADDR = 0
TIMEOUT = 0.6


def find_ch340_port():
    """自动查找 CH340(VID:PID=1A86:7523)串口,找不到返回 None。"""
    for p in lp.comports():
        hwid = p.hwid.upper()
        if "1A86:7523" in hwid or "CH340" in p.description.upper():
            return p.device
    return None


def build_frame(cmd, data=b""):
    """组 26 字节帧。"""
    if len(data) > 22:
        raise ValueError("data too long")
    frame = bytearray([0xAA, ADDR, cmd & 0xFF])
    frame += data
    frame += b"\x00" * (22 - len(data))
    frame.append(sum(frame) & 0xFF)
    return bytes(frame)


def recv_frame(ser):
    """读一帧并校验,返回 (frame, error)。"""
    buf = ser.read(26)
    if len(buf) < 26:
        return None, "short read %d bytes" % len(buf)
    if buf[0] != 0xAA:
        return None, "bad header 0x%02X" % buf[0]
    csum = sum(buf[:25]) & 0xFF
    if csum != buf[25]:
        return None, "checksum fail got 0x%02X want 0x%02X" % (buf[25], csum)
    return buf, None


def show(buf, label):
    hexs = " ".join("%02X" % b for b in buf)
    print("%-22s %s" % (label, hexs))


def send(ser, name, cmd, data=b"", ack=True):
    """发送一帧并显示响应。"""
    ser.reset_input_buffer()
    ser.write(build_frame(cmd, data))
    buf, err = recv_frame(ser)
    if err:
        print("%-22s ERROR %s" % (name, err))
        return None
    show(buf, name)
    if ack and buf[2] == 0x12:
        ok = "OK" if buf[3] == 0x80 else "FAIL(0x%02X)" % buf[3]
        print("%-22s ACK 0x12 success=%s" % ("", ok))
    return buf


def parse_live(buf):
    """解析 0x5F 实时值: V/1000, I/10000, P/1000, status bit3=input_on。"""
    v = struct.unpack_from("<I", buf, 3)[0] / 1000.0
    i = struct.unpack_from("<I", buf, 7)[0] / 10000.0
    p = struct.unpack_from("<I", buf, 11)[0] / 1000.0
    st = buf[15]
    print("  live: V=%.3f V  I=%.3f A  P=%.3f W  status=0x%02X  input_on=%s"
          % (v, i, p, st, "YES" if (st & 0x08) else "no"))
    return v, i, p


def main():
    args = sys.argv[1:]
    if args and args[0] == "ports":
        for p in lp.comports():
            print("%s  %s  %s" % (p.device, p.description, p.hwid))
        return

    port = None
    if args and args[0] == "scan" and len(args) > 1:
        port = args[1]
    if port is None:
        port = find_ch340_port()
    if port is None:
        print("no CH340 port found, pass it explicitly: python it8511a_direct.py scan COM5")
        sys.exit(1)

    ser = serial.Serial(port, BAUD, timeout=TIMEOUT)
    ser.flushInput()
    print("opened %s @ %d baud" % (port, BAUD))

    if not args or args[0] == "scan":
        send(ser, "remote on (0x20)", 0x20, b"\x01")
        send(ser, "product (0x6A)", 0x6A, ack=False)
        send(ser, "serial (0x6B)", 0x6B, ack=False)
        buf = send(ser, "mode read (0x29)", 0x29, ack=False)
        if buf:
            modes = {0: "CC", 1: "CV", 2: "CW", 3: "CR"}
            print("  mode_raw=%d -> %s" % (buf[3], modes.get(buf[3], "?")))
        buf = send(ser, "live (0x5F)", 0x5F, ack=False)
        if buf:
            parse_live(buf)
    elif args[0] == "raw":
        cmd = int(args[1], 16)
        data = bytes.fromhex(args[2].replace(" ", "")) if len(args) > 2 else b""
        print("send cmd 0x%02X data=%s" % (cmd, data.hex()))
        ser.reset_input_buffer()
        ser.write(build_frame(cmd, data))
        buf, err = recv_frame(ser)
        if err:
            print("ERROR", err)
        else:
            show(buf, "response")
            if buf[2] == 0x12:
                ok = "OK" if buf[3] == 0x80 else "FAIL(0x%02X)" % buf[3]
                print("ACK success=%s" % ok)
            if cmd == 0x5F:
                parse_live(buf)
    else:
        print("unknown arg: %s" % args[0])
        sys.exit(2)
    ser.close()


if __name__ == "__main__":
    main()
