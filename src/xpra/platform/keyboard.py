# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default:
Keyboard = None

from xpra.platform import platform_import
platform_import(globals(), "keyboard", True,
                "Keyboard")

def main():
    import sys
    from xpra.os_util import WIN32, OSX, POSIX, bytestostr
    from xpra.util import print_nested_dict, csv
    from xpra.platform import program_context
    from xpra.log import Logger, enable_color
    with program_context("Keyboard-Tool", "Keyboard Tool"):
        #use the logger for the platform module we import from
        global log
        log = None
        platform_import(globals(), "keyboard", True, "log")
        if log is None:
            log = Logger("keyboard")
        enable_color()
        verbose = "-v" in sys.argv or "--verbose" in sys.argv or \
            (WIN32 and not ("-q" in sys.argv or "--quiet"))
        if verbose:
            log.enable_debug()

        #naughty, but how else can I hook this up?
        import os
        if POSIX and not OSX:
            try:
                from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
                init_posix_display_source()
            except Exception as e:
                print("failed to connect to the X11 server:")
                print(" %s" % e)
                #hope for the best..

        keyboard = Keyboard()
        mod_meanings, mod_managed, mod_pointermissing = keyboard.get_keymap_modifiers()
        print("Modifiers:")
        print_nested_dict(mod_meanings)
        print("")
        print("Server Managed                    : %s" % (csv(mod_managed) or "None"))
        print("Missing from pointer events       : %s" % (csv(mod_pointermissing) or "None"))
        print("")
        layout,layouts,variant,variants = keyboard.get_layout_spec()
        print("Layout:     '%s'" % bytestostr(layout or b""))
        print("Layouts:    %s" % csv("'%s'" % x for x in (layouts or [])))
        print("Variant:    '%s'" % bytestostr(variant or b""))
        print("Variants:   %s" % csv("'%s'" % x for x in (variants or [])))
        print("")
        print("Repeat:     %s" % csv(keyboard.get_keyboard_repeat()))
        if verbose and POSIX:
            keysyms = keyboard.get_x11_keymap()
            if keysyms:
                print("Keysyms:")
                for keycode,keysyms in keysyms.items():
                    print(" %3i    : %s" % (keycode, csv(keysyms)))


if __name__ == "__main__":
    main()
