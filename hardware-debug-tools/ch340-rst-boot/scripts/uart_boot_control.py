#!/usr/bin/env python3
"""Control ESP boot/reset lines through USB-UART DTR/RTS.

The mapping matches the common auto-download fixture: DTR drives BOOT and
RTS drives RESET. The script uses pyserial logical line states; if the
external circuit inverts either signal, override the asserted value from
the command line instead of editing the script.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import serial


LINE_NAMES = ("dtr", "rts")


@dataclass(frozen=True)
class LineConfig:
    boot_line: str
    reset_line: str
    boot_asserted: bool
    reset_asserted: bool


def _bool_from_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on", "assert", "asserted"):
        return True
    if normalized in ("0", "false", "no", "off", "deassert", "deasserted"):
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean line value: {value}")


def _line_value(asserted: bool, asserted_value: bool) -> bool:
    return asserted_value if asserted else not asserted_value


def _set_line(port: serial.Serial, line: str, value: bool) -> None:
    if line == "dtr":
        port.dtr = value
        return
    if line == "rts":
        port.rts = value
        return
    raise ValueError(f"unsupported line: {line}")


def _get_line(port: serial.Serial, line: str) -> bool:
    if line == "dtr":
        return bool(port.dtr)
    if line == "rts":
        return bool(port.rts)
    raise ValueError(f"unsupported line: {line}")


def _open_port(args: argparse.Namespace) -> serial.Serial:
    if not args.port:
        raise ValueError("control port is required: pass -p/--port (e.g. /dev/ttyUSB3 on WSL, COM7 on Windows)")
    port = serial.Serial()
    port.port = args.port
    port.baudrate = args.baudrate
    port.timeout = args.timeout
    port.write_timeout = args.timeout
    port.rtscts = False
    port.dsrdtr = False

    # Set a quiet initial state before opening so pyserial applies it as early
    # as the OS driver allows. This avoids an unintended BOOT/RESET assertion
    # when running read-only commands such as status.
    port.dtr = not args.boot_asserted
    port.rts = not args.reset_asserted
    port.open()
    time.sleep(args.settle_ms / 1000.0)
    return port


def _apply_idle(port: serial.Serial, cfg: LineConfig) -> None:
    _set_line(port, cfg.boot_line, _line_value(False, cfg.boot_asserted))
    _set_line(port, cfg.reset_line, _line_value(False, cfg.reset_asserted))


def _apply_boot(port: serial.Serial, cfg: LineConfig, asserted: bool) -> None:
    _set_line(port, cfg.boot_line, _line_value(asserted, cfg.boot_asserted))


def _apply_reset(port: serial.Serial, cfg: LineConfig, asserted: bool) -> None:
    _set_line(port, cfg.reset_line, _line_value(asserted, cfg.reset_asserted))


def _print_status(port: serial.Serial, cfg: LineConfig) -> None:
    dtr = _get_line(port, "dtr")
    rts = _get_line(port, "rts")
    boot_asserted = _get_line(port, cfg.boot_line) == cfg.boot_asserted
    reset_asserted = _get_line(port, cfg.reset_line) == cfg.reset_asserted
    print(f"port={port.port} dtr={int(dtr)} rts={int(rts)} boot_asserted={int(boot_asserted)} reset_asserted={int(reset_asserted)}")


def _pulse_reset(port: serial.Serial, cfg: LineConfig, pulse_ms: int, after_ms: int) -> None:
    _apply_reset(port, cfg, True)
    time.sleep(pulse_ms / 1000.0)
    _apply_reset(port, cfg, False)
    time.sleep(after_ms / 1000.0)


def _enter_bootloader(port: serial.Serial, cfg: LineConfig, pulse_ms: int, after_ms: int, release_boot: bool) -> None:
    _apply_boot(port, cfg, True)
    time.sleep(0.05)
    _pulse_reset(port, cfg, pulse_ms, after_ms)
    if release_boot:
        _apply_boot(port, cfg, False)
        time.sleep(0.05)


def _enter_app(port: serial.Serial, cfg: LineConfig, pulse_ms: int, after_ms: int) -> None:
    _apply_boot(port, cfg, False)
    time.sleep(0.05)
    _pulse_reset(port, cfg, pulse_ms, after_ms)


def _run_command(command: Iterable[str]) -> int:
    command = list(command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("missing command after --", file=sys.stderr)
        return 2
    return subprocess.run(command, check=False).returncode


def _make_line_config(args: argparse.Namespace) -> LineConfig:
    if args.boot_line == args.reset_line:
        raise ValueError("boot-line and reset-line must use different modem-control lines")
    return LineConfig(
        boot_line=args.boot_line,
        reset_line=args.reset_line,
        boot_asserted=args.boot_asserted,
        reset_asserted=args.reset_asserted,
    )


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _print_status(port, cfg)
    return 0


def cmd_lines(args: argparse.Namespace) -> int:
    with _open_port(args) as port:
        if args.dtr is not None:
            port.dtr = args.dtr
        if args.rts is not None:
            port.rts = args.rts
        _print_status(port, _make_line_config(args))
        if args.hold_ms > 0:
            time.sleep(args.hold_ms / 1000.0)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _apply_idle(port, cfg)
        _print_status(port, cfg)
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _apply_idle(port, cfg)
        _pulse_reset(port, cfg, args.pulse_ms, args.after_ms)
        _print_status(port, cfg)
    return 0


def cmd_bootloader(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _apply_idle(port, cfg)
        _enter_bootloader(port, cfg, args.pulse_ms, args.after_ms, not args.hold_boot)
        _print_status(port, cfg)
        if args.hold_ms > 0:
            time.sleep(args.hold_ms / 1000.0)
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _apply_idle(port, cfg)
        _enter_app(port, cfg, args.pulse_ms, args.after_ms)
        _print_status(port, cfg)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _make_line_config(args)
    with _open_port(args) as port:
        _apply_idle(port, cfg)
        if args.sequence == "bootloader":
            _enter_bootloader(port, cfg, args.pulse_ms, args.after_ms, release_boot=True)
        elif args.sequence == "app":
            _enter_app(port, cfg, args.pulse_ms, args.after_ms)
        elif args.sequence == "reset":
            _pulse_reset(port, cfg, args.pulse_ms, args.after_ms)
        else:
            raise ValueError(f"unsupported sequence: {args.sequence}")
        _print_status(port, cfg)
    return _run_command(args.command)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--port", default=None, help="USB-UART control port, e.g. /dev/ttyUSB3 (WSL) or COM7 (Windows)")
    parser.add_argument("-b", "--baudrate", type=int, default=115200, help="baudrate used only to open the port")
    parser.add_argument("--timeout", type=float, default=0.2, help="serial open/read/write timeout in seconds")
    parser.add_argument("--settle-ms", type=int, default=50, help="delay after opening the serial port")
    parser.add_argument("--boot-line", choices=LINE_NAMES, default="dtr", help="modem-control line connected to BOOT")
    parser.add_argument("--reset-line", choices=LINE_NAMES, default="rts", help="modem-control line connected to RESET")
    parser.add_argument("--boot-asserted", type=_bool_from_arg, default=True, help="logical value that asserts BOOT, default: 1")
    parser.add_argument("--reset-asserted", type=_bool_from_arg, default=True, help="logical value that asserts RESET, default: 1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control ESP BOOT/RESET through USB-UART DTR/RTS")
    _add_common_args(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="open the port and print current logical DTR/RTS state")
    status.set_defaults(func=cmd_status)

    lines = sub.add_parser("lines", help="manually set DTR/RTS to verify wiring")
    lines.add_argument("--dtr", type=_bool_from_arg, help="set logical DTR value")
    lines.add_argument("--rts", type=_bool_from_arg, help="set logical RTS value")
    lines.add_argument("--hold-ms", type=int, default=0, help="hold the requested line state before closing")
    lines.set_defaults(func=cmd_lines)

    release = sub.add_parser("release", help="deassert BOOT and RESET")
    release.set_defaults(func=cmd_release)

    reset = sub.add_parser("reset", help="pulse RESET while BOOT is released")
    reset.add_argument("--pulse-ms", type=int, default=120, help="RESET assertion time")
    reset.add_argument("--after-ms", type=int, default=250, help="delay after RESET release")
    reset.set_defaults(func=cmd_reset)

    bootloader = sub.add_parser("bootloader", help="assert BOOT, pulse RESET, then enter ROM download mode")
    bootloader.add_argument("--pulse-ms", type=int, default=120, help="RESET assertion time")
    bootloader.add_argument("--after-ms", type=int, default=250, help="delay after RESET release")
    bootloader.add_argument("--hold-boot", action="store_true", help="keep BOOT asserted after RESET release")
    bootloader.add_argument("--hold-ms", type=int, default=0, help="hold the final state before closing")
    bootloader.set_defaults(func=cmd_bootloader)

    app = sub.add_parser("app", help="release BOOT and pulse RESET to boot normal firmware")
    app.add_argument("--pulse-ms", type=int, default=120, help="RESET assertion time")
    app.add_argument("--after-ms", type=int, default=250, help="delay after RESET release")
    app.set_defaults(func=cmd_app)

    run = sub.add_parser("run", help="perform a sequence, close the port, then run another command")
    run.add_argument("sequence", choices=("bootloader", "app", "reset"), help="sequence to perform before running command")
    run.add_argument("--pulse-ms", type=int, default=120, help="RESET assertion time")
    run.add_argument("--after-ms", type=int, default=250, help="delay after RESET release")
    run.add_argument("command", nargs=argparse.REMAINDER, help="command after --, for example: -- idf.py -p <data-port> flash")
    run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, serial.SerialException, ValueError) as exc:
        print(f"uart boot control failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
