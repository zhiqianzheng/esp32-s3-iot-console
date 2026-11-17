# ESP32 传感器工作台

本地 Linux 桌面上位机，Python 3 + Tkinter + pyserial。通过 USB COM 串口接收 ESP32-S3 的真实数据，不需要浏览器、网络或云服务。

## 启动

应用菜单搜索「ESP32 传感器工作台」，或执行：

```bash
cd /home/cian/workspace/esp32
bash tools/start-dashboard.sh
```

选择对应的 COM 口，点击「连接设备」。当前开发板的稳定路径：
`/dev/ttyACM0`。
也可执行 `bash tools/start-dashboard.sh --port /dev/ttyACM0` 自动连接。

同一串口不能同时被串口监视器和上位机占用。串口权限不足时，重新登录使已有 dialout 组配置生效；当前设备已授予本机用户访问权限。

## 界面功能

- 温度、相对湿度、透明通道C、有效数据帧数。
- RGBC原始计数、通道条形显示和相对颜色预览。
- 颜色、温湿度最近120秒趋势，曲线最多保存240个采样点，长时间断点不连接。
- 每个传感器独立显示状态、读取失败数；断开、错误或超时后清除对应实时读数。
- 颜色面板「开灯／关灯」控制GPIO10，等待开发板回执再显示已开/已关，3秒无匹配回执提示超时。
- 「开始 CSV 记录」选择本地文件；每个传感器包写一行，逐行落盘，停止或关窗时关闭文件。
- CSV包含本机接收时间与时区、传感器类型、状态、数值及错误；失败行不填入旧数值。

颜色预览仅按RGB通道最大值缩放，不是校准后的物体颜色；未实现照度/CCT换算、白平衡标定或颜色分类。温湿度曲线共用0～100刻度，单位分别为°C、%RH。

## 固件和接线

配套固件：`projects/tcs34725/`，已整合DHT11。

| 传感器 | 模块接口 | ESP32-S3 |
|---|---|---|
| 颜色模块 | VIN / GND | 3V3 / GND |
| 颜色模块 | SDA / SCL | GPIO9（J1第15脚） / GPIO8（J1第12脚） |
| DHT11 | VCC / GND / DATA | 3V3 / GND / GPIO4 |
| 颜色模块 | LED | GPIO10（J1第16脚），从原GND连接移出 |

当前颜色芯片实测ID=0x4D，官方手册对应TCS34727。颜色采样100.8ms积分、4倍增益，每0.5秒上报；DHT11每约2.5秒采样。GPIO14保持低电平，不启动舵机PWM。上位机关闭只停止电脑采集，板子固件继续采样。

## 串口协议

UART0 / 115200 / 8N1。忽略普通日志，仅解析以 `SENSOR_JSON:` 标识的JSON行。例如下面两行仅作格式示例：

```text
SENSOR_JSON:{"type":"color","status":"ok","id":77,"c":1000,"r":400,"g":300,"b":200,"saturated":false,"ok":1,"fail":0}
SENSOR_JSON:{"type":"dht","status":"ok","temperature":23.5,"humidity":51.0,"ok":1,"fail":0}
```

错误帧 `status=error`，提供 `error` 字段，不携带假测量值。USB断开由接收线程处理，连接下一次会清空历史和会话计数；不会自动重新打开已断开的设备，需重新点击连接。

## 安装与验证

本机环境已装在本目录 `.venv/`；仅额外依赖 pyserial 3.5。

```bash
python3 -m venv host/sensor-dashboard/.venv
host/sensor-dashboard/.venv/bin/python -m pip install -r host/sensor-dashboard/requirements.txt
host/sensor-dashboard/.venv/bin/python -m unittest discover -s tests -v
```

系统需有Tkinter（Ubuntu包python3-tk）。测试通过伪终端验证真实串口接收线程→协议解析→界面卡片→CSV，以及错误帧、超时和断开重连。实际板卡接入记录见 `logs/dashboard-live-state.json`，界面截图见 `logs/dashboard-preview.png`。

## 补光灯双向控制

