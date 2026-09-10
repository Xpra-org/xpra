#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO
from unittest.mock import patch

from xpra.clipboard import proxy as proxy_module
from xpra.clipboard.proxy import ClipboardProxyCore, filter_data
from xpra.codecs.image_type import get_image_type


class SynchronousProxy(ClipboardProxyCore):
    def __init__(self, responses):
        super().__init__("CLIPBOARD")
        self.responses = responses
        self.requests = []

    def get_contents(self, target, got_contents) -> None:
        self.requests.append(target)
        got_contents(*self.responses.get(target, ("", 0, b"")))


class AsynchronousProxy(ClipboardProxyCore):
    def __init__(self, responses):
        super().__init__("CLIPBOARD")
        self.responses = responses
        self.requests = []
        self.callback = None

    def get_contents(self, target, got_contents) -> None:
        self.requests.append(target)
        self.callback = lambda: got_contents(*self.responses[target])

    def respond(self) -> None:
        callback, self.callback = self.callback, None
        callback()


class FakeGLib:
    """
    Records the timers which are still armed, and lets the test fire them.
    The idle callbacks are kept apart from the timeouts: the proxy uses one
    to lift the owner change block, which is not what these tests are about.
    """

    def __init__(self):
        self.timers: dict[int, tuple] = {}
        self.idles: dict[int, tuple] = {}
        self.counter = 0

    def timeout_add(self, delay: int, callback, *args) -> int:
        self.counter += 1
        self.timers[self.counter] = (delay, callback, args)
        return self.counter

    def idle_add(self, callback, *args) -> int:
        self.counter += 1
        self.idles[self.counter] = (callback, args)
        return self.counter

    def source_remove(self, source: int) -> None:
        for sources in (self.timers, self.idles):
            if source in sources:
                del sources[source]
                return
        raise ValueError(f"source {source} is not armed")

    def delays(self) -> list:
        return [delay for delay, _callback, _args in self.timers.values()]

    def fire_all(self) -> None:
        for timer in tuple(self.timers):
            armed = self.timers.pop(timer, None)
            if armed:
                _delay, callback, args = armed
                callback(*args)


class FakeClock:
    """ lets the tests move time forward without sleeping """

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms / 1000


class CountingProxy(ClipboardProxyCore):
    """ counts the tokens instead of sending them """

    def __init__(self):
        super().__init__("CLIPBOARD")
        self.tokens = 0
        self.sends = True

    def do_emit_token(self) -> bool:
        self.tokens += 1
        return self.sends


class BackingOffProxy(CountingProxy):
    """ counts the tokens of a backend which spaces them out exponentially, as X11 does """

    TOKEN_DELAY = 20
    TOKEN_BACKOFF_MAX = 100


