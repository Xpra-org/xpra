# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.css_overrides import add_screen_css
from xpra.os_util import gi_import

Gtk = gi_import("Gtk")


CSS = b"""
window.xpra-styled-window {
    background-color: @theme_bg_color;
}

.xpra-styled-window headerbar {
    min-height: 38px;
    padding: 4px 8px;
    margin: 0;
}

.xpra-styled-window headerbar button {
    min-width: 28px;
    min-height: 28px;
    padding: 2px 6px;
    border-radius: 7px;
}

.xpra-styled-window .xpra-body {
    padding: 20px;
}

.xpra-styled-window .xpra-card {
    padding: 10px 14px;
    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 10px;
    background-color: alpha(@theme_fg_color, 0.04);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.xpra-styled-window .xpra-title {
    font-size: 20px;
    font-weight: 600;
}

.xpra-styled-window .xpra-subtitle,
.xpra-styled-window .xpra-muted {
    color: alpha(@theme_fg_color, 0.68);
}

.xpra-styled-window .xpra-heading {
    color: alpha(@theme_fg_color, 0.68);
    font-weight: 600;
}

.xpra-styled-window entry,
.xpra-styled-window combobox button {
    min-height: 30px;
    padding: 3px 8px;
    border-radius: 7px;
}

.xpra-styled-window button.xpra-action {
    min-height: 30px;
    padding: 5px 10px;
    border-radius: 8px;
}

.xpra-styled-window .xpra-actions button.xpra-action {
    min-width: 72px;
}

.xpra-styled-window .xpra-warning {
    padding: 8px 12px;
    border-radius: 8px;
    color: #ffffff;
    background-color: #c01c28;
}

.xpra-styled-window .xpra-empty {
    padding: 36px 24px;
    color: alpha(@theme_fg_color, 0.68);
    font-size: 1.1em;
}

.xpra-styled-window .xpra-actions {
    margin-top: 8px;
}

.xpra-styled-window .xpra-dialog-title {
    font-size: 1.15em;
    font-weight: 600;
}

.xpra-styled-window .xpra-table {
    padding: 10px 14px;
}

.xpra-styled-window .xpra-cell {
    padding: 6px;
}

.xpra-styled-window .xpra-countdown {
    color: alpha(@theme_fg_color, 0.68);
}
"""

_loaded = False


def load_common_style() -> None:
    global _loaded
    if not _loaded:
        add_screen_css(CSS)
        _loaded = True


def add_style_class(widget, *names: str) -> None:
    context = widget.get_style_context()
    for name in names:
        context.add_class(name)


def style_window(window, *names: str) -> None:
    load_common_style()
    add_style_class(window, "xpra-styled-window", "xpra-dialog-window", *names)
    window.set_border_width(0)


def style_body(widget) -> None:
    add_style_class(widget, "xpra-body")


def style_button(button, primary=False) -> None:
    add_style_class(button, "xpra-action")
    if primary:
        add_style_class(button, "suggested-action")


def style_actions(widget) -> None:
    add_style_class(widget, "xpra-actions")
    widget.set_spacing(10)
    widget.set_halign(Gtk.Align.END)


def style_dialog(dialog, *names: str) -> None:
    style_window(dialog, *names)
    style_body(dialog.get_content_area())
    actions = dialog.get_action_area()
    style_actions(actions)
    for button in actions.get_children():
        style_button(button)
