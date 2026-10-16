# Customer mappings with `wb`

`wb` configures HTTP mappings on a running WireMock from `wb.yaml` in the current
directory. It works with upstream WireMock; no custom image or extension is needed.
Edit the five named targets in [the example](../wb.yaml) before applying.

Install the `wiremock-benchmark-cli` wheel to use `wb` outside this checkout;
see [installation, packaging and release checks](WB-PACKAGE.md). The examples
below use the repository launcher `./wb`; use `wb` after installation.
`wb --version` prints the application version without reading configuration.

## JSON reports for every command

Add `--output FILE` to `apply` (including the default command), `list`, `verify`
or `clean`. Terminal output stays unchanged. Examples:

```sh
./wb apply -f wb.phase1.yaml --all-mocks --all-customers --output applied.json
./wb list -f wb.phase1.yaml --all-customers --output endpoints.json
./wb verify -f wb.phase1.yaml --all-customers --output verified.json
./wb clean -f wb.phase1.yaml --all-mocks --all-customers --stale-only --dry-run --output cleanup.json
```

Reports are JSON with `report_version: 1`, `command`, UTC `started_at` and
`finished_at`, `status` (`success`, `failed`, or `interrupted`), `exit_code`,
parsed `options` (including CLI overrides and defaults), `config` (absolute path
and SHA-256 of the exact bytes read), `resolved`, `events`, `summary`, and `errors`.
`resolved` contains the canonical mapping plan for apply/verify, endpoint lists
for list, or target URLs and desired mapping IDs for clean. It is null if
configuration resolution failed. `config` is null if the file could not be read.
Reports may contain configured probe bodies, response bodies and headers; treat them as you
would the source YAML.
The raw `--wiremock-api` option is represented by a reference to the validated
URL in `resolved.targets`, so rejected credential-bearing URLs are not saved.
`summary` is null if the command did not reach its final summary; completed
events and errors still describe partial progress.

Apply events distinguish preflight checks, attempted writes and verified
readbacks. Clean events distinguish candidates, attempted deletes, verified
deletions and already-absent mappings. An attempted mutation without its verified
completion has an **unknown outcome**, not a successful or rolled-back outcome.
Verify events contain each endpoint's pass/fail result and diagnostic detail.
List and dry-run plans describe expectations, not live success. Clean preview
reads live mappings but does not delete them. Errors and completed events are
retained on configuration, network and partial-operation failures.

The destination directory must already exist. Existing files are refused before
any HTTP request; `--overwrite-output` explicitly permits replacement and requires
`--output`. The input YAML cannot be the report destination, even with overwrite.
Reports are published atomically at command completion, with private file
permissions. A late write failure makes the command fail; it does not undo any
WireMock changes. Help, argument parsing failures and invalid report destinations
do not produce reports. Ctrl-C produces an interrupted report when possible;
forced process termination cannot guarantee one.

These reports are evidence, not configuration input or a state cache. Re-run the
versioned YAML with the recorded overrides to repeat a configuration; verify it
to establish the current live state.

## Command help

```sh
./wb --help          # Global overview, commands and default apply options
./wb apply --help    # Apply mappings
./wb list --help     # List endpoints from YAML
./wb verify --help   # Verify mappings and probe responses
./wb clean --help    # Preview or explicitly delete owned mappings
```

`-h`, `--h` and `--help` are equivalent at each level. Help exits successfully
without reading YAML or contacting WireMock, including when PyYAML is not installed.
Command help includes options and examples. `apply` is an explicit name for the
existing default operation: `wb apply -f FILE ...` and `wb -f FILE ...` do the same
thing. Put command-specific options after `apply`, `list` or `verify`.

Requires Python 3.10+ and PyYAML. From the repository root:

```sh
python3 -m venv .runtime/wb-venv
. .runtime/wb-venv/bin/activate
python3 -m pip install -e .

./wb apply -f wb.yaml --all-mocks --all-customers --dry-run
./wb apply -f wb.yaml --all-mocks --all-customers
./wb --mock mock-1 --customer 2342342 --delay 6000
./wb --mock mock-1 --customer 2342342 --delay 1000 --error-profile server-error
./wb --mock mock-1 --customer 2342342 --error-profile timeout
# Restore the selected customer's success response:
./wb --mock mock-1 --customer 2342342 --delay 1000 --error-profile none
```

The editable install also provides `wb` in the active virtual environment. Use
`-f PATH` (equivalent to `--config PATH`) to select a YAML file for any command.
Without either option, `wb.yaml` in the current directory is read. Relative paths
are relative to the current directory; a missing or invalid selected file fails
explicitly, without trying another file. For `list` and `verify`, put the option
after the command name:

```sh
./wb -f wb.phase1.yaml --all-mocks --all-customers --delay 1000
./wb list -f wb.phase1.yaml --all-customers
./wb verify -f wb.phase1.yaml --all-customers --delay 1000
```

When applying mappings,
select exactly one of `--mock NAME` or `--all-mocks`, even when only one mock is configured.
`--wiremock-api URL` optionally overrides the URL for a single explicit `--mock`;
it is rejected with `--all-mocks`. Prefix handling and assignments still come
from that named mock.

```sh
./wb --mock mock-1 --group slow-customers --delay 6000
./wb --all-mocks --group slow-customers --delay 6000 --dry-run
./wb --all-mocks --group slow-customers --delay 6000
```

Groups select customer codes, not delays or error profiles. `--delay` and
`--error-profile` retain their existing meanings.

## List configured endpoints

```sh
./wb list --customer 2342342
./wb list --all-customers
./wb list --customer 2342342 --mock mock-2
./wb list --config /path/to/customers.yaml --all-customers
```

`list` reads and validates YAML only. It never contacts WireMock or modifies
mappings, and does not accept `--delay`. It reports the configured public URL and method,
mock name, product class, resolved file delay/source, error-profile selection/source,
normal response profile and whether that response profile comes
from the customer or product. It also shows the actual mapping path and explicit
prefix handling, using the same resolver as mapping creation. It does not claim
the mappings are installed or report a currently active delay/error profile.