class ClipboardSchedulingTest(unittest.TestCase):

    def make_proxy(self, want_targets=False, greedy=False, proxy_class=CountingProxy) -> tuple:
        glib = FakeGLib()
        clock = FakeClock()
        for attr, value in (("GLib", glib), ("monotonic", clock)):
            patcher = patch.object(proxy_module, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        proxy = proxy_class()
        proxy._enabled = True
        proxy._want_targets = want_targets
        proxy._greedy_client = greedy
        return proxy, glib, clock

    def test_delay_grows_with_the_cost_of_the_token(self):
        delay = proxy_module.DELAY_SEND_TOKEN
        for want_targets, greedy, expected in (
            (False, False, delay),
            (True, False, delay * 2),
            (False, True, delay * 2),
            (True, True, delay * 4),
        ):
            with self.subTest(want_targets=want_targets, greedy=greedy):
                proxy = self.make_proxy(want_targets, greedy)[0]
                self.assertEqual(proxy.emit_token_delay(), expected)

    def test_an_isolated_change_is_not_delayed(self):
        # `_last_emit_token` is 0, so the whole delay has already elapsed:
        proxy, glib, _clock = self.make_proxy(greedy=True)
        proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 1)
        self.assertEqual(glib.timers, {})

    def test_the_next_change_waits_for_the_delay(self):
        proxy, glib, _clock = self.make_proxy(greedy=True)
        proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 1)
        # the change which follows straight after is held back:
        proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 1)
        self.assertEqual(glib.delays(), [proxy.emit_token_delay()])
        # ... and sent when the timer fires:
        glib.fire_all()
        self.assertEqual(proxy.tokens, 2)
        self.assertEqual(proxy._emit_token_timer, 0)

    def test_rescheduling_keeps_the_deadline_already_set(self):
        # every change works out the same deadline, since it is counted from the last
        # token sent: the timer is left alone rather than restarted over and over
        proxy, glib, clock = self.make_proxy(greedy=True)
        proxy.schedule_emit_token()
        proxy.schedule_emit_token()
        armed = dict(glib.timers)
        self.assertEqual(glib.delays(), [proxy.emit_token_delay()])
        for _ in range(3):
            clock.advance(50)
            proxy.schedule_emit_token()
            self.assertEqual(glib.timers, armed)
        # and it is still sent exactly once:
        self.assertEqual(proxy.tokens, 1)
        glib.fire_all()
        self.assertEqual(proxy.tokens, 2)

    def test_a_long_delay_does_not_hold_back_the_next_change(self):
        # ie: the win32 backend asks for 500ms for an application which is slow
        # to put its data on the clipboard - the changes after it must not wait
        proxy, glib, clock = self.make_proxy(greedy=True)
        proxy.schedule_emit_token()
        proxy.schedule_emit_token(500)
        self.assertEqual(glib.delays(), [500])
        clock.advance(100)
        proxy.schedule_emit_token()
        self.assertEqual(glib.delays(), [proxy.emit_token_delay() - 100])

    def test_a_long_delay_does_not_hold_back_a_token_already_due(self):
        # the other way around: a change which needs the extra time
        # must not push back the token an earlier one had scheduled
        proxy, glib, clock = self.make_proxy(greedy=True)
        proxy.schedule_emit_token()
        proxy.schedule_emit_token()
        armed = dict(glib.timers)
        clock.advance(100)
        proxy.schedule_emit_token(500)
        self.assertEqual(glib.timers, armed)

    def test_min_delay_is_honoured(self):
        # `min_delay` is a floor: the application which owns the selection needs
        # that long to publish its data, whether a token is due or not
        proxy, glib, _clock = self.make_proxy()
        proxy.schedule_emit_token(500)
        self.assertEqual(proxy.tokens, 0)
        self.assertEqual(glib.delays(), [500])
        glib.fire_all()
        self.assertEqual(proxy.tokens, 1)

    def test_a_token_we_did_not_send_does_not_hold_back_the_next_one(self):
        # ie: the X11 proxy finds the selection holds remote data when the timer fires
        proxy, glib, _clock = self.make_proxy(greedy=True)
        proxy.sends = False
        proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 1)
        self.assertEqual(proxy._sent_token_events, 0)
        # nothing went out, so the change which follows is not spaced out from it:
        proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 2)
        self.assertEqual(glib.timers, {})
        # whereas one that is sent does:
        proxy.sends = True
        proxy.schedule_emit_token()
        self.assertEqual(proxy._sent_token_events, 1)
        proxy.schedule_emit_token()
        self.assertEqual(glib.delays(), [proxy.emit_token_delay()])

    def test_the_back_off_doubles_up_to_its_cap(self):
        proxy, glib, _clock = self.make_proxy(proxy_class=BackingOffProxy)
        # the first change is not delayed, and each one which follows it waits twice as long:
        for expected in (0, 20, 40, 80, 100, 100):
            proxy.schedule_emit_token()
            self.assertEqual(glib.delays(), [expected] if expected else [])
            glib.fire_all()
        self.assertEqual(proxy.tokens, 6)

    def test_the_back_off_resets_once_the_clipboard_is_idle(self):
        proxy, glib, clock = self.make_proxy(proxy_class=BackingOffProxy)
        for _ in range(4):
            proxy.schedule_emit_token()
            glib.fire_all()
        self.assertEqual(proxy._emit_token_backoff, BackingOffProxy.TOKEN_BACKOFF_MAX)
        clock.advance(proxy_module.TOKEN_BACKOFF_RESET)
        proxy.schedule_emit_token()
        # back to the base delay, all of which has already elapsed:
        self.assertEqual(glib.timers, {})
        self.assertEqual(proxy._emit_token_backoff, BackingOffProxy.TOKEN_DELAY)

    def test_a_flat_delay_never_backs_off(self):
        # which is what every backend but X11 asks for
        proxy, glib, _clock = self.make_proxy()
        for _ in range(4):
            proxy.schedule_emit_token()
            glib.fire_all()
        self.assertEqual(proxy._emit_token_backoff, 0)
        proxy.schedule_emit_token()
        self.assertEqual(glib.delays(), [proxy_module.DELAY_SEND_TOKEN])

    def test_delay_can_be_turned_off(self):
        proxy, glib, _clock = self.make_proxy(greedy=True)
        with patch.object(type(proxy), "TOKEN_DELAY", -1):
            self.assertEqual(proxy.emit_token_delay(), 0)
            proxy.schedule_emit_token()
            proxy.schedule_emit_token()
        self.assertEqual(proxy.tokens, 2)
        self.assertEqual(glib.timers, {})