模块LED已由用户接到GPIO10/J1第16脚。GPIO10为开漏输出：拉低关灯，释放后由模块上拉开灯；上电默认关闭。传感器INT引脚仍不接。不要将LED继续同时短接GND，否则软件释放GPIO也不能开灯。

串口命令为换行结束的 `LED ON`、`LED OFF`、`LED STATUS`。固件返回 `SENSOR_JSON:{"type":"led","status":"ok","on":false,"gpio":10}`，并约每2秒报告当前控制状态。回执代表GPIO控制状态，实物灯是否亮还取决于接线。

上位机按钮等待匹配回执；失败不会假显示命令已成功。断开连接后状态变为未确认，断开本身不会修改板上灯状态；复位后默认关闭。CSV中LED状态帧单独一行，`led_on`字段记录布尔状态。

本机实测：关灯C约290，开灯约3450，再关灯回到约290，开关命令均有回执。见 `logs/led-control-hardware-test.json`。该对比仅验证开关效果，不是光强标定。

## 板载炫彩呼吸灯

新增「板载 RGB 呼吸灯 · GPIO48」面板，与颜色模块GPIO10白色补光灯独立。

- 模式：单色呼吸、多色渐变呼吸、彩虹呼吸、关闭。
- 点击编号色块打开选色器；「＋颜色」添加、「−末色」删除，调色板支持1～8色。单色使用第1色，多色按调色板顺序平滑循环；彩虹模式自动遍历色相。
- 频率0.05～2Hz，表示完整变亮变暗周期，界面同步显示周期秒数；例如0.25Hz为4秒一周期，1Hz为1秒一周期。
- 峰值亮度0～100%。编辑完成点击「应用到开发板」；「关闭彩灯」只关闭板载RGB灯。
- 界面等待携带匹配request的设备回执后确认生效；超时/错误不会假显示成功。设备周期回报不会覆盖尚未应用的编辑。
- 设置保存在板子运行内存中；重新连接上位机会读取当前设置，板子复位后恢复默认6色渐变、0.25Hz、35%峰值，不写入Flash。

串口命令：`RGB STATUS` 或 `RGB SET {"mode":"multi","frequency":0.25,"brightness":35,"colors":["#FF0000","#0000FF"],"request":123}`，换行结束。
状态帧type=rgb、status=ok，含配置、request、revision及最近输出的pixel RGB/phase。pixel是软件发给灯的值，不是光学传感器反馈。无效参数返回status=error并保持原设置。RGB状态独立记录CSV的rgb_mode/rgb_frequency_Hz/rgb_brightness_pct/rgb_colors字段。

板载RGB光可能影响附近颜色传感器的环境光测量；需要稳定环境光数据时可在上位机关闭彩灯。


## 舵机和网络控制

控制区现分为RGB、舵机、Wi-Fi三个标签页。舵机支持单次目标角度、±单步、持续往返、上下限、往返周期、单次速度、PWM频率和停止。单步默认5°，持续运行默认60～120°；参数只在点击执行时应用。PWM频率范围40～60Hz，通常使用50Hz。显示角度为控制指令，并非实测位置。停止按钮无需填写合法参数，可优先取消排队的动作；5秒失去控制来源心跳后设备自动停止PWM。

Wi-Fi页可经USB写入2.4GHz名称和密码并重启；不改变已配对的云端密钥。网络状态区分别显示Wi-Fi连接、校时、云端异常和云端在线。

公网网页：https://console.example.com 。账户由部署运行环境配置，未写进前端源码。目前通过本机TLS Wi-Fi网关，真实数据上传与公网远程控制均已验证。开发板直接访问托管入口仍会收到HTTP403浏览器挑战。电脑需保持开机、联网并运行网关；USB桌面功能不依赖云端，关闭桌面程序也不影响网关。


网关后台服务：`systemctl --user status esp32-wifi-cloud-gateway.service`。已启用用户登录后自动启动，出错自动重启。正常使用无需打开终端。停止网关会使设备云端离线，恢复可执行`systemctl --user start esp32-wifi-cloud-gateway.service`。当前电脑LAN IP为192.168.1.100；如果地址改变，网关证书与设备配置需要同步调整。
