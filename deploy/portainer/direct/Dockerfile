# The build script resolves these required bases from ../image-lock.json.
# They retain the qualified fixtures, WireMock and original JVMs. Only the
# capture extension is replaced; the old image tags are never overwritten.
ARG OFFICIAL_BASE
ARG HEADLESS_BASE
ARG ARCHIVE_BASE
FROM ${OFFICIAL_BASE} AS direct-official
COPY capture.jar /var/wiremock/extensions/capture.jar
ENV CAPTURE_MODE=DIRECT_RABBIT
ENV CAPTURE_IDENTITY_MODE=BENCHMARK_HEADERS

FROM ${HEADLESS_BASE} AS direct-headless
COPY capture.jar /app/capture.jar
ENV CAPTURE_MODE=DIRECT_RABBIT
ENV CAPTURE_IDENTITY_MODE=BENCHMARK_HEADERS

FROM ${ARCHIVE_BASE} AS direct-archive
COPY capture.jar /app/capture.jar
