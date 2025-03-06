#!/bin/sh
echo "starting youtube downloader ..."

echo "当前环境IP：$(curl -s https://flyare.azurewebsites.net/ip)"
python3 -u main.py > >(tee log.txt) 2>&1
# python3 -u main.py

# supervisord
# supervisorctl tail -f youtube
