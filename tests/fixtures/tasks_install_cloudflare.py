from pyinfra_nginx import install

install(
    cloudflare_ip_allowlist=True,
    cloudflare_ip_allowlist_extra_cidrs=("203.0.113.5/32",),
)
