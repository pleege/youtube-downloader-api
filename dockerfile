# 基于 py3-alpine 基础镜像构建
FROM python:3.12-alpine

# 设置工作目录
WORKDIR /deploy

# 设置时区
ENV TZ=Asia/Shanghai
ARG DEBIAN_FRONTEND=noninteractive

# 复制并安装依赖
COPY requirements.txt /tmp/requirements.txt
ADD entrypoint.sh /deploy/entrypoint.sh

RUN pip install -r /tmp/requirements.txt
RUN apk update && apk add ffmpeg && apk add curl && apk add supervisor && mkdir -p /etc/supervisor.d && chmod +x /deploy/entrypoint.sh
COPY supervisor.ini /etc/supervisor.d/youtube.ini


# 暴露端口
EXPOSE 80
ENTRYPOINT ["/bin/sh", "-c", "/deploy/entrypoint.sh"]

# 设置容器启动命令


## 构建镜像 docker build -t icebox/youtube . --force-rm --no-cache
## 运行容器 docker run -itd --name youtube -v /home/ubuntu/youtube:/deploy -p 8809:80 icebox/youtube sh run.sh
##
##
