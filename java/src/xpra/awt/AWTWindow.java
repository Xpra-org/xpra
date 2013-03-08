package xpra.awt;

import java.awt.AWTEvent;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Frame;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Insets;
import java.awt.Point;
import java.awt.Window;
import java.awt.event.KeyEvent;
import java.awt.event.KeyListener;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.awt.event.MouseMotionListener;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseWheelListener;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.awt.event.WindowFocusListener;
import java.awt.event.WindowStateListener;
import java.awt.image.BufferedImage;
import java.awt.image.ImageObserver;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.imageio.ImageIO;

import xpra.ClientWindow;

public class AWTWindow extends Frame implements ClientWindow {
	private static final long serialVersionUID = 1L;

	protected AWTClient client = null;
	protected int id = -1;
	protected int x = -1;
	protected int y = -1;
	protected int w = -1;
	protected int h = -1;
	protected Map<String, Object> metadata = null;
	protected boolean override_redirect = false;
	protected int failed_pixbuf_index = 0;

	protected BufferedImage backing = null;
	protected Graphics2D graphics = null;

	public static boolean DEBUG_REDRAWS = false;
	public static boolean save_failed_pixbufs = true;
	public static boolean save_successful_pixbufs = false;
	public static boolean save_backing = false;
	public static boolean save_paint = false;

	public AWTWindow(AWTClient client, int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		this.log("<init>(" + client + ", " + id + ", " + x + ", " + y + ", " + w + ", " + h + ", " + metadata + ", " + override_redirect + ")");
		/*
		 * if (override_redirect) this.setTypeHint(WindowTypeHint.UTILITY); else
		 * this.setTypeHint(WindowTypeHint.NORMAL);
		 */
		this.client = client;
		this.id = id;
		this.x = x;
		this.y = y;
		this.w = w;
		this.h = h;
		this.metadata = new HashMap<String, Object>();
		this.override_redirect = override_redirect;
		this.update_metadata(metadata);

		this.mapEvents();

		this.new_backing(w, h);

		this.setLocation(x, y);
		this.setSize(w, h);
		this.setPreferredSize(new Dimension(w, h));
		this.setEnabled(true);
		if (DEBUG_REDRAWS)
			this.setBackground(Color.RED);
		else
			this.setBackground(Color.WHITE);
		this.setVisible(true);
		// now work out the insets and resize the window to compensate:
		Dimension size = this.getSize();
		Insets insets = this.getInsets();
		int inset_w = insets.left + insets.right;
		int inset_h = insets.top + insets.bottom;
		this.log("<init>(..) w=" + w + ", h=" + h + ", width=" + size.getWidth() + ", height=" + size.getHeight() + ", inset_w=" + inset_w + ", inset_h="
				+ inset_h);
		int iw = (int) size.getWidth() + inset_w;
		int ih = (int) size.getHeight() + inset_h;
		this.setSize(iw, ih);
		// this.setPreferredSize(new Dimension(iw, ih));
	}

	@Override
	public void setVisible(boolean visible) {
		this.log("setVisible(" + visible + ")");
		super.setVisible(visible);
	}

	@Override
	public void removeNotify() {
		this.log("removeNotify()");
		super.removeNotify();
		this.do_unmap_event();
	}

	@Override
	public void update(Graphics g) {
		if (DEBUG_REDRAWS)
			this.log("update(" + g + ")");
		super.update(g);
	}

	@Override
	public void paint(Graphics g) {
		if (DEBUG_REDRAWS)
			this.log("paint(" + g + ") backing=" + this.backing);
		super.paint(g);
		if (this.backing != null) {
			if (DEBUG_REDRAWS)
				this.log("paint(" + g + ") clip=" + g.getClip());
			// g.setPaintMode();
			Insets insets = this.getInsets();
			g.drawImage(this.backing, insets.left, insets.top, this);
			// g.finalize();
			if (save_paint) {
				File outputfile = new File("paint-" + System.currentTimeMillis() + ".png");
				try {
					ImageIO.write(this.backing, "png", outputfile);
				} catch (IOException e) {
					this.log("pain() failed to save backing: " + e);
					e.printStackTrace();
				}
			}
		} else
			g.clearRect(0, 0, getSize().width, getSize().height);
	}

