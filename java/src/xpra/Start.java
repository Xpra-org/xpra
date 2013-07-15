package xpra;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;

public abstract class Start {

	public static final String DEFAULT_HOST = "localhost";
	public static final int DEFAULT_PORT = 10000;

	public void run(String[] args) throws IOException {
		Socket socket = null;
		try {
			socket = new Socket(DEFAULT_HOST, DEFAULT_PORT);
			socket.setKeepAlive(true);
			InputStream is = socket.getInputStream();
			OutputStream os = socket.getOutputStream();
			this.makeClient(is, os).run(args);
		}
		finally {
			if (socket!=null)
				socket.close();
		}
	}

	public abstract AbstractClient makeClient(InputStream is, OutputStream os);
}
