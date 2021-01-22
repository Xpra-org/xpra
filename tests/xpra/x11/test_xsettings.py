#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
import gtk

from xpra.x11.xsettings import XSettingsManager, XSettingsWatcher

class TestXSettings(TestWithSession):

    def test_basic_set_get(self):
        blob = "asdfwheeeee"
        manager = XSettingsManager()
        manager.set_settings(blob)
        watcher = XSettingsWatcher()
        assert watcher.get_settings() == blob

    def test_watching(self):
        blob1 = "blob1"
        manager1 = XSettingsManager()
        manager1.set_settings(blob1)
        watcher = XSettingsWatcher()
        assert watcher.get_settings() == blob1
        blob2 = "blob2"
        manager2 = XSettingsManager()
        manager2.set_settings(blob2)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings() == blob2
        # It's likely that (due to how the GTK+ clipboard code works
        # underneath) all of the managers that we create within a single
        # process are actually using the same selection window, and thus the
        # previous tests could work right even if we only watch for
        # PropertyNotify *or* only watch for selection owner changes.
        # Test where the property change but no manager change message
        # is sent:
        blob3 = "blob3"
        manager2.set_settings(blob3)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings() == blob3
        # Test where the property does not change, but a manager change
        # message is sent:
        manager3 = XSettingsManager()
        manager3.set_settings(blob3)
        assert_mainloop_emits(watcher, "xsettings-changed")
        assert watcher.get_settings() == blob3

