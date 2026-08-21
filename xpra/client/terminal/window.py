# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Final
from collections.abc import Sequence

from xpra.client.gui.window_base import ClientWindowBase
from xpra.client.gui.window.backing import get_backing_client_properties
from xpra.client.terminal import graphics
from xpra.client.terminal.backing import TerminalBacking
from xpra.client.terminal.tty import TerminalOutput
from xpra.exit_codes import ExitCode
from xpra.net.packet_type import WINDOW_MAP, WINDOW_UNMAP, WINDOW_CONFIGURE
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "terminal")
geomlog = Logger("geometry")
drawlog = Logger("paint", "terminal")

# each window uses a single placement, the image id is the window id -
# or the window id plus this offset: full image retransmits alternate
# between the two ids so that the new image can be placed before the old
# one is deleted.  Retransmitting under a single id would delete the
# visible image (and its placement) first, and the screen background then
# shows through until the new image arrives and is placed: with an
# application that redraws constantly, that is a full-screen flicker on
# every update:
PLACEMENT_ID: Final[int] = 1
BACK_IMAGE_OFFSET: Final[int] = 1 << 27


def cell_position(x: int, y: int, cell_width: int, cell_height: int,
                  max_width: int = 0, max_height: int = 0) -> tuple[int, int, int, int]:
    """
    Map a pixel position within the terminal to the placement coordinates
    the kitty graphics protocol wants: a 1-based cell `(row, col)`
    and the pixel offsets within that cell.
    The position is clamped into the terminal pixel area when its size is known.
    """
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError(f"invalid cell size {(cell_width, cell_height)}")
    x = max(0, x)
    y = max(0, y)
    if max_width > 0:
        x = min(x, max_width - 1)
    if max_height > 0:
        y = min(y, max_height - 1)
    return y // cell_height + 1, x // cell_width + 1, x % cell_width, y % cell_height


