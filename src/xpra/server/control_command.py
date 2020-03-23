# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2015-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
from xpra.util import csv, engs
from xpra.os_util import bytestostr

log = Logger("util", "command")


class ControlError(Exception):

    def __init__(self, msg, help_text=None, code=127):
        super().__init__(msg)
        self.help = help_text
        self.code = code


class ControlCommand:
    """ Utility superclass for control commands """

    def __init__(self, name, help_text=None, run=None):
        self.name = name
        self.help = help_text
        if run:
            self.do_run = run

    def run(self, *args):
        log("%s.run: calling %s%s", self, self.do_run, args)
        return self.do_run(*args)

    def do_run(self, *args):
        raise NotImplementedError("control command %s undefined!" % self.name)

    def raise_error(self, msg):
        raise ControlError(msg, self.help)

    def __repr__(self):
        return "ControlCommand(%s)" % self.name


class ArgsControlCommand(ControlCommand):
    """ Adds very basic argument validation """
    def __init__(self, name, help_text=None, run=None, validation=(), min_args=None, max_args=None):
        super().__init__(name, help_text, run)
        self.validation = validation
        self.min_args = min_args
        self.max_args = max_args

    def run(self, *args):
        if self.min_args is not None and len(args)<self.min_args:
            self.raise_error("at least %i argument%s required" % (self.min_args, engs(self.min_args)))
        if self.max_args is not None and len(args)>self.max_args:
            self.raise_error("too many arguments, %i maximum" % self.max_args)
        args = list(args)
        for i,validation in enumerate(self.validation):
            if i>=len(args):
                #argument not supplied
                continue
            v = args[i]
            log("running '%s' validation for argument %i: %s (value=%s, type=%s)", self.name, i, validation, v, type(v))
            if not validation:
                continue
            try:
                args[i] = validation(v)
            except ValueError as e:
                self.raise_error("argument %i failed validation: %s" % (i+1, e))
        return super().run(*args)

    def do_run(self):
        raise NotImplementedError()


class FixedMessageCommand(ControlCommand):
    """ A control command that returns a fixed message """
    def __init__(self, name, message, help_text=None):
        super().__init__(name, help_text)
        self.message = message

    def run(self, *_args):
        return self.message


class HelloCommand(FixedMessageCommand):
    """ Just says hello """

    def __init__(self):
        super().__init__("hello", "hello", "just says hello back")


class HelpCommand(ArgsControlCommand):
    """ The help command looks at the 'help' definition of other commands """
    def __init__(self, control_commands):
        super().__init__("help", max_args=1)
        self.control_commands = control_commands

    def run(self, *args):
        if len(args)==0:
            return "control supports: %s" % csv(self.control_commands)
        name = args[0]
        command = self.control_commands.get(name)
        if not command:
            self.raise_error("unknown command '%s'" % name)
        if not command.help:
            return "sorry, no help message available for '%s'" % name
        return "control command '%s': %s" % (name, command.help)


class DebugControl(ArgsControlCommand):
    def __init__(self):
        super().__init__("debug",
                         "usage: 'debug enable category', 'debug disable category', 'debug status' or 'debug mark'",
                         min_args=1)

    def run(self, *args):
        if len(args)==1 and args[0]=="status":
            from xpra.log import get_all_loggers
            return "logging is enabled for: %s" % str(list([str(x) for x in get_all_loggers() if x.is_debug_enabled()]))
        log_cmd = args[0]
        if log_cmd=="mark":
            for _ in range(10):
                log.info("*"*80)
            if len(args)>1:
                log.info("mark: %s", " ".join(args[1:]))
            else:
                log.info("mark")
            for _ in range(10):
                log.info("*"*80)
            return "mark inserted into logfile"
        if len(args)<2:
            self.raise_error("not enough arguments")
        if log_cmd not in ("enable", "disable"):
            self.raise_error("only 'enable' and 'disable' verbs are supported")
        from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
        #each argument is a group
        loggers = []
        groups = args[1:]
        for group in groups:
            #and each group is a list of categories
            #preferably separated by "+",
            #but we support "," for backwards compatibility:
            categories = [v.strip() for v in group.replace("+", ",").split(",")]
            if log_cmd=="enable":
                add_debug_category(*categories)
                loggers += enable_debug_for(*categories)
            else:
                assert log_cmd=="disable"
                add_disabled_category(*categories)
                loggers += disable_debug_for(*categories)
        if not loggers:
            log.info("%s debugging, no new loggers matching: %s", log_cmd, csv(groups))
        else:
            log.info("%sd debugging for:", log_cmd)
            for l in loggers:
                log.info(" - %s", l)
        return "logging %sd for %s" % (log_cmd, csv(loggers))
