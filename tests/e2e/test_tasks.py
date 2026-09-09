from tests.e2e.conftest import podman_exec, run_pyinfra


def assert_podman_exec(container: str, command: str, expected: int = 0) -> None:
    assert podman_exec(container, command).returncode == expected


def test_install_then_uninstall(systemd_container: str) -> None:
    install_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert install_result.returncode == 0, install_result.stdout + install_result.stderr

    assert_podman_exec(systemd_container, "test -f /etc/nginx/nginx.conf")
    assert_podman_exec(systemd_container, "test -f /etc/nginx/conf.d/http.conf")
    # cloudflare_ip_allowlist defaults to False: this base config is CDN-agnostic.
    assert_podman_exec(
        systemd_container,
        "test -f /etc/nginx/conf.d/allowed-traffic.include",
        expected=1,
    )
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/conf.d/cloudflare-real-ip.include"
    )
    assert_podman_exec(
        systemd_container, "test -L /etc/nginx/sites-enabled/catch-all.conf"
    )
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/sites-available/catch-all.conf"
    )
    assert_podman_exec(systemd_container, "test -f /etc/ssl/certs/default.crt")
    assert_podman_exec(systemd_container, "nginx -t")
    assert (
        podman_exec(systemd_container, "systemctl is-enabled nginx").stdout.strip()
        == "enabled"
    )
    assert (
        podman_exec(systemd_container, "systemctl is-active nginx").stdout.strip()
        == "active"
    )

    # The catch-all default vhost drops any request that doesn't match a real server_name.
    catch_all = podman_exec(
        systemd_container, "curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/"
    )
    assert catch_all.stdout.strip() in ("000", "444")

    # Reinstalling should not re-add the catch-all vhost operations' reload trigger, since nothing
    # about it changed.
    reinstall_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert reinstall_result.returncode == 0, (
        reinstall_result.stdout + reinstall_result.stderr
    )
    assert "Reload nginx after enabling vhost: catch-all" not in reinstall_result.stdout

    uninstall_result = run_pyinfra(systemd_container, "tasks_uninstall.py")
    assert uninstall_result.returncode == 0, (
        uninstall_result.stdout + uninstall_result.stderr
    )

    assert_podman_exec(systemd_container, "test -f /etc/nginx/nginx.conf", expected=1)
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/conf.d/http.conf", expected=1
    )
    # apt.packages(present=False) without purge=True leaves the package in dpkg's "config-files"
    # (rc) state, so `dpkg -s` still exits 0 — check the reported Status line isn't "installed".
    assert_podman_exec(
        systemd_container,
        "dpkg-query -W -f='${Status}' nginx | grep -q ' installed$'",
        expected=1,
    )

    # uninstall() never touches sites-available/sites-enabled or vhosts added via add_vhost.
    assert_podman_exec(
        systemd_container, "test -L /etc/nginx/sites-enabled/catch-all.conf"
    )
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/sites-available/catch-all.conf"
    )


def test_cloudflare_ip_allowlist_toggle(systemd_container: str) -> None:
    install_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert install_result.returncode == 0, install_result.stdout + install_result.stderr

    enable_result = run_pyinfra(systemd_container, "tasks_install_cloudflare.py")
    assert enable_result.returncode == 0, enable_result.stdout + enable_result.stderr

    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/conf.d/allowed-traffic.include"
    )
    assert_podman_exec(
        systemd_container,
        "grep -q 'geo \\$realip_remote_addr \\$is_cloudflare_allowed' "
        "/etc/nginx/conf.d/allowed-traffic.include",
    )
    assert_podman_exec(
        systemd_container,
        "grep -q 'include /etc/nginx/conf.d/allowed-traffic.include' "
        "/etc/nginx/conf.d/http.conf",
    )
    assert_podman_exec(
        systemd_container,
        "grep -q '203.0.113.5/32 1;' /etc/nginx/conf.d/allowed-traffic.include",
    )
    assert_podman_exec(systemd_container, "nginx -t")

    # Toggling back off (the plain install() fixture defaults to False) must remove the file this
    # library uploaded, not leave a stale, unreferenced one behind.
    disable_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert disable_result.returncode == 0, disable_result.stdout + disable_result.stderr

    assert_podman_exec(
        systemd_container,
        "test -f /etc/nginx/conf.d/allowed-traffic.include",
        expected=1,
    )
    assert_podman_exec(systemd_container, "nginx -t")

    uninstall_result = run_pyinfra(systemd_container, "tasks_uninstall.py")
    assert uninstall_result.returncode == 0, (
        uninstall_result.stdout + uninstall_result.stderr
    )


