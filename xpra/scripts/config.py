#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Compatibility imports and entry point; configuration now lives in xpra.config."""

from xpra.config import (
    InitException as InitException,
    InitExit as InitExit,
    InitInfo as InitInfo,
)
from xpra.config.__main__ import (
    main as main,
)
from xpra.config.defaults import (
    DEFAULT_BORDER as DEFAULT_BORDER,
    DEFAULT_NET_WM_NAME as DEFAULT_NET_WM_NAME,
    DEFAULT_POSTSCRIPT_PRINTER as DEFAULT_POSTSCRIPT_PRINTER,
    DEFAULT_PULSEAUDIO as DEFAULT_PULSEAUDIO,
    dict_to_validated_config as dict_to_validated_config,
    do_make_defaults_struct as do_make_defaults_struct,
    get_default_env as get_default_env,
    get_default_key_shortcuts as get_default_key_shortcuts,
    get_default_seccomp as get_default_seccomp,
    get_default_start_env as get_default_start_env,
    get_default_systemd_run as get_default_systemd_run,
    get_defaults as get_defaults,
    has_audio_support as has_audio_support,
    make_defaults_struct as make_defaults_struct,
    unexpand as unexpand,
    unexpand_all as unexpand_all,
)
from xpra.config.fixup import (
    abs_paths as abs_paths,
    csvstr as csvstr,
    csvstrl as csvstrl,
    fixup_backend as fixup_backend,
    fixup_clipboard as fixup_clipboard,
    fixup_compression as fixup_compression,
    fixup_debug_option as fixup_debug_option,
    fixup_encodings as fixup_encodings,
    fixup_keyboard as fixup_keyboard,
    fixup_options as fixup_options,
    fixup_packetencoding as fixup_packetencoding,
    fixup_pings as fixup_pings,
    fixup_socketdirs as fixup_socketdirs,
    nodupes as nodupes,
)
from xpra.config.info import (
    get_build_info as get_build_info,
)
from xpra.config.io import (
    DEBUG_CONFIG_PROPERTIES as DEBUG_CONFIG_PROPERTIES,
    DEFAULT_XPRA_CONF_FILENAME as DEFAULT_XPRA_CONF_FILENAME,
    conf_files as conf_files,
    get_xpra_defaults_dirs as get_xpra_defaults_dirs,
    may_create_user_config as may_create_user_config,
    read_config as read_config,
    read_xpra_conf as read_xpra_conf,
    read_xpra_defaults as read_xpra_defaults,
    save_config as save_config,
)
from xpra.config.paths import (
    find_docs_path as find_docs_path,
    find_html5_path as find_html5_path,
    valid_html_path as valid_html_path,
)
from xpra.config.types import (
    BIND_OPTIONS as BIND_OPTIONS,
    CLIENT_ONLY_OPTIONS as CLIENT_ONLY_OPTIONS,
    CLIENT_OPTIONS as CLIENT_OPTIONS,
    CLONES as CLONES,
    NON_COMMAND_LINE_OPTIONS as NON_COMMAND_LINE_OPTIONS,
    NO_FILE_OPTIONS as NO_FILE_OPTIONS,
    OPTIONS_ADDED_SINCE_V5 as OPTIONS_ADDED_SINCE_V5,
    OPTIONS_COMPAT_NAMES as OPTIONS_COMPAT_NAMES,
    OPTIONS_VALIDATION as OPTIONS_VALIDATION,
    OPTION_TYPES as OPTION_TYPES,
    PROXY_START_OVERRIDABLE_OPTIONS as PROXY_START_OVERRIDABLE_OPTIONS,
    START_COMMAND_OPTIONS as START_COMMAND_OPTIONS,
    URL_SAFE_OPTIONS as URL_SAFE_OPTIONS,
    XpraConfig as XpraConfig,
    dict_to_config as dict_to_config,
    name_to_field as name_to_field,
    remove_dupes as remove_dupes,
)
from xpra.config.validation import (
    do_validate_config as do_validate_config,
    parse_landlock_option as parse_landlock_option,
    split_landlock_option as split_landlock_option,
    validate_config as validate_config,
)
from xpra.config.vfb import (
    X11_DISABLED_EXTENSIONS as X11_DISABLED_EXTENSIONS,
    X11_ENABLED_EXTENSIONS as X11_ENABLED_EXTENSIONS,
    add_ext_net_dpi_fps as add_ext_net_dpi_fps,
    detect_xdummy_command as detect_xdummy_command,
    detect_xvfb_command as detect_xvfb_command,
    get_Xdummy_command as get_Xdummy_command,
    get_Xdummy_confdir as get_Xdummy_confdir,
    get_Xephyr_command as get_Xephyr_command,
    get_Xvfb_command as get_Xvfb_command,
    get_weston_Xwayland_command as get_weston_Xwayland_command,
    get_xorg_bin as get_xorg_bin,
    wrap_cmd_str as wrap_cmd_str,
    xvfb_command as xvfb_command,
)
from xpra.util.parsing import (
    FALSE_OPTIONS as FALSE_OPTIONS,
    TRUE_OPTIONS as TRUE_OPTIONS,
)


