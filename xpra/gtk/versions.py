from typing import Any


GTK_VERSION_INFO : dict[str,dict[str,tuple]] = {}


def get_gtk_version_info() -> dict[str,Any]:
    import gi
    gi.require_version("Gdk", "3.0")  # @UndefinedVariable
    gi.require_version("Gtk", "3.0")  # @UndefinedVariable
    gi.require_version("Pango", "1.0")  # @UndefinedVariable
    gi.require_version("GdkPixbuf", "2.0")  # @UndefinedVariable
    from gi.repository import GLib, GdkPixbuf, Pango, GObject, Gtk, Gdk
    from xpra.util.version import parse_version

    #update props given:
    global GTK_VERSION_INFO
    def av(k, v):
        GTK_VERSION_INFO[k] = parse_version(v)
    def V(k, module, attr_name):
        v = getattr(module, attr_name, None)
        if v is not None:
            av(k, v)
            return True
        return False

    if not GTK_VERSION_INFO:
        V("gobject",    GObject,    "pygobject_version")
        #this isn't the actual version, (only shows as "3.0")
        #but still better than nothing:
        V("gi",         gi,         "__version__")
        V("gtk",        Gtk,        "_version")
        V("gdk",        Gdk,        "_version")
        V("gobject",    GObject,    "_version")
        V("pixbuf",     GdkPixbuf,     "_version")
        V("pixbuf",     GdkPixbuf,     "PIXBUF_VERSION")
        def MAJORMICROMINOR(name, module):
            try:
                v = tuple(getattr(module, x) for x in ("MAJOR_VERSION", "MICRO_VERSION", "MINOR_VERSION"))
                av(name, ".".join(str(x) for x in v))
            except Exception:
                pass
        MAJORMICROMINOR("gtk",  Gtk)
        MAJORMICROMINOR("glib", GLib)
        import cairo
        av("cairo", parse_version(cairo.version_info))  #pylint: disable=no-member
        av("pango", parse_version(Pango.version_string()))
    return GTK_VERSION_INFO.copy()
