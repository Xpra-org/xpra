package xpra.gtk;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.imageio.ImageIO;

import org.freedesktop.cairo.Content;
import org.freedesktop.cairo.Context;
import org.freedesktop.cairo.Operator;
import org.freedesktop.cairo.Surface;
import org.gnome.gdk.Event;
import org.gnome.gdk.EventButton;
import org.gnome.gdk.EventConfigure;
import org.gnome.gdk.EventFocus;
import org.gnome.gdk.EventKey;
import org.gnome.gdk.EventMask;
import org.gnome.gdk.EventMotion;
import org.gnome.gdk.EventScroll;
import org.gnome.gdk.Keyval;
import org.gnome.gdk.ModifierType;
import org.gnome.gdk.Pixbuf;
import org.gnome.gdk.Rectangle;
import org.gnome.gdk.WindowTypeHint;
import org.gnome.gtk.DrawingArea;
import org.gnome.gtk.Widget;

import xpra.CastHelper;
import xpra.Client;
import xpra.ClientWindow;

public class GtkWindow extends org.gnome.gtk.Window implements ClientWindow {
	protected Client client = null;
	protected int id = -1;
	protected int x = -1;
	protected int y = -1;
	protected int w = -1;
	protected int h = -1;
	protected Map<String, Object> metadata = null;
	protected boolean override_redirect = false;
	protected int failed_pixbuf_index = 0;
	protected Surface backing = null;
	protected DrawingArea drawingArea = null;

	public static final boolean save_failed_pixbufs = false;
	public static final boolean save_successful_pixbufs = true;
	public static final boolean save_backing = true;

	public GtkWindow(Client client, int id, int x, int y, int w, int h, Map<String, Object> metadata, boolean override_redirect) {
		super();
		this.log("<init>(" + client + ", " + id + ", " + x + ", " + y + ", " + w + ", " + h + ", " + metadata + ", " + override_redirect + ")");
		if (override_redirect)
			this.setTypeHint(WindowTypeHint.UTILITY);
		else
			this.setTypeHint(WindowTypeHint.NORMAL);
		this.client = client;
		this.id = id;
		this.x = x;
		this.y = y;
		this.w = w;
		this.h = h;
		this.metadata = new HashMap<String, Object>();
		this.override_redirect = override_redirect;
		this.update_metadata(metadata);

		this.drawingArea = new DrawingArea();
		this.add(this.drawingArea);

		// this.setAppPaintable(true);
		// ensure the events will fire:
		this.mapEvents();
		EventMask[] masks = new EventMask[] { EventMask.STRUCTURE, EventMask.FOCUS_CHANGE, EventMask.SCROLL, EventMask.VISIBILITY_NOTIFY, EventMask.EXPOSURE,
				EventMask.KEY_PRESS, EventMask.KEY_RELEASE, EventMask.POINTER_MOTION, EventMask.BUTTON_PRESS, EventMask.BUTTON_RELEASE };
		for (EventMask m : masks)
			this.addEvents(m);

		// new_backing fails without a backing window...
		this.realize();
		this.new_backing(w, h);

		this.move(x, y);
		this.resize(w, h);
		this.setDefaultSize(w, h);
	}

	protected void mapEvents() {
		// Here we just map events to the same method name used in the pygtk
		// version:
		this.connect(new MapEvent() {
			@Override
			public boolean onMapEvent(Widget arg0, Event arg1) {
				do_map_event(arg1);
				return false;
			}
		});
		this.connect(new ConfigureEvent() {
			@Override
			public boolean onConfigureEvent(Widget arg0, EventConfigure arg1) {
				do_configure_event(arg1);
				return false;
			}
		});
		/*
		 * this.drawingArea.connect(new ExposeEvent() {
		 *
		 * @Override public boolean onExposeEvent(Widget arg0, EventExpose arg1)
		 * { do_expose_event(arg0, arg1); return false; } });
		 */
		this.connect(new UnmapEvent() {
			@Override
			public boolean onUnmapEvent(Widget arg0, Event arg1) {
				do_unmap_event(arg1);
				return false;
			}
		});
		this.connect(new DeleteEvent() {
			@Override
			public boolean onDeleteEvent(Widget arg0, Event arg1) {
				do_delete_event(arg1);
				return false;
			}
		});
		this.connect(new KeyPressEvent() {
			@Override
			public boolean onKeyPressEvent(Widget arg0, EventKey arg1) {
				do_key_press_event(arg1);
				return false;
			}
		});
		this.connect(new KeyReleaseEvent() {
			@Override
			public boolean onKeyReleaseEvent(Widget arg0, EventKey arg1) {
				do_key_release_event(arg1);
				return false;
			}
		});
		this.connect(new MotionNotifyEvent() {
			@Override
			public boolean onMotionNotifyEvent(Widget arg0, EventMotion arg1) {
				do_motion_notify_event(arg1);
				return false;
			}
		});
		this.connect(new ButtonPressEvent() {
			@Override
			public boolean onButtonPressEvent(Widget arg0, EventButton arg1) {
				do_button_press_event(arg1);
				return false;
			}
		});
		this.connect(new ButtonReleaseEvent() {
			@Override
			public boolean onButtonReleaseEvent(Widget arg0, EventButton arg1) {
				do_button_release_event(arg1);
				return false;
			}
		});
		this.connect(new ScrollEvent() {
			@Override
			public boolean onScrollEvent(Widget arg0, EventScroll arg1) {
				do_scroll_event(arg1);
				return false;
			}
		});
		this.connect(new FocusInEvent() {
			@Override
			public boolean onFocusInEvent(Widget arg0, EventFocus arg1) {
				do_focus_event(arg1, true);
				return false;
			}
		});
		this.connect(new FocusOutEvent() {
			@Override
			public boolean onFocusOutEvent(Widget arg0, EventFocus arg1) {
				do_focus_event(arg1, false);
				return false;
			}
		});
	}

