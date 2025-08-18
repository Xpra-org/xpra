#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import

# default:
Keyboard: type | None = None


def get_keyboard_device():
    return None


platform_import(globals(), "keyboard", True,
                "Keyboard",
                "get_keyboard_device")


def main() -> int:
    import sys
    from xpra.util.system import is_X11
    from xpra.util.str_fn import print_nested_dict
    from xpra.util.str_fn import csv
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Keyboard-Tool", "Keyboard Tool"):
        # use the logger for the platform module we import from
        enable_color()
        verbose = consume_verbose_argv(sys.argv, "keyboard")

        # naughty, but how else can I hook this up?
        if is_X11():
            try:
                from xpra.x11.bindings.display_source import init_display_source
                init_display_source()
            except Exception as e:
                print("failed to connect to the X11 server:")
                print(" %s" % e)
                # hope for the best..

        print("keyboard device: %s" % get_keyboard_device())

        if not Keyboard:
            print("no keyboard implementation")
            return 1
        keyboard = Keyboard()  # pylint: disable=not-callable
        mod_meanings, mod_managed, mod_pointermissing = keyboard.get_keymap_modifiers()
        print("Modifiers:")
        print_nested_dict(mod_meanings)
        print("")
        print("Server Managed                    : %s" % (csv(mod_managed) or "None"))
        print("Missing from pointer events       : %s" % (csv(mod_pointermissing) or "None"))
        print("")
        model, layout, layouts, variant, variants, options = keyboard.get_layout_spec()
        print(f"Model:      {model!r}")
        print(f"Layout:     {layout!r}")
        print(f"Layouts:    {csv(layouts)}")
        print(f"Variant:    {variant!r}")
        print(f"Variants:   {csv(variants)}")
        print(f"Options:    {options!r}")
        print("")
        print(f"Repeat:     {csv(keyboard.get_keyboard_repeat())}")
        if verbose and is_X11():
            keysyms = keyboard.get_x11_keymap()
            if keysyms:
                print("Keysyms:")
                for keycode, keysyms in keysyms.items():
                    print(" %3i    : %s" % (keycode, csv(keysyms)))
    return 0


if __name__ == "__main__":
    main()
