"""
Install/uninstall nginx, and add/remove vhosts, via pyinfra.

Filesystem paths below are what this package manages and reads back (eg to decide whether a
default cert already exists); the `DEFAULT_*` constants are the tunable performance/security knobs
for `install()`'s base configuration, each mirrored by an `install()` kwarg of the same name
(minus the `DEFAULT_` prefix) — see `install()`'s signature and the README's parameter table for
what each one renders into `nginx.conf`/`http.conf`.
"""

from importlib import resources
from pathlib import Path
from typing import Any, Final

from pyinfra.api import deploy
from pyinfra.api.exceptions import OperationError
from pyinfra.context import host
from pyinfra.facts.files import File
from pyinfra.facts.hardware import Cpus
from pyinfra.facts.server import LinuxDistribution
from pyinfra.operations import apt, files, server, systemd

KEYRING_PATH: Final[str] = "/usr/share/keyrings/nginx-archive-keyring.gpg"
DOWNLOAD_KEY_PATH: Final[str] = "/tmp/nginx_signing.key"
APT_SOURCE_PATH: Final[str] = "/etc/apt/sources.list.d/nginx.sources"
# Path this package wrote the repo to before switching to the DEB822 `.sources` format above;
# install() removes it if present so a host managed by an older version of this package doesn't
# end up with the nginx.org repo listed twice under apt.
LEGACY_APT_SOURCE_PATH: Final[str] = "/etc/apt/sources.list.d/nginx.list"
NGINX_CONF_PATH: Final[str] = "/etc/nginx/nginx.conf"
CONF_D_DIR: Final[str] = "/etc/nginx/conf.d"
HTTP_CONF_PATH: Final[str] = f"{CONF_D_DIR}/http.conf"
ALLOWED_TRAFFIC_INCLUDE_PATH: Final[str] = f"{CONF_D_DIR}/allowed-traffic.include"
CLOUDFLARE_REAL_IP_INCLUDE_PATH: Final[str] = f"{CONF_D_DIR}/cloudflare-real-ip.include"
DEFAULT_CERT_PATH: Final[str] = "/etc/ssl/certs/default.crt"
DEFAULT_KEY_PATH: Final[str] = "/etc/ssl/private/default.key"
CATCH_ALL_VHOST_NAME: Final[str] = "catch-all"
SITES_AVAILABLE_DIR: Final[str] = "/etc/nginx/sites-available"
SITES_ENABLED_DIR: Final[str] = "/etc/nginx/sites-enabled"

# Single source of truth for Cloudflare's published IP ranges (https://www.cloudflare.com/ips/),
# rendered into both allowed-traffic.include.j2 (a `geo` map) and cloudflare-real-ip.include.j2
# (`set_real_ip_from` lines) — two different nginx directive shapes need the same underlying data,
# so keep it here instead of hand-duplicating the list in both static files.
CLOUDFLARE_IPV4_RANGES: Final[tuple[str, ...]] = (
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "108.162.192.0/18",
    "131.0.72.0/22",
    "141.101.64.0/18",
    "162.158.0.0/15",
    "172.64.0.0/13",
    "173.245.48.0/20",
    "188.114.96.0/20",
    "190.93.240.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
)
CLOUDFLARE_IPV6_RANGES: Final[tuple[str, ...]] = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

