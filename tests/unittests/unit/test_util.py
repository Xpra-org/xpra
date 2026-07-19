#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import logging

from xpra.util.env import envbool


def silence_info(module, logger="log"):
    return LoggerSilencer(module, logger, logging.INFO)


def silence_warn(module, logger="log"):
    return LoggerSilencer(module, logger, logging.WARN)


def silence_error(module, logger="log"):
    return LoggerSilencer(module, logger, logging.ERROR)


# to silence warnings triggered by the tests:


class LoggerSilencer:

    def __init__(self, module, logger="log", level=0):
        self.module = module
        self.logger = logger
        self.level = level
        self.saved = 0

    def __enter__(self):
        if not envbool("XPRA_TEST_DEBUG", 0):
            logger = getattr(self.module, self.logger)
            self.saved = logger.min_level
            setattr(logger, "min_level", self.level)

    def __exit__(self, *_args):
        logger = getattr(self.module, self.logger)
        setattr(logger, "min_level", self.saved)

    def __repr__(self):
        return "LoggerSilencer"


_stubbable_cache: dict[type, type] = {}


def stubbable(cls: type) -> type:
    """
    Test-only subclass of a subsystem class.

    Subsystems declare `__slots__` so that typos are caught at runtime
    (see `SignalEmitter`): their instances have no `__dict__`, which also
    means a test cannot replace a method on an instance
    (`x.send = fake` fails with "attribute is read-only").

    This subclass restores the `__dict__` so that stubbing works again,
    but keeps the check that makes `__slots__` worth having: assigning a
    name the class never declared - a typo, or state that belongs on the
    owning client / server - still raises.
    """
    if not isinstance(cls, type):
        # a factory function: it builds the instance itself, so it has to call
        # `stubbable` on the class it instantiates - nothing to do here
        return cls
    subclass = _stubbable_cache.get(cls)
    if subclass is not None:
        return subclass

    def __setattr__(self, name, value) -> None:
        # `hasattr` on the type covers both the declared slots
        # (which are descriptors) and the methods we want to allow stubbing:
        if not hasattr(type(self), name):
            raise AttributeError(f"{cls.__name__!r} has no declared attribute {name!r}")
        object.__setattr__(self, name, value)

    # no `__slots__` here: that is what gives the subclass its `__dict__`.
    # build it with the class's own metaclass, some subsystems are GObject types:
    metaclass = type(cls)
    subclass = metaclass(f"Stubbable{cls.__name__}", (cls,), {"__setattr__": __setattr__})
    _stubbable_cache[cls] = subclass
    return subclass


def get_free_tcp_port() -> int:
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port
