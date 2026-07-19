#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.client.base.stub import StubClientSubsystem
from xpra.server.source.stub import StubClientConnection
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.signal_emitter import SignalEmitter


class Context:

    def __init__(self, owner: bool):
        self.owner = owner

    def is_owner(self) -> bool:
        return self.owner


class MainLoop:

    def __init__(self, running=True, owner=True):
        self.running = running
        self.context = Context(owner)

    def is_running(self) -> bool:
        return self.running

    def get_context(self) -> Context:
        return self.context


class ConcreteEmitter(SignalEmitter):
    """
    `SignalEmitter` declares no slots of its own so that the servers can fuse it
    with `GObject.GObject` (see the note there), which also means it holds no
    state and cannot be used directly: subclasses supply the `__dict__` (or the
    slots) that `_signal_callbacks` and `main_loop` live in.
    """


class SignalEmitterTest(unittest.TestCase):

    def test_base_get_main_loop(self):
        emitter = ConcreteEmitter()
        self.assertIsNone(emitter.get_main_loop())
        main_loop = MainLoop()
        emitter.main_loop = main_loop
        self.assertIs(emitter.get_main_loop(), main_loop)

    def test_should_call_direct_uses_main_loop(self):
        emitter = ConcreteEmitter()
        self.assertTrue(emitter._should_call_direct())
        emitter.main_loop = MainLoop(running=False)
        self.assertTrue(emitter._should_call_direct())
        emitter.main_loop = MainLoop(running=True, owner=True)
        self.assertTrue(emitter._should_call_direct())
        emitter.main_loop = MainLoop(running=True, owner=False)
        self.assertFalse(emitter._should_call_direct())

    def test_stub_get_main_loop(self):
        main_loop = MainLoop()
        server = SimpleNamespace(main_loop=main_loop)
        client = SimpleNamespace(
            main_loop=main_loop,
            idle_add=None,
            timeout_add=None,
            source_remove=None,
        )

        self.assertIs(StubSubsystem(server).get_main_loop(), main_loop)
        self.assertIs(StubClientSubsystem(client).get_main_loop(), main_loop)

        client_mixin = StubClientSubsystem()
        client_mixin.main_loop = main_loop
        self.assertIs(client_mixin.get_main_loop(), main_loop)

        connection = StubClientConnection()
        self.assertIsNone(connection.get_main_loop())
        connection.init_from(None, server)
        self.assertIs(connection.get_main_loop(), main_loop)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
