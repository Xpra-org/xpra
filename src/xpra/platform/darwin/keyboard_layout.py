# coding=utf8
# @PydevCodeAnalysisIgnore
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This file is based on this gist:
# https://gist.github.com/pudquick/cff1ecdc02b4cabe5aa0dc6919d97c6d


from Foundation import NSBundle
import objc

def _get_keyboard_layouts():
    HIToolbox_bundle = NSBundle.bundleWithIdentifier_("com.apple.HIToolbox")
    HIT_functions = [
                     ('TISCreateInputSourceList','@@B'),
                     ('TISGetInputSourceProperty', '@@@'),
                    ]
    
    HIT_constants = [
                     ('kTISPropertyInputSourceType', '@'),
                     ('kTISTypeKeyboardLayout', '@'),
                     ('kTISTypeKeyboardInputMode', '@'),
                     ('kTISPropertyLocalizedName', '@'),
                     ('kTISPropertyBundleID', '@'),
                     ('kTISPropertyInputModeID', '@'),
                     ('kTISPropertyInputSourceID', '@'),
                     ('kTISPropertyLocale', '@'),
                     ('kTISPropertyKeyLayoutNumber', '@'),
                     ('kTISPropertyScriptCode', '@'),
                    ]

    objc.loadBundleFunctions(HIToolbox_bundle, globals(), HIT_functions)
    # Yes, I know it's amusing that loadBundleVariables is loading constants - ... oh, so it's just me then? k
    objc.loadBundleVariables(HIToolbox_bundle, globals(), HIT_constants)
    #silence pydev:

    # get the list of keyboard layouts
    keyboard_layouts = TISCreateInputSourceList({kTISPropertyInputSourceType: kTISTypeKeyboardLayout}, True)
    # (
    #     "<TSMInputSource 0x7ff8e9f2cc00> KB Layout: U.S. (id=0)",
    #     "<TSMInputSource 0x7ff8e9f2c5f0> KB Layout: Czech - QWERTY (id=30778)",
    #     "<TSMInputSource 0x7ff8e9f2b8c0> KB Layout: Czech (id=30776)",
    # [...]
    print("TISCreateInputSourceList keyboard_layouts=%s", keyboard_layouts)
    return keyboard_layouts

def _get_keyboard_layout_dict(layout):
    def getprop(k):
        return TISGetInputSourceProperty(layout, k)
    # Can't figure out the constant names for these ones, so we'll make 'em up
    kTISPropertyKind = u'TSMInputSourcePropertyKind'
    # <TSMInputSource 0x7ff8e9f2c5f0> KB Layout: Czech - QWERTY (id=30778)
    kind   = getprop(kTISPropertyKind)
    # u'TSMInputSourceKindKeyboardLayout'
    name   = getprop(kTISPropertyLocalizedName)
    # u'Czech - QWERTY'
    kid     = getprop(kTISPropertyKeyLayoutNumber)
    # 30778
    script = getprop(kTISPropertyScriptCode)
    # 29
    sid    = getprop(kTISPropertyInputSourceID)
    # u'com.apple.keylayout.Czech-QWERTY'
    locale = getprop(kTISPropertyLocale)
    # u'cs'
    return {
        "kind"      : kind,
        "name"      : name,
        "id"        : kid,
        "script"    : script,
        "sid"       : sid,
        "locale"    : locale,
        }

def get_keyboard_layout():
    layouts = _get_keyboard_layouts()
    if not layouts:
        return {}
    #assume the first layout is the active one...
    return _get_keyboard_layout_dict(layouts[0])

def get_keyboard_layouts():
    return [_get_keyboard_layout_dict(layout) for layout in _get_keyboard_layouts()]
