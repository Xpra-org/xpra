# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from abc import ABCMeta, abstractmethod


class AuthenticationHandler(metaclass=ABCMeta):

    @abstractmethod
    def get_digest(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def handle(self, challenge: bytes, digest: str, prompt: str):
        raise NotImplementedError()


def notify(*messages: str, timeout=10 * 1000) -> None:
    from xpra.log import Logger
    log = Logger("auth")
    for message in messages:
        log.info(message)

    try:
        from xpra.constants import NotificationID
        from xpra.platform.paths import get_icon_filename
        from xpra.client.subsystem import notification
        from xpra.notification.common import parse_image_path
    except ImportError as e:
        log("fido2 cannot show notification: %s", e)
        return
    notifier = notification.notifier
    log("notifier=%s", notifier)
    if not notifier:
        return
    try:
        icon_filename = get_icon_filename("authentication.png")
        icondata = parse_image_path(icon_filename)
        log("IconData(%s)=%s", icon_filename, icondata)
        notifier.show_notify("", None, NotificationID.AUTHENTICATION,
                             "Xpra", 0, "authentication.png",
                             "Fido2 Authentication", "\n".join(messages),
                             actions=(), hints={},
                             timeout=timeout, icon=icondata)
    except Exception as e:
        log("fido2 failed to show notification: %s", e)
