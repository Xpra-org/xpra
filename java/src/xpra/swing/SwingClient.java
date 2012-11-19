package xpra.swing;

import java.awt.Toolkit;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import xpra.InputContextClient;

public class SwingClient extends InputContextClient {

	protected Toolkit toolkit = null;

	public SwingClient(InputStream is, OutputStream os) {
		super(is, os);
	}

	@Override
	public void run(String[] args) {
		this.toolkit = Toolkit.getDefaultToolkit();
		new Thread(this).start();
	}

	@Override
	public void cleanup() {
		super.cleanup();
		this.toolkit = null;
		System.exit(0);
	}

	@Override
	public Map<String, Object> make_hello(String enc_pass) {
		Map<String, Object> caps = super.make_hello(enc_pass);
		caps.put("client_type", "Java/swing");
		return caps;
	}

	@Override
	public Object getLock() {
		return this;
	}

	@Override
	protected SwingWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		return new SwingWindow(this, id, x, y, w, h, metadata, override_redirect);
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
