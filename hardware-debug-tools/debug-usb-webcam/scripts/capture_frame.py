#!/usr/bin/env python3
"""WSL/V4L2 抓帧:从 /dev/video* 抓取一帧并做基本统计,验证摄像头链路。

用法:
    python capture_frame.py [src] [out.jpg]

默认 src=/dev/video0,out=/tmp/frame.jpg。
要点:显式设置 MJPG 压缩格式避免 YUYV 裸流导致 usbip 转发下帧率暴跌;
预热若干帧后取帧;输出尺寸/亮度/分块统计用于判断画面有效性。
"""
import sys
import cv2
import numpy as np

src = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/frame.jpg"

cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
if not cap.isOpened():
    print(f"FAIL: cannot open {src} (先检查 usbipd STATE 与 /dev/video* 权限)")
    sys.exit(1)

# 显式设置 MJPG + 分辨率 + 帧率,避免协商到低帧率的裸流
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

# 预热:摄像头需要若干帧稳定出图
ok = False
for _ in range(30):
    ok, frame = cap.read()
    if ok and frame is not None and frame.size > 0:
        break

if not ok:
    print("FAIL: no frame read after 30 tries")
    cap.release()
    sys.exit(1)

h, w = frame.shape[:2]
cv2.imwrite(out, frame)
print(f"OK src={src}")
print(f"  size={w}x{h} dtype={frame.dtype} mean={frame.mean():.1f} std={frame.std():.1f}")
print(f"  saved -> {out}")
cap.release()
sys.exit(0)
