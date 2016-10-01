# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
from xpra.util import csv, engs
log = Logger("util", "command")


class ControlError(Exception):

    def __init__(self, msg, help_text=None, code=127):
        super(ControlError, self).__init__(msg)
        self.help = help_text
        self.code = code


class ControlCommand(object):
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
    def __init__(self, name, help_text=None, run=None, validation=[], min_args=None, max_args=None):
        super(ArgsControlCommand, self).__init__(name, help_text, run)
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
            v = args[i]
            log("running '%s' validation for argument %i: %s (value=%s, type=%s)", self.name, i, validation, v, type(v))
            if not validation:
                continue
            try:
                args[i] = validation(v)
            except ValueError as e:
                self.raise_error("argument %i failed validation: %s" % (i+1, e))
        return super(ArgsControlCommand, self).run(*args)

    def do_run(self):
        raise NotImplementedError()


class FixedMessageCommand(ControlCommand):
    """ A control command that returns a fixed message """
    def __init__(self, name, message, help_text=None):
        super(FixedMessageCommand, self).__init__(name, help_text)
        self.message = message

    def run(self, *args):
        return self.message


class HelloCommand(FixedMessageCommand):
    """ Just says hello """

    def __init__(self):
        super(HelloCommand, self).__init__("hello", "hello", "just says hello back")


class HelpCommand(ArgsControlCommand):
    """ The help command looks at the 'help' definition of other commands """
    def __init__(self, control_commands):
        super(HelpCommand, self).__init__("help", max_args=1)
        self.control_commands = control_commands

    def run(self, *args):
        if len(args)==0:
            return "control supports: %s" % (", ".join(self.control_commands))
        name = args[0]
        command = self.control_commands.get(name)
        if not command:
            self.raise_error("unknown command '%s'" % name)
        if not command.help:
            return "sorry, no help message available for '%s'" % name
        return "control command '%s': %s" % (name, command.help)


class DebugControl(ArgsControlCommand):
    def __init__(self):
        super(DebugControl, self).__init__("debug", "usage: 'debug enable category', 'debug disable category' or 'debug status'", min_args=1)

    def run(self, *args):
        if len(args)==1 and args[0]=="status":
            from xpra.log import get_all_loggers
            return "logging is enabled for: %s" % str(list([str(x) for x in get_all_loggers() if x.is_debug_enabled()]))
        if len(args)<2:
            self.raise_error("not enough arguments")
        log_cmd = args[0]
        if log_cmd not in ("enable", "disable"):
            self.raise_error("only 'enable' and 'disable' verbs are supported")
        #support both separate arguments and csv:
        categories = []
        for x in args[1:]:
            categories += [v.strip() for v in x.split(",")]
        from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
        if log_cmd=="enable":
            add_debug_category(*categories)
            loggers = enable_debug_for(*categories)
        else:
            assert log_cmd=="disable"
            add_disabled_category(*categories)
            loggers = disable_debug_for(*categories)
        if not loggers:
            log.info("no loggers matching: %s", csv(categories))
        else:
            log.info("%sd debugging for: %s", log_cmd, csv(loggers))
        return "logging %sd for %s" % (log_cmd, csv(loggers))
