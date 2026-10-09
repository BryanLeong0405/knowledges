#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FNIRSI FNB58 USB 电压电流表 - HID 控制工具 (Windows 原生 / WSL2 双端).

设备: VID:PID 2e3c:5558 (复合设备: U盘 + CDC串口 + HID接口3), BUSID 随插拔变化勿写死.
Windows: 设备在 Windows 侧直接用 (hidapi 走 hid.dll, 免驱动, 无需 usbipd 操作).
WSL2:   先 usbipd bind(管理员,一次性)+attach 把设备交给 WSL, 节点 /dev/hidraw*,
        普通用户无权限时用 sudo 或装 udev 规则 (详见技能文档).
协议为社区逆向 (baryluk/fnirsi-usb-power-data-logger, OpenFNB58), 真机已验证:
  命令帧(64B): AA 81/82/83 00...00 CRC8   (CRC8: poly=0x39 init=0x42, 仅命令帧)
  应答帧(64B): AA 04 + 4组15字节采样 + CRC8(poly同上, data[1:-1]参与运算)
  采样布局:    V(u32le/1e5 V) I(u32le/1e5 A) D+(u16le/1e3 V) D-(u16le/1e3 V)
               保留(1B, 恒为1) 板温(u16le/10 C)
  流速:        ~100采样/秒; FNB58 初始化需连发两次 AA 82
  平台差异:    Windows hidapi 写帧首字节须为报告ID 0x00(65B); Linux hidraw 写裸 64B
注意: FNB58 通过 PC 联机端口(Micro-USB)取电并与 PC 通信; 监控口量程 4~28V / 7A。

用法:
  python fnb58_control.py check                    设备在位/身份/快照/链路健康
  python fnb58_control.py once [--json]            单次读数(取最新一包, 4采样均值)
  python fnb58_control.py monitor [--seconds S] [--csv F] [--interval S]
                                                   连续监测, Ctrl+C 退出并给统计汇总
  python fnb58_control.py serve [--host H] [--port P]
                                                   启动 HTTP 后端(默认127.0.0.1:8423),
                                                   浏览器打开控制台页面 fnb58.html
