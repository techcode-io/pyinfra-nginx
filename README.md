<h1 align="center">Pyinfra Nginx</h1>

<p align="center">
  <i align="center">Install and uninstall a high-performance, flexible nginx with pyinfra, with helpers to add/remove vhosts.</i>
</p>

<h4 align="center">
  <a href="https://github.com/techcode-io/pyinfra-nginx/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/techcode-io/pyinfra-nginx/ci.yml?branch=main&label=ci&style=flat-square" alt="continuous integration" style="height: 20px;">
  </a>
  <a href="https://github.com/techcode-io/pyinfra-nginx/graphs/contributors">
    <img src="https://img.shields.io/github/contributors-anon/techcode-io/pyinfra-nginx?color=yellow&style=flat-square" alt="contributors" style="height: 20px;">
  </a>
  <a href="https://opensource.org/licenses/Apache-2.0">
    <img src="https://img.shields.io/badge/apache%202.0-blue.svg?style=flat-square&label=license" alt="license" style="height: 20px;">
  </a>
  <br>
</h4>

- [Source](https://github.com/techcode-io/pyinfra-nginx)
- [Issues](https://github.com/techcode-io/pyinfra-nginx/issues)
- [Contact](mailto:adrien.mannocci@gmail.com)
- [Maintained by techcode.io](https://techcode.io)

## :package: Prerequisites

- [uv](https://docs.astral.sh/uv/) for development.
- [Podman](https://podman.io/docs) to run the end-to-end tests.

## :sparkles: Features

- Idempotent `install()`: adds the official `nginx.org` apt repository, installs `nginx`, renders
  a tuned base configuration (async I/O thread pool, gzip, DDoS-defense buffer/timeout tuning,
  open file cache, JSON access logs), bootstraps a self-signed default certificate, and enables a
  catch-all default vhost that drops any request without a matching `server_name`.
- Always tracks the latest `nginx.org` release for the target Debian codename — no version pin to
  maintain.
- `add_vhost()` / `remove_vhost()`: render any Jinja2 vhost template you own into
  `sites-available/`, symlink it into `sites-enabled/`, and reload nginx only when something
  actually changed. No opinionated vhost builder is bundled — see
  [`examples/vhost-reverse-proxy.conf.j2`](examples/vhost-reverse-proxy.conf.j2) for a starting
  point.
- `uninstall()` reverses the base install (package, repo, keyring, base config) but never deletes
  vhosts you added — they're not this library's to destroy.
- Deploy functions only, no CLI: import it into any [pyinfra](https://pyinfra.com) project.

## :dart: Motivation

- We needed to manage `nginx` the same way across every server we operate, with one flexible,
  reusable base configuration instead of copy-pasted task files.
- Every service behind nginx used to hand-roll its own "drop a vhost file into `sites-enabled/`
  and reload nginx" logic — `add_vhost()`/`remove_vhost()` exist to replace that duplication with
  one tested primitive.
- The solution should be idempotent and skip work that has already been done.

## :hammer: Workflow

### Setup

The following steps will ensure your project is cloned properly.

1. Clone repository:
   ```shell
   git clone https://github.com/techcode-io/pyinfra-nginx
   cd pyinfra-nginx
   ```
2. Install dependencies and setup environment:
   ```shell
   uv sync
   uv run poe env:configure
   ```

### Lint

- To lint you have to use the workflow.

```bash
uv run poe lint
```

### Format

- To format you have to use the workflow.

```bash
uv run poe fmt
```

- It will format the project code using `ruff`.

### Test

- To test you have to use the workflow.
- Tests are based on `pytest` and run the deploy functions against a real systemd container via
  Podman.

```bash
uv run poe test
```

## 📖 Usage

### How it works

- `install()`, `uninstall()`, `add_vhost()` and `remove_vhost()` are
  [pyinfra](https://pyinfra.com) deploy functions, wrapped with `@deploy(...)` from `pyinfra.api`.
- They take explicit keyword arguments instead of reading `host.data`, so any inventory can use
  them.
- `install()` imports the `nginx.org` GPG signing key, adds its apt repository for the target's
  Debian codename (auto-detected from `/etc/os-release` — not configurable),
  installs `nginx` (always the latest release — no version pin), renders
  `/etc/nginx/nginx.conf` and `/etc/nginx/conf.d/http.conf` from bundled Jinja2 templates using the
  tunable parameters below, uploads the Cloudflare real-ip include (always) and the Cloudflare
  IP allowlist (only if `cloudflare_ip_allowlist=True` — off by default), bootstraps a 10-year
  self-signed default certificate if one doesn't already exist, enables a
  catch-all default vhost (via `add_vhost()`, so it behaves exactly like any vhost you add
  yourself) that returns `444` for any request without a matching `server_name`, and cleans up the
  Debian-packaged default layout.
- `uninstall()` stops and disables the service, then removes the package, apt repository, signing
  key, and the base configuration this library wrote — but it never removes
  `/etc/nginx/sites-available`, `/etc/nginx/sites-enabled`, or any vhost you added (including the
  catch-all one): that state isn't this library's to destroy, and you may still want it around to
  reinstall later.

### How to install nginx

- This project isn't published to PyPI yet, so add it as a git dependency pinned to a commit.
- Find the commit you want to pin to on
  the [commit history](https://github.com/techcode-io/pyinfra-nginx/commits/main), then add
  it to your pyinfra project.

```bash
uv add git+https://github.com/techcode-io/pyinfra-nginx --rev <commit-sha>
# or
pip install git+https://github.com/techcode-io/pyinfra-nginx@<commit-sha>
```

- This adds the following to your `pyproject.toml`, which you can also edit directly.

```toml
[project]
dependencies = ["pyinfra-nginx"]

[tool.uv.sources]
pyinfra-nginx = { git = "https://github.com/techcode-io/pyinfra-nginx", rev = "<commit-sha>" }
```

- Then call `install()` from a deploy script.

```python
from pyinfra_nginx import install

install()
```

### How to uninstall nginx

- Call `uninstall()` from a deploy script.

```python
from pyinfra_nginx import uninstall

uninstall()
```

### How vhosts work

- This library ships no opinionated reverse-proxy template — you own the vhost content entirely,
  the same way `pyinfra-alertmanager` lets you own its alerting config.
- `add_vhost(name, src, **context)` renders `src` (a Jinja2 template, any valid pyinfra
  `files.template` source) to `/etc/nginx/sites-available/<name>.conf`, symlinks it into
  `/etc/nginx/sites-enabled/<name>.conf`, and reloads nginx only if the render or the symlink
  actually changed.
- `remove_vhost(name)` disables and deletes it, reloading nginx only if it existed.
- See [`examples/vhost-reverse-proxy.conf.j2`](examples/vhost-reverse-proxy.conf.j2) for an
  annotated starting point (HTTP→HTTPS redirect, TLS 1.3, optional Cloudflare-only access gate,
  security headers, `proxy_pass`), or
  [`examples/vhost-cloudflare-restricted.conf.j2`](examples/vhost-cloudflare-restricted.conf.j2)
  for a minimal example dedicated to a Cloudflare-only origin (real-IP restoration +
  Cloudflare-IP-range gate, via `$is_cloudflare_allowed` — requires
  `install(cloudflare_ip_allowlist=True)`) — neither is deployed by this package, copy and adapt
  them.

```python
from pyinfra_nginx import add_vhost, remove_vhost

add_vhost(
    "example.com",
    src="files/vhosts/example.conf.j2",
    server_name="example.com",
    upstream="127.0.0.1:8080",
    ssl_certificate="/etc/ssl/certs/example.com.crt",
    ssl_certificate_key="/etc/ssl/private/example.com.key",
    restrict_to_cloudflare=False,
)

# ... later, if the service is decommissioned:
remove_vhost("example.com")
```

### How to customize the install

- All functions accept keyword arguments; defaults match the base configuration this library was
  extracted from.

```python
from pyinfra_nginx import install

install(
    worker_connections=2048,
    client_max_body_size="64m",
    gzip=True,
    server_tokens=False,
)
```

| Function   | Parameter                      | Default      | Description                                                          |
|------------|---------------------------------|--------------|------------------------------------------------------------------------|
| `install`  | `worker_connections`            | `1024`       | Max connections per worker (`events { worker_connections }`)           |
| `install`  | `worker_rlimit_nofile`          | `65535`      | Worker file descriptor limit                                           |
| `install`  | `thread_pool_max_queue`         | `65536`      | Max queued jobs for the async I/O `reactor` thread pool                |
| `install`  | `server_name_in_redirect`       | `False`      | Whether to use the matched `server_name` in redirects (vs the request's `Host`) |
| `install`  | `server_names_hash_max_size`    | `512`        | Max size of the `server_name` hash table                               |
| `install`  | `server_names_hash_bucket_size` | `512`        | Bucket size of the `server_name` hash table                            |
| `install`  | `aio`                           | `True`       | Enable threaded asynchronous file I/O (`aio threads=reactor`)          |
| `install`  | `aio_write`                     | `True`       | Also use asynchronous I/O for writes                                   |
| `install`  | `sendfile`                      | `True`       | Enable `sendfile()` for serving static files                           |
| `install`  | `sendfile_max_chunk`            | `512k`       | Max bytes sent per `sendfile()` call, so one connection can't monopolize a worker |
| `install`  | `directio`                      | `4m`         | Bypass the OS page cache for files at/above this size (`off` to disable) |
| `install`  | `directio_alignment`            | `4096`       | Block alignment for `directio` reads (match your disk's block size)    |
| `install`  | `output_buffers`                | `2 512k`     | Number and size of buffers used to read files (pairs with `directio`)  |
| `install`  | `tcp_nopush`                    | `True`       | Send response headers in one packet where possible (pairs with `sendfile`) |
| `install`  | `tcp_nodelay`                   | `True`       | Disable Nagle's algorithm on keep-alive connections                    |
| `install`  | `reset_timedout_connection`     | `True`       | Free memory immediately for timed-out connections                      |
| `install`  | `client_max_body_size`          | `16m`        | Max accepted request body size                                         |
| `install`  | `client_body_buffer_size`       | `256k`       | Client request body buffer size                                        |
| `install`  | `client_body_timeout`           | `1m`         | Client request body read timeout                                       |
| `install`  | `client_header_buffer_size`     | `2k`         | Client request header buffer size                                      |
| `install`  | `client_header_timeout`         | `1m`         | Client request header read timeout                                     |
| `install`  | `keepalive_timeout`             | `30`         | Keep-alive connection timeout (seconds)                                 |
| `install`  | `large_client_header_buffers`   | `4 8k`       | Max number and size of large client header buffers                     |
| `install`  | `send_timeout`                  | `30`         | Response write timeout (seconds)                                       |
| `install`  | `open_file_cache_max`           | `5000`       | Max entries in the open file descriptor/stat cache                     |
| `install`  | `open_file_cache_inactive`      | `20s`        | Evict cache entries not accessed within this time                      |
| `install`  | `open_file_cache_valid`         | `60s`        | How often to revalidate cached entries                                 |
| `install`  | `open_file_cache_min_uses`      | `5`          | Min accesses within `open_file_cache_inactive` to stay cached           |
| `install`  | `open_file_cache_errors`        | `True`       | Also cache file-not-found/permission errors                            |
| `install`  | `gzip`                          | `True`       | Enable gzip compression                                                |
| `install`  | `gzip_comp_level`               | `6`          | Gzip compression level (1-9, higher = smaller/slower)                  |
| `install`  | `gzip_buffers`                  | `16 8k`      | Number and size of buffers used to compress responses                  |
| `install`  | `gzip_types`                    | `DEFAULT_GZIP_TYPES` | MIME types to compress (tuple of strings; text/JS/JSON/XML plus modern static assets — SVG, wasm, web fonts) |
| `install`  | `server_tokens`                 | `False`      | Whether to expose the nginx version in responses/error pages           |
| `install`  | `cloudflare_ip_allowlist`       | `False`      | Upload `conf.d/allowed-traffic.include` and define `$is_cloudflare_allowed` globally (see below) |
| `install`  | `cloudflare_ip_allowlist_extra_cidrs` | `()`   | Extra CIDRs/IPs (eg an office network, a bastion) allowed alongside loopback + Cloudflare |

## :heart: Contributing

If you find this project useful here's how you can help, please click the :eye: **Watch** button
to avoid missing notifications about new versions, and give it a :star2: **GitHub Star**!

You can also contribute by:

- Sending a [Pull Request](https://github.com/techcode-io/pyinfra-nginx/pulls) with your
  awesome new features and bug fixed.
- Be part of the community and help resolve
  [Issues](https://github.com/techcode-io/pyinfra-nginx/issues).

## 🧾 License

The `pyinfra-nginx` project is free and open-source software licensed under the Apache-2.0
license.
