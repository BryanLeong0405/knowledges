# debug-usb-webcam source map

## Local evidence and implementation

- Entry: `SKILL.md`
- Capture scripts: `scripts/capture_frame.py`(WSL/V4L2)、`scripts/win_capture.py`(Windows/DirectShow)
- Enumeration: `usbipd list`(每次运行必须动态核对 BUSID/VID:PID/STATE)

Verified baseline(示例设备,以实际枚举为准):

```text
<busid> / 046d:082b / Webcam C170 / Shared|Attached
WSL nodes: /dev/video0 + /dev/video1(UVC 主视频 + metadata 节点)
WSL permission: /dev/video0 -> crw-rw---- root:video(需加入 video 组或 chmod)
WSL capture: OpenCV 5.0 + CAP_V4L2,640x480x3 uint8
Windows capture: OpenCV + CAP_DSHOW,索引扫描 0..5,640x480
```

Measured frame rate over usbipd forwarding(供参考,随机器/链路变化):

```text
YUYV 640x480(default) -> ~5 fps
MJPG 640x480@30       -> ~25 fps
MJPG 320x240@30       -> ~29 fps
MJPG 1280x720         -> ~4 fps
```

## Official sources

- [usbipd-win(GitHub)](https://github.com/dorssel/usbipd-win):Windows 侧 USB over IP 服务端,`bind`/`attach`/`detach` 语义与权限要求
- [Microsoft Learn: WSL 中连接 USB 设备](https://learn.microsoft.com/en-us/windows/wsl/connect-usb):usbipd 在 WSL2 中转发 USB 设备的官方流程
- [OpenCV VideoCapture / CAP_DSHOW / CAP_V4L2](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html):后端与属性(CAP_PROP_FOURCC 等)文档
- [Linux UVC driver 文档](https://www.kernel.org/doc/html/latest/driver-api/usb/usb-video.html):/dev/video* 节点与 V4L2 能力说明

## Skill scope

- 只管"拿到实时帧":枚举、所有权切换、权限、抓帧、格式与帧率调优。
- 不涉及:视频编解码/推流、图像识别、多路同步、Windows 摄像头隐私设置、驱动安装。
