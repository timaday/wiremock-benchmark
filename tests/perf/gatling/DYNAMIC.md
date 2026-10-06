# Empty-response capture load demonstration

`deploy/portainer/direct/dynamic-load.py --output results/<new-directory>` runs
the local version-2 headless and archive images from `target/direct-image/images.json`
with the dedicated RabbitMQ stack. It retains containers, logs and persistent
capture evidence on the filesystem containing the output directory.

The official published HTTP interface receives POST `/transaction`, with no
X-Bench headers. Bodies cycle through 1, 5, 10 and 50 KiB JSON documents, padded
with repeated `x` characters. Responses are empty HTTP 200 with a fixed delay
selected using `--delay-ms 1000` (default) or `--delay-ms 6000`. The same value
sets the stub delay and the client's minimum response-time check (2 ms tolerance).
A 10/s, ten-second smoke uses `$.correlationId`; the same running
mock's mapping is then edited to `$.requestId` before the full-rate test.

Gatling owns open arrivals: 15 seconds ramp, 30 seconds warmup, then 300 seconds
at 1,020 arrivals/s. At least 1,000 successful client completions/s in each
60-second hold window, zero failed requests, all three capture phases with exact
body hashes for every client ID, no extra captures and no container restart/OOM
are required. Client receipt is the timing authority, not SEND_COMPLETED.
Six-second responses require approximately 6,120 concurrent requests at the
offered rate. The 30-second warmup fills that pipeline before measurement.

The runner records container resources, queues, host available memory, swap
activity and free space. It aborts its own generator on less than 2 GiB available
RAM, less than 5 GiB free evidence storage, less than 1 GiB free Docker storage,
or sustained memory pressure (full avg10 above 5%). This is a five-minute local
demonstration, not an AWS or endurance qualification. No images are published.
