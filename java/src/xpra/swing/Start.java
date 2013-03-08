package xpra.swing;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

import xpra.AbstractClient;

/**
 * This is just a proof of concept and this client does not work properly at
 * present.
 *
 */
public class Start extends xpra.Start {

	public static void main(String[] args) throws IOException {
		new Start().run(args);
	}

	@Override
	public AbstractClient makeClient(InputStream is, OutputStream os) {
		return new SwingClient(is, os);
	}
}
