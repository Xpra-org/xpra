#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ast
import unittest

import xpra
from xpra.net.common import packet_handler, PacketHandlerSpec, PACKET_HANDLER_ATTR
from xpra.net.dispatch import (
    SubsystemPacketHandlers, PacketDispatcher,
    get_packet_handler_specs, get_decorated_handler,
)


class Subsystem(SubsystemPacketHandlers):
    PREFIX = "test"

    def __init__(self):
        self._packet_handlers = {}
        self.feature = True

    @packet_handler("test-early", early=True)
    def _process_early(self, packet) -> None:
        pass

    @packet_handler("test-main", main_thread=True)
    def _process_main(self, packet) -> None:
        pass

    @packet_handler("test-a", "test-b")
    def _process_multi(self, packet) -> None:
        pass

    @packet_handler("test-feature", enabled=lambda self: self.feature)
    def _process_feature(self, packet) -> None:
        pass

    @packet_handler("test-manual", manual=True)
    def _process_manual(self, packet) -> None:
        pass

    @packet_handler("test-static")
    @staticmethod
    def _process_static(packet) -> None:
        pass

    def _process_undecorated(self, packet) -> None:
        pass


class Derived(Subsystem):

    # undecorated override: still registered, using the base class spec
    def _process_main(self, packet) -> None:
        pass

    # re-decorated override: the new spec replaces the base one
    @packet_handler("test-a", "test-b", main_thread=True)
    def _process_multi(self, packet) -> None:
        pass


class PacketHandlerTest(unittest.TestCase):

    def test_decorator(self):
        def fn(_packet) -> None:
            pass
        decorated = packet_handler("foo-bar", "foo-baz", main_thread=True)(fn)
        assert decorated is fn, "the function must be returned unchanged"
        spec = getattr(fn, PACKET_HANDLER_ATTR)
        assert isinstance(spec, PacketHandlerSpec)
        assert spec.packet_types == ("foo-bar", "foo-baz")
        assert spec.main_thread and not spec.early and not spec.manual and spec.enabled is None
        with self.assertRaises(ValueError):
            packet_handler()

    def test_registration(self):
        sub = Subsystem()
        sub.register_packet_handlers()
        assert set(sub.get_packet_types()) == {
            "test-early", "test-main", "test-a", "test-b", "test-feature", "test-static",
        }, sub.get_packet_types()
        handler, main_thread = sub.get_packet_handler("main")
        assert main_thread
        assert handler == sub._process_main
        assert sub.get_packet_handler("a")[0] == sub.get_packet_handler("b")[0] == sub._process_multi
        assert sub.get_packet_handler("static")[0] is Subsystem._process_static

    def test_early(self):
        sub = Subsystem()
        sub.register_packet_handlers(early=True)
        assert sub.get_packet_types() == ("test-early", )
        sub = Subsystem()
        sub.register_packet_handlers(early=False)
        assert "test-early" not in sub.get_packet_types()
        assert "test-main" in sub.get_packet_types()

    def test_enabled(self):
        sub = Subsystem()
        sub.feature = False
        sub.register_packet_handlers()
        assert "test-feature" not in sub.get_packet_types()

    def test_manual(self):
        sub = Subsystem()
        sub.register_packet_handlers()
        assert "test-manual" not in sub.get_packet_types()
        # the lookup used by the endpoints which dispatch packets themselves does include it:
        assert get_decorated_handler(sub, "test-manual") == sub._process_manual
        assert get_decorated_handler(sub, "test-undecorated") is None

    def test_overrides(self):
        sub = Derived()
        sub.register_packet_handlers()
        handler, main_thread = sub.get_packet_handler("main")
        assert main_thread, "undecorated overrides keep the base spec"
        assert handler == sub._process_main
        assert handler.__func__ is Derived._process_main
        handler, main_thread = sub.get_packet_handler("a")
        assert main_thread, "decorated overrides replace the base spec"
        assert handler.__func__ is Derived._process_multi

    def test_duplicate(self):
        class Duplicate(Subsystem):
            @packet_handler("test-main")
            def _process_other(self, packet) -> None:
                pass
        with self.assertRaises(ValueError):
            get_packet_handler_specs(Duplicate)

    def test_namespace(self):
        class Outside(Subsystem):
            @packet_handler("other-thing")
            def _process_other(self, packet) -> None:
                pass
        with self.assertRaises(ValueError):
            Outside().register_packet_handlers()

    def test_dispatcher(self):
        class Dispatcher(PacketDispatcher):
            @packet_handler("hello", early=True)
            def _process_hello(self, proto, packet) -> None:
                pass

            @packet_handler("ping", main_thread=True)
            def _process_ping(self, proto, packet) -> None:
                pass

        d = Dispatcher()
        d.register_packet_handlers(early=True)
        assert list(d._authenticated_packet_handlers) == ["hello"]
        assert not d._authenticated_ui_packet_handlers
        d.register_packet_handlers(early=False)
        assert list(d._authenticated_ui_packet_handlers) == ["ping"]


# `_process_*` methods which are not xpra packet handlers:
NOT_HANDLERS = (
    # websocket opcodes:
    "_process_ws_",
    # RFB messages, dispatched by `RFBServer.process_rfb_packet`:
    "_process_rfb_",
)
HELPERS = {
    # the protocol callback of `RemoteServerAdapter`:
    "_process_packet",
    # called by the decorated handlers:
    "_process_new_common", "_process_image", "_process_status",
    # only called via `super()` by the subclasses which register `startup-complete`:
    "_process_startup_complete",
}


class PacketHandlerCoverageTest(unittest.TestCase):
    """
    Every `_process_*` method must be decorated with `packet_handler`,
    or override a method which is: it is how packet handlers get registered.
    """

    def test_all_decorated(self):
        root = os.path.dirname(xpra.__file__)
        # class name -> [(base names, decorated method names, undecorated methods)]
        classes: dict[str, list[tuple[list[str], set[str], dict[str, str]]]] = {}
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf8") as f:
                    tree = ast.parse(f.read())
                for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
                    bases = [ast.unparse(b).split(".")[-1] for b in cls.bases]
                    decorated = set()
                    undecorated = {}
                    for fn in cls.body:
                        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_process_"):
                            continue
                        if any(ast.unparse(d).startswith("packet_handler(") for d in fn.decorator_list):
                            decorated.add(fn.name)
                        else:
                            undecorated[fn.name] = f"{os.path.relpath(path, root)}:{fn.lineno} {cls.name}.{fn.name}"
                    classes.setdefault(cls.name, []).append((bases, decorated, undecorated))

        def ancestor_decorates(class_name: str, method: str, seen: set) -> bool:
            for bases, decorated, _undecorated in classes.get(class_name, ()):
                for base in bases:
                    if base in seen:
                        continue
                    seen.add(base)
                    for _bases, base_decorated, _ in classes.get(base, ()):
                        if method in base_decorated:
                            return True
                    if ancestor_decorates(base, method, seen):
                        return True
            return False

        missing = []
        for class_name, defs in classes.items():
            for _bases, _decorated, undecorated in defs:
                for method, location in undecorated.items():
                    if method in HELPERS or method.startswith(NOT_HANDLERS):
                        continue
                    if not ancestor_decorates(class_name, method, {class_name}):
                        missing.append(location)
        assert not missing, "missing `@packet_handler` decorator:\n" + "\n".join(sorted(missing))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
