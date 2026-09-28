#!/bin/sh
set -eu
case "$ENGINE_SLOT" in 1|2|3|4) ;; *) echo 'Invalid engine slot' >&2; exit 2 ;; esac
# Wait before launching JMeter: its built-in timer origin is JVM test startup.
# Waiting inside setUp would create a backlog of overdue scheduled arrivals.
now_ns=$(date +%s%N)
now=$((now_ns / 1000000))
wait_ms=$((LOAD_START_MS - now))
if [ "$wait_ms" -le 0 ]; then echo 'Engine missed startup barrier' >&2; exit 2; fi
sleep "$((wait_ms / 1000)).$(printf '%03d' "$((wait_ms % 1000))")"
JVM_ARGS="$JVM_ARGS -Xlog:gc:file=/results/$RUN_ID/engine-$ENGINE_SLOT-gc.log:time,level,tags"
export JVM_ARGS
exec /opt/apache-jmeter-5.6.3/bin/jmeter -n -t /work/tests/benchmark.jmx \
  -l "/results/$RUN_ID/engine-$ENGINE_SLOT.jtl" \
  -j "/results/$RUN_ID/engine-$ENGINE_SLOT.log" \
  -Lorg.apache.jmeter.threads.JMeterThread=WARN \
  "-Jhost=$BENCH_HOST" "-Jrun_id=$RUN_ID" "-Jengine_id=$ENGINE_SLOT" \
  "-Joffered=$ENGINE_RATE" "-Jthreads=$ENGINE_THREADS" \
  "-Jload_start_ms=$LOAD_START_MS" "-Jmeasure_end_ms=$MEASURE_END_MS" \
  "-Jcase=$BENCH_CASE" \
  -Jsample_variables=bench_id,case_id,delay_ms,payload_bytes,request_sha256,response_sha256 \
  -Jjmeter.save.saveservice.output_format=csv -Jjmeter.save.saveservice.print_field_names=true \
  -Jjmeter.save.saveservice.timestamp_format=ms -Jjmeter.save.saveservice.response_data=false \
  -Jjmeter.save.saveservice.assertion_results_failure_message=false
