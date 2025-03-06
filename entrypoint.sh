#!/bin/sh
echo "starting youtube downloader ..."

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
fi

echo "当前环境IP：$(curl -s https://flyare.azurewebsites.net/ip)"
python3 -u main.py > >(tee log.txt) 2>&1

# supervisord
# supervisorctl tail -f youtube
