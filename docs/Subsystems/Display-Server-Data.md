# Display Server Data Inventory

This document inventories the non-framebuffer data that Xpra can retrieve from
a display server or its associated desktop-session services.

The inventory covers all supported platforms and distinguishes data that is:

* **F**: forwarded to clients,
* **I**: consumed internally, or
* **Q**: exposed through capabilities, status, or info.

Availability depends on the platform, server mode, configuration, and optional
display-server extensions.

## Window and Surface Metadata - X11

**F / I / Q**

For each managed, override-redirect, or tray window:

* Identity and hierarchy:
  * XID, parent, and children,
  * transient-for and group-leader references,
  * override-redirect, input-only, and map state,
  * stacking sibling and order.
* Geometry:
  * position, size, border width, and depth,
  * requested position and size,
  * absolute position,
  * configure masks and gravity.
* Process identity:
  * XRes PID and `_NET_WM_PID`,
  * parent PID,
  * client machine or hostname.
* Application identity:
  * title and icon title,
  * `WM_CLASS` class and instance,
  * role, locale, and command,
  * application ID where available.
* Window-manager semantics:
  * window type and workspace,
  * protocols such as delete-window and take-focus,
  * allowed actions and current state atoms,
  * fullscreen, maximized, shaded, and sticky,
  * above, below, and modal,
  * skip-taskbar and skip-pager,
  * urgency or attention, focusability, and focused state,
  * iconic or minimized state.
* Presentation hints:
  * opacity and opaque regions,
  * compositor-bypass hint,
  * decorations and Motif hints,
  * fullscreen monitor assignment,
  * struts and reserved desktop areas,
  * content type,
  * requested Xpra encoding, quality, and speed.
* Size constraints:
  * minimum, maximum, and base size,
  * resize increments,
  * minimum and maximum aspect ratios,
  * position, size, and gravity hints.
* Shapes:
  * bounding, clipping, and input-shape extents,
  * rectangle lists for each shape type,
  * shape serial and change events.
* Window icons:
  * width, height, and BGRA bytes,
  * potentially multiple icon sizes from `_NET_WM_ICON`.
* Arbitrary synchronized X11 properties:
  * property name,
  * X11 type,
  * format: 8, 16, or 32 bits,
  * scalar, list, or raw value.

The current arbitrary-property blocklist excludes the usual `_GTK`, `WM_`,
`_NET`, and `Xdnd` prefixes. Other properties may be forwarded when property
synchronization is negotiated.

The protocol metadata surface is summarized in
[`xpra/server/window/metadata.py`](../../xpra/server/window/metadata.py), with
the X11 sources defined in
[`xpra/x11/models/core.py`](../../xpra/x11/models/core.py),
[`xpra/x11/models/base.py`](../../xpra/x11/models/base.py), and
[`xpra/x11/models/window.py`](../../xpra/x11/models/window.py).

## Window-System Events

**Mostly I; selected results become F**

Core X11 events and their associated fields:

* create, destroy, map, unmap, and reparent,
* map and configure requests,
* configure and resize notifications,
* circulate and restack,
* property changes: window, atom, and timestamp,
* focus-in and focus-out: mode and detail,
* enter, leave, and pointer motion:
  * local and root coordinates,
  * root and subwindow,
  * button and modifier state,
  * focus, mode, detail, and timestamp,
* key press: hardware keycode and modifier state,
* client messages: message type, format, and 8, 16, or 32-bit payload,
* selection request, notify, and clear,
* input and window grabs and ungrabs,
* window bells.

Extension events:

* XDamage: damage handle, level, `more` flag, and rectangle,
* XShape changes,
* XFixes cursor and selection-owner changes,
* RandR screen changes,
* XKB bell notifications,
* Present configure, complete, and idle events, including serial, UST/MSC
  timing, mode, pixmap, and fence,
* optional XRecord request interception, including grab, key, and pointer
  request opcodes and arguments.

XRecord interception is diagnostic tooling rather than normal session
forwarding. These events otherwise drive window lifecycle, metadata, refresh,
clipboard, cursor, and bell packets. The raw event parsers are in
[`xpra/x11/bindings/events.pyx`](../../xpra/x11/bindings/events.pyx).

## Cursor and Pointer Data

**F / I / Q**

Common cursor packet data:

* width and height,
* hotspot coordinates,
* stable serial or identifier,
* cursor name, if provided,
* cursor RGBA or BGRA bitmap bytes,
* default and maximum cursor sizes,
* whether the current cursor matches the default,
* cursor visibility or absence.