__all__ = [
    'InitException', 'InitExit', 'InitInfo', 'main', 'DEFAULT_BORDER', 'DEFAULT_NET_WM_NAME', 'DEFAULT_POSTSCRIPT_PRINTER',
    'DEFAULT_PULSEAUDIO', 'dict_to_validated_config', 'do_make_defaults_struct', 'get_default_env', 'get_default_key_shortcuts',
    'get_default_seccomp', 'get_default_start_env', 'get_default_systemd_run', 'get_defaults', 'has_audio_support', 'make_defaults_struct',
    'unexpand', 'unexpand_all', 'abs_paths', 'csvstr', 'csvstrl', 'fixup_backend', 'fixup_clipboard', 'fixup_compression',
    'fixup_debug_option', 'fixup_encodings', 'fixup_keyboard', 'fixup_options', 'fixup_packetencoding', 'fixup_pings', 'fixup_socketdirs',
    'nodupes', 'get_build_info', 'DEBUG_CONFIG_PROPERTIES', 'DEFAULT_XPRA_CONF_FILENAME', 'conf_files', 'get_xpra_defaults_dirs',
    'may_create_user_config', 'read_config', 'read_xpra_conf', 'read_xpra_defaults', 'save_config', 'find_docs_path', 'find_html5_path',
    'valid_html_path', 'BIND_OPTIONS', 'CLIENT_ONLY_OPTIONS', 'CLIENT_OPTIONS', 'CLONES', 'NON_COMMAND_LINE_OPTIONS', 'NO_FILE_OPTIONS',
    'OPTIONS_ADDED_SINCE_V5', 'OPTIONS_COMPAT_NAMES', 'OPTIONS_VALIDATION', 'OPTION_TYPES', 'PROXY_START_OVERRIDABLE_OPTIONS',
    'START_COMMAND_OPTIONS', 'URL_SAFE_OPTIONS', 'XpraConfig', 'dict_to_config', 'name_to_field', 'remove_dupes', 'do_validate_config',
    'parse_landlock_option', 'split_landlock_option', 'validate_config', 'X11_DISABLED_EXTENSIONS', 'X11_ENABLED_EXTENSIONS',
    'add_ext_net_dpi_fps', 'detect_xdummy_command', 'detect_xvfb_command', 'get_Xdummy_command', 'get_Xdummy_confdir', 'get_Xephyr_command',
    'get_Xvfb_command', 'get_weston_Xwayland_command', 'get_xorg_bin', 'wrap_cmd_str', 'xvfb_command', 'FALSE_OPTIONS', 'TRUE_OPTIONS',
]


if __name__ == "__main__":
    import sys
    main(sys.argv)