	protected void mapEvents() {
		this.addWindowListener(new WindowAdapter() {
			@Override
			public void windowClosing(WindowEvent we) {
				dispose();
			}

			@Override
			public void windowActivated(WindowEvent e) {
				log("windowActivated(" + e + ")");
				// Invoked when the Window is set to be the active Window.
			}

			@Override
			public void windowClosed(WindowEvent e) {
				log("windowClosed(" + e + ")");
				do_unmap_event();
				// Invoked when a window has been closed as the result of
				// calling dispose on the window.
			}

			@Override
			public void windowDeactivated(WindowEvent e) {
				log("windowDeactivated(" + e + ")");
				// Invoked when a Window is no longer the active Window.
			}

			@Override
			public void windowDeiconified(WindowEvent e) {
				log("windowDeiconified(" + e + ")");
				// Invoked when a window is changed from a minimized to a normal
				// state.
			}

			@Override
			public void windowIconified(WindowEvent e) {
				log("windowIconified(" + e + ")");
				// Invoked when a window is changed from a normal to a minimized
				// state.
			}

			@Override
			public void windowOpened(WindowEvent e) {
				log("windowOpened(" + e + ")");
				do_map_event(e);
			}
		});
		this.addWindowFocusListener(new WindowFocusListener() {
			@Override
			public void windowGainedFocus(WindowEvent arg0) {
				log("windowGainedFocus(" + arg0 + ")");
				do_focus_event(true);
			}

			@Override
			public void windowLostFocus(WindowEvent arg0) {
				log("windowLostFocus(" + arg0 + ")");
				do_focus_event(false);
			}
		});
		this.addWindowStateListener(new WindowStateListener() {
			@Override
			public void windowStateChanged(WindowEvent arg0) {
				log("windowStateChanged(" + arg0 + ")");
			}
		});
		this.addKeyListener(new KeyListener() {
			@Override
			public void keyPressed(KeyEvent arg0) {
				log("keyPressed(" + arg0 + ")");
				key_action(arg0, true);
			}

			@Override
			public void keyReleased(KeyEvent arg0) {
				log("keyReleased(" + arg0 + ")");
				key_action(arg0, false);
			}

			@Override
			public void keyTyped(KeyEvent arg0) {
				log("keyTyped(" + arg0 + ")");
			}
		});

		this.addMouseListener(new MouseListener() {
			@Override
			public void mouseClicked(MouseEvent arg0) {
				log("mouseClicked(" + arg0 + ")");
			}

			@Override
			public void mouseEntered(MouseEvent arg0) {
				log("mouseEntered(" + arg0 + ")");
			}

			@Override
			public void mouseExited(MouseEvent arg0) {
				log("mouseExited(" + arg0 + ")");
			}

			@Override
			public void mousePressed(MouseEvent arg0) {
				log("mousePressed(" + arg0 + ")");
				do_button_press_event(arg0);
			}

			@Override
			public void mouseReleased(MouseEvent arg0) {
				log("mouseReleased(" + arg0 + ")");
				do_button_release_event(arg0);
			}
		});

		this.addMouseMotionListener(new MouseMotionListener() {
			@Override
			public void mouseDragged(MouseEvent arg0) {
				log("mouseDragged(" + arg0 + ")");
			}

			@Override
			public void mouseMoved(MouseEvent arg0) {
				// log("mouseMoved("+arg0+")");
			}
		});

		this.addMouseWheelListener(new MouseWheelListener() {
			@Override
			public void mouseWheelMoved(MouseWheelEvent arg0) {
				log("mouseWheelMoved(" + arg0 + ")");
			}
		});

		// move: do_configure_event(arg1);
		// redraw: do_expose_event(arg0, arg1);
		// removed: do_delete_event(arg1);
		this.enableEvents(AWTEvent.ACTION_EVENT_MASK | AWTEvent.FOCUS_EVENT_MASK | AWTEvent.KEY_EVENT_MASK | AWTEvent.MOUSE_EVENT_MASK
				| AWTEvent.MOUSE_MOTION_EVENT_MASK | AWTEvent.MOUSE_WHEEL_EVENT_MASK | AWTEvent.PAINT_EVENT_MASK | AWTEvent.WINDOW_EVENT_MASK
				| AWTEvent.WINDOW_FOCUS_EVENT_MASK | AWTEvent.WINDOW_STATE_EVENT_MASK);
	}