Exactly one of `--customer CODE` or `--all-customers` is required. Listing covers
all configured mocks unless `--mock NAME` restricts it; `--all-mocks` may also be
specified explicitly. This read-only scope differs from applying mappings, which
still requires an explicit target selection. Customers with no assignments in
the selected mocks are explicitly reported as having no configured endpoints.
Unknown customer/mock names or invalid configuration exit with code 2; a valid
listing (including an empty result) exits with code 0. Apply-only flags such as
`--delay`, `--error-profile` and `--wiremock-api` are rejected for `list`.

## Verify installed endpoints

```sh
./wb verify --customer 2342342 --delay 1000
./wb verify --all-customers --delay 1000
./wb verify --customer 2342342 --mock mock-1 --delay 6000
./wb verify --group slow-customers --delay 1000 --error-profile server-error
./wb verify --customer 2342342 --error-profile timeout
```

Verification resolves delays from the same profile file as apply. `--delay` is an
optional explicit override; use the same file and overrides for apply and verify.
Verification never adopts a server value as its expectation. Select a customer, group or all customers. All configured mocks are
included by default; `--mock NAME` restricts the scope and `--all-mocks` makes it
explicit. `--config PATH` selects another configuration file.

For each selected endpoint, verification reads its stable-ID mapping through the
configured admin URL and compares it against the generated mapping, including
the body representation, configured headers and delay. Missing or mismatched
mappings fail that endpoint without sending a probe to it. For matching mappings,
it sends one request using the resolved method and probe body (POST with JSON
`{}` by default) to the
**public endpoint URL**, including its Nginx prefix. The CLI never applies,
repairs or removes mappings. Probes are real requests and may appear in server
logs or capture queues.

Connection failures report a classified reason (such as connection refused, DNS
resolution failed, timeout or TLS certificate verification failed), without
printing raw exception messages. An admin connection failure prevents the probe;
it does not indicate a bad mapping. Check that each YAML `api` points to a running
ingress: `localhost` means the machine running `wb`, not a remote Swarm node.
The command never starts containers or changes target addresses automatically.

Checks cover HTTP status, configured headers (case-insensitive names), exact
UTF-8 bytes for `body`, JSON content/types for `jsonBody` (object order and
whitespace ignored), and time to receive the full response. An empty 200 must
contain zero bytes; if no Content-Type is configured for that empty response,
none may be returned. Extra transport headers such as Date are allowed. Redirects
are not followed, no retries are made, and expected HTTP error statuses can pass.

Timing must fall between `delay - 50ms` (floored at zero) and `delay + 1000ms`.
Use `--early-tolerance-ms` and `--max-overhead-ms` to set those bounds explicitly.
These are acceptance tolerances, not measurement precision: a 1000ms delay has
an inclusive default range of **950.0–2000.0ms**. For an inclusive range of
**990.0–1100.0ms**, use:

```sh
./wb verify --all-customers --delay 1000 \
  --early-tolerance-ms 10 \
  --max-overhead-ms 100
```

Elapsed time uses a monotonic clock around the public HTTP probe through receipt
of the complete response body. It includes connection, network, proxy and server
processing overhead; the preceding admin mapping check is excluded. Displaying
one decimal place does not guarantee 0.1ms measurement accuracy. Choose tolerances
appropriate to the environment; a timing failure alone does not identify which
component caused the extra latency.

Admin requests have a 15-second timeout (`--admin-timeout`); probe socket timeouts
are the expected delay plus the overhead allowance plus five seconds. A socket
timeout is always a failure, including with a timeout profile: verification waits
for that profile's delayed response to check its body, rather than treating a
network failure as proof of correctness. Response reads are capped at the larger
of 1 MiB or four times the expected body length. Probes run sequentially and can
take several minutes when verifying many long-delay endpoints.

Before checking each endpoint, the CLI prints its expected criteria from the
resolved YAML configuration: method and public URL, mapping ID and mapping path,
HTTP status, required response headers, body content and comparison mode, installed
delay and allowed response-time range. Empty responses explicitly show zero bytes
and whether Content-Type must be absent. These expectations appear even if the
admin check fails and no probe is sent. Body strings are JSON-escaped so multiline
content stays readable. The response-time range reflects the supplied tolerance
flags. Each endpoint then prints PASS or FAIL with the reason, followed by totals. Failures
do not prevent checks of subsequent endpoints. Exit code 0 means every selected
endpoint passed; 1 means an admin/probe/check failure; 2 means invalid arguments
or configuration. This is a functional check, not a throughput qualification.

## Clean owned mappings

```sh
# Preview stale mappings on one target/customer:
./wb clean -f wb.phase1.yaml --mock mock-5 --customer 2342342 --stale-only
# Explicit preview (same behavior as the default):
./wb clean -f wb.phase1.yaml --mock mock-5 --customer 2342342 --stale-only --dry-run
# Recalculate the candidates and delete them explicitly:
./wb clean -f wb.phase1.yaml --mock mock-5 --customer 2342342 --stale-only --execute
# Preview all wb-owned mappings across all configured targets:
./wb clean --all-mocks --all-customers
```

Exactly one target selector (`--mock NAME` or `--all-mocks`) and one customer
selector (`--customer CODE` or `--all-customers`) are required. `-f`/`--config`
selects the YAML, and `--admin-timeout` defaults to 15 seconds. No delay or error
profile is needed. Without `--execute`, this command makes GET requests only.
`--dry-run` explicitly selects that preview behavior; it cannot be combined with
`--execute`. Unlike apply's offline dry-run, clean's preview reads live mappings.
Without `--stale-only`, all owned mappings in the selected scope are candidates,
including currently configured endpoints.

Ownership requires the exact supported `wb` metadata shape/version and a stable
mapping UUID matching that metadata. A name beginning with `wb:` alone is not
ownership. Manual mappings, unknown versions, malformed metadata and mismatched
IDs are preserved; the report counts mappings whose ownership is not recognized.
Customer selection uses the ownership metadata, not URL substring matching.
`--customer` can name a code removed from YAML; `--all-customers` includes owned
mappings for customers removed from YAML or no longer assigned to a target.

`--stale-only` selects owned IDs absent from the current target's configured
endpoints. This covers removed products/customers/assignments and old endpoint
scopes. An existing desired ID with a changed path, body or delay is retained;
use `apply` to update it. All desired endpoint sets are resolved through the same
resolver as apply/list/verify before HTTP requests; invalid/conflicting YAML fails.

