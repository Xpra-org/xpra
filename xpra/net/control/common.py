# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence

from xpra.log import Logger
from xpra.util.str_fn import csv
from xpra.scripts.config import str_to_bool
from xpra.common import noop

log = Logger("util", "command")


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

    def run(self, *args):
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

    def run(self, *args):
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

    def run(self, *_args):
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

    def run(self, *args):
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
    try:
        command = commands.get(name) or commands.get("*")
        log(f"process_control_command control_commands[{name!r}]={command}")
        if not command:
            log.warn(f"Warning: invalid command: {name!r}")
            log.warn(f" must be one of: {csv(commands)}")
            return 6, "invalid command"
        log(f"process_control_command calling {command.run}({args[1:]})")
        v = command.run(*args[1:])
        return 0, v
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
