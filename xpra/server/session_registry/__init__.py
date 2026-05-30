# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Session registry: where the proxy server looks up which xpra sessions are
reachable for an authenticated client.

The default backend (`auth`) delegates to `authenticator.get_sessions()`, which
preserves the historical behaviour where the authentication module was also the
source of truth for session lookup. Other backends decouple the two — for
example the `socket` backend always performs a DotXpra socket scan, regardless
of which authenticator was used.

The `Session` data carrier is iterable as a 5-tuple
`(uid, gid, displays, env_options, session_options)` so existing call sites
that destructure the tuple keep working.
"""

from dataclasses import dataclass, field

from xpra.auth.common import SessionData


@dataclass
class Session:
    uid: int
    gid: int
    displays: list[str]
    env_options: dict[str, str] = field(default_factory=dict)
    session_options: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_tuple(cls, data: SessionData | None) -> "Session | None":
        if data is None:
            return None
        uid, gid, displays, env_options, session_options = data
        return cls(uid, gid, list(displays), dict(env_options), dict(session_options))

    def as_tuple(self) -> SessionData:
        return self.uid, self.gid, self.displays, self.env_options, self.session_options

    # Backwards-compatible tuple destructuring (`uid, gid, ... = session`)
    # and slicing (`session[:2]`) — many callers were written against the
    # 5-tuple SessionData type and we don't want to rewrite all of them.
    def __iter__(self):
        return iter(self.as_tuple())

    def __getitem__(self, idx):
        return self.as_tuple()[idx]

    def __len__(self) -> int:
        return 5


class SessionRegistry:
    """
    Abstract base for session registry backends.

    A backend resolves an authenticated protocol's authenticator into the
    `Session` it should be routed to.
    """

    NAME = ""

    def __init__(self, **options):
        # backends may consume options here; unknown options are ignored
        # so that the helper's parse_simple_dict() output is permissive.
        pass

    def lookup(self, authenticator) -> Session | None:
        raise NotImplementedError

    def __repr__(self):
        return f"SessionRegistry({self.NAME!r})"
