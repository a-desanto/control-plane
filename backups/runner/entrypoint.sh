#!/bin/sh
set -e

mkdir -p /root/.config/rclone
envsubst < /etc/rclone.conf.template > /root/.config/rclone/rclone.conf
chmod 0600 /root/.config/rclone/rclone.conf

exec crond -f -d 8
