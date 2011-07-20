#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
import gtk

from xpra.xposix.xsettings import XSettingsManager, XSettingsWatcher

class TestXSettings(TestWithSession):
    def test_basic_set_get(self):
        blob = "asdfwheeeee"
        manager = XSettingsManager(blob)
        watcher = XSettingsWatcher()
        assert watcher.get_settings_blob() == blob

    def test_watching(self):
        blob1 = "blob1"
        manager1 = XSettingsManager(blob1)
        watcher = XSettingsWatcher()
        assert watcher.get_settings_blob() == blob1
        blob2 = "blob2"
        manager2 = XSettingsManager(blob2)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings_blob() == blob2
        # It's likely that (due to how the GTK+ clipboard code works
        # underneath) all of the managers that we create within a single
        # process are actually using the same selection window, and thus the
        # previous tests could work right even if we only watch for
        # PropertyNotify *or* only watch for selection owner changes.
        # Test where the property change but no manager change message
        # is sent:
        blob3 = "blob3"
        manager2._set_blob_in_place(blob3)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings_blob() == blob3
        # Test where the property does not change, but a manager change
        # message is sent:
        manager3 = XSettingsManager(blob3)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings_blob() == blob3

