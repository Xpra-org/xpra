package xpra;

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

	public	static	final	int	RECEIVE_BUFFER_SIZE = 1024*1024*1;	//1MB
	public	static	final	String	VERSION = "0.0.7.26";

	protected	boolean	ended = false;
	protected	boolean	exit = false;
	protected	Runnable onExit = null;
	protected	BencodingInputStream inputStream = null;
	protected	BencodingOutputStream outputStream = null;
	protected	byte[] buffer = null;
    protected	Map<String,Method> handlers = new HashMap<String,Method>(HANDLERS.length);

    protected	int jpeg = 40;
    protected	byte[]	password = null;
    protected	int hellosSent = 0;
    
    protected	Map<Integer,ClientWindow> id_to_window = new HashMap<Integer,ClientWindow>();
    protected	int focused = -1;
    
    protected	String	remote_version = null;

    public static String[] HANDLERS = {"challenge",
    				"disconnect",
    				"hello",
    				"new-window",
    				"new-override-redirect",
    				"draw",
    				"window-metadata",
    				"configure-override-redirect",
    				"lost-window"};
    
	public AbstractClient(InputStream is, OutputStream os) {
		this.inputStream = new BencodingInputStream(is, false);
		this.outputStream = new BencodingOutputStream(os);
		this.registerHandlers();
	}
	public	void	setOnExit(Runnable r) {
		this.onExit = r;
	}
	
	
	public void registerHandlers() {
		Method[] methods = this.getClass().getMethods();
		Method[] abMethods = AbstractClient.class.getDeclaredMethods();
		
		log("registerHandlers() methods="+Arrays.asList(methods));
		for (String h : HANDLERS) {
			String methodName = "process_"+h.replaceAll("-", "_");
			try {
				Method m = null;
				//try actual class
				for (Method t : methods)
					if (t.getName().equals(methodName)) {
						m = t;
						break;
					}
				//try AbstractClient
				if (m==null)
					for (Method t : abMethods)
						if (t.getName().equals(methodName)) {
							m = t;
							break;
						}
				if (m==null)
					throw new IllegalArgumentException("cannot find method "+methodName+" on "+this.getClass());
				this.handlers.put(h, m);
			}
			catch (Exception e) {
				throw	new IllegalStateException("cannot find method "+methodName, e);
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
	
	public void log(String str) {
		System.out.println(this.getClass().getSimpleName()+"."+str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
	}
	public void error(String str, Throwable t) {
		System.out.println(this.getClass().getSimpleName()+"."+str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
		if (t!=null)
			t.printStackTrace(System.out);
	}

	protected abstract ClientWindow createWindow(int id, int x, int y, int w, int h, Map<String,Object> metadata, boolean override_redirect);
	public abstract void run(String[] args);
	public abstract Object	getLock();

	@Override
	public void run() {
		this.send_hello(null);
		while (!this.exit) {
			try {
				List<?> packet = this.inputStream.readList();
				if (packet!=null)
					this.processPacket(packet);
			}
			catch (EOFException e) {
				this.error("run() ", e);
				this.exit = true;
			}
			catch (IOException e) {
				this.error("run()", e);
			}
		}
		this.log("run() loop ended");
		this.ended = true;
		this.cleanup();
		if (this.onExit!=null)
			this.onExit.run();
	}

	public void cleanup() {
		this.log("cleanup()");
		try {
			this.inputStream.close();
		}
		catch (IOException e) {
			this.error("cleanup() failed to close inputStream="+this.inputStream, e);
		}
		try {
			this.outputStream.close();
		}
		catch (IOException e) {
			this.error("cleanup() failed to close outputStream="+this.outputStream, e);
		}
	}
	
	
	public void connectionBroken(Exception exception) {
		log("connectionBroken("+exception+")");
		exception.printStackTrace(System.out);
		this.exit = true;
		for (ClientWindow w : this.id_to_window.values())
			w.destroy();
	}
	
	protected	String	dump(Object in) {
		if (in==null)
			return	"null";
		String str = in.toString();
		if (str.length()<128)
			return	str;
		if (str.length()>=512)
			return	"String["+str.length()+"]";
		return	str.substring(0, 125)+"..";
	}
	
	public void processPacket(List<?> dp) {
		this.log("processPacket("+dp+")");
		if (dp.size()<1) {
			log("processPacket(..) decoded data is too small: "+dp);
			return;
		}
		assert dp.size()>=1;
		String type = this.cast(dp.get(0), String.class);
		Method m = this.handlers.get(type);
		if (m==null) {
			log("processPacket(..) unhandled packet: "+type);
			return;
		}
		Class<?>[] paramTypes = m.getParameterTypes();
		assert dp.size()==(paramTypes.length+1);
		//log("packetReceived(..) calling "+m+"("+paramTypes+")");
		Object[] params = new Object[paramTypes.length];
		Object[] infoParams = new String[paramTypes.length];
		int index = 0;
		for (Class<?> paramType : paramTypes) {
			assert paramType!=null;
			Object v = dp.get(1+index);
			params[index] = this.cast(v, paramType);
			infoParams[index] = dump(v);
			index++;
		}
		log("processPacket(..) calling "+m+"("+Arrays.asList(infoParams)+")");
		try {
			synchronized (this.getLock()) {
				m.invoke(this, params);
			}
		}
		catch (Exception e) {
			log("processPacket("+dp.size()+") error calling "+m+"("+Arrays.asList(infoParams)+")"+e);
			Class<?>[] actualParamTypes = new Class<?>[params.length];
			index = 0;
			for (Object v : params)
				actualParamTypes[index++] = (v==null)?null:v.getClass();
			log("processPacket("+dp.size()+") parameter types: "+Arrays.asList(actualParamTypes));
			e.printStackTrace(System.out);
		}
	}
	
	@SuppressWarnings("unchecked")
	public <T extends Object>	T	cast(Object in, Class<T> desiredType) {
		if (in==null)
			return	null;
		Class<?> t = in.getClass();
		if (t.equals(desiredType) || desiredType.isAssignableFrom(t))
			return	(T) in;
		if (desiredType.equals(int.class) && t.equals(BigInteger.class))
			return	(T) new Integer(((BigInteger) in).intValue());
		if (desiredType.equals(String.class) && t.isArray() && t.getComponentType().equals(byte.class))
			try {
				return	(T) new String((byte[]) in, "UTF-8");
			}
			catch (UnsupportedEncodingException e) {
				//if you don't have UTF-8... you're already in big trouble!
				return	(T) new String((byte[]) in);
			}
		if (desiredType.equals(String.class))
			return	(T) String.valueOf(in);
		this.error("cast("+in+", "+desiredType+") don't know how to handle "+t, null);
		return (T) in;
	}
	
	
    @Override
	public void update_focus(int id, boolean gotit) {
        if (gotit && this.focused!=id) {
            this.send("focus", id);
            this.focused = id;
        }
        if (!gotit && this.focused==id) {
            this.send("focus", 0);
            this.focused = -1;
        }
    }

    public void mask_to_names(Object mask) {
        //return mask_to_names(mask, self._modifier_map)
    }

	@Override
	public synchronized void send(String type, Object... data) {
		this.log("send("+type+", "+Arrays.asList(data)+")");
        Vector<Object> packet = new Vector<Object>(2);
        packet.add(type);
        for (Object v : data)
        	packet.add(v);
		//ByteArrayOutputStream baos = new ByteArrayOutputStream();
		/*if (false) {
			DeflaterOutputStream dos = new DeflaterOutputStream(baos);
			byte[] bytes = baos.toByteArray();
		}*/
		try {
			this.outputStream.writeCollection(packet);
			this.outputStream.flush();
		}
		catch (IOException e) {
			this.connectionBroken(e);
		}
	}

	@Override
	public void send_positional(String type, Object... data) {
        //self._protocol.source.queue_positional_packet(packet)
    	this.send(type, data);
	}
	
    @Override
	public void send_mouse_position(String type, Object... data) {
        //self._protocol.source.queue_mouse_position_packet(packet)
    	this.send(type, data);
    }
    
    
    public int getScreenWidth() {
    	return	640;
    }
    public int getScreenHeight() {
    	return	480;
    }

	public void send_disconnect() {
		this.send("disconnect", "please close the connection");
	}
	
	public void send_hello(String enc_pass) {
        if (this.hellosSent++>3) {
        	this.log("send_hello("+enc_pass+") too many hellos sent: "+this.hellosSent);
            this.exit = true;
            return;
        }
		Map<String,Object> caps= new LinkedHashMap<String,Object>();
		caps.put("__prerelease_version", VERSION);
        if (enc_pass!=null)
        	caps.put("challenge_response", enc_pass);
        //caps.put("deflate", 6);
        Vector<Integer> dims = new Vector<Integer>(2);
        dims.add(this.getScreenWidth());
        dims.add(this.getScreenHeight());
        caps.put("desktop_size", dims);
        if (this.jpeg>0)
        	caps.put("jpeg", this.jpeg);
        caps.put("png_window_icons", true);
        this.send("hello", caps);
	}

    /*protected void	send_jpeg_quality() {
        this.send("jpeg-quality", this.jpegquality);
    }*/


    protected	void process_challenge(String salt) {
        if (this.password==null || this.password.length==0) {
            log("password is required by the server");
            this.exit = true;
            return;
        }
        String enc_pass = this.hmac_password(salt);
        if (enc_pass==null) {
        	this.exit  =true;
        	return;
        }
        this.send_hello(enc_pass);
    }
    public String	hmac_password(String salt) {
        try {
            Mac mac = Mac.getInstance("HMACMD5");
            SecretKeySpec secret = new SecretKeySpec(this.password,"HMACMD5");
            mac.init(secret);
            byte[] digest = mac.doFinal(salt.getBytes());
            this.log("hmac_password("+salt+")=byte["+digest.length+"]");
            String enc_pass = hexlify_raw(digest);
            this.log("hmac_password("+salt+")="+enc_pass);
            return	enc_pass;
        }
        catch (Exception e) {
            log("hmac_password("+salt+") failed: "+e.getMessage());
            return	null;
        }
    }
    
	public static final char[] HEX_DIGITS = "0123456789abcdef".toCharArray();
	public static String hexlify_raw(byte[] in) {
        StringBuffer hex = new StringBuffer(in.length*2);
        for (byte c: in) {
        	hex.append(HEX_DIGITS[(c >>> 4) & 0xF]);
        	hex.append(HEX_DIGITS[c & 0xF]);
        }
        return hex.toString();
    }

    public String version_no_minor(String version) {
        if (version==null || version.length()==0)
            return "";
        int p = version.lastIndexOf(".");
        if (p>0)
            return version.substring(0, p);
        return version;
    }

    public int minor_version_int(String version) {
        if (version==null || version.length()==0)
            return 0;
        int p = version.lastIndexOf(".");
        if (p>0)
            return Integer.parseInt(version.substring(p+1));
        return 0;
    }

	protected void process_hello(Map<String,Object> capabilities) {
		this.log("process_hello("+capabilities+")");
        this.remote_version = this.cast(capabilities.get("__prerelease_version"), String.class);
        if (!this.version_no_minor(this.remote_version).equals(this.version_no_minor(VERSION))) {
            log("sorry, I only know how to talk to v"+this.version_no_minor(VERSION)+".x servers, this one is "+this.remote_version);
            this.exit = true;
            return;
        }
        /*
        Vector<Object> desktop_size = (Vector<Object>) capabilities.get("desktop_size");
        if (desktop_size!=null) {
        	Integer avail_w = (Integer) desktop_size.get(0);
        	Integer avail_h = (Integer) desktop_size.get(1);
            /*root_w, root_h = gtk.gdk.get_default_root_window().get_size()
            if (avail_w, avail_h) < (root_w, root_h):
                log.warn("Server's virtual screen is too small -- "
                         "(server: %sx%s vs. client: %sx%s)\n"
                         "You may see strange behavior.\n"
                         "Please complain to "
                         "parti-discuss@partiwm.org"
                         % (avail_w, avail_h, root_w, root_h))
        }*/
	}

	protected void process_new_common(int id, int x, int y, int w, int h, Map<String,Object> metadata, boolean override_redirect) {
    	ClientWindow window = this.createWindow(id, x, y, w, h, metadata, override_redirect);
        this.id_to_window.put(id, window);
    }
	
	protected void process_new_window(int id, int x, int y, int w, int h, Map<String,Object> metadata) {
		this.process_new_common(id, x, y, w, h, metadata, false);
	}
	protected void process_new_override_redirect(int id, int x, int y, int w, int h, Map<String,Object> metadata) {
		this.process_new_common(id, x, y, w, h, metadata, true);
	}
	protected void process_draw(int id, int x, int y, int w, int h, String coding, byte[] data) {
        ClientWindow window = this.id_to_window.get(id);
        window.draw(x, y, w, h, coding, data);
	}
	protected void process_window_metadata(int id, Map<String,Object> metadata) {
        ClientWindow window = this.id_to_window.get(id);
        window.update_metadata(metadata);
	}
	protected void process_configure_override_redirect(int id, int x, int y, int w, int h) {
        ClientWindow window = this.id_to_window.get(id);
        window.move_resize(x, y, w, h);
	}
	protected void process_lost_window(int id) {
        ClientWindow window = this.id_to_window.remove(id);
        if (window==null)
        	log("window not found: "+id);
        else {
        	window.destroy();
        	this.id_to_window.remove(id);
        }
	}

	protected void process_disconnect(Object o) {
		this.log("process_disconnect("+o+") terminating the connection");
		this.exit = true;
	}
}
