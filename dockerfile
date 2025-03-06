# 基于 alpine 基础镜像构建
FROM python:3.12-alpine

# 设置工作目录
WORKDIR /deploy

# 设置时区
ENV TZ=Asia/Shanghai

# 复制必要文件
COPY requirements.txt /tmp/requirements.txt
COPY entrypoint.sh /entrypoint.sh
COPY supervisor.ini /etc/supervisor.d/youtube.ini

# 合并 RUN 命令减少层数,并在安装完成后清理缓存
RUN apk add --no-cache git ffmpeg curl supervisor && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    mkdir -p /etc/supervisor.d && \
    chmod +x /entrypoint.sh && \
    rm -rf /tmp/* /var/cache/apk/*

# 暴露端口
EXPOSE 80

# 设置入口点
CMD ["/entrypoint.sh"]

# 设置容器启动命令


## 构建镜像 docker build -t ghcr.io/pleege/youtube . --force-rm --no-cache
## 运行容器 docker run -itd --name youtube -v /home/ubuntu/youtube:/deploy -p 8809:80 icebox/youtube sh run.sh
##
##
