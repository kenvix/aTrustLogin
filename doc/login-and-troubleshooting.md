# 登录方式与运行维护

## SSO、CAS 与扫码登录

同时省略 `--username` 和 `--password`，程序会打开门户并等待浏览器完成认证。扫码、统一身份认证和短信验证在浏览器或 VNC 中操作，无需在终端按回车。等待期间保持当前页面，默认等待 300 秒，可通过 `--login_timeout` 调整。用户名和密码需要同时提供或同时省略。

```sh
python3 src/main.py --portal_address="https://vpn.example.com" --login_timeout=600
```

容器使用：

```sh
-e ATRUST_OPTS='--portal_address="https://vpn.example.com" --login_timeout=600'
```

认证返回配置的门户并进入应用中心或用户页面后，程序继续执行保活。服务端再次要求扫码或短信验证时，仍需在浏览器完成该验证。自动填入用户名和密码的范围限于配置的门户，第三方身份提供方的登录页面由用户操作。

提供用户名和密码时，`--interactive=True` 允许在浏览器继续完成图形验证码、短信或其他人工验证。容器默认开启此选项，支持没有交互式终端的 `docker run -d`。

`--cookie_tid` 和 `--cookie_sig` 均为可选参数。已有会话保存到 `--data_dir`；浏览器临时配置目录与该目录分开。门户直接跳转到第三方身份提供方时，程序保留该认证页面，不会向第三方页面写入门户 Cookie。

## TOTP 与短信验证

`--totp_key` 接受为该账号配置的 TOTP 共享密钥。该密钥来自账号绑定身份验证器时显示的设置密钥，或绑定二维码中的 `otpauth://totp/...` URI 的 `secret` 参数。已经完成绑定但无法查看密钥时，应通过账号设置重新绑定，或联系管理员。

短信验证码由服务端发送到手机号，使用短信验证的账号应在浏览器中输入短信验证码。需要改用 TOTP 时，请由管理员确认该账号支持并启用身份验证器。共享账号的验证方式应由账号负责人和管理员管理。

技术参考：[PyOTP 文档](https://pyauth.github.io/pyotp/)。

## macOS 原生运行

在同一台 Mac 上安装并启动机构提供的 aTrust 客户端，以及 Chrome 和项目 Python 依赖。使用 Chrome 的应用内可执行文件路径：

```sh
python3 src/main.py \
  --portal_address="https://vpn.example.com" \
  --browser_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --login_timeout=600
```

密码登录时再添加 `--username` 和 `--password`。需要手动验证码时添加 `--interactive=True`。浏览器驱动可以由 Selenium 管理，也可通过 `--driver_path` 指定。Docker 部署的 VPN 客户端与浏览器需要位于同一个容器环境；原生运行使用本机客户端。

## 浏览器访问本机客户端

程序在首次导航前，为配置的门户授予本机回环网络访问权限，并兼容 Chromium 的两种权限名称。权限范围仅包含门户来源。若浏览器版本不支持自动配置，程序会提示在浏览器的网站设置中允许门户访问本机网络服务。

参考：[Chrome 本地网络访问文档](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access)。

## 客户端启动等待与版本检查

`--wait_atrust=True` 默认等待本机 TCP 54631 端口，最长 120 秒。`--client_timeout=300` 可延长到 300 秒。超时信息包含目标地址、端口及检查方向。只有明确不需要等待本机客户端的测试场景，才使用 `--wait_atrust=False`。

检查容器中的客户端版本和监听端口：

```sh
docker exec atrust sh -lc 'dpkg-query -W 2>/dev/null | grep -i atrust; ss -ltnp | grep 54631'
docker exec atrust sh -lc 'chromium --version; chromedriver --version; ps -eo pid,comm | grep -Ei "atrust|chrome"'
docker logs --tail 200 atrust
```

将 `atrust` 替换为实际容器名称。提交日志前删除账号、密码、Cookie、TOTP 密钥和其他敏感信息。

客户端由 `hagb/docker-atrust:latest` 基础镜像提供。本项目的浏览器自动化与客户端安装包分开维护。报告客户端兼容性时，请提供实际安装版本、CPU 架构、镜像 ID、端口监听结果及相关启动日志。仅客户端版本号不足以定位具体失败环节。

## 日志与磁盘空间

容器浏览器输出保存到 `--data_dir/chrome.log`，每个文件约 5 MiB，最多保留当前文件和两个备份。HTTP 磁盘缓存参数为 64 MiB，媒体缓存参数为 32 MiB。浏览器临时配置目录在会话结束或初始化失败时清理；门户会话数据继续保存在 `--data_dir`。这些设置分别控制浏览器日志和缓存，不限制 aTrust 客户端自身日志及 Docker 日志的大小。

为新容器配置 Docker 日志轮换：

```sh
--log-driver local --log-opt max-size=10m --log-opt max-file=3
```

现有容器需要使用新的日志参数重新创建，保留原有持久化挂载。检查空间占用：

```sh
docker inspect --format '{{.HostConfig.LogConfig}}' atrust
docker ps -s --filter name=atrust
docker exec atrust sh -lc 'du -sh /root/.atrust-data /tmp/atrust-chrome-* /root/.aTrust /usr/share/sangfor/.aTrust /var/log 2>/dev/null'
```

根据增长的目录分别检查浏览器日志、客户端日志或容器日志。会话数据目录和客户端配置目录应保留。

参考：[Docker local 日志驱动](https://docs.docker.com/engine/logging/drivers/local/)。

## 容器参数中的空格与引号

`ATRUST_OPTS` 使用 shell 风格的引号解析。带空格的参数应加引号，例如：

```sh
-e ATRUST_OPTS='--portal_address="https://vpn.example.com" --username="example user" --password="example password"'
```

参数中的命令替换和通配符按普通字符传递，不执行 shell 命令。引号不成对时，启动器报告配置错误并停止该自动登录进程。

## 运行测试

```sh
python3 -m pip install -r src/requirements.txt
ATRUST_BROWSER_TESTS=1 python3 -m unittest discover -s tests -v
```

浏览器集成测试使用本地模拟门户、身份提供方和虚构凭据，不连接生产 VPN。只执行单元测试时省略 `ATRUST_BROWSER_TESTS`。可通过 `CHROME_BINARY` 和 `CHROMEDRIVER` 指定测试浏览器与驱动路径。
