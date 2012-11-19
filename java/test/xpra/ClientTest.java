package xpra;

import java.awt.Toolkit;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.util.Map;

import org.junit.Test;

public class ClientTest extends AbstractTest {

	@Test
	public void testHello() {
		ByteArrayOutputStream baos = new ByteArrayOutputStream();
		TestClient client = new TestClient("fail!", baos);
		client.send_hello("ba59e4110119264f4a6eaf3adc075ea2c5408550");
		byte[] out = baos.toByteArray();
		this.log("testHello() hello=" + new String(out));
	}

	public void testHMAC() {
		TestClient client = new TestClient("fail!", new ByteArrayOutputStream());
		client.password = "71051d81d27745b59c1c56c6e9046c19697e452453e04aa5abbd52c8edc8c232".getBytes();
		// =5eade98226dfec56fbe92e5b08530264d59c6db2
		String salt = "99ea464f-7117-4e38-95b3-d3aa80e7b806";
		String hmac_enc = client.hmac_password(salt);
		this.log("testHMAC() hmac_enc=" + hmac_enc);
	}

	public static void main(String[] args) {
		run(ClientTest.class);
	}

	public static class TestClient extends InputContextClient {

		public TestClient(String in, OutputStream os) {
			super(new ByteArrayInputStream(in.getBytes()), os);
		}

		/*
		 * public byte[] getOutput() { return ((ByteArrayOutputStream)
		 * this.outputStream).toByteArray(); }
		 */

		@Override
		public int getScreenWidth() {
			return 480;
		}

		@Override
		public int getScreenHeight() {
			return 800;
		}

		@Override
		protected ClientWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
			this.log("createWindow(..)");
			return null;
		}

		@Override
		public void run(String[] args) {
			new TestClient("hello", new ByteArrayOutputStream()).run();
		}

		@Override
		public Object getLock() {
			return this;
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
}
