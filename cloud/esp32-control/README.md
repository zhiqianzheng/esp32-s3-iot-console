# ESP32 云端传感器控制台

ESP32-S3通过HTTPS主动同步传感器状态并收取指令；浏览器可从公网访问，不需要设备端口映射。配套固件与桌面程序位于父级工作区的projects/tcs34725和host/sensor-dashboard。

## 功能

- 用户名/密码登录，HttpOnly会话Cookie；用户名和密码由Sites生产环境变量配置，不写入网页源码。
- 颜色RGBC、DHT11、设备在线状态、历史趋势与CSV导出。
- 板载WS2812的单色/多色/彩虹呼吸、频率、亮度和调色板。
- GPIO10补光灯开关。
- GPIO14舵机的单次定位、单步增减、持续往返、PWM频率、速度和停止输出。
- 控制指令有过期时间、设备启动隔离、回执与记录；设备离线时不排队执行新动作。
- 云端与串口控制来源区分；对应控制链路超过5秒未维持通信，舵机停止PWM。网页隐藏会停止更新云端控制租约。

## 运行与存储

由Sites托管Cloudflare Worker，D1表结构在db/schema.ts，迁移在drizzle/。
生产变量：ADMIN_USERNAME、ADMIN_PASSWORD（secret）、DEVICE_KEY（secret）、DEVICE_ID。
设备密钥仅供设备API使用，不能用作网页登录；网页不包含设备密钥。

设备接口POST /api/device/sync，需要Bearer设备密钥；浏览器接口/api/snapshot和/api/command要求登录。/api/control/heartbeat维持当前浏览器的舵机控制租约。
历史保留约6小时，网页最多展示最近240个历史点，设备上报间隔约1秒（受网络耗时影响），历史约5秒存一次。

## 开发检查

使用Sites技能提供的安装、构建、包装和发布脚本。源码及产物提交后再发布，不将本地测试.env或.dev.vars上传。

- npm run db:generate：只在修改schema后生成新迁移，不编辑已应用迁移。
- npx tsc --noEmit：类型检查。
- scripts/qa-api.mjs：使用忽略的.dev.vars测试环境检查鉴权/指令/回执；仅针对隔离的本地数据库。
- scripts/qa-browser.mjs：本地Chrome CDP桌面与移动布局检查。

根工作区logs/保存构建和实机验证记录；本地测试数据不代表真实设备上报。

## 当前设备通信链路

实测托管入口会向ESP32直连请求返回HTTP403浏览器挑战，平台服务凭据也未解除该挑战。当前使用用户电脑上的TLS Wi-Fi网关：ESP32 → 局域网HTTPS → 本机网关 → 公网HTTPS → 本站。所有测量和指令ACK均来自真实设备，网关不读取USB串口、不模拟数据。

本机网关由systemd用户服务esp32-wifi-cloud-gateway.service运行，可独立于桌面上位机工作。电脑必须保持开机、联网并运行网关；当前LAN地址192.168.1.100:8743。TLS服务器证书公钥嵌入设备，私钥仅存电脑的私有配置目录，不进入项目或网页。网关只转发本项目的设备同步接口，云端仍验证Bearer设备密钥。

公网网页可以在其他网络访问；开发板与网关需处于互通的局域网。若电脑IP改变，需更新设备网关URL和对应证书；这不是开发板脱离电脑独立连接云端的最终方案。
