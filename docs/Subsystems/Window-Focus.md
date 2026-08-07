# Window Focus

Focus is not one thing. Every windowing system splits it into several independent
notions which are usually, but not always, changed together - and each system draws the
lines in a different place.
This page describes the mechanisms on each platform and how they relate to each other.

This is background material for the [window subsystem](Window.md): the xpra server acts as
a window manager or compositor, and the `window-focus` packet it receives from the client
has to be translated into whichever set of mechanisms the session is using.


## X11

There are four independent things which are all called "focus" in X11, plus a set of
protocols layered on top of them.
They are easily conflated because a window manager normally changes all of them together.

### Keyboard focus

This is the only "focus" that the X server itself knows about.
The X server keeps exactly one _input focus window_ per keyboard device,
and key events are delivered there (or to the window under the pointer,
depending on the special values):

```c
XSetInputFocus(dpy, window, revert_to, time);
XGetInputFocus(dpy, &window, &revert_to);
```

* `window` can be a real window, `None` (keystrokes are discarded),
  or `PointerRoot` (keystrokes go to whatever window is under the pointer,
  which is the classic "focus follows mouse" implemented in the server).
* `revert_to` is `RevertToParent`, `RevertToPointerRoot` or `RevertToNone`:
  what happens when the focus window becomes unviewable.
  xpra always uses `RevertToParent`, see
  [XSetInputFocus](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/bindings/window.pyx).
* `time` matters: the server ignores the request if `time` is earlier than the last focus
  change. This is a genuine race guard, not a formality, which is why
  [do_give_client_focus](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/window.py)
  fetches a real server timestamp instead of using `CurrentTime`.

Clients learn about focus changes via `FocusIn` and `FocusOut` events, which carry:

* a `mode`: `NotifyNormal`, `NotifyGrab`, `NotifyUngrab`, `NotifyWhileGrabbed`
* a `detail`: `NotifyAncestor`, `NotifyVirtual`, `NotifyInferior`, `NotifyNonlinear`,
  `NotifyNonlinearVirtual`, `NotifyPointer`, `NotifyPointerRoot`, `NotifyDetailNone`

Toolkits get this wrong regularly. The grab related modes in particular are spurious focus
changes which should not update application state.

A keyboard grab (`XGrabKeyboard`, or an implicit grab from `XGrabKey`) overrides focus
entirely for its duration: events go to the grab window no matter who holds the focus.

Under XInput2 there is one focus _per master keyboard_, set with `XISetFocus`.
The core `XSetInputFocus` operates on the "virtual core keyboard".
Multi-pointer X is where "the" focus stops being singular.

### Pointer focus

There is no `XSetPointerFocus`.
Pointer events implicitly go to the smallest window containing the pointer which has
selected for them, walking up the ancestry if it has not.
The things that influence it are:

* `XGrabPointer` and implicit button grabs: redirect all pointer events to one window
* `EnterNotify` / `LeaveNotify`: how a window manager implementing focus-follows-mouse in
  user space decides to call `XSetInputFocus`
* `XWarpPointer`: moves the pointer, which _indirectly_ moves the focus if the focus is
  `PointerRoot`

So "focus follows mouse" is either server side (`PointerRoot` focus) or window manager
policy (enter events triggering `XSetInputFocus`).
These two behave differently, notably with respect to grabs and to windows that decline
focus.

See also the [pointer subsystem](Pointer.md).

### ICCCM: does the client even want the focus?

Focus is cooperative.
The `WM_HINTS` `input` field, combined with the presence of `WM_TAKE_FOCUS` in
`WM_PROTOCOLS`, defines four focus models:

| `input` | `WM_TAKE_FOCUS` | Model           | What the window manager must do                        |
|---------|-----------------|-----------------|--------------------------------------------------------|
| False   | absent          | No Input        | never focus it (eg: `xclock`, docks)                   |
| True    | absent          | Passive         | `XSetInputFocus` only                                  |
| True    | present         | Locally Active  | `XSetInputFocus` **and** send `WM_TAKE_FOCUS`          |
| False   | present         | Globally Active | send `WM_TAKE_FOCUS` only, the client focuses itself   |

ICCCM 4.1.7 claims to describe this but is completely opaque.
What real toolkits actually do:
GTK honours `WM_TAKE_FOCUS`, whereas Qt ignores it (outside of modal windows) and expects
to get the focus from the window manager's `XSetInputFocus`.
Therefore, if both are indicated, both MUST be used.

