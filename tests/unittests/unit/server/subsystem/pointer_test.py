#!/usr/bin/env python3

import unittest
from unittest.mock import Mock

from xpra.server.subsystem.pointer import PointerServer


class PointerPipelineTest(unittest.TestCase):

    @staticmethod
    def make_pointer(window):
        pointer = PointerServer()
        pointer.get_window = lambda _wid: window
        pointer.process_mouse_common = Mock(return_value=(10, 20))
        pointer.may_record_pointer_event = Mock()
        pointer.button_action = Mock()
        return pointer

    def test_stale_window_drops_a_press(self):
        pointer = self.make_pointer(None)
        pointer.do_process_button_action(object(), 0, 1, 3, True, (10, 20), {})
        pointer.may_record_pointer_event.assert_not_called()
        pointer.button_action.assert_not_called()

    def test_stale_window_keeps_a_matching_release(self):
        pointer = self.make_pointer(None)
        pointer.buttons_pressed[0] = {3}
        pointer.do_process_button_action(object(), 0, 1, 3, False, (10, 20), {})
        pointer.button_action.assert_called_once_with(0, 1, 3, False, {})


if __name__ == "__main__":
    unittest.main()
