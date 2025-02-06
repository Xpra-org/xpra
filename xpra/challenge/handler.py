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