`WM_TAKE_FOCUS` is a `ClientMessage` and must carry a real timestamp, never `CurrentTime`:
see [send_wm_take_focus](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/bindings/send_wm.py).

### Stacking order

Raising a window does **not** focus it, and focusing a window does not raise it.
Those couplings are window manager policy.

#### `XRaiseWindow` and `XConfigureWindow`

A direct request from the client.
For a _managed_, reparented top-level window this usually does nothing useful: the client's
window is a child of the window manager's frame, so raising it only reorders it within that
frame. And if the window manager has selected `SubstructureRedirectMask` on the parent, the
request is intercepted rather than executed.

#### `ConfigureRequest`

What the window manager actually receives when a client calls `XConfigureWindow`,
`XMoveResizeWindow` or `XRaiseWindow` on a redirected window.
It carries a `value_mask` (which of x / y / width / height / border / sibling / stack_mode
are meaningful), plus `above` and `detail`
(`Above`, `Below`, `TopIf`, `BottomIf`, `Opposite`).
The window manager is free to honour it, modify it, or ignore it, and must send a synthetic
`ConfigureNotify` if it does not move the window.

This is the low-level, unauthenticated path: it carries no timestamp and no source
indication, so a window manager cannot tell a user driven raise from a background
application being rude.

#### `_NET_RESTACK_WINDOW`

The EWMH replacement for the above: a `ClientMessage` sent to the root window with
`data = [source_indication, sibling_window, detail]`.
It is meant for pagers and taskbars.
It exists precisely because `ConfigureRequest` lacks the source indication, and because
clients should not be reordering themselves without a reason.

#### `_NET_MOVERESIZE_WINDOW`

The same idea for geometry: a root window client message with gravity, source indication
and x / y / width / height, so that the window manager knows who asked and can apply the
correct gravity.

### `_NET_ACTIVE_WINDOW`

This atom is used in two directions, which is a common source of confusion.

**As a root window property**, the window manager _publishes_ which window it considers
active. It is a report, not a control: writing to it directly does nothing.

**As a `ClientMessage` sent to the root window**, a client _requests_ activation:

| Field     | Value                                                            |
|-----------|------------------------------------------------------------------|
| `data[0]` | source indication: 0=legacy / unknown, 1=normal application, 2=pager |
| `data[1]` | timestamp of the event which caused the request                  |
| `data[2]` | the requestor's currently active window, or 0                    |

"Activate" is deliberately vague and means the whole bundle: raise the window, switch to
its desktop, focus it, clear its demands-attention state. The window manager decides.

The source indication and the timestamp exist entirely for **focus stealing prevention**:

* source 2 (a pager, ie: direct user action) is normally obeyed unconditionally
* source 1 is compared against the `_NET_WM_USER_TIME` of the currently focused window:
  if the requesting application's timestamp is older than the user's last interaction with
  the current window, the window manager refuses, and instead sets
  `_NET_WM_STATE_DEMANDS_ATTENTION` (or the ICCCM urgency hint) so that the taskbar entry
  blinks.

`_NET_WM_USER_TIME` (and `_NET_WM_USER_TIME_WINDOW`) is the client's own declaration of
when the user last interacted with it. A value of 0 explicitly means "map me without focus".

### How it all composes

A "click to focus and raise" in a typical window manager is:

1. pointer button press on the frame
2. the window manager decides
3. internal restack
4. `XSetInputFocus` and / or `WM_TAKE_FOCUS`, according to the ICCCM focus model
5. update the root `_NET_ACTIVE_WINDOW` property
6. clear demands-attention

That is five distinct mechanisms for one user gesture.

The practical rules which fall out of this:

* clients should use `_NET_ACTIVE_WINDOW` to be activated, never `XSetInputFocus` on
  themselves (except for Globally Active clients responding to `WM_TAKE_FOCUS`) and never
  `XRaiseWindow`
* always propagate a real event timestamp: `CurrentTime` disables every race guard and
  every anti focus stealing heuristic in the stack
* the X server's notion of focus and the window manager's notion of "active" can
  legitimately diverge: during grabs, on override-redirect windows (menus and tooltips,
  which the window manager never sees), and with `PointerRoot`


## MS Windows

Win32 also has three notions of focus, but it splits them differently: by _scope_ rather
than by _device_.

* **Foreground window** - system wide, one per desktop.
  `GetForegroundWindow()` / `SetForegroundWindow()`.
  This is the window the user is working with, and its thread gets a scheduling boost.
* **Active window** - the top-level window, but _per input queue_ (ie: per thread).
  `GetActiveWindow()` / `SetActiveWindow()` only see windows attached to the calling
  thread's queue.
