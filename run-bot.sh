#! /bin/zsh

alias pythongood="/opt/local/bin/python2.7"

while true
do
kill -9 `ps -eo pid,args | grep scriptbot.py | grep -v grep | cut -c1-6`
pythongood $HOME/Development/bot/scriptbot.py&
sleep 14400
done
