package xpra.gtk;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import org.gnome.gdk.Gdk;
import org.gnome.gtk.Gtk;

import xpra.AbstractClient;

/**
 * This is just a proof of concept and this client does not work properly at
 * present.
 * 
 */
public class GtkClient extends AbstractClient {

	public GtkClient(InputStream is, OutputStream os) {
		super(is, os);
	}

	@Override
	public void run(String[] args) {
		Gtk.init(args);
		new Thread(this).start();
		Gtk.main();
	}

	@Override
	public void cleanup() {
		super.cleanup();
		Gtk.mainQuit();
	}

	@Override
	public Object getLock() {
		return Gdk.lock;
	}

	@Override
	protected GtkWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		GtkWindow window = new GtkWindow(this, id, x, y, w, h, metadata, override_redirect);
		window.showAll();
		window.present();
		return window;
	}
}