* **Focus window** - also per input queue. `GetFocus()` / `SetFocus()`.
  This is the _control_ inside the active window which receives `WM_KEYDOWN`.

That last split has no X11 equivalent: on X11, focus within a top-level window is entirely
a toolkit-internal matter, whereas Win32 tracks it in the OS.
Querying another thread's state requires `GetGUIThreadInfo()`, which returns
`hwndActive`, `hwndFocus` and `hwndCapture` together.

The relevant messages are `WM_ACTIVATE` (`WA_ACTIVE` / `WA_CLICKACTIVE` / `WA_INACTIVE`),
`WM_ACTIVATEAPP` (process level, which is what xpra's win32 client watches to detect
session focus), `WM_NCACTIVATE` (repaint the frame as active or inactive),
`WM_SETFOCUS` / `WM_KILLFOCUS`, and `WM_MOUSEACTIVATE`.
A window answers `WM_MOUSEACTIVATE` with `MA_ACTIVATE`, `MA_ACTIVATEANDEAT`,
`MA_NOACTIVATE` or `MA_NOACTIVATEANDEAT` - a per-click veto on click-to-focus, and on
whether the activating click is also delivered to the window.

There is no separate pointer focus: mouse messages go to the window under the cursor by
hit-testing (`WM_NCHITTEST`) unless a thread holds the mouse capture
(`SetCapture` / `ReleaseCapture`), which is the analogue of `XGrabPointer`.
Unlike X11, leave events are not automatic - a window must ask for `WM_MOUSELEAVE` with
`TrackMouseEvent()`.

Stacking uses `SetWindowPos()` with `HWND_TOP`, `HWND_BOTTOM`, `HWND_TOPMOST` or
`HWND_NOTOPMOST`, and `BringWindowToTop()`.
`SWP_NOACTIVATE` decouples raising from activation and `SWP_NOZORDER` decouples moving
from raising, so unlike X11 the coupling is explicit per call rather than window manager
policy. `WS_EX_TOPMOST` is a genuinely separate stacking band enforced by the OS, where the
X11 equivalent `_NET_WM_STATE_ABOVE` is only a hint the window manager may honour.
`WS_EX_NOACTIVATE` marks a window that never takes the foreground.

Focus stealing prevention is in the OS rather than in a replaceable window manager:
`SetForegroundWindow()` silently fails and returns `FALSE` unless the calling process
qualifies - it is already the foreground process, it was launched by the foreground
process, it received the last input event, no window currently holds the foreground, it is
being debugged, or the foreground lock timeout (`SPI_GETFOREGROUNDLOCKTIMEOUT`) has expired
since the last user input. A process can hand its right over to another with
`AllowSetForegroundWindow()`, which is what `_NET_ACTIVE_WINDOW`'s source indication
achieves by convention.
When activation is refused the taskbar button flashes; `FlashWindowEx()` is the explicit
form, equivalent to `_NET_WM_STATE_DEMANDS_ATTENTION`.
`AttachThreadInput()` is the historical way to bypass all of this by merging input queues.

Focus follows mouse exists as `SPI_SETACTIVEWINDOWTRACKING` but is off by default.


## macOS

macOS also has three levels, but the top one is the **application**, not the window.
This is the single biggest difference from X11, where nothing groups windows by application
for focus purposes (`WM_CLASS` is only a hint).

