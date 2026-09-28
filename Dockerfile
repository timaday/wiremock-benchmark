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
WORKDIR /app
COPY --from=build /src/target/capture.jar /app/capture.jar
COPY --from=build /runtime/wiremock-standalone-3.13.2.jar /app/wiremock.jar
ENTRYPOINT ["java","--enable-native-access=ALL-UNNAMED","-cp","/app/capture.jar:/app/wiremock.jar","bench.Headless"]

FROM wiremock/wiremock:3.13.2 AS official
COPY --from=build /src/target/capture.jar /var/wiremock/extensions/capture.jar

FROM java27 AS archive
WORKDIR /app
COPY --from=build /src/target/capture.jar /app/capture.jar
ENTRYPOINT ["java","--enable-native-access=ALL-UNNAMED","-Xms128m","-Xmx512m","-cp","/app/capture.jar","bench.Archive"]

FROM eclipse-temurin:21-jre AS jmeter
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && apt-get clean \
 && curl -fsSL https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.tgz -o /tmp/jmeter.tgz \
 && echo '5978a1a35edb5a7d428e270564ff49d2b1b257a65e17a759d259a9283fc17093e522fe46f474a043864aea6910683486340706d745fcdf3db1505fd71e689083  /tmp/jmeter.tgz' | sha512sum -c - \
 && tar xzf /tmp/jmeter.tgz -C /opt
ENV HEAP="-Xms512m -Xmx1536m" JVM_ARGS="-Xss256k -XX:MaxMetaspaceSize=256m"
WORKDIR /work
COPY tests/perf /work/tests
COPY fixtures/cases.json /work/fixtures/cases.json
ENTRYPOINT ["/opt/apache-jmeter-5.6.3/bin/jmeter"]
