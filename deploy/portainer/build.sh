#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
prefix=${LAB_IMAGE_PREFIX:-wiremock-lab}
tag=${LAB_TAG:-20260930}
for component in official headless archive rabbit prometheus grafana; do
  target=portable-$component
  if [ "$component" = archive ]; then target=archive; fi
  docker build --target "$target" \
    --label "org.opencontainers.image.source=https://github.com/timaday/wiremock-benchmark" \
    --label "org.opencontainers.image.version=$tag" \
    -t "$prefix-$component:$tag" "$repo"
done
