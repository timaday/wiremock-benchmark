package bench;

import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;

import com.github.tomakehurst.wiremock.WireMockServer;

/** Embedded launcher with the same explicit HTTP/delay/journal settings as the official image. */
public final class Headless {
  public static void main(String[] args) {
    var server =
        new WireMockServer(
            options()
                .port(8080)
                .usingFilesUnderDirectory(Settings.required("FIXTURES"))
                .disableRequestJournal()
                .containerThreads(128)
                .asynchronousResponseEnabled(true)
                .asynchronousResponseThreads(64)
                .gzipDisabled(true)
                .http2PlainDisabled(true)
                .http2TlsDisabled(true)
                .withMaxTemplateCacheEntries(1000L)
                .extensions(new CaptureExtension()));
    server.start();
    Runtime.getRuntime().addShutdownHook(new Thread(server::stop));
  }
}
