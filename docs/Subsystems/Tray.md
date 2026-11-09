# Tray

<div class="docs-section-heading" markdown="1">

## Overview

</div>

The Tray subsystem forwards system-tray icons and menus between the client and
server.

<div class="docs-section-heading" markdown="1">

## System tray forwarding

</div>

Applications running on the server can place icons in a system tray (X11 `_NET_SYSTEM_TRAY`).
A client that advertises the top-level `system_tray: true` capability receives each of these
icons as a regular `window-create` packet whose metadata contains `tray=True`. The icon's
pixels arrive as `window-draw` packets, like any other window, but never use the `scroll`
encoding.

The client shows the pixels as an icon in its own system tray, rather than as a window:

* it does not send `window-map` for tray windows;
* it sends a `window-configure` with the icon's on-screen `geometry` (in server pixels),
  and `properties` containing the tray's `orientation` when known, whenever the icon is
  placed or moved, so that the server can position the popup menus;
* clicks on the icon are sent as `pointer-button` packets for the tray's window id, at the
  position of the click;
* the application's popup menus then arrive as ordinary override-redirect windows.

Clients without a system tray of their own should not advertise `system_tray`.
The server's own tray menu (`tray` client option) is a client side feature and does not
use any packet.
