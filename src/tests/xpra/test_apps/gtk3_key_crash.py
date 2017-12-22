from gi.repository import Gtk

#do_key_press_event(<Gdk.EventKey object at 0x0000000002f8f0e8 (void at 0x00000000029665a0)>) string=
#do_key_press_event(<Gdk.EventKey object at 0x0000000002f8f0e8 (void at 0x00000000029668c0)>) string=
#**
#ERROR:../../pygobject-3.26.1/gi/pygi-argument.c:1004:_pygi_argument_to_object: code should not be reached

class KeyEventWindow(Gtk.Window):

    def do_key_press_event(self, event):
        print("do_key_press_event(%s) string=%s" % (event, event.string))

    def do_key_release_event(self, event):
        print("do_key_release_event(%s) string=%s" % (event, event.string))

if __name__ == "__main__":
    w = KeyEventWindow()
    w.show()
    Gtk.main()