def test_add_vhost_then_remove_vhost(systemd_container: str) -> None:
    install_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert install_result.returncode == 0, install_result.stdout + install_result.stderr

    add_result = run_pyinfra(systemd_container, "tasks_add_vhost.py")
    assert add_result.returncode == 0, add_result.stdout + add_result.stderr

    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/sites-available/example.conf"
    )
    assert_podman_exec(
        systemd_container, "test -L /etc/nginx/sites-enabled/example.conf"
    )
    assert_podman_exec(
        systemd_container,
        "grep -q 'upstream=127.0.0.1:9999' /etc/nginx/sites-available/example.conf",
    )
    assert_podman_exec(systemd_container, "nginx -t")

    # Re-running add_vhost with identical args should not reload nginx a second time.
    reapply_result = run_pyinfra(systemd_container, "tasks_add_vhost.py")
    assert reapply_result.returncode == 0, reapply_result.stdout + reapply_result.stderr
    assert "Reload nginx after enabling vhost: example" not in reapply_result.stdout

    remove_result = run_pyinfra(systemd_container, "tasks_remove_vhost.py")
    assert remove_result.returncode == 0, remove_result.stdout + remove_result.stderr

    assert_podman_exec(
        systemd_container, "test -e /etc/nginx/sites-enabled/example.conf", expected=1
    )
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/sites-available/example.conf", expected=1
    )
    assert_podman_exec(systemd_container, "nginx -t")

    uninstall_result = run_pyinfra(systemd_container, "tasks_uninstall.py")
    assert uninstall_result.returncode == 0, (
        uninstall_result.stdout + uninstall_result.stderr
    )


def test_add_vhost_migrates_stale_non_symlink_file(systemd_container: str) -> None:
    """
    A host previously managed by the pre-symlink runbook (or an older version of this package)
    wrote the vhost straight into sites-enabled/ as a regular file, not a symlink. add_vhost()
    must migrate it rather than fail (pyinfra's files.link refuses to replace a non-symlink path).
    """
    install_result = run_pyinfra(systemd_container, "tasks_install.py")
    assert install_result.returncode == 0, install_result.stdout + install_result.stderr

    assert_podman_exec(
        systemd_container,
        "mkdir -p /etc/nginx/sites-enabled && "
        "echo 'server {}' > /etc/nginx/sites-enabled/example.conf",
    )
    assert_podman_exec(
        systemd_container, "test -f /etc/nginx/sites-enabled/example.conf"
    )
    assert_podman_exec(
        systemd_container, "test -L /etc/nginx/sites-enabled/example.conf", expected=1
    )

    add_result = run_pyinfra(systemd_container, "tasks_add_vhost.py")
    assert add_result.returncode == 0, add_result.stdout + add_result.stderr

    assert_podman_exec(
        systemd_container, "test -L /etc/nginx/sites-enabled/example.conf"
    )
    assert_podman_exec(systemd_container, "nginx -t")

    remove_result = run_pyinfra(systemd_container, "tasks_remove_vhost.py")
    assert remove_result.returncode == 0, remove_result.stdout + remove_result.stderr

    uninstall_result = run_pyinfra(systemd_container, "tasks_uninstall.py")
    assert uninstall_result.returncode == 0, (
        uninstall_result.stdout + uninstall_result.stderr
    )