Pointer data:

* absolute screen position,
* position relative to a shadow window or monitor,
* current button or modifier mask where supplied by the backend.

Backend-specific sources:

* **X11/XFixes:** cursor position, dimensions, hotspot, XFixes serial,
  atom or name, and ARGB image.
* **Windows:** `CURSORINFO` visibility, screen position, and `HCURSOR`;
  `ICONINFO/EX` hotspot, bitmap properties, module or resource name, and
  resource ID.
* **macOS:** current `NSCursor`, logical image size, selected bitmap
  representation, CGImage dimensions, hotspot, and derived serial.
* **EVDI:** cursor-set and cursor-move events containing enabled state,
  hotspot, dimensions, pixel format, stride, buffer length or data, and
  coordinates. The current EVDI handlers do not forward all of this.
* **Wayland portal/PipeWire:** no independent compositor cursor stream is
  currently implemented in this tree.

Cursor packet construction is visible in
[`xpra/server/source/cursor.py`](../../xpra/server/source/cursor.py). Windows
and macOS acquisition are in
[`xpra/platform/win32/shadow/cursor.py`](../../xpra/platform/win32/shadow/cursor.py)
and
[`xpra/platform/darwin/shadow_cursor.py`](../../xpra/platform/darwin/shadow_cursor.py).

## Display, Screen, and Monitor Topology

**F / I / Q**

Common data:

* display name and address,
* root or desktop size and maximum supported size,
* bit depth and alpha capability,
* DPI and X/Y DPI,
* refresh rate,
* monitor count and primary monitor,
* per-monitor:
  * connector or plug name,
  * manufacturer and model,
  * pixel geometry and workarea,
  * physical dimensions,
  * scale factor,
  * refresh rate,
  * subpixel layout,
  * color depth and HDR capability where supported.

X11/RandR adds:

* RandR version and resource timestamps,
* available screen sizes in pixels and millimetres,
* minimum and maximum screen size,
* modes:
  * mode ID and name,
  * width and height,
  * dot clock,
  * horizontal and vertical timing and sync values,
  * skew, flags, and calculated refresh,
* outputs:
  * ID and name,
  * connected state,
  * physical dimensions and subpixel order,
  * preferred modes, current modes, and clones,
  * associated CRTC,
* output properties:
  * property name or atom,
  * actual type and format,
  * integer, cardinal, atom, or byte values,
  * EDID and `non-desktop` property,
* CRTCs:
  * position and size,
  * outputs and possible outputs,
  * mode and rotations,
  * red, green, and blue gamma arrays,
* RandR monitors:
  * name, index, primary and automatic flags,
  * geometry, physical size, and output list.

The base capabilities expose root size, maximum size, display identity, depth,
DPI, and refresh rate in
[`xpra/server/subsystem/display.py`](../../xpra/server/subsystem/display.py).

## Desktop and Root-Window State

**F / I / Q**

X11 root properties:

* current desktop or workspace,
* number and names of desktops,
* desktop geometry and viewport,
* workarea for every desktop,
* window-manager identity,
* `_NET_SUPPORTED` capabilities,
* root size,
* supporting-WM window,
* XKB rules property,
* `RESOURCE_MANAGER` contents, including Xft-related settings,
* ICC profile bytes, source, and version.

XSettings:

* selection owner,
* global settings serial,
* setting type: integer, string, or color,
* setting name and value,
* per-setting last-change serial.

The root-property readers are in
[`xpra/x11/xroot_props.py`](../../xpra/x11/xroot_props.py), including ICC and
Xresources data.

## Keyboard and Input-Device Configuration

**Mostly I / Q**

X11/XKB data:

* extension availability and version,
* rules, model, layout, variant, and options,
* active layout group,
* minimum and maximum keycodes,
* keycode-to-keysyms or keynames mappings,
* keysym-to-groups or keycodes mappings,
* modifier map and modifier masks,
* maximum keys per modifier,
* currently pressed keycodes and corresponding keysyms,
* key repeat rate and delay,
* mapping and layout-change events.

XI2 data:

* XI version,
* device ID, name, use, attachment, and enabled state,
* button classes: button count, labels, and state,
* key classes: key count and keycodes,
* valuator classes:
  * number, label, minimum, maximum, and current value,
  * resolution and relative or absolute mode,
