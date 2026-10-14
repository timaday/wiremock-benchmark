# Customer mappings with `wb`

`wb` configures POST mappings on a running WireMock from `wb.yaml` in the current
directory. It works with upstream WireMock; no custom image or extension is needed.
Edit the five named targets in [the example](../wb.yaml) before applying.

## Help

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
python3 -m pip install -r tools/requirements-wb.txt

./wb --all-mocks --all-customers --delay 1000 --dry-run
./wb --all-mocks --all-customers --delay 1000
./wb --mock mock-1 --customer 2342342 --delay 6000
./wb --mock mock-1 --customer 2342342 --delay 1000 --error-profile server-error
./wb --mock mock-1 --customer 2342342 --error-profile timeout
# Restore the selected customer's success response:
./wb --mock mock-1 --customer 2342342 --delay 1000
```

To call it as `wb`, add this checkout to PATH (`export PATH="$PWD:$PATH"`). Use
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
mappings, and does not need `--delay`. It reports the configured public POST URL,
mock name, product class, resolved response profile and whether the profile comes
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

Verification requires the intended `--delay`, or a timeout profile supplying its
own delay, just as applying does. The YAML allowlist alone does not identify
which delay was installed; verification never adopts a server value as its
expectation. Select a customer, group or all customers. All configured mocks are
included by default; `--mock NAME` restricts the scope and `--all-mocks` makes it
explicit. `--config PATH` selects another configuration file.

For each selected endpoint, verification reads its stable-ID mapping through the
configured admin URL and compares it against the generated mapping, including
the body representation, configured headers and delay. Missing or mismatched
mappings fail that endpoint without sending a probe to it. For matching mappings,
it sends one POST containing `{}` with `Content-Type: application/json` to the
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
    delay:
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
    uri_extension: transactions
    delay:
      - 1000
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
    uri_extension: transactions
    delay:
      - 1000
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

## Configuration and CLI contract (version 5)

Version 5 adds optional `uri_extension` at customer and product level and optional
`customer_path_override` at customer level. Existing files without these fields
retain their routes.

Version 4 requires an explicit `endpoint_scope` on every customer. Set it to
`product-class` to retain the previous URL shape; missing values fail rather than
guessing which route to install. Existing target prefix handling is unchanged.

The configuration requires `wiremocks`, `customer_groups`, `response_profiles`, `customers`
and `error_profiles`. This replaces the earlier top-level `wiremock_api` and
`prefix_handling` fields; old configuration fails explicitly. Move those fields
into a named `wiremocks` entry (`wiremock_api` becomes `api`), add its `customers`
assignment list, and add `customer_groups: {}` if no groups are needed. Unknown
fields, duplicate YAML keys and invalid values fail before any HTTP request.
YAML is parsed safely; it is not executable code.

The former top-level `response` is replaced by named `response_profiles`.
Move it into a named profile (for example `accepted`) and add
`response_profile: accepted` to each customer. Each HTTP-error profile must also
supply its complete response, including `headers`; no response fields are merged.

- `wiremocks`: a nonempty mapping of target names. Every target requires `api`,
  `prefix_handling` and `customers` (a nonempty list of customer codes). Assignment
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
  leading zeros. Each customer requires `name`, `endpoint_scope`, `response_profile`, a nonempty
  `delay` list of allowed integer milliseconds. `ProductClasses` is optional for
  customer scope and required/nonempty for product-class scope. The required
  customer `response_profile` names its default success response. `ProductClasses`
  maps each product name either to null (an empty YAML value, inheriting the
  customer's profile, scope and extension), or to a nonempty mapping containing
  `response_profile`, `endpoint_scope`, `uri_extension`, or any combination for explicit overrides.
  Empty objects, unknown fields, missing customer profiles and unknown
  profile names are errors, including on unselected customers. The delay list is an allowlist, not a
  randomly sampled distribution. One selected delay applies to every selected
  product class. Duplicate delays are invalid.
- `response_profiles`: a nonempty mapping of named, complete success responses.
  Each requires `status` (200–299), `headers` (a mapping of string values; `{}`
  explicitly selects no configured headers), and **exactly one** of `body`
  (a string, including `""`) or `jsonBody` (a JSON object). An empty 200 uses
  `status: 200`, `headers: {}`, `body: ""`; it sends zero body bytes. Profiles for
  HTTP 204/205 must use `body: ""`, because these statuses do not carry content.
  The example includes `accepted` and `empty-ok`.
- `error_profiles`: named profiles (may be `{}`). `type: http-error` requires a
  complete `response` with `status` (400–599), `headers`, and exactly one of
  `body` or `jsonBody`. It replaces the selected success response completely,
  including headers. `type: timeout` requires a positive integer `delay` in
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

`--delay MS` is required for success and HTTP-error responses, and must appear in
every selected customer's allowlist. A timeout profile supplies its own delay,
outside that allowlist; combining it with `--delay` is an error. `--error-profile
NAME` selects a profile; omitting it selects the success response. There is no
implicit customer, delay, error profile or deployment selection.

`--dry-run` validates and prints every selected target, customer codes, warnings,
public request URLs and exact mapping JSON without connecting. Each target's
`resolved_profiles` lists the profile for every mapping and its `source`
(`customer` or `product`), plus any CLI error profile. This is a read-only
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
    delay:
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
rerunning without it restores each product's own response. Existing target,
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
`.`/`..` segments are rejected. Matching is case-sensitive, requires POST, and
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
python3 -m unittest tools.test_wb tools.test_wb_list tools.test_wb_verify -v
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
