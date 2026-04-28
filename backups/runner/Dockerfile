FROM alpine:3.20

RUN apk add --no-cache \
    postgresql16-client \
    rclone \
    dcron \
    curl \
    gettext \
    tzdata

COPY rclone.conf.template /etc/rclone.conf.template
COPY crontab /etc/crontabs/root
COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh \
    && chmod 0600 /etc/crontabs/root

ENV TZ=UTC

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
