# aTrustLogin

[English Version](/README.en.md)

本项目提供深信服 Sangfor aTrust 的浏览器登录自动化，支持密码登录、TOTP 两步验证、会话保活，以及在浏览器中完成 SSO、CAS 或扫码认证。项目功能如下：

- 自动打开 aTrust Web 登录页面
- 自动填写用户名和密码
- 自动利用密钥生成并填写 TOTP 两步验证码
- 保存 Cookie 和会话状态
- KeepAlive 连接保活和掉线/登出重连
- 在浏览器或 VNC 中完成扫码、统一身份认证和人工验证
- 支持 Windows、Linux，支持 x86-64 和 ARM64；macOS 原生配置参见下方说明
- (Docker) 支持端口转发，容器暴露端口然后自动转发到指定地址

SSO、CAS、macOS 原生运行、TOTP 密钥、客户端启动和磁盘空间检查，参见[登录方式与运行维护](doc/login-and-troubleshooting.md)。

## 使用方法

本项目提供 Docker 方法和通用方法两种方法。

Docker 方法适用于 Linux 容器环境，镜像包含 aTrust 客户端、浏览器和 Python 依赖，适合软路由、工控机等无图形界面的环境使用。

通用方法需要在本机安装机构提供的 aTrust 客户端、Python 和项目依赖，并启动 aTrust 客户端。建议使用 Python 3.11。

### 通用方法

首先需要配置浏览器。

