---
name: debug-usb-webcam
description: USB UVC 摄像头实时帧获取技能(Windows 主机 + WSL2)。覆盖 usbipd-win 的 bind/attach/detach 所有权切换、WSL 侧 /dev/video* 权限与 OpenCV/V4L2 抓帧、Windows 侧 DirectShow 抓帧、MJPG 帧率优化与多摄像头索引核对。当任务提到 webcam、摄像头、UVC、usbipd、/dev/video、V4L2、DirectShow、CAP_DSHOW、OpenCV 抓帧、实时画面/实时帧、摄像头被占用/看不到时使用。示例设备:Logitech Webcam C170(VID 046d:082b)。
---

# USB UVC 摄像头实时帧获取(Windows + WSL2)

用于让脚本/Agent 获取 USB 摄像头的实时帧,覆盖 Windows 与 WSL2 两条链路。核心机制:**usbipd-win 把 Windows 侧 USB 设备经虚拟网卡转发进 WSL2,设备同一时刻只能被一侧独占**;因此"摄像头在哪一侧能看到"完全由 usbipd 的 attach/detach 状态决定。

## 一、先确认设备(每次操作前必做)

```bash
"/mnt/c/Program Files/usbipd-win/usbipd.exe" list
```

输出示例(字段会因机器不同而变化):

```text
Connected:
BUSID  VID:PID    DEVICE                                      STATE
<x-x>  046d:082b  Webcam C170                                 Shared        # 已绑定未附加
<x-x>  3277:0033  USB2.0 FHD UVC WebCam, ...                  Not shared    # 未绑定,归 Windows
```

核对三件事:

1. **BUSID 会因重新插拔/换端口变化,绝不写死**;以本次 `list` 输出为准。
2. **VID:PID + 型号**才是设备的稳定身份(如 `046d:082b` = Logitech C170)。
3. **STATE 决定归属**:
   - `Not shared` = 纯 Windows 设备,未参与共享;
   - `Shared` = 已 bind(绑定,权限已登记),仍归 Windows 使用;
   - `Attached` = 当前被 WSL 占用,Windows 端软件(相机 App、OpenCV)看不到它。

> 同一台机器可能同时有多个摄像头(内置 + 外接),务必用 VID:PID 区分目标设备。

## 二、Windows ↔ WSL 所有权切换

在 **Windows 管理员 PowerShell/CMD** 执行:

```powershell
usbipd attach --wsl --busid <busid>   # 交给 WSL:WSL 出现 /dev/video0
usbipd detach --busid <busid>         # 还给 Windows:WSL 的 /dev/video* 消失
usbipd bind --busid <busid>           # 登记绑定(一次性,persisted);attach 前通常需 bind
usbipd bind --busid <busid> --force   # 存在不兼容 filter 时强制绑定
```

原理:attach 时 usbipd 通过 WSL 虚拟网卡(如 `<host_ip>` 一类地址,以实际输出为准)把 USB 设备封装转发给 WSL,因此**转发是网络路径,存在带宽与延迟开销**;detach 后设备回到 Windows,`/dev/video*` 节点随即消失。

纪律:

- **attach 前先确认 Windows 侧没有程序正在用该摄像头**(相机 App、会议软件),否则 attach 会抢走设备。
- **detach 前先确认 WSL 侧没有进程占用**(未 release 的 VideoCapture 会导致 detach 失败或残留)。
- 想永久共享、每次自动 attach:用 `usbipd bind` 后配合 `--auto-attach` 选项(需要时再查 usbipd 文档)。

## 三、WSL 侧抓帧(链路 A)

### 1. 权限(最常见的坑)

WSL 中 usbip 附加的摄像头节点默认属主 `root:video`,权限 `660`,普通用户不在 `video` 组则打不开:

```bash
sudo usermod -aG video $USER   # 永久方案:加入 video 组(重新登录后新 shell 自动生效)
sudo chmod 666 /dev/video0 /dev/video1   # 临时方案:改节点权限,detach 重建节点后失效
```

注意 `usermod` 对**当前已登录的进程组不生效**,可在单次调用内用 `sg video -c "..."` 获取组权限,或重新打开终端。

### 2. 安装 OpenCV(WSL 为 Ubuntu 24.04 时受 PEP 668 保护)

```bash
python3 -m venv /tmp/camvenv            # 推荐 venv,避免污染系统环境
/tmp/camvenv/bin/pip install opencv-python-headless numpy
```

