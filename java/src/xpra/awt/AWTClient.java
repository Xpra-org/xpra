package xpra.awt;

import java.awt.Toolkit;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import xpra.AbstractClient;

/**
 * This is just a proof of concept and this client does not work properly at
 * present.
 * 
 */
public class AWTClient extends AbstractClient {

	protected Toolkit toolkit = null;

	public AWTClient(InputStream is, OutputStream os) {
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
	}

	@Override
	public Object getLock() {
		return this;
	}

	@Override
	protected AWTWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		return new AWTWindow(this, id, x, y, w, h, metadata, override_redirect);
	}
}