在 Windows 下，默认使用系统自带的 Microsoft Edge 浏览器。如果需要使用其他浏览器，请参考 [Selenium 文档](https://www.selenium.dev/documentation/en/webdriver/driver_requirements/) 安装对应的浏览器驱动，也可由 Selenium 管理驱动。

在 Linux 下，需要安装 Chromium 浏览器。Debian/Ubuntu 可以使用 `apt-get install -y chromium chromium-driver chromium-l10n` 命令直接安装。

macOS 使用 Chrome，必要时通过 `--browser_path` 指定 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`。

然后下载本项目，安装依赖库：

```shell
git clone --depth=1 https://github.com/kenvix/aTrustLogin.git aTrustLogin
cd aTrustLogin/src
python3 -m pip install -r requirements.txt
```

然后按照“程序运行参数说明”章节启动程序。

### 程序运行参数说明

各参数的说明如下：

- `--portal_address`：VPN 门户地址（HTTP 或 HTTPS URL）。例如 `https://atrust.moe.edu.cn/`。
- `--username`：VPN 用户名。与 `--password` 同时提供，或同时省略以在浏览器中完成认证。
- `--password`：VPN 密码。SSO、CAS 或扫码登录可同时省略用户名和密码。
- `--totp_key`：账号绑定的 TOTP 共享密钥，用于双因素验证（可选）。
- `--cookie_tid`：会话 Cookie ID（可选）。具体见后文。
- `--cookie_sig`：会话 Cookie 签名（可选）。具体见后文。
- `--keepalive`：可选。会话检查间隔，单位为秒，默认 `200`。`0` 表示完成一次登录后退出。
- `--data_dir`：可选。保存 Cookie、会话数据及容器浏览器日志的目录。
- `--driver_type`：可选。WebDriver 类型，如 `chrome` 或 `edge`。
- `--driver_path`：可选。WebDriver 可执行文件路径。
- `--browser_path`：可选。浏览器可执行文件路径。
- `--interactive`：可选。密码登录遇到人工验证时，在浏览器中等待完成验证，无需终端输入。Docker 默认开启。
- `--login_timeout`：可选。等待浏览器人工认证的最长时间，单位为秒，默认 `300`，必须大于零。
- `--wait_atrust`：可选。是否等待 aTrust 在本机 TCP 54631 端口监听，默认 `True`。
- `--client_timeout`：可选。等待客户端启动的最长时间，单位为秒，默认 `120`，必须大于零。
- `--disk_cache_size_mib`：可选。浏览器磁盘缓存容量提示，单位为 MiB，默认 `256`，必须为正整数。
- `--browser_log_size_mib`：可选。容器浏览器日志每个文件的轮换大小，单位为 MiB，默认 `20`，必须为正整数。
- `--browser_log_files`：可选。容器浏览器日志文件数量，包含当前文件，默认 `5`，必须为不小于 `2` 的整数。

密码登录示例：

```shell
python3 main.py --portal_address "https://example.com" --username "your_username" --password "your_password" --keepalive 300 --interactive True
```

使用 TOTP 时添加 `--totp_key "your_totp_key"`。SSO、CAS 或扫码登录示例：

```shell
python3 main.py --portal_address "https://example.com" --login_timeout 600
```

程序在浏览器认证完成后继续保活。服务端再次要求扫码、短信验证码或其他人工认证时，仍需完成相应验证。

### Docker 方法

首先使用下面的命令拉取镜像：

```shell
# 拉取最新版本；下载缓慢时可以使用国内地址
docker pull kenvix/docker-atrust-autologin:latest
```

Docker 镜像如果下载缓慢，可以替换为国内地址。下载后使用 `xz -dc 文件名.tar.xz | docker load` 命令导入镜像。

国内地址请参见：https://modelscope.cn/models/kenvix/aTrustLoginRepo/files

```shell
# amd64 表示 x86-64；ARM64 请替换为 arm64
wget https://modelscope.cn/models/kenvix/aTrustLoginRepo/resolve/master/docker-atrust-autologin-amd64.tar.xz -O - | xz -dc | docker load
docker tag kenvix/docker-atrust-autologin:amd64 kenvix/docker-atrust-autologin:latest
```

阅读“程序运行参数说明”，将程序参数填入 `ATRUST_OPTS` 环境变量，然后运行容器：

```shell
docker run -it --rm \
  -e ATRUST_OPTS='--portal_address="https://vpn.example.com" --username="your_username" --password="your_password"' \
  --device /dev/net/tun --cap-add NET_ADMIN \
  -e PASSWORD="your_vnc_password" -e URLWIN=1 \
  -v "$HOME/.atrust-data:/root" \
  -p 127.0.0.1:5901:5901 -p 127.0.0.1:8888:8888 \
  --sysctl net.ipv4.conf.default.route_localnet=1 --shm-size 256m \
  --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
  kenvix/docker-atrust-autologin:latest
```

SSO、CAS 或扫码登录时，将 `ATRUST_OPTS` 改为 `--portal_address="https://vpn.example.com" --login_timeout=600`，然后通过 VNC 完成认证。

`cookie_sig` 和 `cookie_tid` 可以省略。需要验证码时，通过 VNC 连接容器的 5901 端口，在浏览器中输入验证码并提交。程序会自动保存会话；后续是否再次要求验证码由服务端决定。

**此命令创建临时容器**，容器停止后会删除。需要保留容器并开机自动启动时，将 `--rm` 替换为 `--restart unless-stopped`；后台运行可将 `-it` 替换为 `-d`，人工认证在 VNC 中操作。

默认每隔 `200` 秒刷新检查登录状态，可通过 `--keepalive` 调整。添加 `--keepalive 0` 会在完成一次登录后退出自动登录进程。

如果还需要发包保活功能，请添加 Docker `PING_ADDR` 和 `PING_INTERVAL` 环境变量，具体[参见此处](https://github.com/docker-easyconnect/docker-easyconnect/blob/master/doc/usage.md)。指定的服务器地址必须是 VPN 可到达的，例如 `-e PING_ADDR=172.20.0.1 -e PING_INTERVAL=200`。

`--shm-size 256m` 参数指定的共享内存大小建议至少为 256 MiB，以满足浏览器运行需要。

Docker 容器基于 [docker-easyconnect](https://github.com/docker-easyconnect/docker-easyconnect) 构建，在此表达感谢。其他 Docker 参数也可以在这里找到。

## 使用已有验证码会话

门户支持 `tid` 和 `tid.sig` 时，可以复用已经通过验证码验证的会话：

1. 打开 aTrust 登录网页，登录并输入验证码。
2. 打开浏览器开发者工具，切换到 Application（应用程序）选项卡。
3. 在左侧导航栏找到 Cookies，选择门户地址。
4. 复制 `tid` 和 `tid.sig` 的值，分别填入 `--cookie_tid` 和 `--cookie_sig`。

这些参数为可选参数。没有对应 Cookie 的 SSO 门户可使用浏览器认证模式。

![Cookie](doc/cookie.webp)

## (Docker) 如何访问、如何端口转发

对于 Docker 容器，通过 Socks5 或 HTTP 代理访问内网网络。具体[参见此处](https://github.com/docker-easyconnect/docker-easyconnect/blob/master/doc/usage.md#%E4%BB%A3%E7%90%86%E6%9C%8D%E5%8A%A1)。

容器支持直接设置端口转发，以便访问内网服务而不经过 Socks5 代理。添加 Docker 环境变量 `FORWARD_PORTS`，使用逗号分隔多组 `本地端口:远程IP:远程端口`。例如，`41301:172.29.1.85:11111,41302:172.29.1.85:7777` 表示监听本地端口 `41301` 并转发到 `172.29.1.85:11111`，监听本地端口 `41302` 并转发到 `172.29.1.85:7777`：

```shell
-e 'FORWARD_PORTS=41301:172.29.1.85:11111,41302:172.29.1.85:7777' -p 41301:41301 -p 41302:41302
```

## 如何与 FRP 结合使用

Frp 是一套内网穿透工具，可以将内网服务映射出去。如果 VPN 客户端在内网，可以使用 Frp 将本地服务映射到 VPN 隧道另一侧的服务器上。

Frp 各版本之间可能存在配置差异，项目提供 `frpc` 目录下的脚本，便于组合使用：

1. 进入 `frpc` 目录，修改 `run.sh` 文件中的部署配置。
2. 下载 frpc 发行版二进制文件，复制到 `frpc/frp` 下。
3. 运行 `run.sh`，创建并启动 Docker 镜像、登录和映射端口。
4. 后续启动也使用 `run.sh`，以执行脚本中的配置步骤。