The preview lists each candidate ID, customer, method/path and reason. All targets
must be readable, and their mapping lists complete, before any deletion starts.
Execution re-reads each candidate and refuses to delete it if it changed since
discovery, then checks that its ID returns 404 after DELETE. An already-absent
candidate is reported separately. Failures stop further deletion and report
verified deletions, already-absent mappings and whether a DELETE was attempted.
No reset, bulk deletion, retries, file persistence or automatic rollback occurs.
Preview and execution are separate fresh reads, not a saved approval plan. The
API offers no conditional DELETE; avoid editing mappings concurrently with clean.
Deletion is not atomic across endpoints/targets, and a failed request may have
applied. Mappings loaded from files can return after a restart; this command only
changes live admin state. Exit codes: 0 successful preview/cleanup (including no
candidates), 1 admin/deletion failure, 2 invalid arguments or configuration.

## Switching configuration files

A configuration switch means replacing the desired endpoint set from one YAML
file with another, for example `wb.phase1.yaml` → `wb.phase2.yaml`. It is separate
from selecting a named request, response or error profile inside a file.
There is no `wb switch` command or automatic deletion.

Apply creates or updates the new file's desired mapping IDs. It leaves IDs that
are no longer desired in place until explicit cleanup. For a customer changing
from products A+B to B+C on the same mock:

| Stage | Live wb-owned mappings |
| --- | --- |
| Phase 1 installed | A, B |
| Phase 2 applied | A, updated B, C |
| Phase 2 stale preview | A is a deletion candidate; nothing changes |
| Phase 2 stale cleanup executed | B, C |