	public void log(String str) {
		System.out.println(this.getClass().getSimpleName() + "." + str.replaceAll("\r", "\\r").replaceAll("\n", "\\n"));
	}

	@Override
	public void update_metadata(Map<String, Object> newMetadata) {
		for (Map.Entry<String, Object> me : newMetadata.entrySet())
			this.metadata.put(me.getKey(), me.getValue());

		String title = CastHelper.cast(newMetadata.get("title"), String.class);
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
		 *
		 * List<Object> icon = (List<Object>) metadata.get("icon"); if
		 * (icon!=null) { Integer width = (Integer) icon.get(0); Integer height
		 * = (Integer) icon.get(1); String coding = (String) icon.get(2); byte[]
		 * data = (byte[]) icon.get(3); assert coding.equals("premult_argb32");
		 * ImageSurface cairo_surf = new ImageSurface(Format.ARGB32,
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
		Surface old_backing = this.backing;
		this.log("new_backing(" + _w + ", " + _h + ") old_backing=" + old_backing);
		Context cr = null;
		if (old_backing != null) {
			this.backing = old_backing.createSimilar(Content.COLOR, _w, _h);
			cr = new Context(this.backing);
			// Really we should respect bit-gravity here but... meh.
			cr.setOperator(Operator.SOURCE);
			// cr.setSource(old_backing, 0d, 0d);
			cr.paint();
			int old_w = this.w;
			int old_h = this.h;
			cr.moveTo(old_w, 0);
			cr.lineTo(_w, 0);
			cr.lineTo(_w, _h);
			cr.lineTo(0, _h);
			cr.lineTo(0, old_h);
			cr.lineTo(old_w, old_h);
			cr.closePath();
			old_backing.finish();
		} else {
			this.backing = new Context(this.getWindow()).getTarget().createSimilar(Content.COLOR, _w, _h);
			cr = new Context(this.backing);
			cr.rectangle(0, 0, _w, _h);
		}
		cr.setSource(1d, 1d, 1d);
		cr.fill();
		this.log("new_backing(" + _w + ", " + _h + ") backing=" + this.backing);
		// this.getWindow().setBackingPixmap(this.backing, false);
	}

	protected void saveFailedPixbuf(String img_data) {
		if (!save_failed_pixbufs && this.failed_pixbuf_index >= 10)
			return;

		this.failed_pixbuf_index++;
		String failed_pixbuf_file = "failed-pixbuf-" + System.currentTimeMillis() + ".rgb24";
		this.savePixbuf(failed_pixbuf_file, img_data);
	}

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
		this.log("draw(" + _x + ", " + _y + ", " + width + ", " + height + ", " + coding + ", [..])");
		// Context gc = new Context(this.getWindow());
		if (!coding.equals("rgb24")) {
			Pixbuf pixbuf = null;
			try {
				byte[] bytes = img_data;
				BufferedImage i = ImageIO.read(new ByteArrayInputStream(bytes));
				if (i == null) {
					// this.saveFailedPixbuf(img_data);
					throw new IllegalArgumentException("cannot parse image data: " + bytes.length + " bytes");
				}
				// else if (save_successful_pixbufs)
				// this.savePixbuf("OK-pixbuf-"+System.currentTimeMillis(),
				// img_data);
				ByteArrayOutputStream baos = new ByteArrayOutputStream();
				ImageIO.write(i, "PNG", baos);
				pixbuf = new Pixbuf(baos.toByteArray());
				// http://permalink.gmane.org/gmane.comp.gnome.bindings.java/1862
				Context gc = new Context(this.backing);
				gc.setSource(pixbuf, _x, _y);
				gc.paint();
				this.backing.flush();
				if (save_backing)
					this.backing.writeToPNG("backing-" + System.currentTimeMillis() + ".png");
				// this.backing.draw_pixbuf(gc, pixbuf, 0, 0, x, y, width,
				// height);
			} catch (IOException e) {
				this.log("failed " + coding + " pixbuf=" + pixbuf + " len=" + img_data.length);
				e.printStackTrace(System.out);
				// this.saveFailedPixbuf(img_data);
			}
		} else {
			assert img_data.length == width * height * 3;
			// int dither = 0; //RgbDither.NONE;
			// this._backing.draw_rgb_image(gc, x, y, width, height, dither,
			// img_data);
		}
		this.getWindow().invalidate(new Rectangle(_x, _y, width, height), true);
	}

	/*
	 * public boolean do_expose_event_test(Widget source, EventExpose event) {
	 * //this.log("expose event: "+event); Rectangle r = event.getArea();
	 * Context cr = new Context(event); cr.setSource(0.4, 0.5, 0.9, 1.0);
	 * cr.rectangle(r.getX(), r.getY(), r.getWidth(), r.getHeight()); cr.fill();
	 * this.log("do_expose_event("+source+", "+event+") filling "+r); return
	 * true; } public boolean do_expose_event(Widget source, EventExpose event)
	 * { //this.log("expose event: "+event); WindowState state =
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

	protected Rectangle geometry() {
		int _x = this.getWindow().getOriginX();
		int _y = this.getWindow().getOriginY();
		int _w = this.getWindow().getWidth();
		int _h = this.getWindow().getHeight();
		return new Rectangle(_x, _y, _w, _h);
	}

	public void do_map_event(Event event) {
		log("Got map event");
		// super.connect(handler);
		// gtk.Window.do_map_event(self, event)
		if (!this.override_redirect) {
			Rectangle r = this.geometry();
			this.client.send("map-window", this.id, r.getX(), r.getY(), r.getWidth(), r.getHeight());
			this.x = r.getX();
			this.y = r.getY();
			this.w = r.getWidth();
			this.h = r.getHeight();
		}
	}

	public void do_configure_event(Event event) {
		log("Got configure event");
		// gtk.Window.do_configure_event(self, event)
		if (!this.override_redirect) {
			Rectangle r = this.geometry();
			if (r.getX() != this.x || r.getY() != this.y) {
				this.x = r.getX();
				this.y = r.getY();
				this.client.send("move-window", this.id, this.x, this.y);
			}
			if (r.getWidth() != this.w || r.getHeight() != this.h) {
				this.w = r.getWidth();
				this.h = r.getHeight();
				this.client.send("resize-window", this.id, this.w, this.h);
				this.new_backing(this.w, this.h);
			}
		}
	}

	@Override
	public void move_resize(int _x, int _y, int _w, int _h) {
		this.log("move resize");
		assert this.override_redirect;
		// this.getWindow().move_resize(_x, _y, _w, _h);
		this.new_backing(_w, _h);
	}

	public void do_unmap_event(Event event) {
		this.log("unmap");
		if (!this.override_redirect)
			this.client.send("unmap-window", this.id);
	}

	public void do_delete_event(Event event) {
		this.log("delete");
		this.client.send("close-window", this.id);
	}

	protected void key_action(EventKey event, boolean depressed) {
		// this.log("key_action("+event+", "+depressed+")");
		Keyval key = event.getKeyval();
		ModifierType mod = event.getState();
		List<String> modifiers = Keys.mask_to_names(mod);
		this.log("key_action(" + event + ", " + depressed + ") key=" + key + ", mod=" + mod + ", modifiers=" + modifiers);
		String code = "" + key.toUnicode();
		String name = key.toString();
		if (name.startsWith("Keyval."))
			name = name.substring("Keyval.".length());
		if (name.endsWith("Left"))
			name = name.substring(0, name.length() - "Left".length());
		if (name.endsWith("Right"))
			name = name.substring(0, name.length() - "Right".length());
		if (name.equals("Return")) {
			code = "Return";
			name = "\r";
		}
		if (name.equals("Alt"))
			name = "alt";
		this.client.send("key-action", this.id, code, boolint(depressed), modifiers, 0, name, 0);
	}

	protected int boolint(boolean b) {
		return b ? 1 : 0;
	}

	public void do_key_press_event(EventKey event) {
		this.key_action(event, true);
	}

	public void do_key_release_event(EventKey event) {
		this.key_action(event, false);
	}

	protected void pointer_modifiers(Object event) {
		// pointer = (int(event.x_root), int(event.y_root))
		// modifiers = self._client.mask_to_names(event.state)
		// return pointer, modifiers
	}

	public void do_motion_notify_event(EventMotion event) {
		// this.log("motion");
		// (pointer, modifiers) = self._pointer_modifiers(event)
		// this.client.send_mouse_position("pointer-position", this.id, pointer,
		// modifiers])
	}

	protected void button_action(Object button, Object event, boolean depressed) {
		this.log("button");
		// (pointer, modifiers) = self._pointer_modifiers(event)
		// this.client.send_positional("button-action", this.id, button,
		// depressed, pointer, modifiers);
	}

	public void do_button_press_event(EventButton event) {
		// this.button_action(event.button, event, true);
	}

	public void do_button_release_event(EventButton event) {
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

	public void do_focus_event(EventFocus event, boolean in) {
		this.log("focus");
	}

	protected void focus_change(Object... args) {
		// this.client.update_focus(this.id,
		// this.getProperty("has-toplevel-focus"));
	}
}