依赖: pip install hidapi
"""
import argparse
import collections
import csv
import json
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import hid
except ImportError:
    sys.exit("缺少依赖: 先执行  pip install hidapi")

VID, PID = 0x2E3C, 0x5558
IS_WIN = sys.platform == "win32"
CMD_INIT1 = b"\xaa\x81" + b"\x00" * 61 + b"\x8e"
CMD_INIT2 = b"\xaa\x82" + b"\x00" * 61 + b"\x96"
CMD_POLL = b"\xaa\x83" + b"\x00" * 61 + b"\x9e"
KEEPALIVE_S = 1.0  # 参考实现: 每秒重发一次 POLL 维持流


def crc8(data):
    crc = 0x42
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x39) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def find_device(serial=None):
    infos = hid.enumerate(VID, PID)
    if serial:
        infos = [i for i in infos if i["serial_number"] == serial]
    return infos[0] if infos else None


def decode_samples(frame):
    """帧 -> 4 组采样字典列表; 调用方需已校验帧头."""
    out = []
    for i in range(4):
        off = 2 + 15 * i
        v = struct.unpack_from("<I", frame, off)[0] / 1e5
        c = struct.unpack_from("<I", frame, off + 4)[0] / 1e5
        dp = struct.unpack_from("<H", frame, off + 8)[0] / 1e3
        dn = struct.unpack_from("<H", frame, off + 10)[0] / 1e3
        t = struct.unpack_from("<H", frame, off + 13)[0] / 10
        out.append({"v": v, "i": c, "dp": dp, "dn": dn, "temp": t})
    return out


def not_found_hint():
    if IS_WIN:
        return " (若已 usbipd attach 到 WSL, 先在 Windows 执行 usbipd detach --busid <busid>)"
    return " (设备可能还在 Windows 侧: 管理员执行 usbipd bind --busid <busid> 一次, 再 usbipd attach --wsl --busid <busid>)"


class FNB58:
    def __init__(self, serial=None):
        self.serial = serial
        self.dev = None
        self.path = None
        self.crc_bad = 0
        self.other_frames = 0

    def open(self):
        info = find_device(self.serial)
        if info is None:
            raise RuntimeError(f"未找到 FNB58 (VID {VID:04x}:{PID:04x}){not_found_hint()}")
        self.path = info["path"]
        try:
            self.dev = hid.device()
            self.dev.open_path(self.path)
        except OSError as e:
            if IS_WIN:
                why = f"设备可能被占用(如 FNIRSI 上位机/另一实例)"
            else:
                why = "多半是权限(/dev/hidraw* 默认仅 root 可写): sudo 运行, 或安装 udev 规则见技能文档"
            raise RuntimeError(f"打开 HID 失败({e}): {why}")
        return self

    def close(self):
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None

    def _cmd(self, frame):
        # Windows hidapi: 首字节=报告ID 0 (65字节); Linux hidapi: 裸 64 字节直写 hidraw
        payload = (b"\x00" + frame) if IS_WIN else frame
        n = self.dev.write(payload)
        if n <= 0:
            raise OSError(f"HID 写入失败 n={n}")

    def handshake(self):
        self._cmd(CMD_INIT1)
        time.sleep(0.15)
        self._cmd(CMD_INIT2)
        time.sleep(0.15)
        self._cmd(CMD_INIT2)  # FNB58 固件要求连发两次
        time.sleep(0.15)

    def drain(self, seconds=0.25):
        end = time.time()
        while time.time() < end:
            if not self.dev.read(64, timeout_ms=50):
                break

    def read_packet(self, timeout_ms=200):
        """读取一帧(64B), 返回 4 组采样列表; 超时/坏帧返回 None."""
        data = bytes(self.dev.read(64, timeout_ms=timeout_ms))
        if not data:
            return None
        if len(data) == 65 and data[0] == 0:  # 某些后端带报告ID前缀
            data = data[1:]
        if len(data) < 64 or data[0] != 0xAA or data[1] != 0x04:
            self.other_frames += 1
            return None
        frame = data[:64]
        if crc8(frame[1:-1]) != frame[63]:
            self.crc_bad += 1
            return None
        return decode_samples(frame)

    def keepalive(self):
        self._cmd(CMD_POLL)


def fmt_val(x, digits=5):
    return f"{x:.{digits}f}"


def snapshot(avgs):
    return (f"V={fmt_val(avgs['v'])}V  I={fmt_val(avgs['i'])}A  "
            f"P={avgs['v'] * avgs['i']:.5f}W  DP={avgs['dp']:.3f}V  "
            f"DN={avgs['dn']:.3f}V  T={avgs['temp']:.1f}C")


def avg_samples(samples):
    return {k: sum(s[k] for s in samples) / len(samples) for k in samples[0]}


def cmd_check(args):
    info = find_device(args.serial)
    if info is None:
        raise RuntimeError(f"未找到 FNB58 (VID {VID:04x}:{PID:04x}){not_found_hint()}")
    m = FNB58(args.serial).open()
    try:
        path_s = info["path"].decode(errors="replace") if isinstance(info["path"], bytes) else info["path"]
        print(f"设备: {info['manufacturer_string']} {info['product_string']}  "
              f"SN={info['serial_number']}  bcdDev=v{info['release_number'] >> 8}.{info['release_number'] & 0xFF:02X}")
        print(f"HID: interface={info['interface_number']}  path=...{path_s[-45:]}")
        m.handshake()
        m.drain()
        m.keepalive()
        pkt = None
        t0 = time.time()
        while time.time() - t0 < 1.5 and pkt is None:
            pkt = m.read_packet()
        if pkt is None:
            raise RuntimeError("握手后 1.5s 内未收到有效数据帧")
        print("快照:", snapshot(avg_samples(pkt)))
        print(f"链路: 每包采样={len(pkt)}  CRC错误={m.crc_bad}  其它帧={m.other_frames}")
        print("OK")
        return 0
    finally:
        m.close()


def cmd_once(args):
    m = FNB58(args.serial).open()
    try:
        m.handshake()
        m.drain()
        m.keepalive()
        pkt = None
        t0 = time.time()
        while time.time() - t0 < 1.5 and pkt is None:
            pkt = m.read_packet()
        if pkt is None:
            raise RuntimeError("1.5s 内未收到有效数据帧")
        avgs = avg_samples(pkt)
        if args.json:
            rec = {"v": avgs["v"], "i": avgs["i"], "p": avgs["v"] * avgs["i"],
                   "dp": avgs["dp"], "dn": avgs["dn"], "temp": avgs["temp"],
                   "samples": pkt}
            print(json.dumps(rec, ensure_ascii=False))
        else:
            print(snapshot(avgs))
        return 0
    finally:
        m.close()


def cmd_monitor(args):
    csv_f = None
    csv_w = None
    if args.csv:
        csv_f = open(args.csv, "w", newline="", encoding="utf-8", buffering=1)
        csv_w = csv.writer(csv_f)
        csv_w.writerow(["time", "t_rel_s", "V", "A", "W", "Dp_V", "Dn_V", "T_C"])
    m = FNB58(args.serial)
    t_start = time.time()
    t_last_print = 0.0
    t_last_keepalive = 0.0
    n_pkt = n_smp = 0
    stats = {"v_min": 1e9, "v_max": -1e9, "v_sum": 0.0,
             "i_min": 1e9, "i_max": -1e9, "i_sum": 0.0, "p_max": 0.0}
    wh = mah = 0.0
    last_t = None
    retries = 0
    end_at = t_start + args.seconds if args.seconds else None
    rc = 0
    try:
        m.open()
        m.handshake()
        m.drain()
        print("monitor 开始 (Ctrl+C 停止)" + (f", {args.seconds}s 后自动结束" if args.seconds else ""))
        while True:
            if end_at and time.time() >= end_at:
                break
            now = time.time()
            if now - t_last_keepalive >= KEEPALIVE_S:
                m.keepalive()
                t_last_keepalive = now
            try:
                pkt = m.read_packet(timeout_ms=200)
                retries = 0
            except (OSError, ValueError) as e:
                retries += 1
                if retries > 5:
                    raise RuntimeError(f"连续读失败({e}), 设备可能被拔出")
                print(f"[warn] 读取异常({e}), 尝试重连 {retries}/5", file=sys.stderr)
                m.close()
                time.sleep(1.0)
                m.open()
                m.handshake()
                m.drain()
                continue
            if pkt is None:
                continue
            n_pkt += 1
            n_smp += len(pkt)
            now = time.time()
            dt = 0.0 if last_t is None else min(now - last_t, 0.5) / len(pkt)
            last_t = now
            for s in pkt:
                wh += s["v"] * s["i"] * dt
                mah += s["i"] * dt * 1000.0
                stats["v_min"] = min(stats["v_min"], s["v"])
                stats["v_max"] = max(stats["v_max"], s["v"])
                stats["v_sum"] += s["v"]
                stats["i_min"] = min(stats["i_min"], s["i"])
                stats["i_max"] = max(stats["i_max"], s["i"])
                stats["i_sum"] += s["i"]
                stats["p_max"] = max(stats["p_max"], s["v"] * s["i"])
            if csv_w:
                for s in pkt:
                    csv_w.writerow([time.strftime("%H:%M:%S"), round(now - t_start, 3),
                                    f"{s['v']:.5f}", f"{s['i']:.5f}",
                                    f"{s['v'] * s['i']:.5f}", f"{s['dp']:.3f}",
                                    f"{s['dn']:.3f}", f"{s['temp']:.1f}"])
            if now - t_last_print >= args.interval:
                t_last_print = now
                print(f"[{now - t_start:7.1f}s] {snapshot(avg_samples(pkt))}  "
                      f"| {wh:.4f}Wh {mah:.2f}mAh")
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        rc = 1
    finally:
        elapsed = time.time() - t_start
        m.close()
        if csv_f:
            csv_f.close()
        if n_smp:
            print("-" * 72)
            print(f"时长 {elapsed:.1f}s  包={n_pkt}  采样={n_smp}  "
                  f"CRC错误={m.crc_bad}  其它帧={m.other_frames}")
            print(f"电压 min/avg/max = {stats['v_min']:.5f}/"
                  f"{stats['v_sum'] / n_smp:.5f}/{stats['v_max']:.5f} V")
            print(f"电流 min/avg/max = {stats['i_min']:.5f}/"
                  f"{stats['i_sum'] / n_smp:.5f}/{stats['i_max']:.5f} A")
            print(f"峰值功率 = {stats['p_max']:.5f} W  "
                  f"累计电能 = {wh:.4f} Wh  累计容量 = {mah:.2f} mAh")
    return rc


# ---------------------------------------------------------------- serve 后端

CHART_MAXLEN = 6000   # 曲线环形缓冲: 20点/秒 x 5分钟
FULL_MAXLEN = 7000    # 全速环形缓冲(CSV导出用): 100采样/秒 x 70秒


class Store:
    """后端共享状态: 读数线程写入, HTTP 线程只读."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0                    # 曲线点序号, 单调递增
        self.chart = collections.deque(maxlen=CHART_MAXLEN)  # [seq,t,v,i,p,dp,dn,temp]
        self.full = collections.deque(maxlen=FULL_MAXLEN)    # [t,v,i,p,dp,dn,temp]
        self.stats = self.fresh_stats()
        self.t_start = time.time()
        self.state = "waiting"          # waiting|ok|error
        self.error = ""
        self.info = {}
        self.rate_t = collections.deque(maxlen=200)  # 近2秒采样时刻, 用于测采样率

    @staticmethod
    def fresh_stats():
        return {"n": 0, "v_sum": 0.0, "v_min": None, "v_max": None,
                "i_sum": 0.0, "i_min": None, "i_max": None, "p_max": None,
                "wh": 0.0, "mah": 0.0}

    def reset(self):
        with self.lock:
            self.stats = self.fresh_stats()
            self.chart.clear()
            self.full.clear()
            self.t_start = time.time()

    def stats_view(self):
        s = self.stats
        n = max(s["n"], 1)
        return {"n": s["n"], "elapsed": time.time() - self.t_start,
                "v_avg": s["v_sum"] / n, "v_min": s["v_min"], "v_max": s["v_max"],
                "i_avg": s["i_sum"] / n, "i_min": s["i_min"], "i_max": s["i_max"],
                "p_max": s["p_max"], "wh": s["wh"], "mah": s["mah"]}

    def ingest(self, samples, now):
        dt = 0.0 if not self.rate_t else min(now - self.rate_t[-1], 0.5) / len(samples)
        s = self.stats
        for x in samples:
            p = x["v"] * x["i"]
            s["n"] += 1
            s["v_sum"] += x["v"]
            s["i_sum"] += x["i"]
            s["v_min"] = x["v"] if s["v_min"] is None else min(s["v_min"], x["v"])
            s["v_max"] = x["v"] if s["v_max"] is None else max(s["v_max"], x["v"])
            s["i_min"] = x["i"] if s["i_min"] is None else min(s["i_min"], x["i"])
            s["i_max"] = x["i"] if s["i_max"] is None else max(s["i_max"], x["i"])
            s["p_max"] = p if s["p_max"] is None else max(s["p_max"], p)
            s["wh"] += p * dt
            s["mah"] += x["i"] * dt * 1000.0
            self.rate_t.append(now)
            self.full.append([now, x["v"], x["i"], p, x["dp"], x["dn"], x["temp"]])
        if self.rate_t:
            span = self.rate_t[-1] - self.rate_t[0]
            rate = (len(self.rate_t) - 1) / span if span > 0 else 0.0
        else:
            rate = 0.0
        avg = {k: sum(x[k] for x in samples) / len(samples) for k in samples[0]}
        self.seq += 1
        self.chart.append([self.seq, now, avg["v"], avg["i"], avg["v"] * avg["i"],
                           avg["dp"], avg["dn"], avg["temp"]])
        return self.seq, rate


