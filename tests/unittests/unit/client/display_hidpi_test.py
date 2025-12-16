#!/usr/bin/env python3

import unittest

from xpra.client.subsystem.display import get_platform_default_scaling


class TestDisplayHidpi(unittest.TestCase):

    def test_osx_hidpi_default_scaling_applied_for_on(self) -> None:
        assert get_platform_default_scaling(
            osx=True,
            enabled=True,
            desktop_scaling_opt="on",
            display_scale_factor=2.0,
        ) == (0.5, 0.5)

    def test_osx_hidpi_default_scaling_not_applied_for_explicit_value(self) -> None:
        assert get_platform_default_scaling(
            osx=True,
            enabled=True,
            desktop_scaling_opt="0.5",
            display_scale_factor=2.0,
        ) is None

    def test_osx_hidpi_default_scaling_not_applied_for_scale_1(self) -> None:
        assert get_platform_default_scaling(
            osx=True,
            enabled=True,
            desktop_scaling_opt="on",
            display_scale_factor=1.0,
        ) is None

    def test_osx_hidpi_default_scaling_can_be_disabled(self) -> None:
        assert get_platform_default_scaling(
            osx=True,
            enabled=False,
            desktop_scaling_opt="on",
            display_scale_factor=2.0,
        ) is None

    def test_osx_hidpi_default_scaling_uses_inverse(self) -> None:
        assert get_platform_default_scaling(
            osx=True,
            enabled=True,
            desktop_scaling_opt="on",
            display_scale_factor=1.5,
        ) == (2.0 / 3.0, 2.0 / 3.0)


def main() -> None:
    unittest.main()


if __name__ == '__main__':
    main()
