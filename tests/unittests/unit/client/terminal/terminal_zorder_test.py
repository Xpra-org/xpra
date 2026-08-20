#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO

from xpra.util.env import OSEnvContext
from xpra.util.objects import typedict
from xpra.client.gui import ui_client_base
from unit.test_util import silence_info
from unit.client.terminal.terminal_test_util import TERMINAL_SIZE, placements

try:
    from xpra.client.terminal import graphics
    from xpra.client.terminal import client as terminal_client
    from xpra.client.terminal.tty import TerminalOutput
    from xpra.client.terminal.window import ClientWindow
except ImportError:
    graphics = None
    terminal_client = None
    TerminalOutput = None
    ClientWindow = None


@unittest.skipIf(terminal_client is None, "the terminal client component is not available")
class TerminalZOrderTest(unittest.TestCase):
    """
    Drives the window manager state of a real `XpraTerminalClient` with real
    `ClientWindow` objects, and checks the kitty `z` indexes, the focus
    transitions and the hit testing that result.
    """

    def setUp(self):
        super().setUp()
        env_context = OSEnvContext(XPRA_NOX11="1")
        env_context.__enter__()
        self.addCleanup(env_context.__exit__)
        with silence_info(ui_client_base):
            self.client = terminal_client.XpraTerminalClient()
        self.addCleanup(self.client.cleanup)
        self.client.terminal_size = TERMINAL_SIZE
        self.buffer = BytesIO()
        self.client.terminal_output = TerminalOutput(self.buffer)
        self.window_sub = self.client.get_subsystem("window")
        self.assertIsNotNone(self.window_sub, "no `window` subsystem composed")

    ######################################################################
    # helpers

    def make_window(self, wid: int, geom=(0, 0, 100, 100), override_redirect=False, metadata=None):
        md = typedict({"has-alpha": True})
        md.update(metadata or {})
        window = ClientWindow(self.client, None, wid, geom, geom[2:],
                              md, override_redirect, typedict(),
                              None, (0, 0), 24, "no")
        # `register_window` fires the "new-window" signal the client listens to:
        self.window_sub.register_window(wid, window)
        # the paints are normally deferred to the GLib main loop, run them inline:
        window._backing.with_gfx_context = lambda function, *args: function(None, *args)
        window.show_all()
        return window

    def drain(self) -> bytes:
        data = self.buffer.getvalue()
        self.buffer.seek(0)
        self.buffer.truncate()
        return data

    def zorder(self) -> dict[int, int]:
        return dict(self.client._zorder)

    def destroy(self, wid: int) -> None:
        # this is what `_process_window_destroy` does:
        window = self.window_sub._id_to_window.pop(wid)
        self.window_sub._window_to_id.pop(window)
        self.client.destroy_window(wid, window)

    ######################################################################
    # z index assignment

    def test_z_indexes_follow_the_creation_order(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3)
        base = graphics.WINDOW_Z_BASE
        step = graphics.WINDOW_Z_STEP
        self.assertEqual(self.zorder(), {1: base, 2: base + step, 3: base + 2 * step})
        self.assertEqual(self.client.stacking_order(), [1, 2, 3])
        self.assertEqual(self.client.window_z(3), base + 2 * step)
        # an unknown window still gets a usable index:
        self.assertEqual(self.client.window_z(99), base)

    def test_show_places_at_the_assigned_z(self):
        self.make_window(1)
        self.assertEqual(placements(self.drain()), [(1, 10)])
        self.make_window(2)
        self.assertEqual(placements(self.drain()), [(2, 12)])

    ######################################################################
    # raise / lower / restack

    def test_raise_moves_to_the_top(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3)
        self.drain()
        # `present()` is what the server's `window-raise` packet ends up calling:
        self.window_sub.get_window(1).present()
        self.assertEqual(self.client.stacking_order(), [2, 3, 1])
        self.assertEqual(self.zorder(), {2: 10, 3: 12, 1: 14})
        # every window whose index changed is placed again:
        self.assertEqual(sorted(placements(self.drain())), [(1, 14), (2, 10), (3, 12)])

    def test_raising_the_top_window_changes_nothing(self):
        self.make_window(1)
        self.make_window(2)
        self.drain()
        self.client.raise_window(2)
        self.assertEqual(self.zorder(), {1: 10, 2: 12})
        # nothing was re-placed by the client (the window itself did not ask):
        self.assertEqual(placements(self.drain()), [])

    def test_lower_moves_to_the_bottom(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3)
        self.drain()
        self.client.lower_window(3)
        self.assertEqual(self.client.stacking_order(), [3, 1, 2])
        self.assertEqual(self.zorder(), {3: 10, 1: 12, 2: 14})
        self.assertEqual(sorted(placements(self.drain())), [(1, 12), (2, 14)])

    def test_restack_above_a_sibling(self):
        w1 = self.make_window(1)
        self.make_window(2)
        w3 = self.make_window(3)
        self.drain()
        # `_process_window_restack` calls `window.restack(other, above)`:
        w1.restack(w3, 1)
        self.assertEqual(self.client.stacking_order(), [2, 3, 1])
        self.assertEqual(self.zorder(), {2: 10, 3: 12, 1: 14})

    def test_restack_below_a_sibling(self):
        w1 = self.make_window(1)
        self.make_window(2)
        w3 = self.make_window(3)
        self.drain()
        w3.restack(w1, 0)
        self.assertEqual(self.client.stacking_order(), [3, 1, 2])
        self.assertEqual(self.zorder(), {3: 10, 1: 12, 2: 14})

    def test_restack_against_an_unknown_window(self):
        self.make_window(1)
        self.make_window(2)
        self.client.restack_window(1, 99, 1)
        self.assertEqual(self.client.stacking_order(), [2, 1])
        self.client.restack_window(1, 99, 0)
        self.assertEqual(self.client.stacking_order(), [1, 2])
        # an unknown window cannot be restacked:
        self.client.restack_window(99, 1, 1)
        self.assertEqual(self.client.stacking_order(), [1, 2])

    ######################################################################
    # override-redirect windows

    def test_override_redirect_sits_above_its_parent(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3, override_redirect=True, metadata={"transient-for": 1})
        base = graphics.WINDOW_Z_BASE
        self.assertEqual(self.client.stacking_order(), [1, 3, 2])
        self.assertEqual(self.zorder(), {
            1: base,
            3: base + graphics.OVERRIDE_REDIRECT_Z_OFFSET,
            2: base + graphics.WINDOW_Z_STEP,
        })

    def test_override_redirect_follows_its_parent(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3, override_redirect=True, metadata={"parent": 1})
        self.drain()
        self.client.raise_window(1)
        self.assertEqual(self.client.stacking_order(), [2, 1, 3])
        self.assertEqual(self.zorder(), {2: 10, 1: 12, 3: 13})
        # the popup is placed again, at its new index:
        self.assertIn((3, 13), placements(self.drain()))

    def test_parentless_override_redirect_goes_on_top(self):
        self.make_window(1)
        self.make_window(2, override_redirect=True)
        self.assertEqual(self.client.stacking_order(), [1, 2])
        # without a parent to sit on, it takes the slot the next regular window
        # would have used, plus the override-redirect offset: above everything
        zorder = self.zorder()
        self.assertEqual(zorder[1], graphics.WINDOW_Z_BASE)
        self.assertGreater(zorder[2], graphics.WINDOW_Z_BASE + graphics.WINDOW_Z_STEP)

    def test_override_redirect_is_not_part_of_the_regular_ladder(self):
        self.make_window(1, override_redirect=True, metadata={"transient-for": 0})
        self.make_window(2)
        self.make_window(3)
        # the popup does not consume a slot of its own:
        self.assertEqual(self.zorder()[2], graphics.WINDOW_Z_BASE)
        self.assertEqual(self.zorder()[3], graphics.WINDOW_Z_BASE + graphics.WINDOW_Z_STEP)

    ######################################################################
    # destroy

    def test_destroy_renumbers_the_others(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3)
        self.drain()
        self.destroy(1)
        self.assertEqual(self.client.stacking_order(), [2, 3])
        self.assertEqual(self.zorder(), {2: 10, 3: 12})
        self.assertEqual(sorted(placements(self.drain())), [(2, 10), (3, 12)])

    def test_destroy_drops_the_override_redirect_child(self):
        self.make_window(1)
        self.make_window(2, override_redirect=True, metadata={"transient-for": 1})
        self.destroy(2)
        self.assertEqual(self.client.stacking_order(), [1])
        self.assertEqual(self.zorder(), {1: 10})

    def test_destroy_clears_the_focus(self):
        self.make_window(1)
        self.client.focus_window(1)
        self.assertEqual(self.client._focused, 1)
        self.destroy(1)
        self.assertEqual(self.client._focused, 0)

    ######################################################################
    # hit testing

    def test_hit_test_picks_the_topmost(self):
        self.make_window(1, (0, 0, 100, 100))
        self.make_window(2, (50, 50, 100, 100))
        # only the second window covers this pixel:
        self.assertEqual(self.client.hit_test(120, 120)[0], 2)
        # both cover this one, and window 2 is on top:
        self.assertEqual(self.client.hit_test(60, 60)[0], 2)
        self.client.raise_window(1)
        self.assertEqual(self.client.hit_test(60, 60)[0], 1)

    def test_hit_test_prefers_an_override_redirect_child(self):
        self.make_window(1, (0, 0, 100, 100))
        self.make_window(2, (200, 0, 100, 100))
        self.make_window(3, (10, 10, 20, 20), override_redirect=True, metadata={"transient-for": 1})
        self.assertEqual(self.client.hit_test(15, 15)[0], 3)
        self.assertEqual(self.client.hit_test(50, 50)[0], 1)

    def test_hit_test_edges(self):
        self.make_window(1, (10, 20, 30, 40))
        self.assertEqual(self.client.hit_test(10, 20)[0], 1)
        self.assertEqual(self.client.hit_test(39, 59)[0], 1)
        self.assertEqual(self.client.hit_test(9, 20)[0], 0)
        self.assertEqual(self.client.hit_test(40, 59)[0], 0)
        self.assertEqual(self.client.hit_test(10, 60)[0], 0)

    def test_hit_test_skips_unmapped_windows(self):
        window = self.make_window(1, (0, 0, 100, 100))
        self.assertEqual(self.client.hit_test(10, 10)[0], 1)
        window.hide()
        self.assertEqual(self.client.hit_test(10, 10), (0, None))

    def test_hit_test_without_any_window(self):
        self.assertEqual(self.client.hit_test(0, 0), (0, None))

    ######################################################################
    # focus

    def test_focus_transitions(self):
        w1 = self.make_window(1)
        w2 = self.make_window(2)
        # the first regular window took the focus when it was created:
        self.assertTrue(w1.has_toplevel_focus())
        self.assertFalse(w2.has_toplevel_focus())
        self.client.focus_window(2)
        self.assertFalse(w1.has_toplevel_focus())
        self.assertTrue(w2.has_toplevel_focus())
        # the window subsystem was told about it:
        self.assertEqual(self.window_sub._focused, 2)

    def test_first_window_takes_the_focus(self):
        # without this, the keyboard is dead until the user clicks:
        self.make_window(1)
        self.assertEqual(self.client._focused, 1)
        # later windows do not steal it:
        self.make_window(2)
        self.assertEqual(self.client._focused, 1)

    def test_override_redirect_does_not_take_the_focus(self):
        self.make_window(1, override_redirect=True)
        self.assertEqual(self.client._focused, 0)
        # the first regular window still does, even after an override-redirect one:
        self.make_window(2)
        self.assertEqual(self.client._focused, 2)

    def test_destroy_focus_falls_back_to_the_top(self):
        self.make_window(1)
        self.make_window(2)
        self.make_window(3)
        self.client.focus_window(3)
        self.destroy(3)
        # focus falls back to the window now at the top of the stack:
        self.assertEqual(self.client._focused, 2)
        self.destroy(2)
        self.assertEqual(self.client._focused, 1)
        self.destroy(1)
        self.assertEqual(self.client._focused, 0)

    def test_present_takes_the_focus(self):
        self.make_window(1)
        w2 = self.make_window(2)
        w2.present()
        self.assertEqual(self.window_sub._focused, 2)
        # the client's own focus state (which key events are routed with)
        # has to follow, or the keystrokes keep going to the previous window:
        self.assertEqual(self.client._focused, 2)
        self.assertTrue(w2.has_toplevel_focus())

    def test_click_focuses_the_topmost_window(self):
        self.make_window(1, (0, 0, 100, 100))
        self.make_window(2, (50, 50, 100, 100))
        # a press inside both windows focuses the one on top:
        self.client.send_click(*self.client.hit_test(60, 60), 1, True, (60, 60, 10, 10))
        self.assertEqual(self.client._focused, 2)
        self.client.send_click(*self.client.hit_test(10, 10), 1, True, (10, 10, 10, 10))
        self.assertEqual(self.client._focused, 1)

    def test_click_raises_the_window(self):
        self.make_window(1, (0, 0, 100, 100))
        self.make_window(2, (50, 50, 100, 100))
        self.drain()
        # a press inside window 1 only (window 2 is on top but does not cover it):
        self.client.send_click(*self.client.hit_test(10, 10), 1, True, (10, 10, 10, 10))
        self.assertEqual(self.client.stacking_order(), [2, 1])
        self.assertEqual(self.zorder(), {2: 10, 1: 12})
        self.assertEqual(sorted(placements(self.drain())), [(1, 12), (2, 10)])

    def test_click_does_not_raise_an_override_redirect_window(self):
        self.make_window(1, (0, 0, 100, 100))
        self.make_window(2, (200, 0, 100, 100))
        self.make_window(3, (10, 10, 20, 20), override_redirect=True, metadata={"transient-for": 1})
        order = self.client.stacking_order()
        self.client.send_click(*self.client.hit_test(15, 15), 1, True, (15, 15, 5, 5))
        self.assertEqual(self.client._focused, 3)
        self.assertEqual(self.client.stacking_order(), order)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
