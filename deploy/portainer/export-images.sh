#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo 'Usage: export-images.sh /path/with/enough/space/images.tar.gz' >&2
  exit 2
fi
prefix=${LAB_IMAGE_PREFIX:-wiremock-lab}
tag=${LAB_TAG:-20260930}
# Refuse to overwrite existing evidence or image archives.
if [ -e "$1" ]; then echo 'Output already exists' >&2; exit 2; fi
# Keep Docker save failure visible; no shell pipeline hides its exit code.
archive=$1.tar
if [ -e "$archive" ]; then echo 'Temporary output already exists' >&2; exit 2; fi
docker image save -o "$archive" \
  "$prefix-official:$tag" "$prefix-headless:$tag" "$prefix-archive:$tag" \
  "$prefix-rabbit:$tag" "$prefix-prometheus:$tag" "$prefix-grafana:$tag"
gzip -c "$archive" > "$1"
echo "Created $1; uncompressed $archive is also retained."