* scroll classes: valuator number, orientation or type, increment, and flags,
* touch classes: touch mode and supported touch count,
* arbitrary device properties: name, type, format, and value or raw bytes,
* device, raw-motion, and hierarchy events:
  * device, detail, and flags,
  * root and local coordinates,
  * valuators and raw valuators,
  * buttons and modifier or group state,
  * hierarchy flags.

This data is primarily used to establish and diagnose input mappings. Normal
remote keyboard and pointer actions originate from the Xpra client, so those
client-originated events are outside this server-data inventory.

## Clipboard and Selections

**F / I / Q**

Protocol-level data:

* selection name: `CLIPBOARD`, `PRIMARY`, or `SECONDARY`,
* ownership and token changes,
* available targets, MIME types, or atoms,
* requested target,
* data type and 8, 16, or 32-bit format,
* wire encoding: bytes, integers, or atoms,
* clipboard contents,
* request ID and pending-request state,
* claim, greedy, synchronous, and want-targets flags,
* direction and enabled state,
* truncation indication,
* X11 timestamps and selection properties,
* X11 INCR type, declared length, and chunks.

Native formats include:

* plain and UTF-8 text,
* HTML,
* URI lists,
* PNG, JPEG, and TIFF images,
* X11 atoms and arbitrary supported selection types,
* Windows `CF_UNICODETEXT`, `CF_TEXT`, `CF_OEMTEXT`, `CF_DIBV5`, registered
  PNG or JPEG, `CF_HDROP` file paths, and `HTML Format`,
* macOS pasteboard type list, change count, NSString or text, HTML, URL, and
  image representations,
* Windows owner HWND, native format IDs or names, and clipboard-update
  messages.

The generic clipboard packet schema is implemented in
[`xpra/clipboard/core.py`](../../xpra/clipboard/core.py).

## Desktop Notifications

**F / Q**

The Linux/POSIX notification forwarder receives:

* D-Bus session identifier or address,
* notification ID and replacement ID,
* application name,
* application icon name or path,
* summary and body,
* action key or label sequence,
* expiry timeout,
* hints:
  * action-icons,
  * category,
  * desktop-entry,
  * resident,
  * transient,
  * urgency,
  * X and Y coordinates,
* image hints:
  * width, height, and rowstride,
  * alpha flag, bits per pixel, and channel count,
  * image bytes,
  * normalized application-icon image data,
* active notification IDs and notification counter,
* close events.

Client action invocation and close responses travel in the opposite direction.
The received D-Bus schema is explicit in
[`xpra/dbus/notifications.py`](../../xpra/dbus/notifications.py).

Xpra does not capture arbitrary session-bus traffic. Notifications, portal
responses, and power-related signals are the specific subscribed D-Bus
channels.

## Session Audio

**F / I / Q**

Server speaker or monitor capture provides:

* encoded audio payload,
* codec and codec description,
* container or muxer description,
* stream sequence,
* start-of-stream and end-of-stream state,
* buffer presentation timestamp and duration,
* monotonic send time,
* calculated timestamp and latency,
* optional stream-compression method,
* codec or header packet metadata,
* buffer and byte counters,
* pipeline state, volume, and bitrate,
* encoder latency and AV-sync delay,
* keepalive timestamps,
* GStreamer version, plugins, muxers, and demuxers,
* available source or sink plugins and codecs,
* PulseAudio server, ID or cookie, selected monitor device, and device
  properties.

Audio buffer metadata originates in
[`xpra/audio/src.py`](../../xpra/audio/src.py) and is forwarded in
[`xpra/server/source/audio.py`](../../xpra/server/source/audio.py). Client
microphone input is excluded because it does not originate from the server
desktop.

## Menus, Application Entries, and Tray Data

**F / I / Q**

XDG menu and desktop-session entries:

* category or menu name, generic name, and comment,
* path and icon name,
* entry type and version string,
* display and hidden restrictions,
* `OnlyShowIn` and `NotShowIn`,
* `Exec`, resolved command, `TryExec`, and working directory,
* terminal flag,
* MIME types and categories,
* startup notification and startup WM class,
* URL,
* icon type, icon file, and icon bytes,
* nested menu, category, and entry structure,
* menu-directory change events.

The exported fields are listed in
[`xpra/platform/posix/menu_helper.py`](../../xpra/platform/posix/menu_helper.py).

X11 system-tray retrieval includes:

* tray selection owner and state,
* tray window XID,
* title, geometry, depth, and visual,
* XEmbed messages and state,
* tray icon or window metadata and lifecycle events.

## Wayland Portal and PipeWire Metadata

**Mostly I / Q; source or window descriptions become F**

Portal responses:

