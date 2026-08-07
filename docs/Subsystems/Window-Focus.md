# X11 Focus

There are four independent things which are all called "focus" in X11, plus a set of
protocols layered on top of them.
They are easily conflated because a window manager normally changes all of them together.

This page is background material for the [window subsystem](Window.md): the server side
of xpra is a window manager, and the `window-focus` packet it receives from the client
has to be translated into all of the mechanisms below.


## Keyboard focus

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


## Pointer focus

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
These two behave differently, notably with respect to grabs and to windows which decline
focus.

See also the [pointer subsystem](Pointer.md).


## ICCCM: does the client even want the focus?

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


## Stacking order

Raising a window does **not** focus it, and focusing a window does not raise it.
Those couplings are window manager policy.

### `XRaiseWindow` and `XConfigureWindow`

A direct request from the client.
For a _managed_, reparented top-level window this usually does nothing useful: the client's
window is a child of the window manager's frame, so raising it only reorders it within that
frame. And if the window manager has selected `SubstructureRedirectMask` on the parent, the
request is intercepted rather than executed.

### `ConfigureRequest`

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

### `_NET_RESTACK_WINDOW`

The EWMH replacement for the above: a `ClientMessage` sent to the root window with
`data = [source_indication, sibling_window, detail]`.
It is meant for pagers and taskbars.
It exists precisely because `ConfigureRequest` lacks the source indication, and because
clients should not be reordering themselves without a reason.

### `_NET_MOVERESIZE_WINDOW`

The same idea for geometry: a root window client message with gravity, source indication
and x / y / width / height, so that the window manager knows who asked and can apply the
correct gravity.


## `_NET_ACTIVE_WINDOW`

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


## How it all composes

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


## How xpra uses this

The xpra server is a window manager
([xpra.x11.wm](https://github.com/Xpra-org/xpra/blob/master/xpra/x11/wm.py))
whose "user" is a remote client.
Focus decisions arrive over the wire as a `window-focus` packet, and
`WindowModel.give_client_focus()` replays them into the X11 session using the ICCCM rules
above, whilst the real keyboard focus on the client's own display is managed by whatever
window manager is running there.

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

Debugging output for all of this is available with `-d focus`.
