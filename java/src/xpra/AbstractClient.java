package xpra;

import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.lang.reflect.Method;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Vector;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.ardverk.coding.BencodingInputStream;
import org.ardverk.coding.BencodingOutputStream;

/**
 * Abstract utility superclass for all Xpra client implementations.
 * 
 */
public abstract class AbstractClient implements Runnable, Client {

	public static final String[] ENCODINGS = new String[] { "png", "jpeg" };
	public static final String VERSION = "0.1.0";
	public static boolean DEBUG = false;

	protected boolean ended = false;
	protected boolean exit = false;
	protected Runnable onExit = null;
	protected InputStream inputStream = null;
	protected OutputStream outputStream = null;
	protected Map<String, Method> handlers = new HashMap<String, Method>(HANDLERS.length);

	protected String encoding = "png";
	protected int jpeg = 40;
	protected byte[] password = null;
	protected int hellosSent = 0;

	protected Map<Integer, ClientWindow> id_to_window = new HashMap<Integer, ClientWindow>();
	protected int focused = -1;

	protected String remote_version = null;

	public static String[] HANDLERS = { "challenge", "disconnect", "hello", "new-window", "new-override-redirect", "draw", "window-metadata",
			"configure-override-redirect", "lost-window" };

	public AbstractClient(InputStream is, OutputStream os) {
		this.inputStream = is;
		this.outputStream = new BufferedOutputStream(os);
		this.registerHandlers();
	}

	public void setOnExit(Runnable r) {
		this.onExit = r;
	}

	public void registerHandlers() {
		Method[] methods = this.getClass().getMethods();
		Method[] abMethods = AbstractClient.class.getDeclaredMethods();

		log("registerHandlers() methods=" + Arrays.asList(methods));
		for (String h : HANDLERS) {
			String methodName = "process_" + h.replaceAll("-", "_");
			try {
				Method m = null;
				// try actual class
				for (Method t : methods)
					if (t.getName().equals(methodName)) {
						m = t;
						break;
					}
				// try AbstractClient
				if (m == null)
					for (Method t : abMethods)
						if (t.getName().equals(methodName)) {
							m = t;
							break;
						}
				if (m == null)
					throw new IllegalArgumentException("cannot find method " + methodName + " on " + this.getClass());
				this.handlers.put(h, m);
			} catch (Exception e) {
				throw new IllegalStateException("cannot find method " + methodName, e);
			}
		}
	}

	public void setPassword(byte[] password) {
		this.password = password;
	}

	public void stop() {
		this.exit = true;
		this.send_disconnect();
	}

	public boolean hasEnded() {
		return this.ended;
	}

