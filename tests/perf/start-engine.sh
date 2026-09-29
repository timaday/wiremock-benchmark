#!/bin/sh
set -eu
case "$ENGINE_SLOT" in 1|2|3|4) ;; *) echo 'Invalid engine slot' >&2; exit 2 ;; esac
# Compile at image build time; initialize the JVM before the shared barrier.
exec java $HEAP $JVM_ARGS \
  --add-opens=java.base/java.lang=ALL-UNNAMED \
  --add-opens=java.base/jdk.internal.misc=ALL-UNNAMED \
  "-Xlog:gc:file=/results/$RUN_ID/engine-$ENGINE_SLOT-gc.log:time,level,tags" \
  -cp '/opt/gatling/classes:/opt/gatling/dependency/*' \
  io.gatling.app.Gatling -s bench.load.BenchmarkSimulation -nr \
  -rf "/results/$RUN_ID/engine-$ENGINE_SLOT-gatling" \
  > "/results/$RUN_ID/engine-$ENGINE_SLOT.log" 2>&1
