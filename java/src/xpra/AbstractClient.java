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
import java.util.UUID;
import java.util.Vector;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

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
	public static final String VERSION = "1.0.8";
	public static final String MIN_VERSION = "0.5";
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

	public static String[] HANDLERS = { "challenge", "disconnect", "hello", "new-window", "new-override-redirect", "window-metadata",
			"configure-override-redirect", "lost-window", "draw", "bell", "notify_show", "notify_close", "ping", "ping_echo" };

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

	public void error(String str) {
		this.error(str, null);
	}

	public void error(String str, Throwable t) {
		System.out.println(this.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
		if (t != null)
			t.printStackTrace(System.out);
	}

	public void warnUser(String message) {
		this.log(message);
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
		byte[] header = new byte[8];
		byte[] buffer = new byte[4096];
		byte[] inflate_buffer = new byte[4096];
		Map<Integer, byte[]> raw_packets = new HashMap<Integer, byte[]>(5);
		int packet_index = 0;
		int compression_level = 0;
		while (!this.exit) {
			try {
				int bytes = this.inputStream.read(buffer);
				int pos = 0;
				this.debug("run() read "+bytes+" bytes");
				while (bytes > 0) {
					if (packetSize<=0) {
						// we don't have the packet size, so we must still be parsing the header
						assert headerSize<8;
						// copy up to 8 chars into header
						int missHeader = 8 - headerSize;
						if (bytes < missHeader) {
							//partial header: copy what we have and wait for next chunk
							for (int i = 0; i < bytes; i++)
								header[headerSize + i] = buffer[pos + i];
							pos += bytes;
							headerSize += bytes;
							bytes = 0;
							this.debug("run() only got " + headerSize + " of header, continuing");
							break; // we need more data
						}
						// we have the full header
						for (int i = 0; i < missHeader; i++)
							header[headerSize + i] = buffer[pos + i];
						//clear it for next header:
						headerSize = 0;
						pos += missHeader;
						bytes -= missHeader;
						this.debug("run() got full header: 0x" + hexlify_raw(header));
						// we now have a complete header, parse it:
						assert header[0] == 'P';
						assert header[1] == 0;		//version
						compression_level = header[2];
						packet_index = header[3];
						packetSize = 0;
						for (int b=0; b<4; b++) {
							packetSize = packetSize<<8;
							//this.debug("run() header["+(4+b)+"]="+(header[4+b] & 0xFF));
							packetSize += header[4+b] & 0xFF;
						}
						this.debug("run() got packet size=" + packetSize + ", pos=" + pos + ", bytes=" + bytes);
						assert packetSize > 0;
						if (bytes == 0)
							break;
					}
					if (readBuffer == null)
						readBuffer = new ByteArrayOutputStream(packetSize);

					// how much we need for a full packet:
					int missBuffer = packetSize - readBuffer.size();
					if (bytes < missBuffer) {
						// not enough bytes for a full packet, just append them:
						readBuffer.write(buffer, pos, bytes);
						this.debug("run() added " + bytes + " bytes starting at " + pos + " to read buffer, now continuing");
						break;
					}
					// we have enough bytes (or more)
					this.debug("run() adding " + missBuffer + " bytes starting at " + pos + " out of " + bytes + " total bytes");
					readBuffer.write(buffer, pos, missBuffer);
					bytes -= missBuffer;
					pos += missBuffer;
					// clear size for next packet (so we parse the header again):
					packetSize = 0;
					// extract the packet:
					this.debug("run() parsing packet of size "+readBuffer.size()+" with compression level="+compression_level+", with index="+packet_index+", remains " + bytes + " bytes at " + pos);
					byte[] packet = readBuffer.toByteArray();
					readBuffer.close();
					readBuffer = null;
					if (compression_level>0) {
						Inflater decompresser = new Inflater();
						decompresser.setInput(packet, 0, packet.length);
						ByteArrayOutputStream tmp = new ByteArrayOutputStream(packet.length+100);
						while (decompresser.getRemaining()>0) {
							int dec_len = decompresser.inflate(inflate_buffer);
							tmp.write(inflate_buffer, 0, dec_len);
						}
						decompresser.end();
						packet = tmp.toByteArray();
						tmp.close();
					}
					if (packet_index>0) {
						//byte[] data to patch into main packet later: store it
						raw_packets.put(packet_index, packet);
						continue;
					}
					//patch raw packets into main packet:
					List<Object> lpacket = this.parsePacket(packet);
					if (raw_packets.size()>0) {
						for (Map.Entry<Integer, byte[]> me : raw_packets.entrySet())
							lpacket.set(me.getKey().intValue(), me.getValue());
						//now safe to clear for the next packet:
						raw_packets = new HashMap<Integer, byte[]>(5);
					}
					//process current packet:
					this.processPacket(lpacket);
				}
			} catch (EOFException e) {
				this.error("run() ", e);
				this.exit = true;
			} catch (IOException e) {
				this.error("run()", e);
				this.exit = true;
			} catch (DataFormatException e) {
				this.error("run()", e);
				this.exit = true;
			}
		}
		this.log("run() loop ended");
		this.ended = true;
		this.cleanup();
		if (this.onExit != null)
			this.onExit.run();
	}

	public List<Object>	parsePacket(byte[] packetBytes) {
		List<Object> packet = null;
		try {
			BencodingInputStream bis = new BencodingInputStream(new ByteArrayInputStream(packetBytes));
			packet = bis.readList();
			bis.close();
			return packet;
		} catch (IOException e) {
			byte[] dump = packetBytes;
			if (packetBytes.length>200) {
				dump = new byte[200];
				System.arraycopy(packetBytes, 0, dump, 0, 200);
			}
			this.error("parsePacket(" + packetBytes.length + " bytes) packet header: "+new String(dump), e);
			throw new IllegalStateException("cannot continue after parsing error: "+e);
		}
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
		if (!this.exit) {
			this.exit = true;
			for (ClientWindow w : this.id_to_window.values())
				w.destroy();
		}
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
		String type = CastHelper.cast(dp.get(0), String.class);
		Method m = this.handlers.get(type);
		if (m == null) {
			this.log("processPacket(..) unhandled packet: " + type);
			return;
		}
		Class<?>[] paramTypes = m.getParameterTypes();
		assert dp.size() == (paramTypes.length + 1);
		Object[] params = new Object[paramTypes.length];
		int index = 0;
		for (Class<?> paramType : paramTypes) {
			assert paramType != null;
			Object v = dp.get(1 + index);
			params[index] = this.cast(v, paramType);
			index++;
		}
		this.invokePacketMethod(m, params);
	}

	public void invokePacketMethod(Method m, Object[] params) {
		this.doInvokePacketMethod(m, params);
	}

	public void doInvokePacketMethod(Method m, Object[] params) {
		this.debug("doInvokePacketMethod(" + m + ", " + params.length + " arguments )");
		try {
			synchronized (this.getLock()) {
				m.invoke(this, params);
			}
		} catch (Exception e) {
			Class<?>[] paramTypes = m.getParameterTypes();
			String[] infoParams = new String[paramTypes.length];
			for (int i=0; i<params.length; i++)
				infoParams[i] = this.dump(params[i]);
			this.error("doInvokePacketMethod(" + m + ", " + Arrays.asList(infoParams) + ")", e);
			Class<?>[] actualParamTypes = new Class<?>[params.length];
			for (int i=0; i<params.length; i++)
				actualParamTypes[i] = (params[i] == null) ? null : params[i].getClass();
			this.log("doInvokePacketMethod(" + m + ", " + params.length + " arguments ) actual parameter types: " + Arrays.asList(actualParamTypes));
		}
	}

	@SuppressWarnings("unchecked")
	public <T extends Object> T cast(Object in, Class<T> desiredType) {
		if (in == null)
			return null;
		Class<?> t = in.getClass();
		if (t.equals(desiredType) || desiredType.isAssignableFrom(t))
			return (T) in;
		if ((desiredType.equals(int.class) || desiredType.equals(Integer.class)) && t.equals(BigInteger.class))
			return (T) new Integer(((BigInteger) in).intValue());
		if ((desiredType.equals(long.class) || desiredType.equals(Integer.class)) && t.equals(BigInteger.class))
			return (T) new Long(((BigInteger) in).longValue());
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
	public void update_focus(int id, boolean gotit, boolean forceit) {
		if (gotit && (forceit || this.focused != id)) {
			this.send("focus", id);
			this.focused = id;
		}
		if (!gotit && (forceit || this.focused == id)) {
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
			bos.close();
			byte[] header = new byte[8];
			int packetSize = bytes.length;
			//(_, protocol_version, compression_level, packet_index, current_packet_size) = struct.unpack_from('!cBBBL', read_buffer)
			header[0] = 'P';
			header[1] = 0;
			header[2] = 0;
			//big endian size as 4 bytes:
			for (int b=0; b<4; b++)
				header[4+b] = (byte) ((packetSize >>> (24-b*8)) % 256);
			this.debug("send(...) header=0x"+hexlify_raw(header)+", payload is "+packetSize+" bytes");
			this.outputStream.write(header);
			this.outputStream.write(bytes);
			this.outputStream.flush();
		} catch (IOException e) {
			this.connectionBroken(e);
		}
	}

	public void send_screen_size_changed(int w, int h) {
        this.send("desktop_size", w, h);
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
			this.warnUser("Failed to connect");
			this.exit = true;
			return;
		}
		Map<String, Object> caps = this.make_hello(enc_pass);
		this.send("hello", caps);
	}

	public Map<String, Object> make_hello(String enc_pass) {
		Map<String, Object> caps = new LinkedHashMap<String, Object>();
		caps.put("version", VERSION);
		if (enc_pass != null)
			caps.put("challenge_response", enc_pass);
		Vector<Integer> dims = new Vector<Integer>(2);
		dims.add(this.getScreenWidth());
		dims.add(this.getScreenHeight());
		caps.put("desktop_size", dims);
		Vector<Vector<Integer>> ss = new Vector<Vector<Integer>>(2);
		ss.add(dims);
		caps.put("dpi", 100);
		caps.put("client_type", "Java");
		caps.put("screen_sizes", dims);
		caps.put("encodings", ENCODINGS);
		caps.put("clipboard", false); // not supported
		caps.put("notifications", true);
		caps.put("keyboard", true);
		caps.put("keyboard_sync", true);
		caps.put("cursors", false);		// not shown!
		caps.put("bell", true);			// uses vibrate on Android
		caps.put("rencode", false);		// would need porting to Java (unlikely)
		caps.put("chunked_compression", true);
		if (this.encoding != null) {
			caps.put("encoding", this.encoding);
			if (this.encoding.equals("jpeg") && this.jpeg > 0)
				caps.put("jpeg", this.jpeg);
		}
		caps.put("platform", System.getProperty("os.name").toLowerCase());
		caps.put("uuid", UUID.randomUUID().toString().replace("-", ""));
		caps.put("keyboard", true);
		caps.put("xkbmap_layout", this.getKeyboardLayout());
		caps.put("xkbmap_keycodes", this.getKeycodes());
		return caps;
	}

	protected abstract String getKeyboardLayout();

	protected abstract List<?>[]	getKeycodes();

	protected void process_challenge(String salt) {
		if (this.password == null || this.password.length == 0) {
			this.warnUser("This session requires a password");
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

	/**
	 * To make it easier to compare version numbers,
	 * returns the version number as a long.
	 * Each part multiplied by 1000, no more than 3 parts.
	 * ie: 0.3.11 -> 0003011
	 * ie: 0.5.0  -> 0005000
	 * ie: 1.3.2  -> 1003002
	 */
	public long version_as_number(String version) {
		if (version == null || version.length() == 0)
			return 0;
		String[] parts = version.split("\\.");
		long vno = 0;
		for (int i=0; i<3; i++) {
			vno *= 1000;
			int pval = 0;
			if (i<parts.length)
				try {
					pval = Integer.parseInt(parts[i]);
				}
				catch (NumberFormatException e) {
					//ignore
				}
			vno += pval;
		}
		return vno;
	}

	protected void process_hello(Map<String, Object> capabilities) {
		this.log("process_hello(" + capabilities + ")");
		this.remote_version = this.cast(capabilities.get("version"), String.class);
		if (this.version_as_number(this.remote_version)<this.version_as_number(MIN_VERSION)) {
			log("sorry, I only know how to talk to server versions " + MIN_VERSION + " or newer, this one is " + this.remote_version);
			this.warnUser("The server version is incompatible with this client");
			this.exit = true;
			return;
		}
		@SuppressWarnings("unchecked")
		List<Object> desktop_size = (List<Object>) capabilities.get("desktop_size");
		if (desktop_size != null) {
			Integer avail_w = this.cast(desktop_size.get(0), Integer.class);
			Integer avail_h = this.cast(desktop_size.get(1), Integer.class);
			if (avail_w < this.getScreenWidth() || avail_h < this.getScreenHeight()) {
				this.warnUser("The server's virtual screen is too small! You may see strange behaviour");
			} else if (avail_w > (this.getScreenWidth() * 12 / 10) || (avail_h > (this.getScreenHeight() * 12 / 10))) {
				this.warnUser("The server's virtual screen is too big! It should be using Xdummy, this client may crash and/or misbehave.");
			}
		}
		this.send_deflate(3);
	}

	protected void send_deflate(int level) {
		this.send("set_deflate", level);
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

	protected void process_draw(int id, int x, int y, int w, int h, String coding, byte[] data, int packet_sequence, int rowstride) {
		ClientWindow window = this.id_to_window.get(id);
		long start = System.currentTimeMillis();
		window.draw(x, y, w, h, coding, data);
		long end = System.currentTimeMillis();
        if (packet_sequence>=0)
            this.send("damage-sequence", packet_sequence, id, w, h, end-start);
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

	protected abstract void process_bell(int wid, int device, int percent, int pitch, int duration, String bell_class, int bell_id, String bell_name);

	protected abstract void process_notify_show(int dbus_id, int nid, String app_name, int replaced_id, String app_icon, String summary, String body,
			int expire_timeout);

	protected abstract void process_notify_close(int nid);

	protected void send_ping() {
		this.send("ping", System.currentTimeMillis());
	}

	protected void process_ping(long echotime) {
		// TODO: load average:
		long l1 = 1;
		long l2 = 1;
		long l3 = 1;
		int serverLatency = -1;
		// if len(self.server_latency)>0:
		// sl = self.server_latency[-1]
		this.send("ping_echo", echotime, l1, l2, l3, serverLatency);
	}

	protected void process_ping_echo(long echoedtime, long l1, long l2, long l3, int clientLatency) {
		long diff = System.currentTimeMillis() - echoedtime;
		// this.server_latency.append(diff)
		// this.server_load = (l1, l2, l3)
		// if cl>=0:
		// self.client_latency.append(cl)
		log("process_ping_echo(" + echoedtime + ", " + l1 + ", " + l2 + ", " + l3 + ", " + clientLatency + ") server latency=" + diff);
	}

	protected void process_disconnect(Object o) {
		this.log("process_disconnect(" + o + ") terminating the connection");
		this.exit = true;
	}
}
