package xpra.awt;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

import xpra.AbstractClient;

public class Start extends xpra.Start {

	public static void main(String[] args) throws IOException {
		new Start().run(args);
	}

	@Override
	public AbstractClient makeClient(InputStream is, OutputStream os) {
		return new AWTClient(is, os);
	}
}
