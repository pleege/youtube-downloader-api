#!/bin/sh
echo "starting youtube downloader ..."
echo "current dir: $(pwd)"
echo "file dir: $(dirname "$(realpath "$0")")"
if [ "$1" = "--local" ]; then
    echo "本地模式,部署目录即开发目录，跳过git pull"
    cd $(dirname "$(realpath "$0")")
    echo "已切换到 $(pwd)"
else
    echo "不是本地模式"
    if [ ! -d ".git" ]; then
      echo "首次运行，执行 git clone ..."
      git init .
      git remote add origin https://github.com/pleege/youtube-downloader-api.git
      git fetch --depth=1 origin main
      git reset --hard origin/main
      git branch --set-upstream-to=origin/main master
    else
      echo "拉取最新代码 ..."
      git pull
      echo "拉取最新代码完成"
    fi
fi



echo "当前环境IP：$(curl -s https://flyare.azurewebsites.net/ip)"
python3 -u main.py > >(tee log.txt) 2>&1

# supervisord
# supervisorctl tail -f youtube