	public void debug(String str) {
		if (DEBUG)
			System.out.println(this.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
	}

	public void log(String str) {
		System.out.println(this.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
	}

	public void error(String str, Throwable t) {
		System.out.println(this.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
		if (t != null)
			t.printStackTrace(System.out);
	}

	protected abstract ClientWindow createWindow(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect);

	public abstract void run(String[] args);

	public abstract Object getLock();

	@Override
	public void run() {
		this.send_hello(null);
		int headerSize = 0;
		int packetSize = 0;
		ByteArrayOutputStream readBuffer = null;
		byte[] header = new byte[16];
		byte[] buffer = new byte[4096];
		while (!this.exit) {
			try {
				int bytes = this.inputStream.read(buffer);
				int pos = 0;
				this.debug("run() read "+bytes);
				while (bytes>0) {
					if (headerSize<16) {
						assert packetSize<0;
						int missHeader = 16-headerSize;		//how much we need for a full header
						if (bytes<missHeader) {
							//copy what we have to the header:
							for (int i=0; i<bytes; i++)
								header[headerSize+i] = buffer[pos+i];
							pos += bytes;
							headerSize += bytes;
							bytes = 0;
							this.debug("run() only got "+headerSize+" of header, continuing");
							break;			//we need more data
						}
						//copy all the missing bits to the header
						for (int i=0; i<missHeader; i++)
							header[headerSize+i] = buffer[pos+i];
						headerSize += missHeader;
						pos += missHeader;
						bytes -= missHeader;
						this.debug("run() got full header: "+new String(header));
						//we now have a complete header, parse it:
						assert header[0]=='P';
						assert header[1]=='S';
						packetSize = 0;
						for (int i=2; i<16; i++) {
							int decimal_value = header[i]-'0';
							assert decimal_value>=0 && decimal_value<10;
							packetSize *= 10;
							packetSize += decimal_value;
						}
						this.debug("run() got packet size="+packetSize+", pos="+pos+", bytes="+bytes);
						assert packetSize>0;
						if (bytes==0)
							break;
					}
					if (readBuffer==null)
						readBuffer = new ByteArrayOutputStream(packetSize);

					int missBuffer = packetSize-readBuffer.size();	//how much we need for a full packet
					if (bytes<missBuffer) {
						//not enough bytes for the full packet, just append them:
						readBuffer.write(buffer, pos, bytes);
						this.debug("run() added "+bytes+" bytes starting at "+pos+" to read buffer, now continuing");
						break;
					}
					//we have enough bytes (or more)
					this.debug("run() adding "+missBuffer+" bytes starting at "+pos+" out of "+bytes+" total bytes");
					readBuffer.write(buffer, pos, missBuffer);
					bytes -= missBuffer;
					pos += missBuffer;
					//clear sizes for next packet:
					headerSize = 0;
					packetSize = 0;
					//extract the packet:
					this.debug("run() parsing packet, remains "+bytes+" bytes at "+pos);
					byte[] packet = readBuffer.toByteArray();
					readBuffer = null;
					this.parsePacket(packet);
				}
			} catch (EOFException e) {
				this.error("run() ", e);
				this.exit = true;
			} catch (IOException e) {
				this.error("run()", e);
			}
		}
		this.log("run() loop ended");
		this.ended = true;
		this.cleanup();
		if (this.onExit != null)
			this.onExit.run();
	}

	public void parsePacket(byte[] packetBytes) {
		List<?> packet = null;
		try {
			BencodingInputStream bis = new BencodingInputStream(new ByteArrayInputStream(packetBytes));
			packet = bis.readList();
		}
		catch (IOException e) {
			this.error("parsePacket("+packetBytes.length+" bytes) trying to continue..", e);
		}
		if (packet != null)
			this.processPacket(packet);
	}

	public void cleanup() {
		this.log("cleanup()");
		try {
			this.inputStream.close();
		} catch (IOException e) {
			this.error("cleanup() failed to close inputStream=" + this.inputStream, e);
		}
		try {
			this.outputStream.close();
		} catch (IOException e) {
			this.error("cleanup() failed to close outputStream=" + this.outputStream, e);
		}
	}

	public void connectionBroken(Exception exception) {
		log("connectionBroken(" + exception + ")");
		exception.printStackTrace(System.out);
		this.exit = true;
		for (ClientWindow w : this.id_to_window.values())
			w.destroy();
	}

	protected String dump(Object in) {
		if (in == null)
			return "null";
		String str = in.toString();
		if (str.length() < 128)
			return str;
		if (str.length() >= 512)
			return "String[" + str.length() + "]";
		return str.substring(0, 125) + "..";
	}

	public void processPacket(List<?> dp) {
		this.debug("processPacket(" + dp + ")");
		if (dp.size() < 1) {
			this.log("processPacket(..) decoded data is too small: " + dp);
			return;
		}
		assert dp.size() >= 1;
		String type = this.cast(dp.get(0), String.class);
		Method m = this.handlers.get(type);
		if (m == null) {
			this.log("processPacket(..) unhandled packet: " + type);
			return;
		}
		Class<?>[] paramTypes = m.getParameterTypes();
		assert dp.size() == (paramTypes.length + 1);
		// log("packetReceived(..) calling "+m+"("+paramTypes+")");
		Object[] params = new Object[paramTypes.length];
		Object[] infoParams = new String[paramTypes.length];
		int index = 0;
		for (Class<?> paramType : paramTypes) {
			assert paramType != null;
			Object v = dp.get(1 + index);
			params[index] = this.cast(v, paramType);
			infoParams[index] = dump(v);
			index++;
		}
		this.log("processPacket(..) calling " + m + "(" + Arrays.asList(infoParams) + ")");
		try {
			synchronized (this.getLock()) {
				m.invoke(this, params);
			}
		} catch (Exception e) {
			log("processPacket(" + dp.size() + ") error calling " + m + "(" + Arrays.asList(infoParams) + ")" + e);
			Class<?>[] actualParamTypes = new Class<?>[params.length];
			index = 0;
			for (Object v : params)
				actualParamTypes[index++] = (v == null) ? null : v.getClass();
			log("processPacket(" + dp.size() + ") parameter types: " + Arrays.asList(actualParamTypes));
			e.printStackTrace(System.out);
		}
	}

	@SuppressWarnings("unchecked")
	public <T extends Object> T cast(Object in, Class<T> desiredType) {
		if (in == null)
			return null;
		Class<?> t = in.getClass();
		if (t.equals(desiredType) || desiredType.isAssignableFrom(t))
			return (T) in;
		if (desiredType.equals(int.class) && t.equals(BigInteger.class))
			return (T) new Integer(((BigInteger) in).intValue());
		if (desiredType.equals(String.class) && t.isArray() && t.getComponentType().equals(byte.class))
			try {
				return (T) new String((byte[]) in, "UTF-8");
			} catch (UnsupportedEncodingException e) {
				// if you don't have UTF-8... you're already in big trouble!
				return (T) new String((byte[]) in);
			}
		if (desiredType.equals(String.class))
			return (T) String.valueOf(in);
		this.error("cast(" + in + ", " + desiredType + ") don't know how to handle " + t, null);
		return (T) in;
	}

	@Override
	public void update_focus(int id, boolean gotit) {
		if (gotit && this.focused != id) {
			this.send("focus", id);
			this.focused = id;
		}
		if (!gotit && this.focused == id) {
			this.send("focus", 0);
			this.focused = -1;
		}
	}

	public void mask_to_names(Object mask) {
		// return mask_to_names(mask, self._modifier_map)
	}

	@Override
	public synchronized void send(String type, Object... data) {
		this.log("send(" + type + ", " + Arrays.asList(data) + ")");
		Vector<Object> packet = new Vector<Object>(2);
		packet.add(type);
		for (Object v : data)
			packet.add(v);

		try {
			ByteArrayOutputStream baos = new ByteArrayOutputStream(4096);
			BencodingOutputStream bos = new BencodingOutputStream(baos);
			bos.writeCollection(packet);
			bos.flush();
			byte[] bytes = baos.toByteArray();
			byte[] header = new byte[16];
			header[0] = 'P';
			header[1] = 'S';
			int packetSize = bytes.length; 
			for (int i=15; i>=2; i--) {
				header[i] = (byte) ('0'+(packetSize % 10));
				packetSize /= 10;
			}
			this.outputStream.write(header);
			this.outputStream.write(bytes);
			this.outputStream.flush();
		} catch (IOException e) {
			this.connectionBroken(e);
		}
	}

	@Override
	public void send_positional(String type, Object... data) {
		// self._protocol.source.queue_positional_packet(packet)
		this.send(type, data);
	}

	@Override
	public void send_mouse_position(String type, Object... data) {
		// self._protocol.source.queue_mouse_position_packet(packet)
		this.send(type, data);
	}

	public int getScreenWidth() {
		return 640;
	}

	public int getScreenHeight() {
		return 480;
	}

	public void send_disconnect() {
		this.send("disconnect", "please close the connection");
	}

	public void send_hello(String enc_pass) {
		if (this.hellosSent++ > 3) {
			this.log("send_hello(" + enc_pass + ") too many hellos sent: " + this.hellosSent);
			this.exit = true;
			return;
		}
		Map<String, Object> caps = this.make_hello(enc_pass);
		this.send("hello", caps);
	}

	public Map<String, Object> make_hello(String enc_pass) {
		Map<String, Object> caps = new LinkedHashMap<String, Object>();
		caps.put("__prerelease_version", VERSION);
		if (enc_pass != null)
			caps.put("challenge_response", enc_pass);
		// caps.put("deflate", 6);
		Vector<Integer> dims = new Vector<Integer>(2);
		dims.add(this.getScreenWidth());
		dims.add(this.getScreenHeight());
		caps.put("desktop_size", dims);
		if (this.encoding != null) {
			caps.put("encodings", ENCODINGS);
			caps.put("encoding", this.encoding);
			if (this.encoding.equals("jpeg") && this.jpeg > 0)
				caps.put("jpeg", this.jpeg);
		}
		caps.put("png_window_icons", true);
		return caps;
	}

	/*
	 * protected void send_jpeg_quality() { this.send("jpeg-quality",
	 * this.jpegquality); }
	 */

	protected void process_challenge(String salt) {
		if (this.password == null || this.password.length == 0) {
			log("password is required by the server");
			this.exit = true;
			return;
		}
		String enc_pass = this.hmac_password(salt);
		if (enc_pass == null) {
			this.exit = true;
			return;
		}
		this.send_hello(enc_pass);
	}

	public String hmac_password(String salt) {
		try {
			Mac mac = Mac.getInstance("HMACMD5");
			SecretKeySpec secret = new SecretKeySpec(this.password, "HMACMD5");
			mac.init(secret);
			byte[] digest = mac.doFinal(salt.getBytes());
			this.log("hmac_password(" + salt + ")=byte[" + digest.length + "]");
			String enc_pass = hexlify_raw(digest);
			this.log("hmac_password(" + salt + ")=" + enc_pass);
			return enc_pass;
		} catch (Exception e) {
			log("hmac_password(" + salt + ") failed: " + e.getMessage());
			return null;
		}
	}

	public static final char[] HEX_DIGITS = "0123456789abcdef".toCharArray();

	public static String hexlify_raw(byte[] in) {
		StringBuffer hex = new StringBuffer(in.length * 2);
		for (byte c : in) {
			hex.append(HEX_DIGITS[(c >>> 4) & 0xF]);
			hex.append(HEX_DIGITS[c & 0xF]);
		}
		return hex.toString();
	}

	public String version_no_minor(String version) {
		if (version == null || version.length() == 0)
			return "";
		int p = version.lastIndexOf(".");
		if (p > 0)
			return version.substring(0, p);
		return version;
	}

	public int minor_version_int(String version) {
		if (version == null || version.length() == 0)
			return 0;
		int p = version.lastIndexOf(".");
		if (p > 0)
			return Integer.parseInt(version.substring(p + 1));
		return 0;
	}

	protected void process_hello(Map<String, Object> capabilities) {
		this.log("process_hello(" + capabilities + ")");
		this.remote_version = this.cast(capabilities.get("version"), String.class);
		if (!this.version_no_minor(this.remote_version).equals(this.version_no_minor(VERSION))) {
			log("sorry, I only know how to talk to v" + this.version_no_minor(VERSION) + ".x servers, this one is " + this.remote_version);
			this.exit = true;
			return;
		}
		/*
		 * Vector<Object> desktop_size = (Vector<Object>)
		 * capabilities.get("desktop_size"); if (desktop_size!=null) { Integer
		 * avail_w = (Integer) desktop_size.get(0); Integer avail_h = (Integer)
		 * desktop_size.get(1); /*root_w, root_h =
		 * gtk.gdk.get_default_root_window().get_size() if (avail_w, avail_h) <
		 * (root_w, root_h): log.warn("Server's virtual screen is too small -- "
		 * "(server: %sx%s vs. client: %sx%s)\n"
		 * "You may see strange behavior.\n" "Please complain to "
		 * "parti-discuss@partiwm.org" % (avail_w, avail_h, root_w, root_h)) }
		 */
	}

	protected void process_new_common(int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		ClientWindow window = this.createWindow(id, x, y, w, h, metadata, override_redirect);
		this.id_to_window.put(id, window);
	}

	protected void process_new_window(int id, int x, int y, int w, int h, Map<String, Object> metadata) {
		this.process_new_common(id, x, y, w, h, metadata, false);
	}

	protected void process_new_override_redirect(int id, int x, int y, int w, int h, Map<String, Object> metadata) {
		this.process_new_common(id, x, y, w, h, metadata, true);
	}

	protected void process_draw(int id, int x, int y, int w, int h, String coding, byte[] data) {
		ClientWindow window = this.id_to_window.get(id);
		window.draw(x, y, w, h, coding, data);
	}

	protected void process_window_metadata(int id, Map<String, Object> metadata) {
		ClientWindow window = this.id_to_window.get(id);
		window.update_metadata(metadata);
	}

	protected void process_configure_override_redirect(int id, int x, int y, int w, int h) {
		ClientWindow window = this.id_to_window.get(id);
		window.move_resize(x, y, w, h);
	}

	protected void process_lost_window(int id) {
		ClientWindow window = this.id_to_window.remove(id);
		if (window == null)
			log("window not found: " + id);
		else {
			window.destroy();
			this.id_to_window.remove(id);
		}
	}

	protected void process_disconnect(Object o) {
		this.log("process_disconnect(" + o + ") terminating the connection");
		this.exit = true;
	}
}
