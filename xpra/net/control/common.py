# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence

from xpra.log import Logger
from xpra.util.str_fn import csv
from xpra.util.parsing import str_to_bool, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.common import noop

log = Logger("util", "command")


def add_control_command(server, name: str, control) -> None:
    # weak dependency on the control subsystem:
    add = getattr(server, "add_control_command", noop)
    log("%s.add_control_command: %s(%s, %s)", server, add, name, control)
    add(name, control)


def add_args_control_command(server, name: str, descr: str, **kwargs) -> None:
    control = ArgsControlCommand(name, descr, **kwargs)
    add_control_command(server, name, control)


def control_get_sources(server, client_uuids_str="*"):
    # find the client uuid specified as a string:
    sources = getattr(server, "_server_sources", None)
    if sources is None:
        raise RuntimeError("no server sources found in %s" % server)
    if client_uuids_str == "*":
        sources = sources.values()
    else:
        client_uuids = client_uuids_str.split(",")
        sources = [ss for ss in sources.values() if ss.uuid in client_uuids]
        uuids = tuple(ss.uuid for ss in sources)
        notfound = any(x for x in client_uuids if x not in uuids)
        if notfound:
            log.warn(f"Warning: client connection not found for uuid(s): {notfound}")
    return sources


def parse_4intlist(v) -> list:
    if not v:
        return []
    intlist = []
    # ie: v = " (0,10,100,20), (200,300,20,20)"
    while v:
        v = v.strip().strip(",").strip()  # ie: "(0,10,100,20)"
        lp = v.find("(")
        assert lp == 0, "invalid leading characters: %s" % v[:lp]
        rp = v.find(")")
        assert (lp + 1) < rp
        item = v[lp + 1:rp].strip()  # "0,10,100,20"
        items = [int(x) for x in item]  # 0,10,100,20
        assert len(items) == 4, f"expected 4 numbers but got {len(items)}"
        intlist.append(items)
    return intlist


def parse_boolean_value(v):
    if str(v).lower() in TRUE_OPTIONS:
        return True
    if str(v).lower() in FALSE_OPTIONS:
        return False
    raise ControlError(f"a boolean is required, not {v!r}")


class ControlError(Exception):
    def __init__(self, msg: str, help_text: str = "", code: int = 127):
        super().__init__(msg)
        self.help = help_text
        self.code = code


class ControlCommand:
    """ Utility superclass for control commands """
    __slots__ = ("name", "help", "do_run")

    def __init__(self, name: str, help_text: str = "", run: Callable = noop):
        self.name = name
        self.help = help_text
        self.do_run = run

    def run(self, *args) -> str:
        log("%s.run: calling %s%s", self, self.do_run, args)
        if self.do_run is None:
            raise NotImplementedError(f"control command {self.name} undefined!")
        return self.do_run(*args)

    def raise_error(self, msg) -> None:
        raise ControlError(msg, self.help)

    def __repr__(self):
        return f"ControlCommand({self.name})"


class ArgsControlCommand(ControlCommand):
    """ Adds very basic argument validation """
    __slots__ = ("validation", "min_args", "max_args")

    def __init__(self, name: str, help_text: str = "", run: Callable = noop, validation=(),
                 min_args=-1, max_args=-1):
        super().__init__(name, help_text, run)
        self.validation = validation
        self.min_args = min_args
        self.max_args = max_args

    def run(self, *args) -> str:
        if self.min_args != -1 and len(args) < self.min_args:
            self.raise_error(f"not enough arguments for control command {self.name!r}, minimum is {self.min_args}")
        if self.max_args != -1 and len(args) > self.max_args:
            self.raise_error(f"too many arguments for control command {self.name!r}, maximum is {self.max_args}")
        args = self.get_validated_args(*args)
        return super().run(*args)

    def get_validated_args(self, *targs) -> Sequence[Any]:
        args = list(targs)
        for i, validation in enumerate(self.validation):
            if i >= len(args):
                # argument not supplied
                continue
            v = args[i]
            log("running '%s' validation for argument %i: %s (value=%s, type=%s)", self.name, i, validation, v, type(v))
            if not validation:
                continue
            try:
                args[i] = validation(v)
            except ValueError as e:
                self.raise_error(f"argument {i + 1} failed validation: {e}")
        return tuple(args)


class FixedMessageCommand(ControlCommand):
    """ A control command that returns a fixed message """
    __slots__ = ("message",)

    def __init__(self, name: str, message: str, help_text: str = ""):
        super().__init__(name, help_text)
        self.message = message

    def run(self, *_args) -> str:
        return self.message


class DisabledCommand(FixedMessageCommand):
    __slots__ = ()

    def __init__(self):
        super().__init__("*", "the control channel is disabled")


class HelloCommand(FixedMessageCommand):
    """ Just says hello """
    __slots__ = ()

    def __init__(self):
        super().__init__("hello", "hello", "just says hello back")


class HelpCommand(ArgsControlCommand):
    """ The help command looks at the 'help' definition of other commands """
    __slots__ = ("control_commands",)

    def __init__(self, control_commands: Sequence[str]):
        super().__init__("help", max_args=1)
        self.control_commands = control_commands

    def run(self, *args) -> str:
        if len(args) == 0:
            return "control supports: " + csv(sorted(self.control_commands))
        name = args[0]
        command = self.control_commands.get(name)
        if not command:
            self.raise_error(f"unknown command {name!r}")
        if not command.help:
            return f"sorry, no help message available for {name!r}"
        return f"control command {name!r}: {command.help}"


def process_control_command(protocol, commands: dict[str, Callable], *args) -> tuple[int, str]:
    try:
        options = protocol._conn.options
        control = options.get("control", "yes")
    except AttributeError:
        control = "no"
    if not str_to_bool(control):
        err = "control commands are not enabled on this connection"
        log.warn(f"Warning: {err}")
        return 6, err
    if not args:
        err = "control command must have arguments"
        log.warn(f"Warning: {err}")
        return 6, err
    name = args[0]
    command = commands.get(name) or commands.get("*")
    log(f"process_control_command control_commands[{name!r}]={command}")
    if not command:
        log.warn(f"Warning: invalid command: {name!r}")
        log.warn(f" must be one of: {csv(commands)}")
        return 6, "invalid command"
    try:
        log(f"process_control_command calling {command.run}({args[1:]})")
        v = command.run(*args[1:])
        return 0, v
    except ValueError as e:
        log("command=%s args=%s", command, args[1:], exc_info=True)
        log.error(f"Error processing control command {name!r}")
        log.estr(e)
        return 127, str(e)
    except ControlError as e:
        log.error(f"Error {e.code} processing control command {name!r}")
        msgs = [f" {e}"]
        if e.help:
            msgs.append(f" {name!r}: {e.help}")
        for msg in msgs:
            log.error(msg)
        return e.code, "\n".join(msgs)
    except Exception as e:
        log.error(f"error processing control command {name!r}", exc_info=True)
        return 127, f"error processing control command: {e}"
