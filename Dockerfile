FROM hagb/docker-atrust:latest
LABEL authors="Kenvix"

ENV TZ="Asia/Shanghai"
COPY ./docker/bin /bin
COPY ./src /opt/atrust-autologin

# 再次定义 ARG 变量以确保构建过程中可以使用这些参数
ARG ANDROID_PATCH
ARG EC_HOST
ARG VPN_TYPE=EC_GUI
ARG VPN_URL
ARG ELECTRON_URL
ARG USE_VPN_ELECTRON
ARG VPN_DEB_PATH

# 重新定义 ENV 变量，以确保环境变量在最终镜像中可用
ENV PING_INTERVAL=1800

# 保留基础镜像的卷（这会继承 `/root` 和 `/usr/share/sangfor/EasyConnect/resources/logs/` 的设置）
VOLUME ["/root", "/usr/share/sangfor/EasyConnect/resources/logs/"]

RUN echo "Begin build" && \
    sed -i 's|http://.*archive.ubuntu.com|https://mirrors.ustc.edu.cn|g; s|http://.*security.ubuntu.com|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list && \
    mkdir -p ~/.pip && \
    date > /etc/build-date.txt && \
    sed -i 's|http://deb.debian.org|https://mirrors.ustc.edu.cn|g; s|http://security.debian.org|https://mirrors.ustc.edu.cn/debian-security|g' /etc/apt/sources.list && \
    echo "[global]" > ~/.pip/pip.conf && \
    echo "index-url = https://mirrors.ustc.edu.cn/pypi/web/simple" >> ~/.pip/pip.conf && \
    chmod +x /bin/start-with-autologin.sh && \
    chmod +x /bin/start-with-autologin-actual.sh && \
    chmod +x /bin/start-port-forwarding.sh && \
    apt-get update && \
    apt-get install -y --no-install-recommends --no-install-suggests apt-utils curl x11-xserver-utils && \
    apt-get install -y --no-install-recommends --no-install-suggests chromium chromium-driver chromium-l10n python3 python3-pip && \
    cd /opt/atrust-autologin && \
    pip3 install --break-system-packages -r requirements.txt && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

CMD ["/bin/start-with-autologin.sh"]