def reader_loop(store, stop_evt, serial):
    """后台读数线程: 设备拔出/被占用时每 2s 自动重试."""
    while not stop_evt.is_set():
        m = FNB58(serial)
        try:
            m.open()
        except RuntimeError as e:
            with store.lock:
                store.state, store.error = "error", str(e)
            stop_evt.wait(2.0)
            continue
        with store.lock:
            store.state, store.error = "ok", ""
        try:
            info = find_device(serial)
            if info:
                with store.lock:
                    store.info = {"product": f"{info['manufacturer_string']} {info['product_string']}",
                                  "serial": info["serial_number"],
                                  "bcd": f"v{info['release_number'] >> 8}.{info['release_number'] & 0xFF:02X}",
                                  "path": str(info['path'])[-45:]}
            m.handshake()
            m.drain()
            with store.lock:
                store.state, store.error = "ok", ""
            last_ka = time.time()
            while not stop_evt.is_set():
                now = time.time()
                if now - last_ka >= KEEPALIVE_S:
                    m.keepalive()
                    last_ka = now
                pkt = m.read_packet(timeout_ms=200)
                if pkt is None:
                    continue
                with store.lock:
                    store.ingest(pkt, time.time())
        except (OSError, RuntimeError, ValueError) as e:
            with store.lock:
                store.state, store.error = "error", f"读数中断: {e}"
        finally:
            m.close()
        stop_evt.wait(2.0)


