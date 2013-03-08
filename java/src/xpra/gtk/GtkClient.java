package xpra.gtk;

import java.awt.Toolkit;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import org.gnome.gdk.Gdk;
import org.gnome.gtk.Gtk;

import xpra.InputContextClient;

/**
 * This is just a proof of concept and this client does not work properly at
 * present.
 *
 */
public class GtkClient extends InputContextClient {

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
	public Map<String, Object> make_hello(String enc_pass) {
		Map<String, Object> caps = super.make_hello(enc_pass);
		caps.put("client_type", "Java/Gtk");
		return caps;
	}

	@Override
	protected GtkWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		GtkWindow window = new GtkWindow(this, id, x, y, w, h, metadata, override_redirect);
		window.showAll();
		window.present();
		return window;
	}

	@Override
	protected void process_bell(int wid, int device, int percent, int pitch, int duration, String bell_class, int bell_id, String bell_name) {
		Toolkit.getDefaultToolkit().beep();
	}

	@Override
	protected void process_notify_show(int dbus_id, int nid, String app_name, int replaced_id, String app_icon, String summary, String body, int expire_timeout) {
		//Not implemented
	}

	@Override
	protected void process_notify_close(int nid) {
		//Not implemented
	}
}
