# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import deque, OrderedDict
from ipaddress import ip_address, ip_network
from threading import Lock
from time import monotonic, sleep

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.util.objects import typedict


def pop_int(kwargs: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    v = kwargs.pop(name, default)
    try:
        value = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name!r} value: {v!r}") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name!r} must be between {minimum} and {maximum}, not {value}")
    return value


def pop_float(kwargs: dict, name: str, default: float, minimum: float, maximum: float) -> float:
    v = kwargs.pop(name, default)
    try:
        value = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name!r} value: {v!r}") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name!r} must be between {minimum} and {maximum}, not {value}")
    return value


def get_peer_ip(connection) -> str:
    # `remote` is a `(host, port)` tuple for INET sockets,
    # unix sockets, vsock and named pipes have no address we can rate limit
    remote = getattr(connection, "remote", None)
    if isinstance(remote, (tuple, list)) and remote:
        return str(remote[0])
    return ""


def get_ip_key(ip: str, ipv4_prefix: int, ipv6_prefix: int) -> str:
    # the key used for grouping the failures of a client,
    # empty if this address should not be rate limited
    if not ip:
        return ""
    try:
        # strip any interface scope, ie: "fe80::1%eth0"
        addr = ip_address(ip.split("%", 1)[0])
    except ValueError:
        log("cannot parse peer address %r", ip, exc_info=True)
        return ""
    # so that "::ffff:1.2.3.4" is grouped with "1.2.3.4":
    addr = getattr(addr, "ipv4_mapped", None) or addr
    if addr.is_loopback:
        return ""
    prefix = ipv4_prefix if addr.version == 4 else ipv6_prefix
    return str(ip_network(f"{addr}/{prefix}", strict=False))


class Authenticator(SysAuthenticator):
    """
        Rejects clients that have failed to authenticate too many times recently.
        This module does not authenticate anyone by itself,
        it is a gate that should be placed before a real authentication module.
        It relies on the `auth_failed` and `auth_succeeded` callbacks
        fired by `xpra.server.auth.AuthenticationManager`
        to find out how each connection ended up.
    """
    # a new authenticator is instantiated for each connection,
    # so the failures have to be recorded at the class level
    # (just like `SysAuthenticatorBase.USED_SALT`)
    FAILURES: OrderedDict[str, deque[float]] = OrderedDict()
    LOCK = Lock()

    def __init__(self, **kwargs):
        self.max_failures = pop_int(kwargs, "max-failures", 5, 1, 1000)
        self.window = pop_int(kwargs, "window", 60, 1, 24 * 60 * 60)
        self.delay = pop_float(kwargs, "delay", 1, 0, 60)
        self.max_delay = pop_float(kwargs, "max-delay", 8, 0, 60)
        self.ipv4_prefix = pop_int(kwargs, "ipv4-prefix", 32, 0, 32)
        self.ipv6_prefix = pop_int(kwargs, "ipv6-prefix", 128, 0, 128)
        self.max_tracked = pop_int(kwargs, "max-tracked", 10000, 1, 1000 * 1000)
        ip = get_peer_ip(kwargs.get("connection"))
        self.ip_key = get_ip_key(ip, self.ipv4_prefix, self.ipv6_prefix)
        # set when we are the ones rejecting this client,
        # so that we don't count our own rejections as failures:
        self.rejected = False
        log("ratelimit.Authenticator(..) ip=%r, key=%r", ip, self.ip_key)
        super().__init__(**kwargs)

    def __repr__(self):
        return "ratelimit"

    def get_uid(self) -> int:
        return -1

    def get_gid(self) -> int:
        return -1

    def requires_challenge(self) -> bool:
        return False

    def count_failures(self, now: float) -> int:
        # the lock must be held
        failures = self.FAILURES.get(self.ip_key)
        if not failures:
            return 0
        while failures and failures[0] < now - self.window:
            failures.popleft()
        if not failures:
            del self.FAILURES[self.ip_key]
            return 0
        self.FAILURES.move_to_end(self.ip_key)
        return len(failures)

    def prune(self, now: float) -> None:
        # the lock must be held.
        # when multiple sockets use this module with different `window` values,
        # the shortest one wins - which just means we forgive faster
        for key in tuple(self.FAILURES):
            failures = self.FAILURES[key]
            while failures and failures[0] < now - self.window:
                failures.popleft()
            if not failures:
                del self.FAILURES[key]
        # bound the memory used: an attacker rotating through a large address range
        # (ie: an IPv6 block) must not be able to make us grow without limit
        while len(self.FAILURES) > self.max_tracked:
            self.FAILURES.popitem(last=False)

    def get_delay(self, failures: int) -> float:
        if failures <= 0 or self.delay <= 0:
            return 0
        return min(self.delay * 2 ** (failures - 1), self.max_delay)

    def authenticate(self, _caps: typedict) -> bool:  # pylint: disable=arguments-differ
        if not self.ip_key:
            # local or unknown client: not rate limited
            return True
        now = monotonic()
        with self.LOCK:
            failures = self.count_failures(now)
        if failures >= self.max_failures:
            self.rejected = True
            log.warn("Warning: too many authentication failures for %r", self.ip_key)
            log.warn(" %i failures in the last %i seconds", failures, self.window)
            return False
        delay = self.get_delay(failures)
        if delay > 0:
            log.info("delaying authentication of %r by %.1f seconds", self.ip_key, delay)
            log.info(" %i recent authentication failure(s)", failures)
            # we run in the connection's own authentication thread,
            # so this does not block the main loop or any other client
            sleep(delay)
        return True

    def auth_failed(self) -> None:
        if not self.ip_key or self.rejected:
            # counting the clients we rejected ourselves
            # would keep extending the block forever
            return
        now = monotonic()
        with self.LOCK:
            self.FAILURES.setdefault(self.ip_key, deque()).append(now)
            self.FAILURES.move_to_end(self.ip_key)
            self.prune(now)
            failures = len(self.FAILURES.get(self.ip_key, ()))
        log("%i authentication failure(s) recorded for %r", failures, self.ip_key)

    def auth_succeeded(self) -> None:
        if not self.ip_key:
            return
        with self.LOCK:
            if self.FAILURES.pop(self.ip_key, None):
                log("cleared the authentication failures recorded for %r", self.ip_key)

    @classmethod
    def reset(cls) -> None:
        with cls.LOCK:
            cls.FAILURES.clear()