class ClipboardProxyTest(unittest.TestCase):
    def test_filter_additional_image_formats(self):
        from PIL import Image
        buf = BytesIO()
        Image.new("RGBA", (2, 2), (1, 2, 3, 255)).save(buf, "PNG")
        png = buf.getvalue()
        for target in ("image/webp", "image/bmp"):
            with self.subTest(target=target):
                converted = filter_data("image/png", 8, png, trusted=True, output_dtype=target)
                self.assertEqual(get_image_type(converted), target.split("/", 1)[1])

    def test_get_eager_targets(self):
        proxy = SynchronousProxy({})
        proxy.set_preferred_targets(("text/html", "UTF8_STRING"))
        self.assertEqual(
            proxy.get_eager_targets(("text/uri-list", "UTF8_STRING", "text/html")),
            ("UTF8_STRING", "text/html"),
        )

    def test_local_owner_change_discards_remote_origin(self):
        proxy = SynchronousProxy({})
        proxy._clipboard_origin = "remote-origin"
        proxy.do_owner_changed()
        self.assertEqual(proxy._clipboard_origin, "")

    def test_collect_contents(self):
        proxy = SynchronousProxy({
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
        })
        results = []
        proxy.collect_contents(("UTF8_STRING", "text/html", "UTF8_STRING", "missing"), results.append)
        self.assertEqual(proxy.requests, ["UTF8_STRING", "text/html", "missing"])
        self.assertEqual(results, [{
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
        }])

    def test_collect_contents_size_limit(self):
        proxy = SynchronousProxy({
            "too-large": ("text/plain", 8, b"123456"),
            "small": ("text/uri-list", 8, b"uri"),
            "over-budget": ("text/html", 8, b"html"),
        })
        results = []
        proxy.collect_contents(("too-large", "small", "over-budget"), results.append, max_size=5)
        self.assertEqual(results, [{
            "small": ("text/uri-list", 8, b"uri"),
        }])

    def test_collect_contents_asynchronously(self):
        proxy = AsynchronousProxy({
            "text/plain": ("text/plain", 8, b"text"),
            "text/html": ("text/html", 8, b"<b>text</b>"),
        })
        results = []
        proxy.collect_contents(("text/plain", "text/html"), results.append)
        self.assertEqual(proxy.requests, ["text/plain"])
        self.assertEqual(results, [])
        proxy.respond()
        self.assertEqual(proxy.requests, ["text/plain", "text/html"])
        self.assertEqual(results, [])
        proxy.respond()
        self.assertEqual(results, [{
            "text/plain": ("text/plain", 8, b"text"),
            "text/html": ("text/html", 8, b"<b>text</b>"),
        }])


if __name__ == "__main__":
    unittest.main()
