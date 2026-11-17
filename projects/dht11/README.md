# DHT11 温湿度读取

接线：模块 VCC → ESP32-S3 3V3，DATA → GPIO4，GND → GND。
按模块实际丝印确认引脚顺序。三针模块通常带上拉；若没有，DATA 与 3V3 间需接 4.7kΩ～10kΩ 上拉电阻。

在工作区根目录执行：

```bash
source tools/activate.sh
idf.py -C projects/dht11 build
idf.py -C projects/dht11 -p /dev/ttyACM0 flash monitor
```

烧录会将板上的应用程序替换为本示例。如果连接下载失败，按住 BOOT、短按 RESET/EN，再松开 BOOT 后重试。USB 串口编号可能改变，以当前设备为准。按 Ctrl+] 退出监视器。

程序使用 USB Serial/JTAG 控制台，DATA 为 GPIO4。上电等待 2 秒，之后每 2.5 秒读取一次。
DATA 使用开漏输出和输入，先拉低至少 18ms，然后释放总线并测量响应脉冲；仅在读取响应的约 4ms 内禁止本核任务切换，以降低时序误差。
每帧读取 5 字节并验证校验和，成功才输出温湿度。

输出示例（仅格式示例，不代表实测）：

```text
DHT11: Temperature: 25.0 C | Humidity: 50.0 %RH | OK=1 FAIL=0
```

出现 `ESP_ERR_TIMEOUT phase=0` 表示未检测到传感器响应，检查供电、接地、GPIO4、模块实物针脚顺序和上拉。
出现 `ESP_ERR_INVALID_CRC` 表示数据校验失败，优先检查接触、过长导线和上拉。
本示例不启用 Wi-Fi 和 PSRAM。

## 本机实测结果

已烧录并运行，连续读取到第 11 帧时失败次数为 0，温度约 27.4°C、湿度约 49%RH。
这是调通时的现场读数，不是精度校准结果。串口记录见 `logs/dht11-readings-live.log`。
本机原始固件全量备份见 `downloads/backups/original-esp32s3-8MB-before-dht11.bin`。

USB 重新枚举后的串口为 `/dev/ttyACM1`，稳定设备路径为
`/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_C4:9E:7E:02:36:10-if00`。
在工作区根目录运行以下脚本即可实时查看，不主动复位板子：

```bash
bash tools/monitor-dht11.sh
```

退出监视器按 `Ctrl+]`。同一串口同时只开一个监视器。

## GPIO14 舵机往返测试

当前固件同时读取 DHT11 和控制三线位置舵机：

- 舵机信号线 → J1 第 20 脚 GPIO14。
- 舵机电源线 → 额定 5V 电源；当前用户接 J1 第 21 脚 5V。
- 舵机地线 → J1 第 22 脚 GND；独立电源供电时需与板子共地。

舵机控制源码：`main/servo.c`。使用 LEDC 低速模式、定时器 0、通道 0，频率 50Hz，14 位占空比分辨率。PWM 由硬件持续生成，不依赖软件延时产生脉冲。

上电先输出 1500µs 中位并等待 2 秒，然后在 833µs～2167µs 之间反复缓慢往返（按用户说明书的 500µs～2500µs 对应 0°～180°，名义约 30°～150°）。每 20ms 调整约 10µs，到端点停 2 秒。

实际角度取决于舵机校准和舵盘安装位置，串口只记录发出的 PWM 指令，没有角度反馈。默认不测试机械行程两端。需要停止时断开舵机电源；退出串口监视器不会停止运动。

直接占空比更新使用 `ledc_set_duty()` 加 `ledc_update_duty()`，仅舵机任务访问该通道，不依赖 fade 服务。
若出现供电相关重启或抖动，应改用容量满足舵机要求的独立 5V 电源，保持共地。

## 当前停止状态

用户要求停止后，`main/servo.c` 中 `SERVO_ENABLED` 已设为 0，启动时 GPIO14 输出低电平，不初始化 PWM、不创建往返任务；温湿度读取继续运行。需要再次启动时将其改为 1，重新编译烧录。停止 PWM 不等于切断舵机电源。

## 最近状态更新

用户要求再次启动：`SERVO_ENABLED=1`，已重新编译烧录，恢复 GPIO14 的 30°～150°往返，端点停 2 秒。此前停止状态已解除。

## 供电排查暂停固件（当前）

用户要求暂停应用以测供电：`APPLICATION_PAUSED=1`、`SERVO_ENABLED=0`。已通过 1a86 COM 接口烧录并校验。启动后 GPIO14 设置为输出低电平，app_main 随即返回，不启动舵机任务或 DHT11 采样。复位后仍保持此状态。GPIO14 的低电平不是舵机断电；隔离信号影响时可以物理断开橙线。
