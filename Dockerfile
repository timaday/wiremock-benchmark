FROM maven:3.9.16-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
COPY src src
RUN mvn -B -ntp package
RUN mvn -B -ntp dependency:copy -Dartifact=org.wiremock:wiremock-standalone:3.13.2 -DoutputDirectory=/runtime

FROM ubuntu:24.04 AS java27
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && apt-get clean
ARG TARGETARCH
RUN set -eu; case "$TARGETARCH" in \
 amd64) arch=x64; sha=95fc37eb3a18a27a26d5904c2d89d52bace8dafa9a078ca27f4747fbc4bf070b ;; \
 arm64) arch=aarch64; sha=da4e9dde1fff90204739e969187bab4751bd59a2a1c479672e1a1810f7dd23ea ;; \
 *) echo "Unsupported architecture: $TARGETARCH"; exit 1 ;; esac; \
 curl -fsSL "https://download.java.net/java/GA/jdk27/55ce5470a6294008af0057ff4626d0e5/35/GPL/openjdk-27_linux-${arch}_bin.tar.gz" -o /tmp/jdk.tar.gz; \
 echo "$sha  /tmp/jdk.tar.gz" | sha256sum -c -; mkdir /opt/java; tar xzf /tmp/jdk.tar.gz --strip-components=1 -C /opt/java
ENV PATH=/opt/java/bin:$PATH
ENV JAVA_HOME=/opt/java

FROM java27 AS headless
ENV CAPTURE_MODE=OUTBOX
ENV CAPTURE_IDENTITY_MODE=BENCHMARK_HEADERS
WORKDIR /app
COPY --from=build /src/target/capture.jar /app/capture.jar
COPY --from=build /runtime/wiremock-standalone-3.13.2.jar /app/wiremock.jar
ENTRYPOINT ["java","--enable-native-access=ALL-UNNAMED","-cp","/app/capture.jar:/app/wiremock.jar","bench.Headless"]

FROM wiremock/wiremock:3.13.2 AS official
ENV CAPTURE_MODE=OUTBOX
ENV CAPTURE_IDENTITY_MODE=BENCHMARK_HEADERS
COPY --from=build /src/target/capture.jar /var/wiremock/extensions/capture.jar

FROM java27 AS archive
WORKDIR /app
COPY --from=build /src/target/capture.jar /app/capture.jar
ENTRYPOINT ["java","--enable-native-access=ALL-UNNAMED","-Xms128m","-Xmx512m","-cp","/app/capture.jar","bench.Archive"]

FROM maven:3.9.16-eclipse-temurin-21 AS gatling-build
WORKDIR /src
COPY tests/perf/gatling/pom.xml .
COPY tests/perf/gatling/src src
RUN mvn -B -ntp package dependency:copy-dependencies -DincludeScope=runtime

FROM eclipse-temurin:21-jre AS gatling
COPY --from=gatling-build /src/target/classes /opt/gatling/classes
COPY --from=gatling-build /src/target/dependency /opt/gatling/dependency
COPY tests/perf/start-engine.sh /work/tests/start-engine.sh
ENV HEAP="-Xms128m -Xmx1g" JVM_ARGS="-Xss256k -XX:MaxMetaspaceSize=160m -XX:+ExitOnOutOfMemoryError"
ENTRYPOINT ["/bin/sh", "/work/tests/start-engine.sh"]

# Portable lab images contain fixtures and monitoring configuration; no bind mounts.
FROM python:3.12-slim AS portable-fixtures
COPY tools/fixtures.py /build/fixtures.py
RUN python /build/fixtures.py

FROM official AS portable-official
COPY --from=portable-fixtures /fixtures /home/wiremock

FROM headless AS portable-headless
COPY --from=portable-fixtures /fixtures /home/wiremock

FROM rabbitmq:3.13.7-management-alpine AS portable-rabbit
RUN rabbitmq-plugins enable --offline rabbitmq_prometheus

FROM prom/prometheus:v3.15.0 AS portable-prometheus
COPY deploy/portainer/prometheus/ /etc/prometheus/

FROM grafana/grafana:13.2.3 AS portable-grafana
COPY deploy/portainer/grafana/provisioning/ /etc/grafana/provisioning/
COPY deploy/portainer/grafana/dashboards/ /etc/grafana/dashboards/
