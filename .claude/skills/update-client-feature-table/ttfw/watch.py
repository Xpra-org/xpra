#!/usr/bin/env python3
# usage: watch.py TITLE
# prints "ready" once it is watching $DISPLAY, then the CLOCK_MONOTONIC time at which
# a top-level window whose title contains TITLE is mapped (or gets that title after being mapped)
import sys
import time

from Xlib import X, display

d = display.Display()
root = d.screen().root
root.change_attributes(event_mask=X.SubstructureNotifyMask)
NET_WM_NAME = d.intern_atom("_NET_WM_NAME")
UTF8_STRING = d.intern_atom("UTF8_STRING")
want = sys.argv[1]
mapped = set()


def title(w) -> str:
    try:
        p = w.get_full_property(NET_WM_NAME, UTF8_STRING)
        if p:
            return p.value.decode("utf8", "replace")
        n = w.get_wm_name()
        return n.decode("latin1") if isinstance(n, bytes) else (n or "")
    except Exception:
        return ""


def found() -> bool:
    return want in title(e.window)


d.sync()
print("ready", flush=True)
while True:
    e = d.next_event()
    now = time.monotonic()
    if e.type == X.MapNotify:
        mapped.add(e.window.id)
        if found():
            break
        try:
            e.window.change_attributes(event_mask=X.PropertyChangeMask)
        except Exception:
            pass
    elif e.type == X.PropertyNotify and e.window.id in mapped and found():
        break
print(now, flush=True)
