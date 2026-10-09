# 源与证据索引

## 脚本来源

- 控制器本体:宿主工程(WSL 侧 ESP 工程)`tools/uart_boot_control.py`,配套 bash wrapper `uart_boot_control.sh`(`--CMD BOT/RST/STA`、`flash`、`run bootloader -- ...`)
- 本技能副本:`scripts/uart_boot_control.py`(2026-09-28 同步)
- 副本相对上游的差异(整改,勿回退):
  1. `-p/--port` 改为必填,不绑定任何默认端口号;
  2. 移除源码注释中的工程/台架特定字样。
  上游脚本更新时需重新同步并保持这两点。

## 判别与验证方法

- 端口判别:RTS 按住静默法(`lines --rts 1 --hold-ms 1200` + 观察目标数据口日志流)、esptool `--before no_reset` 旁证,详见 SKILL.md"端口判别"。
- 进下载模式判据:目标数据口出现 `boot:0x2x (DOWNLOAD...)` + `waiting for download`,且 `esptool --before no_reset --after no_reset flash_id` 成功。
- 原始实测日志(具体台架的端口映射、抓包输出)不随本技能分发。
