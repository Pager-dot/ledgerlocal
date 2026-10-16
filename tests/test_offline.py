import socket

import pytest

from ledgerlocal.errors import OfflineViolation
from ledgerlocal.offline import enforced, is_enforced


def test_public_address_is_refused():
    with enforced():
        with pytest.raises(OfflineViolation):
            socket.socket().connect(("93.184.216.34", 80))


def test_hostname_is_refused_without_resolving_it():
    with enforced():
        with pytest.raises(OfflineViolation) as exc:
            socket.create_connection(("api.example.com", 443))
    assert "api.example.com" in str(exc.value)


def test_loopback_is_allowed_through():
    with enforced():
        # Connecting fails because nothing is listening, but it must fail as an
        # ordinary OSError rather than as a policy violation.
        with pytest.raises(OSError) as exc:
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
    assert not isinstance(exc.value, OfflineViolation)


def test_explicit_allowlist_lets_a_lan_gpu_box_through():
    with enforced(["192.168.1.40"]):
        with pytest.raises(OSError) as exc:
            socket.create_connection(("192.168.1.40", 11434), timeout=0.2)
        assert not isinstance(exc.value, OfflineViolation)
        with pytest.raises(OfflineViolation):
            socket.create_connection(("192.168.1.41", 11434), timeout=0.2)


def test_unix_sockets_are_not_network_hops():
    with enforced():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        with pytest.raises(OSError) as exc:
            sock.connect("/tmp/ledgerlocal-does-not-exist.sock")
        assert not isinstance(exc.value, OfflineViolation)


def test_guard_is_removed_on_exit():
    with enforced():
        assert is_enforced()
    assert not is_enforced()
