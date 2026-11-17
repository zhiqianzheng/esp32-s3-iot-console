# TCS34725 / ESP32-S3 颜色采集

接线：模块 VIN → 板子3V3，GND → GND，SDA → GPIO9（用户排针图 J1 第15脚），SCL → GPIO8（J1 第12脚）。模块3V3、INT暂不接，LED接GPIO10/J1第16脚。以实物丝印和模块资料为准。

本项目独立于此前 DHT11/舵机工程。启动后 GPIO14 保持低电平，不输出舵机 PWM，已整合 GPIO4 的 DHT11 采样。

使用 ESP-IDF v6.1.1 的硬件 I²C 主机驱动，100kHz，扫描7位地址并查找0x29，读取ID寄存器0x12；官方手册中0x44对应TCS34725，0x4D对应TCS34727。配置100.8ms积分时间、4倍增益，每500ms输出16位 C/R/G/B 及 R/C、G/C、B/C 比值。比值不是经过标定的显示RGB或颜色名称。

主要寄存器依据：`docs/sensors/TCS34725/TCS3472_DS000390_datasheet_en.pdf`。寄存器访问设置命令位0x80；连续读取额外设置自动递增位0x20；数据从0x14按小端读取C、R、G、B。

通过板上 COM 接口（1a86 USB串口）输出 UART0 日志，115200波特率。按 Ctrl+] 退出实时监视器。

```bash
source tools/activate.sh
idf.py -C projects/tcs34725 build
idf.py -C projects/tcs34725 -p /dev/ttyACM0 flash monitor
```

初次验证先观察芯片ID和原始读数；用手遮挡、靠近白纸及红绿蓝物体，应看到光强和各通道比例变化。保持距离、补光与环境光一致后再做颜色识别标定。出现 SATURATED 时需降低增益/积分时间或光照；DARK 表示光量低。若地址0x29无响应，先断电检查供电和接线，再测模块内部3V3节点电压。

## 本机实测（当前接线）

最初约定SDA8/SCL9未应答。增加约10kHz开漏地址探测后，原方向0/3应答，交换方向3/3应答。因此代码已适配用户实际接线：SDA=GPIO9、SCL=GPIO8，用户无需改线。若日后按最初约定重新接线，要同步调整宏定义。

100kHz硬件I²C扫描发现0x29，读到ID=0x4D；官方手册对应TCS34727（与商品标题TCS34725不同，记录实测ID，不仅凭标题确定芯片）。当前兼容寄存器配置后RGBC连续17次读取成功、失败0次。示例现场读数：C=6700、R=2022、G=2577、B=1368。未做颜色标定。

诊断记录：`logs/tcs34725-diagnostic-runtime.log`；成功记录：`logs/tcs34725-verified-runtime.log`。
实时查看：在工作区根目录执行 `bash tools/monitor-color.sh`。

## 上位机集成

当前固件同时采集 GPIO4 的DHT11，通过 UART0发送 `SENSOR_JSON:` JSON帧。桌面程序在 `host/sensor-dashboard/`，启动 `bash tools/start-dashboard.sh`。GPIO14默认停止PWM，通过SERVO命令启用。

## 补光灯控制

`main/led_control.c` 使用GPIO10开漏控制LED，默认拉低关闭，通过UART0接收LED ON/OFF/STATUS命令并回执。新固件依赖esp_driver_uart，安装UART0接收驱动；颜色和温湿度采集不受开关命令影响。

## 板载呼吸灯

`main/breathing_led.c` 使用GPIO48驱动厂家说明中的WS2812，RMT硬件10MHz产生GRB时序，单颗灯的蓝色分量0～64/255，20ms刷新，周期4秒，使用平滑曲线变亮变暗。与GPIO10补光灯、GPIO14舵机独立。灯光可能影响附近颜色传感器的环境光读数。用户已短接IN-OUT焊盘，确认板上5V可驱动当前舵机；USB-OTG焊盘未改动。

## 可配置炫彩呼吸灯（当前）

GPIO48 WS2812现支持single/multi/rainbow/off模式、0.05～2Hz呼吸频率、0～100%峰值亮度、1～8色调色板。RGB SET命令由led_control.c接收，breathing_led.c使用espressif/cjson组件校验后原子更新配置，RMT每20ms发送1颗灯的GRB数据。颜色过渡使用平滑插值，亮度使用余弦曲线并平方调整；多色每个呼吸周期过渡到下一个调色板颜色，彩虹3个呼吸周期遍历一次色相。配置切换从暗端开始。

此配置与补光GPIO10、舵机GPIO14分开。颜色和温湿度继续采集。配套上位机RGB面板可配置，无需重新烧录。配置不写入NVS；重启默认多色、0.25Hz、35%。组件版本锁在dependencies.lock，managed_components为自动下载依赖。


## 舵机与Wi-Fi云端（当前）

GPIO14由LEDC输出，支持单次定位、相对单步、持续往返、40～60Hz PWM、到位保持与停止。显示的是指令角度，没有编码器实测反馈。默认禁用；通信心跳丢失5秒后停止PWM。USB和云端各有控制来源，USB心跳不会延长云端来源的运行租期。停止命令可从任意来源发出。实板验证记录见根目录logs/servo-hardware-verification.json。

Wi-Fi配置和设备密钥由USB写入NVS，不编入源码。只支持2.4GHz；使用SNTP校时、证书包验证HTTPS，约每秒上传缓存状态并接收控制命令。设备命令确认后回传ACK，服务器有命令有效期与启动标识隔离。应用分区扩大为3MB，保留原NVS地址。

公网网页已部署。托管入口会向ESP32直连返回HTTP403浏览器挑战，正式服务访问凭据也未消除挑战。当前已启用本机TLS Wi-Fi网关：ESP32经Wi-Fi访问192.168.1.100:8743，电脑网关转发到公网；实际传感器数据和控制ACK已验证，见logs/cloud-real-device-lighting-tests.json及cloud-real-device-tests.json。电脑须保持开机、联网并运行网关，关闭桌面上位机不会停止网关。此方案未实现脱离电脑的独立云端直连。


`NET GATEWAY {"url":"https://192.168.1.100:8743"}`经USB保存TLS网关地址并重启；url为空字符串可关闭网关。网关服务器证书公钥位于main/gateway_ca.pem，由CMake嵌入固件；私钥仅在本机私有目录，不编入固件。域名/IP和证书验证均保留，未禁用TLS验证。电脑地址变化需重新配置URL及匹配证书。`NET SERVICE`可写入Sites官方服务访问凭据，该凭据仅向固定的本项目Sites域名发送，不转交本机网关。
