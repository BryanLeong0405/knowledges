#!/usr/bin/env python3
"""Windows/DirectShow 抓帧:扫描摄像头索引 0..5,抓帧保存并打印统计。

用法(需先 usbipd detach 把摄像头还给 Windows):
    python win_capture.py [outdir]

多摄像头时 DirectShow 索引顺序不固定,本脚本扫描所有可打开索引并各自
保存一帧;用 Windows PowerShell `Get-PnpDevice -Class Camera` 与画面内容
核对哪个索引是目标摄像头。GUI 预览请安装 opencv-python(带 imshow);
本脚本仅存图,headless 版也可运行。
"""
import os
import sys
import cv2
import numpy as np

outdir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
os.makedirs(outdir, exist_ok=True)

results = []
for idx in range(0, 6):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        results.append((idx, "open-fail"))
        continue
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    ok = False
    frame = None
    for _ in range(30):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size > 0:
            break
    if not ok:
        results.append((idx, "read-fail"))
        cap.release()
        continue
    h, w = frame.shape[:2]
    path = os.path.join(outdir, f"win_frame_{idx}.jpg")
    cv2.imwrite(path, frame)
    results.append((idx, f"OK {w}x{h} mean={frame.mean():.1f} std={frame.std():.1f} -> {path}"))
    cap.release()

for idx, msg in results:
    print(f"index={idx}: {msg}")
