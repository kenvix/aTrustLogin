# aTrustLogin

[中文版本](/README.md)

This project automates browser login to Sangfor aTrust. It supports password login, TOTP verification, session keepalive, and browser-assisted SSO, CAS, or QR-code authentication.

- Opens the aTrust web portal and fills in username and password
- Generates and submits TOTP codes using the account's configured secret
- Saves cookies and portal session state
- Checks the connection periodically and logs in again after disconnection
- Waits for QR-code, SSO, or manual verification in the browser or VNC
- Provides a Linux Docker image with the client, browser, and Python dependencies

See [Login and operational diagnostics (Chinese)](doc/login-and-troubleshooting.md) for detailed authentication, client startup, and disk-usage instructions.

## General Method

Install and start your institution's aTrust client on the same machine as the browser. Install Python and the project dependencies; Python 3.11 is recommended.

### Browser Setup

Windows uses Microsoft Edge by default. Linux and macOS use Chrome or Chromium. Selenium can manage the browser driver, or you can provide it with `--driver_path`. See the [Selenium documentation](https://www.selenium.dev/documentation/en/webdriver/driver_requirements/).

On Debian/Ubuntu:

```sh
apt-get install -y chromium chromium-driver chromium-l10n
```

On macOS, the Chrome executable can be specified with:

```sh
--browser_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

### Project Setup

```sh
git clone --depth=1 https://github.com/kenvix/aTrustLogin.git aTrustLogin
cd aTrustLogin/src
python3 -m pip install -r requirements.txt
```

### Program Parameters

- `--portal_address`: HTTP or HTTPS URL of the VPN portal.
- `--username` and `--password`: Provide both for automatic password entry, or omit both for browser-assisted authentication.
- `--totp_key`: Optional TOTP shared secret obtained when enrolling the account's authenticator.
- `--cookie_tid` and `--cookie_sig`: Optional portal session cookies. Portals that do not provide these cookies can use browser-assisted authentication.
- `--keepalive`: Session check interval in seconds, default `200`. Set to `0` to exit after one successful login.
- `--data_dir`: Directory for cookies, session data, and container browser logs.
- `--driver_type`: `chrome` or `edge`.
- `--driver_path`: Optional browser-driver executable path.
- `--browser_path`: Optional browser executable path.
- `--interactive`: Allow browser interaction when password login needs manual verification. Enabled by default in Docker. Terminal input is not required.
- `--login_timeout`: Maximum wait for browser-assisted authentication in seconds, default `300`; must be positive.
- `--wait_atrust`: Wait for the local aTrust client on TCP port 54631, default `True`.
- `--client_timeout`: Maximum client startup wait in seconds, default `120`; must be positive.

Password login:

```sh
python3 main.py --portal_address="https://vpn.example.com" \
  --username="your_username" --password="your_password" --interactive=True
```

Add `--totp_key="your_totp_key"` when the account uses TOTP. A TOTP secret is supplied during authorized authenticator enrollment. SMS verification uses a code sent by the server; enter that code in the browser when requested.

SSO, CAS, or QR-code login:

```sh
python3 main.py --portal_address="https://vpn.example.com" --login_timeout=600
```

Complete authentication in the browser or VNC. The program waits without refreshing the identity-provider page during the authentication timeout, then continues keepalive after returning to an authenticated portal page. Complete any further verification requested by the server in the same browser.

## Docker Method

The image runs the browser and aTrust client together in a Linux container.

```sh
docker pull kenvix/docker-atrust-autologin:latest
```

An alternative download is available from ModelScope. Replace `amd64` with `arm64` for ARM64:

```sh
wget https://modelscope.cn/models/kenvix/aTrustLoginRepo/resolve/master/docker-atrust-autologin-amd64.tar.xz -O - | xz -dc | docker load
docker tag kenvix/docker-atrust-autologin:amd64 kenvix/docker-atrust-autologin:latest
```

Set the login parameters in `ATRUST_OPTS`:

```sh
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

For SSO, CAS, or QR-code authentication, use `--portal_address="https://vpn.example.com" --login_timeout=600` as `ATRUST_OPTS` and complete authentication through VNC on port 5901.

The example creates a temporary container. For persistent operation and automatic restart, replace `--rm` with `--restart unless-stopped`. Replace `-it` with `-d` to run in the background; manual authentication is performed in VNC. Keep the same persistent volume when recreating the container.

`ATRUST_OPTS` supports shell-style quoting for values containing spaces. Command substitution and wildcard expansion are not executed.

### Session Cookies

When the portal provides `tid` and `tid.sig`, you can supply an existing verified session:

1. Log in through the aTrust webpage and complete any CAPTCHA.
2. Open browser developer tools and select the Application tab.
3. Find the portal's `tid` and `tid.sig` cookies and pass their values using `--cookie_tid` and `--cookie_sig`.

These parameters are optional. The program also saves session state after a successful login. The server determines when verification is required again.

![Cookie Example](doc/cookie.webp)

### Logs and Client Startup

Container browser output is rotated in `data_dir/chrome.log`, with approximately 5 MiB per file and two backups. Browser disk and media caches are configured to 64 MiB and 32 MiB. Owned temporary browser profiles are removed when the session closes or initialization fails. These settings do not limit the aTrust client's own logs or Docker's logs.

The Docker example configures the `local` logging driver with rotation. To change logging options for an existing container, recreate it while preserving its persistent volume. See [Docker local logging](https://docs.docker.com/engine/logging/drivers/local/).

When client startup times out, check the installed client version, architecture, and listener inside the container:

```sh
docker exec atrust sh -lc 'dpkg-query -W 2>/dev/null | grep -i atrust; ss -ltnp | grep 54631'
docker logs --tail 200 atrust
```

Replace `atrust` with the container name. Remove passwords, cookies, TOTP secrets, and other sensitive information before sharing logs. The client package is supplied by the `hagb/docker-atrust:latest` base image.

## Integration with FRP

FRP can expose selected services through another server. The `frpc` directory contains scripts for combining it with aTrust.

1. Edit the deployment settings in `frpc/run.sh`.
2. Download the FRP binary and place it in `frpc/frp`.
3. Run `run.sh` to create and start the container and configure port mappings.
4. Use `run.sh` for subsequent starts so its configuration steps are executed.

For additional environment variables such as `PING_ADDR` and `PING_INTERVAL`, refer to the [docker-easyconnect documentation](https://github.com/docker-easyconnect/docker-easyconnect/blob/master/doc/usage.md).

## Tests

From the repository root:

```sh
python3 -m pip install -r src/requirements.txt
ATRUST_BROWSER_TESTS=1 python3 -m unittest discover -s tests -v
```

Browser tests use local test portals and synthetic credentials. They do not connect to a production VPN. Omit `ATRUST_BROWSER_TESTS` to run only the unit tests.