def make_handler(store, html_path):
    class ApiHandler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默访问日志
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _text(self, body, ctype, code=200, dispo=None):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if dispo:
                self.send_header("Content-Disposition", dispo)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html", "/fnb58.html"):
                try:
                    with open(html_path, "r", encoding="utf-8") as f:
                        self._text(f.read(), "text/html; charset=utf-8")
                except OSError as e:
                    self._text(f"fnb58.html 缺失: {e}", "text/plain; charset=utf-8", 500)
            elif url.path == "/api/history":
                since = int(parse_qs(url.query).get("since", ["0"])[0])
                with store.lock:
                    pts = [p for p in store.chart if p[0] > since][-1200:]
                    latest = store.chart[-1] if store.chart else None
                    rate = 0.0
                    if len(store.rate_t) > 10:
                        span = store.rate_t[-1] - store.rate_t[0]
                        rate = (len(store.rate_t) - 1) / span if span > 0 else 0.0
                    resp = {"state": store.state, "error": store.error,
                            "info": store.info, "seq": store.seq,
                            "rate": round(rate, 1),
                            "latest": latest, "points": pts,
                            "stats": store.stats_view()}
                self._json(resp)
            elif url.path == "/api/csv":
                rows = ["time,t_rel_s,V,A,W,Dp_V,Dn_V,T_C"]
                t0 = store.t_start
                with store.lock:
                    lines = [f"{time.strftime('%H:%M:%S', time.localtime(r[0]))},"
                             f"{r[0] - t0:.3f},{r[1]:.5f},{r[2]:.5f},{r[3]:.5f},"
                             f"{r[4]:.3f},{r[5]:.3f},{r[6]:.1f}" for r in store.full]
                rows += lines
                fname = time.strftime("fnb58_%Y%m%d_%H%M%S.csv")
                self._text("\n".join(rows) + "\n", "text/csv; charset=utf-8",
                           dispo=f'attachment; filename="{fname}"')
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path == "/api/reset":
                store.reset()
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)

    return ApiHandler


