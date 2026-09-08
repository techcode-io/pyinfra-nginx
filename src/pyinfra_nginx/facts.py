import re
from typing import Final

from pyinfra.api import FactBase

BINARY_PATH: Final[str] = "/usr/sbin/nginx"

_VERSION_MATCHER: Final[re.Pattern] = re.compile(r"nginx/(?P<version>\S+)")


class NginxVersion(FactBase):
    """
    Returns the currently installed nginx version (eg ``1.29.3``), or ``None`` if nginx is not
    installed.
    """

    @staticmethod
    def command() -> str:
        return f"{BINARY_PATH} -v 2>&1"

    def requires_command(self) -> str:
        return BINARY_PATH

    def process(self, output) -> str | None:
        match = _VERSION_MATCHER.search("\n".join(output))
        return match.group("version") if match else None