	public void log(String str) {
		log(this, str);
	}

	public void log(Object instance, String str) {
		System.out.println(instance.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
	}

	@Override
	public void update_metadata(Map<String, Object> newMetadata) {
		for (Map.Entry<String, Object> me : newMetadata.entrySet())
			this.metadata.put(me.getKey(), me.getValue());

		String title = this.client.cast(newMetadata.get("title"), String.class);
		if (title == null)
			title = "unknown";
		this.setTitle(title);
		Map<?, ?> size_constraints = (Map<?, ?>) newMetadata.get("size-constraints");
		if (size_constraints != null) {
			// Map<?,?> hints = new HashMap<?,?>();
			/*
			 * for (a, h1, h2) in [ ("maximum-size", "max_width", "max_height"),
			 * ("minimum-size", "min_width", "min_height"), ("base-size",
			 * "base_width", "base_height"), ("increment", "width_inc",
			 * "height_inc"), ]: if a in self._metadata["size-constraints"]:
			 * hints[h1], hints[h2] = size_metadata[a] for (a, h) in [
			 * ("minimum-aspect", "min_aspect_ratio"), ("maximum-aspect",
			 * "max_aspect_ratio"), ]: if a in self._metadata: hints[h] =
			 * size_metadata[a][0] * 1.0 / size_metadata[a][1]
			 * self.set_geometry_hints(None, **hints)
			 */
		}

		/*
		 * WindowState state = this.getWindow().getState(); if
		 * (state==WindowState.WITHDRAWN) {
		 * //this.set_wmclass(*self._metadata.get("class-instance", ("xpra",
		 * "Xpra"))) if not (self.flags() & gtk.REALIZED):
		 * self.set_wmclass(*self._metadata.get("class-instance", ("xpra",
		 * "Xpra"))) }
		 */

		/*
		 * List<Object> icon = (List<Object>) metadata.get("icon"); if
		 * (icon!=null) { Integer width = (Integer) icon.get(0); Integer height
		 * = (Integer) icon.get(1); String coding = (String) icon.get(2); byte[]
		 * data = (byte[]) icon.get(3); assert coding.equals("premult_argb32");
		 * //ImageSurface cairo_surf = new ImageSurface(Format.ARGB32,
		 * width.intValue(), height.intValue()); //cairo_surf.get_data()[:] =
		 * data /* FIXME: We round-trip through PNG. This is ridiculous, but
		 * faster than doing a bunch of alpha un-premultiplying and
		 * byte-swapping by hand in Python (better still would be to write some
		 * Pyrex, but I don't have time right now) //PixbufLoader loader = new
		 * PixbufLoader(); //cairo_surf.writeToPNG(loader); //loader.close();
		 * //Pixbuf pixbuf = loader.getPixbuf(); //this.setIcon(pixbuf); }
		 */
	}

	protected void new_backing(int _w, int _h) {
		Image old_backing = this.backing;
		this.log("new_backing(" + _w + ", " + _h + ") old_backing=" + old_backing);
		if (old_backing != null) {
			this.backing = new BufferedImage(_w, _h, BufferedImage.TYPE_4BYTE_ABGR);
			this.graphics = this.backing.createGraphics();
			// Shape shape = null;
			// g.fill(shape);
			this.graphics.drawImage(old_backing, 0, 0, this);
		} else {
			this.backing = new BufferedImage(_w, _h, BufferedImage.TYPE_4BYTE_ABGR);
			this.graphics = this.backing.createGraphics();
		}
		this.log("new_backing(" + _w + ", " + _h + ") backing=" + this.backing);
	}

	/*
	 * protected void saveFailedPixbuf(String img_data) { if
	 * (!save_failed_pixbufs && this.failed_pixbuf_index>=10) return;
	 *
	 * this.failed_pixbuf_index++; String failed_pixbuf_file =
	 * "failed-pixbuf-"+System.currentTimeMillis()+".rgb24";
	 * this.savePixbuf(failed_pixbuf_file, img_data); }
	 */

	protected void savePixbuf(String filename, String img_data) {
		// FileWriter fw;
		FileOutputStream fos = null;
		try {
			// fw = new FileWriter(failed_pixbuf_file);
			// fw.write(img_data);
			// fw.close();
			fos = new FileOutputStream(filename);
			for (char c : img_data.toCharArray())
				fos.write(c);
			fos.close();
			this.log("saved pixmap to " + filename);
		} catch (IOException e) {
			this.log("failed to save pixmap to " + filename + ": " + e);
			e.printStackTrace(System.out);
		}
	}

	@Override
	public void draw(int _x, int _y, int width, int height, String coding, byte[] img_data) {
		if (DEBUG_REDRAWS)
			this.log("draw(" + _x + ", " + _y + ", " + width + ", " + height + ", " + coding + ", [..])");
		// Context gc = new Context(this.getWindow());
		if (!coding.equals("rgb24")) {
			// Pixbuf pixbuf = null;
			try {
				/*
				 * byte[] bytes = new byte[img_data.length()]; int index = 0;
				 * for (char c : img_data.toCharArray()) bytes[index++] = (byte)
				 * c;
				 */
				byte[] bytes = img_data;
				BufferedImage i = ImageIO.read(new ByteArrayInputStream(bytes));
				if (i == null) {
					// this.saveFailedPixbuf(img_data);
					throw new IllegalArgumentException("cannot parse image data: " + bytes.length + " bytes");
				}
				// else if (save_successful_pixbufs)
				// this.savePixbuf("OK-pixbuf-"+System.currentTimeMillis(),
				// img_data);
				if (DEBUG_REDRAWS)
					this.log("draw(" + _x + ", " + _y + ", " + width + ", " + height + ", " + coding + ", [..]) going to drawImage");
				if (this.graphics.drawImage(i, _x, _y, new ImageObserver() {
					@Override
					public boolean imageUpdate(Image img, int infoflags, int __x, int __y, int _w, int _h) {
						if (DEBUG_REDRAWS)
							log(this, "imageUpdate(" + img + ", " + infoflags + ", " + __x + ", " + __y + ", " + _w + ", " + _h + ")");
						if ((infoflags & ImageObserver.WIDTH) != 0 && (infoflags & ImageObserver.HEIGHT) != 0) {
							Insets insets = getInsets();
							repaint(100, __x + insets.left, __y + insets.top, _w, _h);
						}
						return false;
					}
				})) {
					Insets insets = this.getInsets();
					this.repaint(100, _x + insets.left, _y + insets.top, width, height);
				}
			} catch (IOException e) {
				this.log("failed " + coding + " len=" + img_data.length);
				e.printStackTrace(System.out);
				// this.saveFailedPixbuf(img_data);
			}
		} else {
			assert img_data.length == width * height * 3;
			// int dither = 0; //RgbDither.NONE;
			// this._backing.draw_rgb_image(gc, x, y, width, height, dither,
			// img_data);
			// image = Toolkit.getDefaultToolkit().createImage(new
			// MemoryImageSource(width, height,
			// colorModel, generatePixels(width, height, loc), 0, width));
		}
		// this.repaint();
	}

	/*
	 * public boolean do_expose_event(Widget source, EventExpose event) {
	 * //this.log("expose event: "+event); WindowState state =
	 * this.getWindow().getState(); //if (!this.flags() & Flags.MAPPED) return
	 * False; if (state==WindowState.WITHDRAWN) return false; if
	 * (event.getWindow()!=this.getWindow())
	 * this.log("expose incorrect window?!"); Rectangle r = event.getArea();
	 * Context cr = new Context(event); cr.setOperator(Operator.SOURCE);
	 * cr.setSource(this.backing, 0d, 0d); cr.paint();
	 * this.log("expose event showing "+this.backing+" to "+r); if
	 * (save_backing) try {
	 * this.backing.writeToPNG("backing-exposed-"+System.currentTimeMillis
	 * ()+".png"); } catch (IOException e) {
	 * this.log("expose failed to save backing: "+e); } return false; }
	 */

	public void do_map_event(WindowEvent event) {
		log("Got map event");
		// super.connect(handler);
		// gtk.Window.do_map_event(self, event)
		if (!this.override_redirect) {
			Window window = event.getWindow();
			if (this != window)
				log("wrong window!?");
			Point l = this.getLocation();
			Dimension d = this.getSize();
			this.client.send("map-window", this.id, l.x, l.y, d.width, d.height);
			this.x = l.x;
			this.y = l.y;
			this.w = d.width;
			this.h = d.height;
		}
	}

	public void do_configure_event() {
		log("Got configure event");
		// gtk.Window.do_configure_event(self, event)
		if (!this.override_redirect) {
			/*
			 * Rectangle r = this.geometry(); if (r.getX()!=this.x ||
			 * r.getY()!=this.y) { this.x = r.getX(); this.y = r.getY();
			 * this.client.send("move-window", this.id, x, y); } if
			 * (r.getWidth()!=this.w || r.getHeight()!=this.h) { this.w =
			 * r.getWidth(); this.h = r.getHeight();
			 * this.client.send("resize-window", this.id, w, h);
			 * this.new_backing(w, h); }
			 */
		}
	}

	@Override
	public void move_resize(int _x, int _y, int _w, int _h) {
		this.log("move resize");
		assert this.override_redirect;
		// this.getWindow().move_resize(x, y, w, h);
		this.new_backing(_w, _h);
	}

	public void do_unmap_event() {
		this.log("unmap");
		if (!this.override_redirect)
			this.client.send("unmap-window", this.id);
	}

	public void do_delete_event() {
		this.log("delete");
		this.client.send("close-window", this.id);
	}

	protected void key_action(KeyEvent event, boolean depressed) {
		char c = event.getKeyChar();
		String code = String.valueOf(c);
		List<String> modifiers = Keys.mask_to_names(event.getModifiers());
		String name = KeyEvent.getKeyText(c);
		int keyval = event.getKeyCode();
		int keycode = 0;
		if (Keys.codeToKeycode.containsKey(keyval))
			keycode = Keys.codeToKeycode.get(keyval);

		this.log("key_action(" + event + ", " + depressed + ") int(char)=" + new Integer(c) + ", code=" + code + ", keyText=" + name);
		Map<Character, String> map = null;
		if (Keys.codeToName.containsKey(event.getKeyCode())) {
			code = Keys.codeToName.get(event.getKeyCode());
			name = code;
		} else {
			if (event.getKeyLocation() == KeyEvent.KEY_LOCATION_NUMPAD)
				map = Keys.numpadToName;
			else
				map = Keys.charsToName;
			if (modifiers.contains("control")) {
				if (name.equals("Cancel")) {
					name = "c";
					code = "c";
				} else if (name.equals("Clear")) {
					name = "l";
					code = "l";
				}
			} else {
				if (map.containsKey(c)) {
					code = map.get(c);
					name = code;
				}
			}
		}
		this.client.send("key-action", this.id, code, boolint(depressed), modifiers, keyval, name, keycode);
	}

	protected int boolint(boolean b) {
		return b ? 1 : 0;
	}

	protected void pointer_modifiers(Object event) {
		// pointer = (int(event.x_root), int(event.y_root))
		// modifiers = self._client.mask_to_names(event.state)
		// return pointer, modifiers
	}

	public void do_motion_notify_event() {
		// this.log("motion");
		// (pointer, modifiers) = self._pointer_modifiers(event)
		// this.client.send_mouse_position("pointer-position", this.id, pointer,
		// modifiers])
	}

	protected void button_action(Object button, MouseEvent event, boolean depressed) {
		this.log("button");
		// (pointer, modifiers) = self._pointer_modifiers(event)
		// this.client.send_positional("button-action", this.id, button,
		// depressed, pointer, modifiers);
	}

	public void do_button_press_event(MouseEvent event) {
		// this.button_action(event.button, event, true);
	}

	public void do_button_release_event(MouseEvent event) {
		// this.button_action(event.button, event, False);
	}

	public void do_scroll_event(Object event) {
		this.log("scroll");
		// Map scroll directions back to mouse buttons. Mapping is taken from
		// gdk/x11/gdkevents-x11.c.
		/*
		 * scroll_map = {gtk.gdk.SCROLL_UP: 4, gtk.gdk.SCROLL_DOWN: 5,
		 * gtk.gdk.SCROLL_LEFT: 6, gtk.gdk.SCROLL_RIGHT: 7, }
		 */
		// this.button_action(scroll_map[event.direction], event, true);
		// this.button_action(scroll_map[event.direction], event, false);
	}

	public void do_focus_event(boolean in) {
		this.log("focus");
	}

	protected void focus_change(Object... args) {
		// this.client.update_focus(this.id,
		// this.getProperty("has-toplevel-focus"));
	}

	@Override
	public void destroy() {
		this.setVisible(false);
		this.dispose();
	}
}
