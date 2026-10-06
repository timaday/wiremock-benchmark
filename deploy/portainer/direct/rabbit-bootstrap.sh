#!/bin/sh
# Own dedicated-broker boot configuration; never modify or delete broker data.
set -eu
case "${RABBIT_PASSWORD:?required}" in
  *[!a-fA-F0-9]*) echo 'RABBIT_PASSWORD must be hexadecimal' >&2; exit 1 ;;
esac
if [ "${#RABBIT_PASSWORD}" -lt 32 ] || [ "${#RABBIT_PASSWORD}" -gt 128 ]; then
  echo 'RABBIT_PASSWORD must contain 32-128 hexadecimal characters' >&2
  exit 1
fi
for value in "${CAPTURE_QUEUE_MAX_BYTES:?required}" \
             "${CAPTURE_QUEUE_MAX_MESSAGES:?required}" \
             "${RABBIT_DISK_FREE_LIMIT_BYTES:?required}"; do
  case "$value" in
    ''|0*|*[!0-9]*) echo 'Broker limits must be positive decimal integers' >&2; exit 1 ;;
  esac
done
umask 077
mkdir -p /tmp/benchmark-config
chmod 755 /tmp/benchmark-config
cat > /tmp/benchmark-config/definitions.json <<EOF
{
  "users": [{"name":"benchmark","password":"$RABBIT_PASSWORD","tags":["administrator"]}],
  "vhosts": [{"name":"/"}],
  "permissions": [{"user":"benchmark","vhost":"/","configure":".*","write":".*","read":".*"}],
  "policies": [{"vhost":"/","name":"capture-bounds","pattern":".*","apply-to":"queues","priority":100,
    "definition":{"max-length-bytes":$CAPTURE_QUEUE_MAX_BYTES,"max-length":$CAPTURE_QUEUE_MAX_MESSAGES,"overflow":"reject-publish"}}]
}
EOF
cat > /tmp/benchmark-config/rabbitmq.conf <<EOF
listeners.tcp.default = 5672
management.tcp.port = 15672
default_queue_type = classic
definitions.import_backend = local_filesystem
definitions.local.path = /tmp/benchmark-config/definitions.json
disk_free_limit.absolute = $RABBIT_DISK_FREE_LIMIT_BYTES
vm_memory_high_watermark.absolute = 1GB
EOF
chown rabbitmq:rabbitmq /tmp/benchmark-config/definitions.json /tmp/benchmark-config/rabbitmq.conf
export RABBITMQ_CONFIG_FILE=/tmp/benchmark-config/rabbitmq
exec docker-entrypoint.sh rabbitmq-server