* response code and result dictionary,
* session handle, object path, and token,
* selected device or source state,
* number and type of available input devices,
* stream list,
* per-stream PipeWire node ID and portal property dictionary,
* source position, size, and source type where supplied,
* PipeWire remote file descriptor.

PipeWire stream and frame descriptors:

* stream state and error message,
* SPA format ID and name,
* width and height,
* DRM format and modifier,
* memory versus DMA-BUF buffer type,
* plane count and file descriptors,
* per-plane stride and offset,
* chunk offset, size, and maximum buffer size,
* buffer lease and release state,
* frame counter and pixel-format descriptor.

The portal response path is in
[`xpra/platform/posix/fd_portal_shadow.py`](../../xpra/platform/posix/fd_portal_shadow.py),
and native frame descriptors are constructed in
[`xpra/codecs/pipewire/_native.pyx`](../../xpra/codecs/pipewire/_native.pyx).

## Native Shadow-Platform Data

**F / I / Q**

### Windows

* Monitor handles and `GetMonitorInfo` dictionaries:
  * device name,
  * monitor rectangle,
  * work rectangle,
  * flags.
* Desktop or session name, display size, color depth, and DPI.
* Visible top-level window enumeration:
  * HWND,
  * title and title length,
  * PID and thread ID,
  * rectangle and visibility.
* Visible-window rectangles used as seamless shadow shapes.
* Display-change messages.
* Virtual-display-driver status, slot, and current display name.
* DXGI output index, position, size, format, and depth.
* DXGI accumulated-frame count.
* D3D adapter description, vendor, device, subsystem, revision, LUID, and
  video, system, or shared memory sizes.
* NvFBC status, output IDs, names or boxes, screen size, version, capture
  availability, and frame ID or new-frame state.

### macOS

* Active and online display IDs.
* Main, built-in, active, online, asleep, mirroring, and stereo state.
* Display bounds and logical or pixel size.
* Unit, vendor, model, and serial IDs.
* Rotation and physical size.
* Current and available modes:
  * dimensions, refresh, and pixel encoding,
  * mode ID, I/O flags, and desktop usability.
* Color-space name, model, and components.
* ICC data and wide-gamut or output support.
* OpenGL acceleration.
* Scale factor, depth, and HDR or EDR capability.
* `NSScreen` frames and workareas.
* Screen-capture display ID, frame count, and dropped-frame count.

### Linux EVDI

* Device presence and status.
* Mode dimensions, refresh, bits per pixel, and pixel format.
* DPMS and CRTC state changes.
* Damage rectangle lists.
* Cursor-set and cursor-move events.
* DDC/CI address, flags, and raw buffer.

## Session Lifecycle and Settings Services

**Mostly I; selected events become F notifications or server events**

* D-Bus session PID, address, window ID, and environment.
* Suspend and resume state from:
  * UPower `Sleeping` and `Resuming`,
  * logind `PrepareForSleep`,
  * GNOME ScreenSaver `ActiveChanged`,
  * Windows power broadcasts,
  * Windows screensaver-running state,
  * macOS display-sleep state and workspace notifications.
* GSettings:
  * schema and key names selected for synchronization,
  * original GVariant values,
  * current values and server defaults.
* Display availability and accessibility state.
* Window-manager name, used as a possible shadow-session name.

POSIX signal subscriptions are shown in
[`xpra/platform/posix/events.py`](../../xpra/platform/posix/events.py).

## Capability and Diagnostic-Only Display Data

**Q / I**

* X server protocol version or revision, vendor, and release.
* Extension availability, versions, opcodes, and event or error bases.
* Default or RGBA visuals and depth.
* Input-focus window and revert mode.
* Selection-owner XIDs.
* X server timestamp.
* Composite overlay or pixmap IDs and Damage handles.
* Present capabilities.
* OpenGL:
  * GL and GLU version,
  * vendor, renderer, and shading-language version,
  * extension list,
  * maximum texture and viewport sizes,
  * framebuffer and function availability.
* Capture backend name, state, frame counters, format or layout, and device
  identifiers.
* GTK display-backend capabilities and enumerated GDK devices.

## Scope Boundary

Included despite containing bitmap data:

* cursor images,
* window icons,
* notification icons,
* menu and application icons,
* clipboard image formats.

Excluded:

* screen and window framebuffer pixels,
* encoded screen or video updates derived from those pixels,
* client-originated microphone and webcam content,
* client keyboard and pointer input,
* printing payloads,
* requested file transfers,
* generic control commands and network or session authentication data.