Changes to a mapping's method, response or delay normally update its existing
ID. Removed products, customers, assignments, or changed endpoint scopes can
leave obsolete IDs. See [Paths and updates](#paths-and-updates) for identity rules.

### Switch workflow with reports

Use the **new file** for apply, stale detection and verification. Keep it unchanged
throughout the switch. The examples assume `wb.phase2.yaml` is the complete desired
configuration for all selected mocks; see cleanup scope below before using
`--all-customers`. Run each stage separately and continue only after a successful
exit. Review the preview before executing deletion.

1. Create a new report directory and preview the desired mappings offline:

   ```sh
   mkdir -p results
   wb_switch_reports="$(mktemp -d results/wb-switch-phase2.XXXXXXXX)"
   ./wb apply -f wb.phase2.yaml --all-mocks --all-customers --dry-run \
     --output "$wb_switch_reports/01-apply-preview.json"
   ```

2. Apply the new mappings and check the verified readback results:

   ```sh
   ./wb apply -f wb.phase2.yaml --all-mocks --all-customers \
     --output "$wb_switch_reports/02-apply.json"
   ```

3. Preview obsolete mappings against the new file. This reads live WireMock state:

   ```sh
   ./wb clean -f wb.phase2.yaml --all-mocks --all-customers --stale-only --dry-run \
     --output "$wb_switch_reports/03-stale-preview.json"
   ```

   Review each candidate's mock, customer, mapping ID and method/path. If anything
   should remain, correct the desired configuration or narrow the cleanup scope
   and repeat the relevant previews before continuing.

4. After reviewing the candidates, explicitly execute stale cleanup:

   ```sh
   ./wb clean -f wb.phase2.yaml --all-mocks --all-customers --stale-only --execute \
     --output "$wb_switch_reports/04-stale-cleanup.json"
   ```

   Execution recalculates candidates; it does not consume or replay the preview
   report. Avoid concurrent edits between preview and execution. Keep
   `--stale-only`: omitting it also selects currently desired owned mappings.

5. Verify the new endpoints, then confirm no stale owned IDs remain in scope:

   ```sh
   ./wb verify -f wb.phase2.yaml --all-mocks --all-customers \
     --output "$wb_switch_reports/05-verify.json"
   ./wb clean -f wb.phase2.yaml --all-mocks --all-customers --stale-only --dry-run \
     --output "$wb_switch_reports/06-final-stale-check.json"
   ```

   Require passing endpoint verification and zero candidates in the final stale
   check. A successful clean preview can still contain candidates; exit code 0
   alone does not establish that the stale set is empty. Verify checks desired
   endpoints, not the absence of obsolete mappings.

Reports record the input file hash, resolved settings and observed outcomes.
Keep them with the configuration used. Existing output files are refused; use
new report filenames for retries so earlier failure evidence is retained.
If apply uses CLI `--delay` or `--error-profile`, repeat those overrides in its
preview and verification. Clean accepts neither override; they do not change
mapping IDs. Prefer storing phase behavior in YAML for repeatable switches.

### Cleanup scope and removed mocks

- `--all-mocks` means mocks declared in the selected file, not every server used
  by an earlier configuration. A removed mock, or a mock whose API URL moved to
  another server, is not cleaned at its old address by the new file.
- On selected mocks, `--all-customers` considers every recognized wb-owned
  mapping, including removed customers and assignments. Other wb configurations
  do not have separate ownership namespaces: their mappings can be candidates
  if absent from the new file. Use a complete desired file or narrow cleanup with
  `--mock NAME --customer CODE`; clean has no `--group` selector.
- Manual mappings and mappings whose wb ownership cannot be recognized are
  preserved. This does not guarantee that they cannot overlap or interfere with
  the new endpoints; public verification checks the actual responses.

To retire all wb-owned mappings on a removed mock, keep the old valid file (or a
separate valid cleanup file) declaring its old API address. Preview that target
without `--stale-only`, because its mappings are still desired in the old file:

```sh
./wb clean -f wb.phase1.yaml --mock mock-5 --all-customers --dry-run \
  --output "$wb_switch_reports/07-retired-mock-preview.json"
```

Only if that entire owned scope is being retired, review and execute:

```sh
./wb clean -f wb.phase1.yaml --mock mock-5 --all-customers --execute \
  --output "$wb_switch_reports/08-retired-mock-cleanup.json"
./wb clean -f wb.phase1.yaml --mock mock-5 --all-customers --dry-run \
  --output "$wb_switch_reports/09-retired-mock-final-check.json"
```

The final preview should show zero candidates. Use `--customer CODE` instead of
`--all-customers` when retiring only one customer's mappings. A cleanup file must
still satisfy schema validation; empty mock assignment maps are not supported.

### Partial failures and recovery

A switch is not atomic. Old and new mappings coexist between apply and cleanup;
run the switch outside the measured load period if that overlap would affect
results. No automatic rollback restores the previous configuration.

- If apply fails, stop before cleanup. Inspect its verified writes and any
  attempted write whose outcome is unknown. Correct the failure and rerun apply
  with the same intended file and overrides, writing a new report. Continue only
  after apply succeeds.
- If cleanup fails, some deletions may already have completed. Inspect the
  report, correct the cause, take a fresh preview and review it before another
  execution. A failed DELETE may have taken effect even without verified readback.
- If verification fails, the switch is not verified complete. Investigate the
  reported mapping/probe mismatch; verification does not repair it. After any
  correction, rerun the relevant apply/cleanup stages and verification.
- If report publication fails after an operation, remote changes may still be
  in effect. Inspect live state before retrying; a missing report is not evidence
  that no changes happened.

To return to phase 1, perform the same reviewed workflow with `wb.phase1.yaml` as
the desired file, including stale cleanup of phase-2-only IDs. Applying the old
file alone does not remove newly introduced mappings. Cleanup affects live admin
state; mappings loaded from files may return after a WireMock restart.

## Endpoint scope and product overrides

Each customer must declare `endpoint_scope: customer` or
`endpoint_scope: product-class`. Products inherit that setting unless they
explicitly override `endpoint_scope`. Response profiles inherit independently.

A customer with `endpoint_scope: customer` may omit `ProductClasses` or set it
to `{}`. It then creates exactly one customer endpoint using the customer's
profile, path override and extension. No placeholder product is required. With
`endpoint_scope: product-class`, a nonempty `ProductClasses` mapping is required.
Explicit `ProductClasses: null` or a list is invalid for either scope.

```yaml
customers:
  "2342342":
    name: SecondCustomer
    endpoint_scope: customer
    response_profile: empty-ok
    error_profile: none
    delay_ms: 1000
    allowed_delays_ms:
      - 1000
      - 6000
    ProductClasses:
      Productclass:  # Inherits customer-only URL and empty-ok response
      SharedProduct:  # Shares that same URL and response
      AnotherProduct:
        endpoint_scope: product-class
        response_profile: accepted
```

On mock-5 this creates:

- `POST http://localhost:19081/mock-5/SecondCustomer/2342342`
- `POST http://localhost:19081/mock-5/SecondCustomer/2342342/productClasses/AnotherProduct`

`customer` removes the complete `/productClasses/<name>` suffix. It does not add
a second route. Products can independently override scope, response profile and
URI extension; null inherits all three. Empty objects and unknown scope values are errors. Products
using the customer-only route share **one mapping and one verification probe**.
They must resolve to the same named response profile; different profiles on the
same URL fail explicitly before HTTP requests (even when an HTTP-error override
is selected). Use a product-class URL for a product needing a different response.

Apply, list, dry-run and verify use the same resolved routes. Listing shows the
effective scope, its source and all products sharing each route. A `mixed` source
means some products inherited the setting and others explicitly selected it.
Product-class mapping IDs still identify customer code plus product name. A shared
customer mapping has its own stable ID based on customer code and its extension,
independent of product order or membership. Changing scope creates the destination mapping;
old mappings at the previous scope are not deleted automatically. Retire those
old mappings explicitly if their routes should no longer be served.

## Customer path override

Optional customer-level `customer_path_override` replaces the complete
`/<customer name>/<customer code>` path beneath the target API URL. It does not
change the admin API URL or the target's `/mock-N` prefix.

```yaml
customers:
  "2342342":
    name: SecondCustomer
    customer_path_override: partner/orders
    endpoint_scope: customer
    response_profile: empty-ok
    error_profile: none
    uri_extension: transactions
    delay_ms: 1000
    ProductClasses:
      ProductA:
      ProductB:
        endpoint_scope: product-class
```

On mock-5, A uses `/mock-5/partner/orders/transactions` and B uses
`/mock-5/partner/orders/transactions/productClasses/ProductB`. Without an extension,
a customer-scoped endpoint is simply `/mock-5/partner/orders`.

Omit `customer_path_override` to use the normal customer name/code path. An override
must be a nonempty relative path without leading/trailing slashes; `null`, `""`,
empty segments, query strings, fragments and dot segments are rejected. Segments
are encoded using the existing path rules. This setting belongs to the customer;
products can override their URI extension and scope, but not the customer path.
Customer code/name remain required for selection, identity and configuration.
Changing the override keeps mapping IDs and ownership unchanged, so apply updates
the existing paths. `clean --stale-only` does not select an ID solely because its
path changed. Overrides that cause distinct mapping identities to share a method
and path fail before HTTP requests, even if responses agree.

## URI extension

Optional `uri_extension` adds a relative path after the customer path (normally
name/code, or `customer_path_override`) and before the product-class suffix.
A product inherits its customer's extension unless it
explicitly overrides it. An override replaces the entire extension; `""` explicitly
removes it. Omitting it at customer level means no extension. `null` is invalid.

```yaml
customers:
  "2342342":
    name: SecondCustomer
    endpoint_scope: customer
    response_profile: empty-ok
    error_profile: none
    uri_extension: transactions
    delay_ms: 1000
    ProductClasses:
      ProductA:
      ProductB:
      ProductC:
        endpoint_scope: product-class
        uri_extension: special/v1
      ProductD:
        endpoint_scope: product-class
        uri_extension: ""
```

Under `http://localhost:19081/mock-5`, A and B share
`/SecondCustomer/2342342/transactions`; C uses
`/SecondCustomer/2342342/special/v1/productClasses/ProductC`; D uses
`/SecondCustomer/2342342/productClasses/ProductD`.

Extensions are literal relative paths, not regexes, templates or complete URLs.
Use `transactions` or `transactions/v1`, without leading/trailing slashes or empty
segments. Each segment follows the same validation and percent-encoding rules as
customer/product names; query strings, fragments, pre-encoded values, dot segments
and control characters fail before HTTP requests. Extensions do not change the
target's admin URL or prefix handling. All wb commands use the resolved route.
Listing and dry-run show the effective extension and its inheritance source.

Customer-scoped products share a mapping only when their complete resolved URLs
and response profiles agree. Different extensions create distinct customer routes,
whose IDs and ownership include the extension, independent of product membership.
The empty-extension customer route retains its existing ID. Changing a customer
extension can leave an old shared mapping; use `clean --stale-only --dry-run` to
review it. Product-class IDs remain unchanged when their extension changes, so
`apply` updates their path. Routes from different scopes that collide are rejected.

## Configuration schema version 1

### Reusable request profiles

Optional top-level `request_profiles` defines named method/probe-body pairs.
Omitting it is equivalent to `{}`. Each named profile requires `method` and
`probe_body`; its definition is complete and is never merged with another one.
Customers optionally select `request_profile`; products may override that
selection. A normal response profile may also declare its default `request_profile`.
Precedence: **product → customer → resolved normal response profile → built-in `default`**.

```yaml
response_profiles:
  accepted:
    request_profile: submit-order
    status: 200
    headers:
      Content-Type: application/json
    jsonBody:
      result: ACCEPTED
```

With `submit-order` defined in `request_profiles`, selecting `response_profile:
accepted` also selects that request unless a customer/product overrides it.
A product's response-profile override supplies its own request default; it does
not inherit the original response profile's link. If the selected response has
no link, the built-in default applies. An explicit `request_profile: default` at
any supported level selects POST with JSON `{}`.

The link is optional and is configuration metadata, not a WireMock response
field. All links are validated before HTTP, including unused response profiles.
Error profiles cannot declare request defaults: HTTP-error and timeout selection
retain the request resolved from the normal response profile and explicit
overrides. Errors therefore do not change what verification sends.

The reserved `default` profile is POST with JSON `{}`. It may be selected
explicitly to reset inheritance, but cannot be redefined in `request_profiles`.
Unknown names, null and empty selections fail, including on unselected customers.
Inline `request_method`/`probe_body` customer or product settings are not supported.
Mock assignments and CLI flags do not override request profiles.

```yaml
request_profiles:
  submit-order:
    method: POST
    probe_body:
      type: json
      value:
        correlationId: wb-check
  update-text:
    method: PUT
    probe_body:
      type: text
      value: "example payload"
  read-only:
    method: GET
    probe_body:
      type: none

customers:
  "2342342":
    name: SecondCustomer
    endpoint_scope: product-class
    response_profile: empty-ok
    delay_ms: 1000
    request_profile: submit-order
    ProductClasses:
      Inherited:
      Update:
        request_profile: update-text
      Read:
        request_profile: read-only
      Reset:
        request_profile: default
```

Supported methods are uppercase `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`,
`OPTIONS`. Other spellings and methods fail validation.

| Probe type | Required fields | Bytes and Content-Type sent |
| --- | --- | --- |
| `json` | `type`, `value` (any finite JSON value) | UTF-8 JSON, `application/json` |
| `text` | `type`, `value` (string, including `""`) | Exact UTF-8 text, `text/plain; charset=utf-8` |
| `none` | `type` only | No body and no configured Content-Type |

GET and HEAD profiles require `probe_body: {type: none}`. Bodies are never
silently discarded. Null for `probe_body` is invalid;
`{type: json, value: null}` deliberately sends JSON `null`. JSON arrays/scalars
are supported. Probe bodies cannot reference external files or templates.

The method is installed in the WireMock mapping. Probe bodies are verification
inputs only: mappings still match method and path, without body/header matchers.
Verify sends the resolved method/body. List, dry-run and JSON reports expose the
same settings plus `request_profile` and `request_profile_source` (`default`,
`response-profile`, `customer`, `product`, or `mixed` for a shared route with mixed selection sources).
HEAD verification checks status, headers, delay and an empty received body; the
configured response body remains in the mapping and is checked through the admin API.

Mapping IDs remain stable when profiles change. Applying a profile with another
method updates the existing mapping. Products sharing a customer endpoint must
select the same request profile and response profile; otherwise configuration
fails. A shared mapping ID cannot represent multiple methods. Distinct mapping
IDs may use the same path with different methods. Probe-body differences do not
create additional mappings or verification probes.

All profile definitions and references are validated before HTTP. Existing files
that omit request profiles retain POST with a JSON `{}` probe.

### Repeatable error-profile selection

Customer `error_profile` is optional and defaults to `none` when omitted.
When supplied, use `none` or the name of a profile in `error_profiles`. A mock/customer assignment may override `error_profile`;
omitting it inherits the customer setting. Apply and verify may override both
with `--error-profile NAME` or `--error-profile none`.

Precedence: **CLI → mock/customer assignment → customer → default `none`**. Error-profile and
normal delay selection are independent. Product-class error overrides are not
supported; all endpoints for that customer on that mock share the selection.
`none` is reserved and cannot name a profile definition. Null, empty, non-string
and unknown selections are errors, including on unselected customers/targets.

```yaml
customers:
  "2342342":
    name: SecondCustomer
    endpoint_scope: customer
    response_profile: empty-ok
    error_profile: none
    delay_ms: 1000
wiremocks:
  mock-1:
    api: http://localhost:19081/mock-1
    prefix_handling: strip
    customers:
      "2342342": {}
  mock-2:
    api: http://localhost:19081/mock-2
    prefix_handling: strip
    customers:
      "2342342":
        error_profile: server-error
        delay_ms: 6000
```

This fragment uses the `empty-ok` response and `server-error` definitions in
`wb.yaml`: mock-1 returns the normal response after 1000ms; mock-2 returns the
configured HTTP error after 6000ms. Apply and verify the same file without
repeating error flags. Explicitly override a file's errors for a normal run with:

```sh
./wb apply -f wb.yaml --all-mocks --all-customers --error-profile none
./wb verify -f wb.yaml --all-customers --error-profile none
```

A resolved timeout profile supplies its own delay and keeps the resolved normal
response. `--delay` fails if **any selected endpoint** still resolves to a
timeout. `--error-profile none --delay MS` is valid and uses normal delay
constraints. Unselected timeout customers do not block a normal delay override.
Named HTTP errors replace the response and use normal delay precedence.

List, apply, verify and their JSON reports show `error_profile` and
`error_profile_source` (`default`, `customer`, `mock-customer`, or `cli`) alongside delay
resolution. List shows file selections; it does not inspect live state.
Reapplying without a CLI override restores the file's behavior, which may itself
be an error profile. Mapping IDs and ownership remain unchanged across profiles.
Existing schema-1 files may omit customer `error_profile`; normal responses are
the default. Explicit null and empty values remain invalid. An omitted mock
override inherits the customer selection, while explicit `none` clears it.

### File format and delay selection

Every file requires the integer `schema_version: 1`. This is the first version
embedded in YAML; earlier documentation revision numbers were not file versions.
Missing, non-integer or unsupported versions fail before HTTP requests. No legacy
format detection or automatic conversion is performed.

A file defines a repeatable profile. Apply and verify without a delay argument:

```sh
./wb apply -f wb.baseline.yaml --all-mocks --all-customers
./wb verify -f wb.baseline.yaml --all-customers
./wb list -f wb.baseline.yaml --all-customers
```

```yaml
schema_version: 1
wiremocks:
  mock-1:
    api: http://localhost:19081/mock-1
    prefix_handling: strip
    customers:
      "2342342": {}
  mock-2:
    api: http://localhost:19081/mock-2
    prefix_handling: strip
    customers:
      "2342342":
        delay_ms: 6000
customer_groups: {}
response_profiles:
  empty-ok:
    status: 200
    headers: {}
    body: ""
customers:
  "2342342":
    name: SecondCustomer
    endpoint_scope: customer
    response_profile: empty-ok
    error_profile: none
    delay_ms: 1000
    allowed_delays_ms:
      - 0
      - 1000
      - 6000
error_profiles: {}
```

Here mock-1 uses 1000ms and mock-2 uses 6000ms. Normal delay precedence is:
**CLI `--delay` → mock/customer `delay_ms` → customer `delay_ms`**. The customer
value is required. A target assignment uses `{}` to inherit it or
`{delay_ms: N}` to override it. Null assignments are invalid. Delays are integers
from 0 through 2147483647 milliseconds; zero is a valid explicit override.

`allowed_delays_ms` is an optional customer constraint. When present it must be a
nonempty list of unique valid delays. Customer defaults, all configured target
assignment overrides (even on unselected targets), and normal CLI overrides must
satisfy it. When omitted, any delay in the supported range is permitted.
No product-level delay override is supported.

A timeout error profile uses its required `delay_ms` instead of the normal delay
and deliberately bypasses `allowed_delays_ms`. Combining it with `--delay` fails.
An HTTP-error profile changes the response but uses normal delay precedence.
List shows file-configured delays and sources; apply/dry-run/verify report their
resolved delays and sources, including explicit CLI and timeout overrides.

To migrate an unversioned file: add `schema_version: 1`; replace every customer
`delay` list with a chosen scalar `delay_ms`, optionally retaining the list as
`allowed_delays_ms`; change each target's customer list to a mapping of code to
`{}` or `{delay_ms: N}`; rename timeout profile `delay` to `delay_ms`.
Customer `error_profile` may be omitted for normal responses.
Mapping IDs and ownership metadata are unchanged, so applying the new profile
updates existing mappings. Applying another file does not remove old mappings;
preview `clean --stale-only --dry-run` if you need to remove obsolete routes.

The configuration requires `schema_version`, `wiremocks`, `customer_groups`,
`response_profiles`, `customers` and `error_profiles`. `request_profiles` is optional.
Unknown fields, duplicate
keys and invalid settings fail before HTTP requests. YAML is data, not executable
code. The loader and shared delay resolver implement this contract.

- `wiremocks`: a nonempty mapping of target names. Every target requires `api`,
  `prefix_handling` and `customers` (a nonempty mapping of customer codes to assignment settings). Assignment
  lists may overlap when the same customer should exist on several mocks.
  Duplicate assignments, unknown codes and duplicate normalized API URLs fail.
  URLs must identify independent WireMock instances; DNS/proxy aliases to the
  same backend cannot be detected automatically.
- Each target's `api`: HTTP(S) base URL of one WireMock. Set
  `http://HOST:19081/mock-1` through our Nginx, or `http://HOST:19001` directly.
  Do not append `/__admin/mappings`. Query strings, fragments, embedded credentials
  and redirects are unsupported. The admin endpoint must be accessible without
  additional authentication. HTTPS uses normal certificate verification.
- `prefix_handling`: required, either `strip` or `preserve`. `strip` explicitly
  declares that the proxy removes the path prefix in that target’s `api` before
  forwarding requests. The CLI prints a warning naming the omitted prefix,
  including during dry-run. `preserve` includes that prefix in every mapping.
  There is no default or auto-detection. Missing/unknown modes fail; `strip`
  with a root URL fails because there is no prefix to strip. Direct WireMock
  URLs use `preserve`. If overriding a proxy URL with a direct URL, also update
  this setting in the YAML. Admin calls always use the complete base URL;
  the proxy must route its admin path to WireMock's admin API in either mode.
- `customer_groups`: mapping from group names to nonempty lists of customer codes;
  use `{}` if none are needed. Groups may overlap, but duplicate codes within a
  group and unknown codes fail. Nested groups, wildcards and implicit assignments
  are not supported.
- `customers`: mapping keyed by customer code. Quote numeric codes to preserve
  leading zeros. Each customer requires `name`, `endpoint_scope`, `response_profile`
  and a scalar `delay_ms` default. Optional `error_profile` defaults to `none`.
  Optional `request_profile` selects a reusable request definition; omission uses
  the normal response profile's request default, or built-in `default` (POST with
  JSON `{}`) if that response has no link. `allowed_delays_ms` optionally
  constrains normal delays. `ProductClasses` is optional for
  customer scope and required/nonempty for product-class scope. The required
  customer `response_profile` names its default success response. `ProductClasses`
  maps each product name either to null (an empty YAML value, inheriting the
  customer's profile, scope and extension), or to a nonempty mapping containing
  `response_profile`, `endpoint_scope`, `uri_extension`, `request_profile`,
  or any combination for explicit overrides.
  Empty objects, unknown fields, missing customer profiles and unknown
  profile names are errors, including on unselected customers. Each customer uses one resolved delay per mock, shared by all its endpoints.
- `response_profiles`: a nonempty mapping of named, complete success responses.
  Optional `request_profile` supplies the default request for endpoints using
  that response; customer and product request selections take precedence.
  Each requires `status` (200–299), `headers` (a mapping of string values; `{}`
  explicitly selects no configured headers), and **exactly one** of `body`
  (a string, including `""`) or `jsonBody` (a JSON object). An empty 200 uses
  `status: 200`, `headers: {}`, `body: ""`; it sends zero body bytes. Profiles for
  HTTP 204/205 must use `body: ""`, because these statuses do not carry content.
  The example includes `accepted` and `empty-ok`.
- `error_profiles`: named profiles (may be `{}`). `type: http-error` requires a
  complete `response` with `status` (400–599), `headers`, and exactly one of
  `body` or `jsonBody`. It replaces the selected success response completely,
  including headers. `type: timeout` requires a positive integer `delay_ms` in
  milliseconds and retains each product's resolved success response, including
  empty bodies. Choose a delay longer than the application's request
  timeout. It is a delayed response, not a socket fault or a guaranteed timeout
  for every client. The proxy's own timeout can also terminate the request.

Customer selection requires exactly one of `--customer CODE`, `--group NAME`
or `--all-customers`. `--all-customers` means all customers assigned to each
selected mock, not the entire catalogue. `--customer` and `--group` restrict those
assignments; they never grant additional assignments. With `--all-mocks`, a group
can span several mocks and each receives only its assigned group members.

The complete configuration and every selected delay are validated before any
HTTP request. If a requested customer/group member has no assignment on any
selected mock, the command fails before writing. Selected targets with no matching
customers are included in the plan and reported with a warning; no request is
sent to them. Every active target lists the exact selected customer codes. There
is no silent customer or target omission.

`--delay MS` optionally overrides success and HTTP-error delays, subject to any
selected customer allowlists. A timeout profile supplies its own delay,
outside those allowlists; combining it with `--delay` is an error. `--error-profile
NAME` selects a profile; `none` explicitly selects normal responses. Omitting
the flag uses the resolved file selection. There is no
implicit customer, delay, error profile or deployment selection.

`--dry-run` validates and prints every selected target, customer codes, warnings,
public request URLs and exact mapping JSON without connecting. Each target's
`resolved_profiles` lists the profile for every mapping and its `source`
(`customer` or `product`), plus the effective error profile and its source. This is a read-only
explanation of the generated mappings, not another configuration source.
`--admin-timeout SECONDS` bounds each admin request
(default 15); it does not set the mock response delay. Exit codes: 0 success,
2 invalid configuration/arguments, 1 admin transport/API/readback failure.

## Customer defaults and product overrides

```yaml
response_profiles:
  empty-ok:
    status: 200
    headers: {}
    body: ""
  accepted:
    status: 200
    headers:
      Content-Type: application/json
    jsonBody:
      txn_result:
        result: ACCEPTED
        result_message: Mocked success request

customers:
  "2342342":
    name: Test Customer
    endpoint_scope: product-class
    response_profile: empty-ok
    error_profile: none
    delay_ms: 1000
    allowed_delays_ms:
      - 0
      - 1000
      - 6000
    ProductClasses:
      ProductA:
      ProductB:
        response_profile: accepted
```

ProductA inherits `empty-ok`; ProductB explicitly uses `accepted`. Both inherit
`product-class` scope. There is no implicit global profile or property merging.
Selecting an error profile temporarily overrides the resolved success behavior;
rerunning without the CLI flag restores the file's selection. Use
`--error-profile none` to restore each product's normal response. Existing target,
customer, group and delay CLI flags are unchanged.

## Paths and updates

With `product-class` scope, each product becomes an exact WireMock `urlPath`:

```text
/<customer name>/<customer code>/productClasses/<product class>
```

With `customer` scope, products share `/<customer name>/<customer code>` plus
their resolved URI extension, if any.
See the endpoint scope section above for inheritance and conflict rules.

Names are used literally and percent-encoded as individual path segments. Thus
`Test Customer` becomes `Test%20Customer`; use `name: Test_Customer` if your caller
sends underscores. Legal path punctuation such as `+` stays literal. Slashes,
backslashes, `%`, `?`, `#`, semicolons (servlet path parameters), control characters and
`.`/`..` segments are rejected. Matching is case-sensitive, requires the configured method (POST by default), and
ignores query parameters. No request body or correlation header is required.

For a target with `api: http://HOST:19081/mock-1`, a sample public URL is:
`http://HOST:19081/mock-1/Test%20Customer/3243423434/productClasses/Productclass`.
With explicit `prefix_handling: strip`, the same base URL routes admin calls;
`/mock-1` is excluded from the mapping and the CLI warns about that choice.
With `prefix_handling: preserve`, the mapping starts with `/mock-1` instead.
Our supplied Nginx stack requires `strip`; incorrectly configuring `preserve`
will leave customer requests unmatched. Admin readback verifies stored mappings,
not the proxy's routing behavior; the CLI never silently repairs that mismatch.
Use the appropriate base for each of the five independent WireMocks.

Product-class IDs are stable UUIDs derived from customer code and product class;
shared customer IDs are derived from customer code and extension in separate namespaces.
Both are independent of delay, name and error profile. All desired mappings are validated and existing
IDs on **all active selected targets** are checked before the first write. An
unreachable target or ownership conflict during this preflight prevents writes
to every target. An existing ID without matching `wb` ownership metadata is
rejected. The CLI creates missing mappings and updates
existing ones, then reads each back to verify the requested settings. It never
resets the server or deletes unrelated mappings. Removing a product class,
customer or mock assignment from YAML does not remove an old server mapping; manage such removals
explicitly through WireMock. Renaming a customer updates its existing mappings.
Changing response profiles keeps the same mapping ID and replaces the entire
response. JSON-to-empty changes remove the old JSON body and configured headers;
readback checks both body representation and headers to detect stale values.

Updates across mappings and mocks are **not atomic**. Writes proceed in YAML
target order. On an API failure, the CLI stops, exits nonzero and reports the
failed target, completed targets and how many mappings were verified;
the failing write may also have reached WireMock. Re-run the same command after
fixing connectivity to converge. Do not run concurrent writers for the same
customer. Existing overlapping stubs can affect request matching; inspect them
if the observed response differs from these mappings.

Mappings are in memory. On our read-only upstream deployments, reapply after a
restart; `wb` does not request filesystem persistence. This tool does not enable
capture or change runtime tuning.

WireMock references: [stub creation and editing](https://wiremock.org/docs/stubbing/),
[fixed response delays](https://wiremock.org/docs/simulating-faults/).

## Verification

```sh
python3 -m unittest tools.test_wb tools.test_wb_list tools.test_wb_verify \
  tools.test_wb_http_errors tools.test_wb_help tools.test_wb_endpoint_scope \
  tools.test_wb_clean tools.test_wb_uri_extension tools.test_wb_profiles_v1 \
  tools.test_wb_report tools.test_wb_error_profiles tools.test_wb_requests -v
# Adds unique mappings to a dedicated test instance; use its public Nginx route:
WB_INTEGRATION_API=http://localhost:19081/mock-1 \
  python3 -m unittest tools.test_wb_integration -v
# Five independent instances behind our Nginx routes:
WB_INTEGRATION_FIVE_BASE=http://localhost:19081 \
  python3 -m unittest tools.test_wb_targets_integration -v
# Customer defaults, product overrides, empty/JSON/text transitions:
WB_INTEGRATION_API=http://localhost:19081/mock-1 \
  python3 -m unittest tools.test_wb_profiles_integration -v
# Installs test fixtures, then checks verify success/failure without repairs:
WB_INTEGRATION_FIVE_BASE=http://localhost:19081 \
  python3 -m unittest tools.test_wb_verify_integration -v
```

On 16 October 2026, response-profile request defaults passed 135 focused tests.
Checks cover resolved response selection, product/customer precedence, explicit
default selection, invalid unused links, and exclusion of the link from WireMock
responses. HTTP fixtures confirm apply/list/verify/report agreement and unchanged
request method/body under normal, HTTP-error and timeout profiles. Running
WireMocks were not modified by these checks.

On 15 October 2026, reusable request profiles passed 131 focused tests. Coverage
includes default behavior, customer/product selection, explicit reset, invalid
and unselected definitions, shared-route conflicts and stable mapping identities.
HTTP fixtures verify actual JSON/text/no-body bytes, Content-Type, all supported
methods, HEAD expectations, and apply/list/verify/report agreement after a method
change. These checks did not modify running WireMocks.

Earlier that day, file-configured error profiles passed 121 focused tests.
Coverage includes customer/mock/CLI precedence, explicit `none`, reserved and
unknown names, unselected-target validation, timeout/delay conflicts, stable
mapping IDs, and report provenance. HTTP fixtures apply and verify configured
HTTP errors, short delayed responses, and restoration of normal responses. This
did not apply errors to running WireMocks.

Earlier that day, the report-enabled CLI passed 115 focused tests. Report tests
exercise all four commands against an HTTP fixture, partial write/delete failures,
failed verification, invalid configuration, Ctrl-C, missing dependencies, exclusive
file creation and late output failures. These checks do not modify running
WireMocks.

Earlier that day, schema version 1 passed 101 focused tests, including HTTP
fixtures applying and verifying a single file with different per-target delays,
explicit zero overrides, and failure when verify omits an apply override. Tests
also cover version rejection, constraints on unselected targets, optional
allowlists, timeout behavior and preservation of mapping identities. The updated
example's dry-run resolves 1000ms defaults and a 6000ms mock-2/customer override.
This check did not change the running WireMocks. Earlier checks below refer to
documentation revisions of the previously unversioned configuration.

On 14 October 2026, all 16 validation/HTTP tests passed. The opt-in integration
test also passed against isolated upstream WireMock 3.13.2 through Nginx using
our `/mock-1` routing. It exercised spaces, Unicode and `C++` product names,
one-second responses (1.004–1.005s), a six-second update (6.003s), HTTP 500,
a 600ms timeout profile with a 100ms client deadline, and restoring success.
Repeated application retained the same mapping count, unselected customer
delays and unrelated mappings. This is a functional smoke, not a load test.
Original single-target evidence: `results/wb-cli-20261014/`.

The version-2 extension passed 25 validation/HTTP tests and both integration
tests on 14 October 2026. Five isolated upstream WireMocks behind Nginx verified
disjoint and overlapping assignments, group updates spanning targets, unchanged
unselected customers, explicit no-match reporting, duplicate-free reruns and
single-target updates. An unassigned group was rejected without changing any
target. The HTTP tests also verified that a later target's preflight failure
prevents earlier writes, and that write failures identify completed targets.
Evidence: `results/wb-targets-20261014/`. All six test containers were stopped
after verification; existing deployments were not modified.

Version 3 passed all 31 validation/HTTP tests and all three live integration
tests on 14 October 2026, against five isolated upstream WireMock 3.13.2 instances
behind Nginx. The profile test verified inherited empty HTTP 200 responses with
zero body bytes (1.007s with a 1000ms delay), an independent JSON override,
JSON/empty/text transitions, cleared Content-Type/custom headers, error and
timeout behavior, stable mapping IDs and unchanged other customers. Dry-run
reported the effective profile and its customer/product source. Evidence:
`results/wb-profiles-20261014/`. The six test containers were stopped afterward.

The listing extension passed all 38 validation/HTTP/list tests on 14 October
2026. Listing tests verified no WireMock calls or configuration writes, all five
targets, customer/mock filters, inherited and overridden profiles, explicit
empty results, invalid selections, and the executable `wb list` entrypoint.
Listed paths/profiles match mapping generation; the extracted shared resolver
also reproduced the previously live-tested profile plan exactly.

The verify extension passed 50 validation/HTTP/list/verification tests and its
live integration test on 14 October 2026. Against five isolated upstream
WireMocks through Nginx, it passed all 15 configured endpoints, checked zero-byte
200s and JSON, expected HTTP 500s, one-second responses and shortened timeout
profiles. It rejected an incorrect expected delay before probing and detected a
higher-priority competing stub returning the wrong body. Before/after mapping
snapshots confirmed that verification made no changes. Evidence:
`results/wb-verify-20261014/`. Test containers were stopped after the checks.