DEFAULT_WORKER_CONNECTIONS: Final[int] = 1024
DEFAULT_WORKER_RLIMIT_NOFILE: Final[int] = 65535
DEFAULT_THREAD_POOL_MAX_QUEUE: Final[int] = 65536
DEFAULT_SERVER_NAME_IN_REDIRECT: Final[bool] = False
DEFAULT_SERVER_NAMES_HASH_MAX_SIZE: Final[int] = 512
DEFAULT_SERVER_NAMES_HASH_BUCKET_SIZE: Final[int] = 512
DEFAULT_AIO: Final[bool] = True
DEFAULT_AIO_WRITE: Final[bool] = True
DEFAULT_SENDFILE: Final[bool] = True
DEFAULT_SENDFILE_MAX_CHUNK: Final[str] = "512k"
DEFAULT_DIRECTIO: Final[str] = "4m"
DEFAULT_DIRECTIO_ALIGNMENT: Final[int] = 4096
DEFAULT_OUTPUT_BUFFERS: Final[str] = "2 512k"
DEFAULT_TCP_NOPUSH: Final[bool] = True
DEFAULT_TCP_NODELAY: Final[bool] = True
DEFAULT_RESET_TIMEDOUT_CONNECTION: Final[bool] = True
DEFAULT_CLIENT_MAX_BODY_SIZE: Final[str] = "16m"
DEFAULT_CLIENT_BODY_BUFFER_SIZE: Final[str] = "256k"
DEFAULT_CLIENT_BODY_TIMEOUT: Final[str] = "1m"
DEFAULT_CLIENT_HEADER_BUFFER_SIZE: Final[str] = "2k"
DEFAULT_CLIENT_HEADER_TIMEOUT: Final[str] = "1m"
DEFAULT_KEEPALIVE_TIMEOUT: Final[int] = 30
DEFAULT_LARGE_CLIENT_HEADER_BUFFERS: Final[str] = "4 8k"
DEFAULT_SEND_TIMEOUT: Final[int] = 30
DEFAULT_OPEN_FILE_CACHE_MAX: Final[int] = 5000
DEFAULT_OPEN_FILE_CACHE_INACTIVE: Final[str] = "20s"
DEFAULT_OPEN_FILE_CACHE_VALID: Final[str] = "60s"
DEFAULT_OPEN_FILE_CACHE_MIN_USES: Final[int] = 5
DEFAULT_OPEN_FILE_CACHE_ERRORS: Final[bool] = True
DEFAULT_GZIP: Final[bool] = True
DEFAULT_GZIP_COMP_LEVEL: Final[int] = 6
DEFAULT_GZIP_BUFFERS: Final[str] = "16 8k"
DEFAULT_GZIP_TYPES: Final[tuple[str, ...]] = (
    "text/plain",
    "text/css",
    "application/json",
    "application/x-javascript",
    "text/xml",
    "application/xml",
    "application/xml+rss",
    "text/javascript",
    "application/javascript",
    "text/x-js",
    # Modern static asset types.
    "image/svg+xml",
    "application/wasm",
    "application/manifest+json",
    "font/ttf",
    "font/otf",
    "font/woff",
    "font/woff2",
    "application/vnd.ms-fontobject",
)
DEFAULT_SERVER_TOKENS: Final[bool] = False
# Off by default: this base config is CDN-agnostic (bare metal first), so it shouldn't bake in a
# Cloudflare-specific, externally-maintained IP list unless the caller actually wants it.
DEFAULT_CLOUDFLARE_IP_ALLOWLIST: Final[bool] = False
# Additional CIDRs/IPs (eg an office network, a bastion, a VPN exit) to allow alongside loopback
# and Cloudflare's ranges. Only used when cloudflare_ip_allowlist=True.
DEFAULT_CLOUDFLARE_IP_ALLOWLIST_EXTRA_CIDRS: Final[tuple[str, ...]] = ()

_TEMPLATES: Final = resources.files("pyinfra_nginx") / "templates"


@deploy("Add nginx vhost")
def add_vhost(name: str, src: str | Path, **context: Any) -> None:
    """
    Render a vhost from a Jinja2 template into sites-available and enable it by symlinking into
    sites-enabled, reloading nginx only if the rendered configuration or the symlink actually
    changed.

    This library ships no opinionated vhost template — the caller owns `src` entirely (routing,
    TLS, upstreams, headers, ...); see `examples/vhost-reverse-proxy.conf.j2` for a starting point.

    Args:
        name: vhost identifier; used as the filename (`<name>.conf`) in both sites-available/ and
            sites-enabled/.
        src: path to a Jinja2 template (any valid pyinfra `files.template` src).
        **context: template variables passed through to `files.template`.
    """
    vhost = files.template(
        name=f"Render nginx vhost configuration: {name}",
        src=str(src),
        dest=f"{SITES_AVAILABLE_DIR}/{name}.conf",
        **context,
    )

    link = files.link(
        name=f"Enable nginx vhost: {name}",
        path=f"{SITES_ENABLED_DIR}/{name}.conf",
        target=f"{SITES_AVAILABLE_DIR}/{name}.conf",
    )

    systemd.service(
        name=f"Reload nginx after enabling vhost: {name}",
        service="nginx.service",
        running=True,
        reloaded=True,
        _if=lambda: vhost.did_change() or link.did_change(),
    )


