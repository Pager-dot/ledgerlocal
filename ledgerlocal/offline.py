"""A hard guarantee that client data cannot leave the machine.

"Local-first" is easy to claim and hard to trust. A freelancer handing this
tool a folder of client invoices has no practical way to audit that no
dependency, telemetry hook or future refactor quietly POSTs a receipt
somewhere. So instead of asking them to trust the code, we take the capability
away: :func:`enforce` patches the socket layer so that any connection to
anything other than the loopback interface (plus hosts the user explicitly
allowlisted) raises :class:`OfflineViolation` before a byte is sent.

The local inference server lives on loopback, so the model still works. Nothing
else does. This is the single most important reason the project is built on an
open-weight model: a closed API *requires* the egress that this module forbids.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from ledgerlocal.errors import OfflineViolation

#: Addresses that always count as "this machine".
LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection

_enforced = False
_extra_hosts: frozenset[str] = frozenset()


def _host_allowed(host: str) -> bool:
    host = host.strip().strip("[]").lower()
    if not host:
        return True  # an unbound/empty address never leaves the box
    if host in LOOPBACK_NAMES or host in _extra_hosts:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A name we did not allowlist. We refuse rather than resolve it, because
        # resolving is itself a network action and the answer can change.
        return False
    return ip.is_loopback or ip.is_unspecified


def _check(address: object) -> None:
    if isinstance(address, (str, bytes)):
        return  # AF_UNIX socket: a path on this filesystem, not a network hop
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if not _host_allowed(str(host)):
            raise OfflineViolation(
                f"blocked outbound connection to {host!r}: LedgerLocal only talks to "
                f"localhost. If you deliberately run inference on another machine, add "
                f"its address to allow_hosts in your config."
            )


def enforce(extra_hosts: Iterable[str] = ()) -> None:
    """Block every outbound socket except loopback and ``extra_hosts``."""
    global _enforced, _extra_hosts
    _extra_hosts = frozenset(h.strip().strip("[]").lower() for h in extra_hosts if h.strip())
    if _enforced:
        return

    def connect(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return _real_connect(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return _real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        _check(address)
        return _real_create_connection(address, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.create_connection = create_connection  # type: ignore[assignment]
    _enforced = True


def release() -> None:
    """Undo :func:`enforce`. Only used by the test suite."""
    global _enforced, _extra_hosts
    socket.socket.connect = _real_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _real_connect_ex  # type: ignore[method-assign]
    socket.create_connection = _real_create_connection  # type: ignore[assignment]
    _enforced = False
    _extra_hosts = frozenset()


def is_enforced() -> bool:
    return _enforced


@contextmanager
def enforced(extra_hosts: Iterable[str] = ()) -> Iterator[None]:
    was = _enforced
    enforce(extra_hosts)
    try:
        yield
    finally:
        if not was:
            release()