### 3. 抓帧脚本(见 `scripts/capture_frame.py`)

```bash
/tmp/camvenv/bin/python scripts/capture_frame.py /dev/video0 /tmp/frame.jpg
```

要点:

- 打开设备用 `cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)`。
- **必须显式设置 MJPG 压缩格式**,否则协商为 YUYV 裸流,帧率暴跌(见第五节)。
- 预热 10~30 帧再取帧,摄像头需要时间稳定出图。

## 四、Windows 侧抓帧(链路 B)

先 `usbipd detach` 把摄像头还给 Windows,然后:

```powershell
python -m pip install --user opencv-python        # GUI 版,支持 imshow 预览
# 或 headless 版(无窗口,只能 imwrite 存图):opencv-python-headless
```

脚本要点(见 `scripts/win_capture.py`):

- 打开设备用 `cv2.VideoCapture(idx, cv2.CAP_DSHOW)`(DirectShow)。
- **索引 0,1,2... 不固定**:多个摄像头时顺序取决于枚举,先扫描能打开的索引,再用 `Get-PnpDevice -Class Camera | Select FriendlyName, InstanceId` 与抓帧画面核对。
- `cv2.CAP_DSHOW` 后端按索引打开失败会快速返回,扫描 0~5 即可覆盖常见情况。
- headless 版没有 `cv2.imshow`;预览请装 GUI 版 `opencv-python`(会替换 headless)。

## 五、帧率与带宽(usbip 转发是关键瓶颈)

实测规律(适用于通过 usbipd 转发的 UVC 摄像头):

| 配置 | 实际帧率 | 说明 |
|---|---|---|
| 默认(YUYV 裸流)640x480 | ≈5 fps | 未压缩带宽大,usbip 网络转发成瓶颈 |
| MJPG 640x480@30 | ≈25 fps | 传感器端压缩,带宽降一个量级 |
| MJPG 320x240@30 | ≈29 fps | 接近标称 |
| MJPG 1280x720 | ≈4 fps | 分辨率再高仍受转发带宽限制 |

- 设置方法:`cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))`,同时设宽高与 FPS。
- usbip 转发 MJPG 时可能刷 `Corrupt JPEG data: premature end of data segment` 警告——转发截断所致,通常仍能解码出帧,可忽略;若频繁黑帧再考虑降低分辨率。
- Windows 原生 DirectShow 链路不受 usbip 转发影响,帧率可达标称值。

## 六、实时性验证方法

避免"拿到的是重复帧"的假象,抓多帧后校验:

```python
import hashlib
hashes = {hashlib.md5(f.tobytes()).hexdigest()[:12] for _, f in ...}
len(hashes)  # >=2 说明画面确实在变化,是真实传感器流
```

静止场景下帧间像素差会很小,不能据此判断"非实时";帧内容哈希 + 有效帧率(计时读 N 帧)才是可靠证据。

## 七、实测注意(踩过的坑)

1. **WSL 里没有 /dev/video\* 时,先查 usbipd STATE**:`Not shared` 说明根本没 attach;`Attached` 但无节点则查 udev/权限。
2. **权限两步缺一不可**:只有 attach 没有 `usermod/chmod`,OpenCV 报 `Permission denied` / `can't be used to capture by name`。
3. **attach 后 Windows 端"消失"是正常现象**:相机 App 打不开或枚举不到,先 detach。
4. **cv2 的 V4L2 后端按路径打开失败**时报 `VIDEOIO(V4L2): backend is generally available but can't be used to capture by name`,多半是权限,先查 `ls -l /dev/video*`。
5. **多摄像头时 DirectShow 索引不确定**,别写死 0;用扫描 + 抓帧核对。
6. **headless 与 GUI 版 OpenCV 互斥**,装 GUI 版会卸载 headless。
7. **usbipd 存在不兼容 filter(如 hrdevmon)时,bind 需 `--force`**,attach 前留意 warning。
8. **帧率不达标先查格式**:YUYV→MJPG 是性价比最高的修复,不要急着调分辨率。

## 参考

- 本地验证证据与官方来源见 `references/source-map.md`。
- 脚本:`scripts/capture_frame.py`(WSL/V4L2 抓帧)、`scripts/win_capture.py`(Windows/DirectShow 抓帧)。