@deploy("Remove nginx vhost")
def remove_vhost(name: str) -> None:
    """
    Disable and delete a vhost previously added with `add_vhost`, reloading nginx only if it
    actually existed.

    Args:
        name: vhost identifier, matching the `name` originally passed to `add_vhost`.
    """
    link = files.link(
        name=f"Disable nginx vhost: {name}",
        path=f"{SITES_ENABLED_DIR}/{name}.conf",
        present=False,
    )

    conf = files.file(
        name=f"Remove nginx vhost configuration: {name}",
        path=f"{SITES_AVAILABLE_DIR}/{name}.conf",
        present=False,
    )

    systemd.service(
        name=f"Reload nginx after removing vhost: {name}",
        service="nginx.service",
        running=True,
        reloaded=True,
        _if=lambda: link.did_change() or conf.did_change(),
    )


@deploy("Install nginx")
def install(
    worker_connections: int = DEFAULT_WORKER_CONNECTIONS,
    worker_rlimit_nofile: int = DEFAULT_WORKER_RLIMIT_NOFILE,
    thread_pool_max_queue: int = DEFAULT_THREAD_POOL_MAX_QUEUE,
    server_name_in_redirect: bool = DEFAULT_SERVER_NAME_IN_REDIRECT,
    server_names_hash_max_size: int = DEFAULT_SERVER_NAMES_HASH_MAX_SIZE,
    server_names_hash_bucket_size: int = DEFAULT_SERVER_NAMES_HASH_BUCKET_SIZE,
    aio: bool = DEFAULT_AIO,
    aio_write: bool = DEFAULT_AIO_WRITE,
    sendfile: bool = DEFAULT_SENDFILE,
    sendfile_max_chunk: str = DEFAULT_SENDFILE_MAX_CHUNK,
    directio: str = DEFAULT_DIRECTIO,
    directio_alignment: int = DEFAULT_DIRECTIO_ALIGNMENT,
    output_buffers: str = DEFAULT_OUTPUT_BUFFERS,
    tcp_nopush: bool = DEFAULT_TCP_NOPUSH,
    tcp_nodelay: bool = DEFAULT_TCP_NODELAY,
    reset_timedout_connection: bool = DEFAULT_RESET_TIMEDOUT_CONNECTION,
    client_max_body_size: str = DEFAULT_CLIENT_MAX_BODY_SIZE,
    client_body_buffer_size: str = DEFAULT_CLIENT_BODY_BUFFER_SIZE,
    client_body_timeout: str = DEFAULT_CLIENT_BODY_TIMEOUT,
    client_header_buffer_size: str = DEFAULT_CLIENT_HEADER_BUFFER_SIZE,
    client_header_timeout: str = DEFAULT_CLIENT_HEADER_TIMEOUT,
    keepalive_timeout: int = DEFAULT_KEEPALIVE_TIMEOUT,
    large_client_header_buffers: str = DEFAULT_LARGE_CLIENT_HEADER_BUFFERS,
    send_timeout: int = DEFAULT_SEND_TIMEOUT,
    open_file_cache_max: int = DEFAULT_OPEN_FILE_CACHE_MAX,
    open_file_cache_inactive: str = DEFAULT_OPEN_FILE_CACHE_INACTIVE,
    open_file_cache_valid: str = DEFAULT_OPEN_FILE_CACHE_VALID,
    open_file_cache_min_uses: int = DEFAULT_OPEN_FILE_CACHE_MIN_USES,
    open_file_cache_errors: bool = DEFAULT_OPEN_FILE_CACHE_ERRORS,
    gzip: bool = DEFAULT_GZIP,
    gzip_comp_level: int = DEFAULT_GZIP_COMP_LEVEL,
    gzip_buffers: str = DEFAULT_GZIP_BUFFERS,
    gzip_types: tuple[str, ...] = DEFAULT_GZIP_TYPES,
    server_tokens: bool = DEFAULT_SERVER_TOKENS,
    cloudflare_ip_allowlist: bool = DEFAULT_CLOUDFLARE_IP_ALLOWLIST,
    cloudflare_ip_allowlist_extra_cidrs: tuple[
        str, ...
    ] = DEFAULT_CLOUDFLARE_IP_ALLOWLIST_EXTRA_CIDRS,
):
    files.download(
        name="Download nginx signing key",
        src="https://nginx.org/keys/nginx_signing.key",
        dest=DOWNLOAD_KEY_PATH,
    )

    server.shell(
        name="Import nginx signing key",
        commands=f"gpg --dearmor --batch --yes -o {KEYRING_PATH} {DOWNLOAD_KEY_PATH}",
    )

    files.file(
        name="Delete nginx signing key",
        path=DOWNLOAD_KEY_PATH,
        present=False,
    )

    debian_codename = host.get_fact(LinuxDistribution)["release_meta"].get(
        "VERSION_CODENAME"
    )
    if not debian_codename:
        raise OperationError(
            "Could not detect the target's Debian codename from /etc/os-release "
            "(VERSION_CODENAME) — is this a Debian host?"
        )

    files.file(
        name="Remove legacy nginx repository (pre-DEB822 upgrade path)",
        path=LEGACY_APT_SOURCE_PATH,
        present=False,
    )

    files.template(
        name="Add nginx repository",
        src=str(_TEMPLATES / "nginx.sources.j2"),
        dest=APT_SOURCE_PATH,
        debian_codename=debian_codename,
    )

    apt.packages(
        name="Install nginx server",
        update=True,
        latest=True,
        packages=["nginx"],
    )

    nginx_conf = files.template(
        name="Set main nginx configuration",
        src=str(_TEMPLATES / "nginx.conf.j2"),
        dest=NGINX_CONF_PATH,
        nginx_threads=host.get_fact(Cpus),
        worker_connections=worker_connections,
        worker_rlimit_nofile=worker_rlimit_nofile,
        thread_pool_max_queue=thread_pool_max_queue,
    )

    http_conf = files.template(
        name="Set nginx http configuration",
        src=str(_TEMPLATES / "http.conf.j2"),
        dest=HTTP_CONF_PATH,
        server_name_in_redirect=server_name_in_redirect,
        server_names_hash_max_size=server_names_hash_max_size,
        server_names_hash_bucket_size=server_names_hash_bucket_size,
        aio=aio,
        aio_write=aio_write,
        sendfile=sendfile,
        sendfile_max_chunk=sendfile_max_chunk,
        directio=directio,
        directio_alignment=directio_alignment,
        output_buffers=output_buffers,
        tcp_nopush=tcp_nopush,
        tcp_nodelay=tcp_nodelay,
        reset_timedout_connection=reset_timedout_connection,
        client_max_body_size=client_max_body_size,
        client_body_buffer_size=client_body_buffer_size,
        client_body_timeout=client_body_timeout,
        client_header_buffer_size=client_header_buffer_size,
        client_header_timeout=client_header_timeout,
        keepalive_timeout=keepalive_timeout,
        large_client_header_buffers=large_client_header_buffers,
        send_timeout=send_timeout,
        open_file_cache_max=open_file_cache_max,
        open_file_cache_inactive=open_file_cache_inactive,
        open_file_cache_valid=open_file_cache_valid,
        open_file_cache_min_uses=open_file_cache_min_uses,
        open_file_cache_errors=open_file_cache_errors,
        gzip=gzip,
        gzip_comp_level=gzip_comp_level,
        gzip_buffers=gzip_buffers,
        gzip_types=gzip_types,
        server_tokens=server_tokens,
        cloudflare_ip_allowlist=cloudflare_ip_allowlist,
    )

    if cloudflare_ip_allowlist:
        files.template(
            name="Upload nginx conf: allowed-traffic.include",
            src=str(_TEMPLATES / "allowed-traffic.include.j2"),
            dest=ALLOWED_TRAFFIC_INCLUDE_PATH,
            cloudflare_ipv4_ranges=CLOUDFLARE_IPV4_RANGES,
            cloudflare_ipv6_ranges=CLOUDFLARE_IPV6_RANGES,
            extra_cidrs=cloudflare_ip_allowlist_extra_cidrs,
            mode="644",
        )
    else:
        # Remove it if a previous install() call had cloudflare_ip_allowlist=True — otherwise
        # toggling it off would leave a stale, unreferenced file behind.
        files.file(
            name="Remove nginx conf: allowed-traffic.include (cloudflare_ip_allowlist disabled)",
            path=ALLOWED_TRAFFIC_INCLUDE_PATH,
            present=False,
        )

    files.template(
        name="Upload nginx conf: cloudflare-real-ip.include",
        src=str(_TEMPLATES / "cloudflare-real-ip.include.j2"),
        dest=CLOUDFLARE_REAL_IP_INCLUDE_PATH,
        cloudflare_ipv4_ranges=CLOUDFLARE_IPV4_RANGES,
        cloudflare_ipv6_ranges=CLOUDFLARE_IPV6_RANGES,
        mode="644",
    )

    files.directory(
        name="Create nginx sites-available directory", path=SITES_AVAILABLE_DIR
    )
    files.directory(name="Create nginx sites-enabled directory", path=SITES_ENABLED_DIR)

    if not host.get_fact(File, DEFAULT_CERT_PATH):
        server.shell(
            name="Generate default certificate",
            commands=[
                (
                    "openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes "
                    f"-keyout {DEFAULT_KEY_PATH} -out {DEFAULT_CERT_PATH} -subj '/CN=default'"
                )
            ],
        )

    # Must run before add_vhost() below: the Debian package ships a conf.d/default.conf with its
    # own `server {}` block, which fails `nginx -t` (and so any reload) until it's removed.
    server.shell(
        name="Ensure the nginx layout",
        commands=["rm -rf /etc/nginx/modules", "rm -f /etc/nginx/conf.d/default.conf"],
    )

    add_vhost(
        CATCH_ALL_VHOST_NAME,
        src=str(_TEMPLATES / "catch-all.conf.j2"),
        ssl_certificate=DEFAULT_CERT_PATH,
        ssl_certificate_key=DEFAULT_KEY_PATH,
    )

    systemd.service(
        name="Restart and enable the nginx service",
        service="nginx.service",
        running=True,
        restarted=nginx_conf.will_change or http_conf.will_change,
        enabled=True,
    )