* **Active application** - one per session, and it owns the menu bar.
  `NSApplication.activate()`, `NSRunningApplication.activate(options:)`.
  Cmd-Tab switches applications, Cmd-\` cycles windows within the active application.
* **Key window** - the window of the active application which receives keyboard events.
  `makeKeyAndOrderFront:`, `makeKeyWindow`, `NSApp.keyWindow`.
  A window can refuse by returning false from `canBecomeKey`, which is the analogue of
  `WM_HINTS.input=False`.
* **Main window** - the application's primary document window, which may _differ_ from the
  key window: a floating inspector panel can be key while the document behind it remains
  main and keeps its active title bar. `NSApp.mainWindow`, `canBecomeMain`.
  X11 has nothing equivalent.
* **First responder** - within the key window, the responder chain decides which view gets
  the event. `makeFirstResponder:`, `acceptsFirstResponder`.
  This corresponds to the Win32 focus window.

Ordering uses `orderFront:`, `orderBack:`, `orderOut:` and `orderWindow:relativeTo:`.
Window **levels** (`NSWindow.level`: normal, floating, modalPanel, mainMenu, statusBar,
screenSaver) are hard stacking bands, the same way `HWND_TOPMOST` is on Win32.

Focus stealing prevention: an application cannot make itself active unless the user asked
for it. `activateIgnoringOtherApps:` was the historical escape hatch - xpra's macOS client
uses it as a workaround in
[xpra.platform.darwin.gui](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/gui.py).
macOS 14 tightened this so that the currently active application must yield activation
(`NSApplication.yieldActivation(to:)`), which moves macOS much closer to Wayland's token
model. The polite fallback is `requestUserAttention:`: `NSCriticalRequest` bounces the Dock
icon until the user responds, `NSInformationalRequest` bounces it once - matching
`_NET_WM_STATE_DEMANDS_ATTENTION`.

`acceptsFirstMouse:` decides whether the click which activates a window is also delivered
to the view, exactly the question `WM_MOUSEACTIVATE` answers on Win32.

`NSApplicationActivationPolicy` (`.regular`, `.accessory`, `.prohibited`) controls whether
an application can become active at all: `.accessory` (`LSUIElement`) applications have no
Dock icon and no menu bar, and cannot normally be activated.


## Wayland

The Wayland answer is short: **a client cannot focus or raise itself, and there is no
request to do so**. Focus is entirely the compositor's decision and the protocol only
notifies the client. Everything else follows from that.

* `wl_seat` is the unit of input, and there can be more than one.
  Each seat has its own keyboard, pointer and touch focus, so multi-seat is a first class
  citizen rather than the retrofit XI2 is on X11.
* `wl_keyboard.enter(serial, surface, keys)` and `wl_keyboard.leave(serial, surface)` tell
  the client which surface holds the keyboard focus. There is no corresponding request.
* `wl_pointer.enter` and `wl_pointer.leave` do the same for pointer focus, which is tracked
  separately from keyboard focus, per seat. `wl_touch` has its own focus per touch point.
* `xdg_toplevel.configure` carries a `states` array containing
  `XDG_TOPLEVEL_STATE_ACTIVATED`, which is how a client knows to draw itself as focused.
  It is purely a notification - the mirror image of `_NET_ACTIVE_WINDOW`, which is both a
  notification and a request.

### Serials

Serials replace X11 timestamps and do the job `_NET_WM_USER_TIME` does, but with
enforcement instead of convention.
Nearly every privileged action must quote the serial of a recent input event:
`xdg_toplevel.move`, `xdg_toplevel.resize`, `xdg_toplevel.show_window_menu`,
`xdg_popup.grab`, `wl_data_device.start_drag` and `wl_data_device.set_selection`.
The compositor validates the serial and refuses stale or invented ones.
On X11 the equivalent checks are advisory, and every window manager reimplements them.

### `xdg_activation_v1`

The sanctioned replacement for `_NET_ACTIVE_WINDOW` client messages.
It works by laundering the user's intent across a process boundary:

1. the client which currently has focus asks for a token with
   `xdg_activation_v1.get_activation_token`, setting `set_serial` (the input event which
   justifies the request), `set_surface` and `set_app_id`
2. it passes the token out of band to the target, typically through the
   `XDG_ACTIVATION_TOKEN` environment variable or a DBus call
3. the target calls `xdg_activation_v1.activate(token, surface)`

The compositor may still refuse and mark the surface urgent instead.
The important structural difference is that the party which must already have focus is the
_requesting_ one, so the "background application steals focus" case is prevented by
construction rather than detected by heuristic.

### No raise, no grabs

There is no equivalent of `XRaiseWindow`. Stacking is compositor policy:
`xdg_toplevel.set_parent` expresses a transient relationship and `xdg_positioner` places
popups, but nothing reorders arbitrary toplevels.
Taskbars and pagers use privileged protocols
(`ext_foreign_toplevel_list_v1`, `zwlr_foreign_toplevel_management_v1`)
which are not exposed to ordinary clients.

Grabs are replaced by narrow, revocable equivalents: `xdg_popup.grab` for menus (the
compositor dismisses the popup rather than letting a client wedge the session),
`zwp_pointer_constraints_v1` to lock or confine the pointer, `zwp_relative_pointer_v1` for
delta motion, and `zwp_keyboard_shortcuts_inhibit_v1` for remote desktop and VM viewers
which need to receive Alt-Tab.
An X11 client can freeze the entire server with a badly behaved grab; a Wayland client
cannot.

Under XWayland, X11 clients still see the X11 world described above: the compositor runs an
X window manager internally and maps `_NET_ACTIVE_WINDOW` and friends onto its own policy.
The two models coexist but do not fully align, which is why activation across the XWayland
boundary is a recurring source of bugs.


## Platform comparison

|                            | X11                                          | MS Windows                                | macOS                                        | Wayland                                       |
|----------------------------|----------------------------------------------|-------------------------------------------|----------------------------------------------|-----------------------------------------------|
| Focus granularity          | window                                       | window, per thread input queue            | application, then window                     | surface, per `wl_seat`                        |
| Keyboard focus             | `XSetInputFocus`                             | `SetFocus`                                | key window                                   | `wl_keyboard.enter` (notification only)       |
| Pointer focus              | implicit, window under pointer               | implicit, hit-tested                      | implicit, window under pointer               | `wl_pointer.enter`, separate per seat         |
| "Active" state             | `_NET_ACTIVE_WINDOW` root property           | foreground window                         | active application + main window             | `xdg_toplevel` `activated` state              |
| Focus within a window      | toolkit internal                             | `SetFocus`, tracked by the OS             | first responder                              | toolkit internal                              |
| Client can raise itself    | `XRaiseWindow`, usually intercepted          | `SetWindowPos`, `BringWindowToTop`        | `orderFront:`                                | no API at all                                 |
| Request activation         | `_NET_ACTIVE_WINDOW` client message          | `SetForegroundWindow`                     | `activate()`                                 | `xdg_activation_v1` token                     |
| Steal prevention           | timestamp + source indication, WM policy     | OS rules + foreground lock timeout        | must be frontmost or be yielded activation   | token must originate from a focused client    |
| Enforcement                | advisory, per window manager                 | in the OS                                 | in the OS                                    | in the compositor, mandatory                  |
| Polite fallback            | `_NET_WM_STATE_DEMANDS_ATTENTION`, urgency   | `FlashWindowEx`                           | `requestUserAttention:`                      | compositor urgency handling                   |
| Client declines focus      | `WM_HINTS.input=False`                       | `WS_EX_NOACTIVATE`, `WM_MOUSEACTIVATE`    | `canBecomeKey=false`, `.accessory` policy    | compositor decides                            |
| Always on top              | `_NET_WM_STATE_ABOVE`, WM policy             | `HWND_TOPMOST` band                       | `NSWindow.level` band                        | layer shell, compositor policy                |
| Pointer grab               | `XGrabPointer`, can freeze the server        | `SetCapture`, per thread                  | event taps, needs permission                 | pointer constraints, popup grab               |
| Multi-seat                 | XI2 master devices                           | no                                        | no                                           | native                                        |
| Focus follows mouse        | `PointerRoot` or WM policy                   | `SPI_SETACTIVEWINDOWTRACKING`, off        | not supported                                | compositor policy                             |


## How xpra uses this

The xpra server is a window manager
([xpra.x11.wm](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/wm.py))
or a Wayland compositor, whose "user" is a remote client.
Focus decisions arrive over the wire as a `window-focus` packet and are replayed into the
session using the mechanisms above, whilst the real focus on the client's own display is
managed by whatever window manager or compositor is running there.

On X11:

| Mechanism                                | Implementation                                                                                                |
|------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `XSetInputFocus` and `WM_TAKE_FOCUS`     | [xpra.x11.models.window](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/window.py)               |
| `WM_HINTS` `input` field                 | [xpra.x11.models.base](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/base.py)                   |
| `_NET_ACTIVE_WINDOW` client message      | [xpra.x11.models.base](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/base.py)                   |
| `_NET_ACTIVE_WINDOW` root property       | [xpra.x11.models.core](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/core.py)                   |
| `_NET_RESTACK_WINDOW`                    | [xpra.x11.models.base](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/base.py)                   |
| `_NET_MOVERESIZE_WINDOW`                 | [xpra.x11.models.window](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/window.py)               |
| `ConfigureRequest`                       | [xpra.x11.models.core](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/models/core.py)                   |
| supported EWMH atoms                     | [xpra.x11.common](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/common.py)                             |

The Wayland server tracks keyboard and pointer focus separately, mirroring the protocol,
and handles `xdg_activation_v1` requests in `activate_request()`:
[xpra.wayland.server.subsystem.window](https://github.com/Xpra-org/xpra/blob/master/xpra/wayland/server/subsystem/window.py).

On the client side, the win32 shim watches `WM_ACTIVATEAPP` to detect session level focus
([xpra.platform.win32.window_events](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/window_events.py))
and the macOS shim uses `activateIgnoringOtherApps:` as a focus workaround
([xpra.platform.darwin.gui](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/gui.py)).

Debugging output for all of this is available with `-d focus`.
