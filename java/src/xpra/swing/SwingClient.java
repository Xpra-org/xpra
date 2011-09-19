package xpra.swing;

import java.awt.Toolkit;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import xpra.AbstractClient;

public class SwingClient extends AbstractClient {

	protected	Toolkit toolkit = null;

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
	public Object	getLock() {
		return	this;
	}
	
    @Override
	protected SwingWindow createWindow(int id, int x, int y, int w, int h, Map<String,Object> metadata, boolean override_redirect) {
    	return	new SwingWindow(this, id, x, y, w, h, metadata, override_redirect);
    }
}