@deploy("Uninstall nginx")
def uninstall():
    """
    Reverse `install()`: stop/disable the service, remove the package/repo/keyring and the base
    configuration this library owns.

    Deliberately does NOT remove `/etc/nginx/sites-available`, `/etc/nginx/sites-enabled`, or any
    vhost added via `add_vhost` (including the catch-all default vhost) — this library doesn't own
    that state by convention, and a caller may still want it around (eg to reinstall later, or
    because another process manages those vhosts).
    """
    systemd.service(
        name="Stop and disable the nginx service",
        service="nginx.service",
        running=False,
        enabled=False,
    )

    # Deliberately not purge=True: the nginx.org package's postrm purge script does
    # `rm -rf /etc/nginx`, which would delete sites-available/sites-enabled and any vhost a
    # caller added — exactly the state this function must not touch (see docstring).
    apt.packages(
        name="Remove nginx server",
        packages=["nginx"],
        present=False,
    )

    files.file(name="Remove nginx repository", path=APT_SOURCE_PATH, present=False)
    files.file(
        name="Remove legacy nginx repository (pre-DEB822 upgrade path)",
        path=LEGACY_APT_SOURCE_PATH,
        present=False,
    )
    files.file(name="Remove nginx signing key", path=KEYRING_PATH, present=False)
    files.file(
        name="Remove main nginx configuration", path=NGINX_CONF_PATH, present=False
    )
    files.file(
        name="Remove nginx http configuration", path=HTTP_CONF_PATH, present=False
    )
    files.file(
        name="Remove nginx conf: allowed-traffic.include",
        path=ALLOWED_TRAFFIC_INCLUDE_PATH,
        present=False,
    )
    files.file(
        name="Remove nginx conf: cloudflare-real-ip.include",
        path=CLOUDFLARE_REAL_IP_INCLUDE_PATH,
        present=False,
    )