class ClientWindow(ClientWindowBase):
    """
    A window rendered into the terminal as a single kitty graphics image
    (the image id is the window id), positioned with one placement.
    Everything that touches the terminal runs on the UI thread.
    """

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        # this backing can always paint with alpha, so honour the server's request:
        self._window_alpha = self._has_alpha and TerminalBacking.HAS_ALPHA
        self._mapped = False
        self._frozen = False
        self._placed = False
        # the buffer generation we last transmitted, 0 means "nothing transmitted yet":
        self._transmitted_serial = 0
        # the image id the terminal currently holds for this window,
        # 0 means "nothing transmitted yet" (see `BACK_IMAGE_OFFSET`):
        self._image_id = 0
        self._resize_counter = 0
        self._window_state: dict[str, Any] = {}
        self._transient_for = 0
        self._decorated = True
        self._modal = False
        self._role = ""
        self._title = ""
        self._icon_name = ""
        self._opacity = 1
        super().init_window(client, metadata, client_props)

    def __repr__(self):
        return f"TerminalClientWindow({self.wid:#x})"

    def get_backing_class(self) -> type:
        return TerminalBacking

    def get_size(self) -> tuple[int, int]:
        return self._size

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info |= {
            "mapped": self._mapped,
            "frozen": self._frozen,
            "placed": self._placed,
            "transmitted-serial": self._transmitted_serial,
            "z": self._client.window_z(self.wid),
        }
        return info

    def terminal_output(self) -> TerminalOutput | None:
        """ the single terminal writer, `None` when the terminal is not in graphics mode yet """
        return self._client.terminal_output

    ######################################################################
    # terminal output

    def transmit_image(self, output: TerminalOutput) -> bool:
        """ send the whole backing buffer as a new image, place it, then drop the old image """
        backing = self._backing
        if backing is None:
            return False
        bw, bh = backing.size
        if bw <= 0 or bh <= 0:
            return False
        old_id = self._image_id
        new_id = self.wid + BACK_IMAGE_OFFSET if old_id == self.wid else self.wid
        pixels = bytes(backing.pixels)
        name = self._client.shm_transfer(pixels)
        if name:
            output.write(graphics.transmit_shm(new_id, bw, bh, name))
        else:
            output.write(graphics.transmit(new_id, bw, bh, pixels))
        self._image_id = new_id
        self._transmitted_serial = backing.buffer_serial
        # the whole image has just been sent, nothing is pending:
        backing.get_damage()
        self.place_image(output)
        if old_id:
            # only deleted after the new image was placed on top of it,
            # so the window never disappears between two updates:
            output.write(graphics.delete_image(old_id))
        return True

    def place_image(self, output: TerminalOutput) -> None:
        cell_width, cell_height = self._client.cell_size()
        max_width, max_height = self._client.terminal_pixel_size()
        px, py = self._pos
        row, col, x_off, y_off = cell_position(px, py, cell_width, cell_height, max_width, max_height)
        geomlog("place_image() window %#x at %s -> cell %s offset %s", self.wid, (px, py), (row, col), (x_off, y_off))
        output.write(graphics.place(self._image_id, PLACEMENT_ID, row, col, x_off, y_off,
                                    self._client.window_z(self.wid)))
        self._placed = True

    def remove_placement(self, output: TerminalOutput) -> None:
        if not self._placed:
            return
        self._placed = False
        output.write(graphics.delete_placement(self._image_id, PLACEMENT_ID))

    def refresh_placement(self) -> None:
        """
        Make the terminal show the current buffer at the current position:
        a buffer that was never transmitted (or was reallocated) is sent in full,
        otherwise only the placement is updated.
        """
        output = self.terminal_output()
        backing = self._backing
        if output is None or backing is None or not self._mapped or self._frozen:
            return
        if self._transmitted_serial != backing.buffer_serial:
            self.transmit_image(output)
        else:
            self.place_image(output)
        output.flush()

    def after_draw_refresh(self, success, message="") -> None:
        """
        Present the whole screen update at once - this runs on the paint thread.
        The superclass schedules one refresh per draw packet, but the backing has
        already recorded a damage rectangle for each of them,
        so a single presentation covers the lot.
        """
        self.pending_refresh = []
        self.idle_add(self.present_damage)

    def present_damage(self) -> None:
        """ emit the areas painted since the last presentation - UI thread """
        backing = self._backing
        if backing is None or not self.can_write():
            # the damage stays pending until we can write to the terminal again
            return
        self.emit_updates(backing.get_damage())

    def repaint(self, x: int, y: int, w: int, h: int) -> None:
        """ present a rectangle (and anything else that is pending) - UI thread """
        backing = self._backing
        if backing is None:
            return
        backing.add_damage(x, y, w, h)
        self.present_damage()

    def redraw(self) -> None:
        """
        The superclass repaints the whole window here, to refresh the alert spinner
        this backend does not render. Re-encoding the whole buffer costs
        (up to megabytes of) terminal output for a pixel-identical result,
        and `redraw_windows()` runs at 10Hz for as long as the server is unresponsive,
        so only the damage that is actually pending is presented.
        """
        self.present_damage()

    def can_write(self) -> bool:
        return self._mapped and not self._frozen and self.terminal_output() is not None

    def emit_updates(self, rects: Sequence[Sequence[int]]) -> None:
        output = self.terminal_output()
        backing = self._backing
        if output is None or backing is None or not self._mapped or self._frozen:
            return
        shm = self._client.shm_ok
        if self._transmitted_serial != backing.buffer_serial or not (shm or self._client.frame_edits):
            # the buffer was (re)allocated so the terminal has nothing to patch,
            # or this terminal cannot patch at all (no `a=f` frame edit support
            # and no shared memory to patch through):
            if self.transmit_image(output):
                output.flush()
            return
        data = b""
        for rect in rects:
            x, y, w, h = rect
            cx, cy, cw, ch = backing.clip(x, y, w, h)
            if cw <= 0 or ch <= 0:
                continue
            pixels = backing.pixels_for(cx, cy, cw, ch)
            if shm:
                name = self._client.shm_transfer(pixels)
                if not name:
                    # shared memory just failed on us: re-send the whole image
                    # instead, the direct frame edit path may not be supported
                    if self.transmit_image(output):
                        output.flush()
                    return
                data += graphics.patch_shm(self._image_id, cx, cy, cw, ch, name)
            else:
                data += graphics.patch(self._image_id, cx, cy, cw, ch, pixels)
        drawlog("emit_updates(%s) %i bytes", rects, len(data))
        if data:
            output.write(data)
            output.flush()

    ######################################################################
    # map / unmap / destroy

    def show(self) -> None:
        self._mapped = True
        self._been_mapped = True
        if self._override_redirect:
            # the server maps override-redirect windows itself and rejects map packets for them,
            # the client properties still have to reach it somehow:
            self.send_client_properties()
        else:
            self.send_map()
            self.fit_to_terminal()
        output = self.terminal_output()
        if output is not None:
            self.transmit_image(output)
            output.flush()

    def show_all(self) -> None:
        self.show()

    def send_map(self) -> None:
        x, y = self._pos
        w, h = self._size
        props = dict(self._client_properties)
        self._client_properties = typedict()
        state = self._window_state
        self._window_state = {}
        log("map-window wid=%#x, geometry=%s, client properties=%s", self.wid, (x, y, w, h), props)
        self.send(WINDOW_MAP, self.wid, x, y, w, h, props, state)
        # the client may only give a window the focus once the server has seen it
        # mapped: focusing an unmapped window is a `BadMatch` the server swallows,
        # which leaves the X input focus on `PointerRoot`:
        self._client.window_mapped(self)

    def hide(self) -> None:
        if not self._mapped:
            return
        self._mapped = False
        output = self.terminal_output()
        if output is not None:
            self.remove_placement(output)
            output.flush()
        if not self._override_redirect:
            # the server rejects unmap packets for override-redirect windows:
            self.send(WINDOW_UNMAP, self.wid)

    def destroy(self) -> None:
        log("destroy() window %#x", self.wid)
        output = self.terminal_output()
        if output is not None:
            self.remove_placement(output)
            if self._image_id:
                output.write(graphics.delete_image(self._image_id))
            output.flush()
        self._mapped = False
        self._transmitted_serial = 0
        self._image_id = 0
        super().destroy()

    ######################################################################
    # key shortcut actions
    # (`KeyboardHelper.key_handled_as_shortcut` invokes these on the window)

    def quit(self) -> None:
        """ detach from the server: the default `#+F4:quit` shortcut lands here """
        log.info("quit shortcut: detaching")
        self._client.quit(ExitCode.OK)

    ######################################################################
    # geometry

    def is_desktop(self) -> bool:
        """ whether this window is a whole remote display (`xpra start-desktop`) """
        return self._metadata.boolget("desktop", False)

    def fit_to_terminal(self) -> None:
        """
        A desktop window is the whole remote display: ask the server to resize
        the display to match the terminal (`--resize-display` permitting) - a
        terminal cannot scroll or scale the window, anything beyond the
        terminal area would be invisible.
        The window itself is only resized when the server sends back the new
        geometry, so a server which cannot resize its display changes nothing.
        """
        if not self.is_desktop():
            return
        width, height = self._client.terminal_pixel_size()
        if width <= 0 or height <= 0 or (width, height) == tuple(self._size):
            return
        geomlog("fit_to_terminal() window %#x: asking for %s, showing %s",
                self.wid, (width, height), self._size)
        self.send(WINDOW_CONFIGURE, self.wid, {
            "geometry": (0, 0, width, height),
            "resize-counter": self._resize_counter,
        })

    def move_resize(self, x: int, y: int, w: int, h: int, resize_counter: int = 0) -> None:
        w = max(1, w)
        h = max(1, h)
        geomlog("move_resize%s window %#x", (x, y, w, h, resize_counter), self.wid)
        self._resize_counter = resize_counter
        moved = (x, y) != self._pos
        resized = (w, h) != self._size
        self._pos = (x, y)
        self._size = (w, h)
        if resized:
            self.set_backing_size(w, h)
        if moved or resized:
            self.refresh_placement()
        if self._override_redirect:
            # the server owns the geometry of override-redirect windows,
            # only the client properties are ours to send:
            self.send_client_properties()
        else:
            self.send_configure()

    def resize(self, w: int, h: int, resize_counter: int = 0) -> None:
        self.move_resize(self._pos[0], self._pos[1], w, h, resize_counter)

    def set_backing_size(self, w: int, h: int) -> None:
        backing = self._backing
        if backing is None:
            self.new_backing(w, h)
        else:
            # we never use desktop scaling, so the render size and the buffer size match:
            backing.init(w, h, w, h)
        self.update_client_properties()

    def update_client_properties(self) -> None:
        backing = self._backing
        if backing is None:
            return
        enc = self.get_subsystem("encoding")
        encoding_defaults = enc.encoding_defaults if enc else {}
        self._client_properties.update(get_backing_client_properties(backing, encoding_defaults))

    def send_configure(self) -> None:
        x, y = self._pos
        w, h = self._size
        config: dict[str, Any] = {
            "geometry": (x, y, w, h),
            "resize-counter": self._resize_counter,
        }
        if props := dict(self._client_properties):
            config["properties"] = props
            self._client_properties = typedict()
        if state := self._window_state:
            config["state"] = state
            self._window_state = {}
        geomlog("sending configure for %#x: %s", self.wid, config)
        self.send(WINDOW_CONFIGURE, self.wid, config)

    def send_client_properties(self) -> None:
        """
        Send the backing's client properties on their own, without any geometry:
        this is the only way to deliver them for override-redirect windows,
        whose map and configure geometry the server refuses.
        """
        props = dict(self._client_properties)
        if not props:
            return
        self._client_properties = typedict()
        config: dict[str, Any] = {"properties": props}
        geomlog("sending client properties for %#x: %s", self.wid, config)
        self.send(WINDOW_CONFIGURE, self.wid, config)

    def initiate_moveresize(self, x_root: int, y_root: int, direction: int, button: int,
                            source_indication: int) -> None:
        geomlog("initiate_moveresize%s is not supported by the terminal client",
                (x_root, y_root, direction, button, source_indication))

    ######################################################################
    # stacking and focus

    def present(self) -> None:
        self._client.raise_window(self.wid)
        self.refresh_placement()
        # the client owns the focus state that key events are routed with,
        # and it forwards the focus to the window subsystem:
        self._client.focus_window(self.wid)

    def restack(self, other_window, above: int = 0) -> None:
        # `other_window` is `None` when the sibling is not one of our windows:
        other_wid = other_window.wid if other_window is not None else 0
        log("restack(%s, %s) window %#x", other_window, above, self.wid)
        self._client.restack_window(self.wid, other_wid, above)
        self.refresh_placement()

    def has_toplevel_focus(self) -> bool:
        return self._client._focused == self.wid

    ######################################################################
    # suspend / resume

    def freeze(self) -> None:
        if self._frozen:
            return
        self._frozen = True
        output = self.terminal_output()
        if output is not None:
            self.remove_placement(output)
            output.flush()

    def unfreeze(self) -> None:
        if not self._frozen:
            return
        self._frozen = False
        self.refresh_placement()
        self.present_damage()

    ######################################################################
    # metadata hooks: the terminal has no window manager,
    # so most of these only have to record the value

    def update_icon(self, img) -> None:
        self._current_icon = img

    def apply_transient_for(self, wid: int) -> None:
        self._transient_for = wid

    def apply_geometry_hints(self, hints: typedict) -> None:
        """ the terminal cannot enforce size constraints, the server does it for us """

    def set_decorated(self, decorated: bool) -> None:
        self._decorated = decorated

    def get_decorated(self) -> bool:
        return self._decorated

    def set_modal(self, modal: bool) -> None:
        self._modal = modal

    def get_modal(self) -> bool:
        return self._modal

    def set_role(self, role: str) -> None:
        self._role = role

    def set_title(self, title: str) -> None:
        self._title = title

    def set_icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name

    def set_opacity(self, opacity) -> None:
        self._opacity = opacity

    def set_keep_above(self, above: bool) -> None:
        """ there is no window manager to ask """

    def set_keep_below(self, below: bool) -> None:
        """ there is no window manager to ask """

    def set_skip_taskbar_hint(self, skip: bool) -> None:
        """ the terminal has no taskbar """

    def set_skip_pager_hint(self, skip: bool) -> None:
        """ the terminal has no pager """

    def stick(self) -> None:
        """ the terminal has a single workspace """

    def unstick(self) -> None:
        """ the terminal has a single workspace """

    def maximize(self) -> None:
        """ the server decides the window size """

    def unmaximize(self) -> None:
        """ the server decides the window size """

    def iconify(self) -> None:
        self.hide()

    def deiconify(self) -> None:
        self.show()
