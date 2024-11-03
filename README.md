# aTrustLogin

本项目提供了一个自动化的深信服 Sangfor aTrust 登录的解决方案，无需人工干预即可实现 VPN 联网。项目功能如下：

- 自动打开 aTrust Web 登录页面
- 自动填写用户名和密码
- 自动利用密钥推导 TOTP 两步验证并填写
- 使用 Cookie 状态绕过验证码
- KeepAlive 连接保活和掉线/登出重连
- 支持 Windows、Linux，支持 x86-64 和 ARM64

## 使用方法
本项目提供Docker方法和通用方法两种方法。

Docker 方法只适用于 Linux 平台，但无需安装配置任何依赖，全自动运行，只需安装 Docker 即可。非常适合软路由、工控机等无图形界面的环境使用。

通用方法适合于所有平台，但需要手动安装 Python 3.8+ 和 Selenium 等依赖库。如果有条件，请使用 Docker 方法。

### 通用方法

首先需要配置浏览器。

在 Windows 下，默认使用系统自带的 Microsoft Edge 浏览器，因此对于 Windows 10 1903+、Windows 11 通常不需要额外安装浏览器和浏览器驱动。如果需要使用其他浏览器，请参考 [Selenium 文档](https://www.selenium.dev/documentation/en/webdriver/driver_requirements/) 安装对应的浏览器驱动。

在 Linux 下，需要安装 Chromium 浏览器。Debian/Ubuntu 可以使用 `apt-get install -y chromium chromium-driver chromium-l10n` 命令直接安装。

然后，下载本项目，安装依赖库。提供国内地址和国外地址两个下载方法。如果国外地址下载缓慢，可以使用国内地址：

国外地址：

```shell
# 如果下载缓慢，可以替换为国内地址 （见后文）
git clone --depth=1 https://github.com/kenvix/aTrustLogin.git aTrustLogin
cd aTrustLogin/src
pip install -r requirements.txt
```

国内地址：

```shell
git clone https://www.modelscope.cn/kenvix/aTrustLogin.git
cd aTrustLogin/src
pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/web/simple
```

然后按照 “程序运行参数说明” 章节启动程序即可。

### 程序运行参数说明

各参数的说明如下：

- `--portal_address`：VPN 门户地址（URL）。例如 https://atrust.moe.edu.cn/
- `--username`：VPN 用户名。
- `--password`：VPN 密码。
- `--totp_key`：TOTP 密钥，用于双因素验证（可选，如果不需要双因素验证则无需提供）。
- `--cookie_tid`：用于会话追踪的 cookie ID（可选，用于绕过图形验证码）。具体见后文
- `--cookie_sig`：用于会话追踪的 cookie 签名（可选，用于绕过图形验证码）。具体见后文
- `--keepalive`：可选。会话保持时间（秒），每隔几秒后刷新页面检查是否掉线。0 为禁用
- `--data_dir`：可选。存储 cookies 和会话数据的目录路径。
- `--driver_type`：可选。WebDriver 类型（如 "chrome" 或 "edge"）。
- `--driver_path`：可选。WebDriver 可执行文件路径。
- `--browser_path`：可选。浏览器可执行文件路径。
- `--interactive`：可选。是否启用交互模式。
- `--wait_atrust`：可选。是否等待 aTrust 在指定端口上监听。用于等待 atrust 启动。

示例：

```shell
python main.py --portal_address "https://example.com" --username "your_username" --password "your_password" --totp_key "your_totp_key" --cookie_tid "your_cookie_tid" --cookie_sig "your_cookie_sig" --keepalive 300 --interactive True --wait_atrust True
```

### Docker 方法

阅读“程序运行参数说明” ，然后请将程序参数填入 `ATRUST_OPTS` 环境变量中，然后运行 Docker 容器即可。

```shell
docker run -it --rm -e ATRUST_OPTS='--portal_address="门户地址" --username=用户名 --password=密码 --totp_key=TOTP密钥 --cookie_tid "your_cookie_tid" --cookie_sig "your_cookie_sig" --device /dev/net/tun --cap-add NET_ADMIN -ti -e PASSWORD=xxxx -e URLWIN=1 -v $HOME/.atrust-data:/root -p 127.0.0.1:5901:5901 -p 127.0.0.1:8888:8888 --sysctl net.ipv4.conf.default.route_localnet=1 --shm-size 256m  kenvix/atrust-autologin:latest
```

cookie_sig 和 cookie_tid 可以不必设置，如果不设置，首次登录会遇到验证码，但是可以通过 VNC 远程连接服务器（VNC 端口 5901 ），手动输入验证码，然后程序会自动保存 cookie，之后就不会再遇到验证码了。

shm 大小不建议小于 256M，否则可能导致浏览器崩溃。

Docker 容器基于 [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect) 构建，在此表达感谢。其他的 Docker 参数也可以在这里找到。

## 如何绕过图形验证码

在第一次登录时，aTrust 会要求输入验证码。为了避免每次登录都需要输入验证码，可以通过以下方法绕过：

1. 打开 aTrust 登录网页，登录并输入验证码
2. 在浏览器中打开开发者工具（F12），切换到 Application（应用程序） 选项卡
3. 在左侧导航栏中找到 Cookies，点击对应的网站地址
4. 找到名为 `tid` 和 `sig` 的两个 Cookie，将其值填入程序的 `--cookie_tid` 和 `--cookie_sig` 参数中
