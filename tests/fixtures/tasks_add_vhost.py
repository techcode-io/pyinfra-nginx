from pathlib import Path

from pyinfra_nginx import add_vhost

add_vhost(
    "example",
    src=str(Path(__file__).parent / "test-vhost.conf.j2"),
    upstream="127.0.0.1:9999",
)
