#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
gtk = import_gtk()

opacity = 50

def main():
    win = gtk.Window()

    win.set_title('Alpha Demo')
    win.connect('delete-event', gtk.main_quit)

    btn = gtk.Button("Change Opacity")
    def change_opacity(*args):
        global opacity
        opacity = (opacity + 5) % 100
        btn.set_label("Change Opacity: %i%%" % opacity)
        win.set_opacity(opacity/100.0)
    btn.connect('clicked', change_opacity)
    win.add(btn)
    change_opacity()

    win.show_all()
    gtk.main()
    return 0


if __name__ == '__main__':
    main()