def cmd_serve(args):
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fnb58.html")
    store = Store()
    stop_evt = threading.Event()
    threading.Thread(target=reader_loop, args=(store, stop_evt, args.serial),
                     daemon=True).start()

    class Httpd(ThreadingHTTPServer):
        allow_reuse_address = False  # 防新旧后端并存抢请求

    try:
        httpd = Httpd((args.host, args.port), make_handler(store, html_path))
    except OSError as e:
        sys.exit(f"绑定 {args.host}:{args.port} 失败({e}): 可能已有一个 serve 在运行")
    url = f"http://{args.host}:{args.port}"
    print(f"FNB58 控制台: {url}   (Ctrl+C 退出)")
    print(f"设备状态: {store.state} (后台自动重连中)" if store.state != "ok"
          else "设备状态: ok")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        httpd.server_close()


def main():
    ap = argparse.ArgumentParser(description="FNIRSI FNB58 USB 电压电流表控制 (HID)")
    ap.add_argument("--serial", default=None, help="多设备时按序列号选择")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="在位检查+快照+链路健康")
    c.set_defaults(fn=cmd_check)
    o = sub.add_parser("once", help="单次读数")
    o.add_argument("--json", action="store_true")
    o.set_defaults(fn=cmd_once)
    mo = sub.add_parser("monitor", help="连续监测")
    mo.add_argument("--seconds", type=float, default=None, help="运行秒数(缺省直到 Ctrl+C)")
    mo.add_argument("--interval", type=float, default=0.5, help="打印间隔秒")
    mo.add_argument("--csv", default=None, help="CSV 记录文件路径(逐采样)")
    mo.set_defaults(fn=cmd_monitor)
    sv = sub.add_parser("serve", help="启动 HTTP 后端并托管 fnb58.html 控制台")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8423)
    sv.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
