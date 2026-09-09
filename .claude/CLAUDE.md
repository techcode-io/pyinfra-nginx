# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`pyinfra-nginx` is a [pyinfra](https://pyinfra.com) extension package: it exposes `install()` /
`uninstall()` / `add_vhost()` / `remove_vhost()` deploy functions that another pyinfra project
imports to manage `nginx` on a host with a high-performance, security-conscious base
configuration, instead of copy-pasting task files. It follows pyinfra's `pyinfra_*` extension
convention — deploy functions wrapped in `@deploy(...)` from `pyinfra.api`, taking explicit keyword
arguments rather than reading `host.data`, so the caller's inventory model stays decoupled from
this library. It's a sibling of
[`pyinfra-alertmanager`](https://github.com/techcode-io/pyinfra-alertmanager) and
[`pyinfra-node-exporter`](https://github.com/techcode-io/pyinfra-node-exporter) for scaffolding
purposes, but the install shape differs significantly — see below.

## Commands

Managed with `uv`; a `poethepoet` task runner wraps the common commands (`pyproject.toml`
`[tool.poe.tasks]`):

- `uv sync` — install/update the dev environment
- `uv run poe lint` (or `uv run ruff check src`) — lint
- `uv run poe fmt` — fix import order + format (`ruff check --select I --fix` then `ruff format`)
- `uv run poe test` (or `uv run pytest tests`) — run the test suite
- `uv run pytest tests/e2e/test_tasks.py::test_install_then_uninstall -v` — run a single e2e test
- `uv run poe env:configure` — install pre-commit hooks (ruff-check, ruff-format, LF line endings,
  gitlint) for local development

Always invoke tools through `uv run <tool>` (or the `poe` tasks above). Do not call
`.venv/bin/<tool>` directly — `uv run` is what keeps the environment synced with `pyproject.toml`/
`uv.lock` before running, so a stale `.venv` doesn't silently mask dependency changes.

## Architecture

Source lives under `src/pyinfra_nginx/` (src layout, `uv_build` backend):

- **`tasks.py`** — `install()`, `uninstall()`, and `add_vhost()`/`remove_vhost()` all live in this
  one module (not split out, despite `add_vhost`/`remove_vhost` being conceptually a separate
  primitive from the base install) — `install()` calls `add_vhost()` directly for the catch-all
  vhost, and keeping them in one file avoids an import-ordering dance for a two-function-pair
  addition that doesn't warrant its own module.
  - **`install()`/`uninstall()`**: unlike `pyinfra-alertmanager`/`pyinfra-node-exporter` (which
    download a pinned binary release), nginx is installed from the official `nginx.org` apt
    repository via `apt.packages(latest=True)` — **there is no version pin and no
    `DEFAULT_VERSION`, by design**: this matches how the `nginx.org` repo is normally consumed, and
    means there's also no Dependabot++ version-bump workflow in this repo (unlike its siblings) —
    nothing to bump. `install()` imports the nginx.org GPG signing key, adds the apt repo for the
    target's Debian codename — always auto-detected from `/etc/os-release`'s `VERSION_CODENAME`
    via pyinfra's `LinuxDistribution` fact, **not a caller-facing parameter** (see Testing below) —
    installs the package, renders `nginx.conf`/`http.conf` from bundled Jinja templates with the
    tunable performance/security parameters as explicit kwargs (worker connections, client
    body/header buffer sizes and timeouts, gzip, `server_tokens`, ...), uploads the static
    Cloudflare real-ip/allowed-traffic includes, bootstraps a 10-year self-signed default
    certificate if one doesn't already exist, adds the catch-all default vhost via `add_vhost()`
    (not hand-rolled — see below), and cleans up the Debian-packaged default layout
    (`/etc/nginx/modules`, `conf.d/default.conf`). `uninstall()` reverses the package/repo/base
    config, but **deliberately does not remove `sites-available`/`sites-enabled` or any vhost**
    (including the catch-all one) — this library doesn't own that state by convention, and a
    caller may still want it around (eg to reinstall later, or because another process manages
    those vhosts).
    **Ordering matters**: the `conf.d/default.conf`/`modules` cleanup must run *before*
    `add_vhost()`'s catch-all render — the Debian package's stock `default.conf` fails
    `nginx -t`, so any reload attempted before cleanup (including add_vhost's own conditional
    reload) breaks the whole deploy. **Never `apt.packages(purge=True)` on uninstall** — the
    nginx.org package's `postrm purge` script runs `rm -rf /etc/nginx`, which would violate the
    no-vhost-deletion guarantee above.
  - **`add_vhost(name, src, **context)` / `remove_vhost(name)`**: the reusable primitive this
    whole package exists to provide. There is no precedent for this anywhere in the org
    (`pyinfra-alertmanager`/`pyinfra-victoria-metrics` both push all "multi-entry config" out to a
    single caller-owned template, not a per-entry add/remove API), so this is genuinely new
    ground:
    - Uses `sites-available/` + a symlink into `sites-enabled/` — a deliberate improvement over
      the original hand-rolled runbook this was extracted from (which only ever wrote directly
      into `sites-enabled/`): this is now a general-purpose library other repos depend on, and
      disable-without-delete is a real operational need the standard nginx convention already
      solves.
    - The caller owns the vhost template entirely — this library ships no opinionated
      reverse-proxy builder. See `examples/vhost-reverse-proxy.conf.j2` (general-purpose, with an
      optional Cloudflare-only gate) and `examples/vhost-cloudflare-restricted.conf.j2` (minimal,
      dedicated to a Cloudflare-only origin) — neither is deployed by the package, both are
      starting points to copy/adapt.
    - Reload is conditional via `_if=lambda: op.did_change() or ...`, not the eager `.will_change`
      style `install()` uses for its own `restarted=` decision. This matters: `_if` callables are
      evaluated lazily at actual execution time (confirmed in pyinfra internals,
      `api/operation.py`'s `command_generator`), which is the only way to get an accurate "did
      this particular `add_vhost`/`remove_vhost` call actually change anything" answer when
      several such calls run in the same deploy. `.will_change` is a build-time prediction and
      would be wrong here for exactly that reason.
    - `install()` calls `add_vhost()` internally for the catch-all vhost instead of hand-rolling
      render+link+reload again — that duplication (every downstream service in the source runbook
      re-implemented "drop a vhost file + unconditionally reload nginx") is the exact anti-pattern
      this package exists to fix, so `install()` doesn't get to skip it either.
- **`facts.py`** — `NginxVersion`, a pyinfra `FactBase` that runs `nginx -v` and parses the
  installed version, gated by `requires_command` so it returns `None` cleanly when nginx isn't
  present yet. It is **not** used to gate `install()`'s idempotency — apt already handles that for
  the package itself — it exists purely for introspection/tests, matching the sibling convention
  of always shipping a `*Version` fact for the managed thing.
- **`templates/`** — `nginx.conf.j2` and `http.conf.j2` are real Jinja templates (parameterized
  performance/security knobs). `allowed-traffic.include.j2` (a `geo` map defining
  `$is_cloudflare_allowed`) and `cloudflare-real-ip.include.j2` (`set_real_ip_from` lines) both
  render Cloudflare's published IP ranges, but from a **single source of truth** —
  `CLOUDFLARE_IPV4_RANGES`/`CLOUDFLARE_IPV6_RANGES` in `tasks.py` — rather than the two files
  hand-duplicating the same CIDR list in two different nginx directive shapes (the original
  design, before this became a template-driven package: easy to let the two copies drift if
  Cloudflare's ranges ever change and only one file gets updated). **`allowed-traffic.include` is
  only uploaded, and only `include`d by `http.conf.j2`, when `install(cloudflare_ip_allowlist=True)`
  — off by default** (`DEFAULT_CLOUDFLARE_IP_ALLOWLIST = False`): this base config is CDN-agnostic
  (bare metal first, per the repo's own framing — see Architecture intro), so it shouldn't bake in
  an externally-maintained, Cloudflare-specific IP list unless the caller actually wants it. When
  enabled, its `geo` block must still live in `http.conf.j2` rather than a caller's vhost template
  (unlike `cloudflare-real-ip.include`, which stays per-vhost opt-in regardless of this flag) — the
  `geo` directive is only valid at the `http` context in nginx, unlike `real_ip`'s directives (valid
  in `http`/`server`/`location`), so there's no way for a caller's vhost template to `include` it
  itself; `install()` also removes a stale `allowed-traffic.include` from disk if the flag is
  toggled back off after a prior install had it on. `cloudflare_ip_allowlist_extra_cidrs` (default
  `()`) renders an additional `# Extra` section in the `geo` block for CIDRs/IPs the caller wants
  allowed alongside loopback + Cloudflare (eg an office network or bastion) — only meaningful when
  `cloudflare_ip_allowlist=True`. `catch-all.conf.j2` and `nginx.sources.j2` are
  templated purely because `add_vhost`/
  `files.template` always renders through Jinja (one code path, no `template=True/False` toggle),
  even though their only variables (`ssl_certificate`/`ssl_certificate_key`, `debian_codename`) are
  simple substitutions. All resolved via `importlib.resources.files("pyinfra_nginx")` (not a
  `__file__`-relative path), so it works both editable and installed as a wheel. `nginx.sources.j2`
  renders the DEB822 format
  (`Types:`/`URIs:`/`Suites:`/`Components:`/`Signed-By:` key-value pairs) to
  `/etc/apt/sources.list.d/nginx.sources` — the format Debian 12+ supports and Debian 13 (trixie)
  defaults to for its own sources — rather than the legacy one-line `deb [...] <url> <suite>
  <component>` `.list` format. Confirmed against a real `debian:12-slim` (bookworm) container
  during development, not just inferred from apt's changelog: apt 2.6.1 parses `.sources` files
  fine even though bookworm's own default sources are still `.list`-format — DEB822 support long
  predates it becoming the default.
  `install()` also removes `LEGACY_APT_SOURCE_PATH` (`/etc/apt/sources.list.d/nginx.list`) if
  present — a host managed by a version of this package from before the DEB822 switch would
  otherwise end up with the nginx.org repo listed twice under apt. `uninstall()` does the same
  cleanup defensively, in case a host goes straight to `uninstall()` without an intervening
  `install()` on the new version.
- **`__init__.py`** — re-exports the public surface: `install`, `uninstall`, `add_vhost`,
  `remove_vhost`, `NginxVersion`, and the `DEFAULT_*` constants.

## Testing

`tests/e2e/` runs the deploy functions against a **real systemd** container via pyinfra's native
`@podman` connector (not `@docker`), because the whole point of `install()`/`uninstall()` is
systemd unit + real nginx config management (`nginx -t` must actually pass), which a bare Docker
container can't exercise as cleanly.

- `tests/fixtures/systemd/Containerfile` builds a systemd-enabled `debian:13-slim` ("trixie")
  image, with `gnupg` (for `gpg --dearmor`ing the nginx.org signing key), `openssl` (for the
  default self-signed cert), and `procps` (the nginx.org systemd unit's `ExecReload` shells out to
  `/bin/kill`, which isn't in a minimal Debian image without it) added on top of the base
  sibling-repo package set.
- `install()`'s Debian codename auto-detection (via the `LinuxDistribution` fact) means the test
  fixtures don't need to know the container's codename — it just works whether the base image is
  `bookworm`, `trixie`, or anything else `nginx.org` publishes a repo for. If `/etc/os-release`
  has no `VERSION_CODENAME` (eg a non-Debian target), `install()` raises `OperationError` rather
  than guessing — there is no hardcoded fallback codename.
- `tests/e2e/conftest.py`'s `systemd_container` fixture builds that image, starts a
  `--privileged --cgroupns=host` container with `/sys/fs/cgroup` mounted, polls
  `systemctl is-system-running` until ready, and yields the container name; the whole module
  auto-skips (with a clear reason) if `podman` isn't installed or its machine/socket isn't
  reachable.
- `tests/e2e/test_tasks.py` invokes the real `pyinfra` CLI (via `run_pyinfra()`, a subprocess
  helper) against `@podman/<container>` running the fixture scripts under `tests/fixtures/`
  (`tasks_install.py`, `tasks_uninstall.py`, `tasks_add_vhost.py`, `tasks_remove_vhost.py`), then
  asserts on-disk/systemd/`nginx -t` state via `podman exec`, and checks pyinfra's stdout for
  operation names to verify idempotency (eg a no-op re-run of `add_vhost` must not print "Reload
  nginx after enabling vhost: example").
- Unlike alertmanager/node-exporter, there's **no amd64-only gating** here — nginx is a normal
  Debian package (arm64-portable), not a `linux-amd64`-only binary release, so every assertion
  runs unconditionally, including under Podman emulation on Apple Silicon.

CI (`.github/workflows/ci.yml`) installs `podman` via `apt-get` before the test job — skip that
step and the e2e test still "passes" by doing nothing.

On macOS, a stopped podman machine (`podman machine start`) looks identical to podman being
absent — `_podman_available()` returns `False` either way and the module just skips.

`subprocess.run` calls where `check=` is supplied dynamically through `**kwargs` (see
`direct_bind()` in `tests/e2e/conftest.py`) need `# noqa: PLW1510` — ruff can't verify it
statically.

`dpkg -s <pkg>` still exits 0 for a package in "removed, config remains" (`rc`) state — assert
package removal via `dpkg-query -W -f='${Status}' <pkg> | grep -q ' installed$'` (expect no match)
instead.

**Faster than the full pytest fixture** when iterating on a template/config change: build the
image once and run a scratch container by hand (`podman build`/`run` per `Containerfile`), then
`uv run pyinfra -y @podman/<container> tests/fixtures/tasks_install.py` + `podman exec
<container> nginx -t` / `cat <file>` to inspect — skips the fixture's per-test image rebuild and
full install→uninstall→add_vhost sequence. For pure Jinja logic/whitespace bugs, skip pyinfra
entirely and render the `.j2` file directly: `uv run python -c "import jinja2; ..."`.

## Conventions

- README/`.github/` scaffolding (badges, section layout, issue/PR templates, `dependabot.yml`,
  `labels.yml`, the CI shape) is deliberately copied from sibling `techcode-io` repos
  (`pyinfra-alertmanager`, `pyinfra-node-exporter`) — check those before inventing new structure or
  wording. Two things are intentionally *not* copied here: `scripts/project.py` and
  `.github/workflows/dependabot-plus-plus.yml` (both exist solely to bump a pinned upstream
  version, which this repo doesn't have) and `.github/workflows/setup-github-bot/action.yml`
  (its only consumer was that workflow).
- Commit titles must satisfy `.gitlint`: `type: subject` where type is one of
  `build|ci|docs|feat|fix|perf|refactor|test|chore|release`, 5-80 chars total; enforced by the
  commit-msg pre-commit hook.
