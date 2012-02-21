package org.xpra;

import java.math.BigInteger;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Vector;

import org.xpra.draggable.DragLayer;
import org.xpra.draggable.MyAbsoluteLayout.AbsoluteLayoutParams;

import xpra.ClientWindow;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.os.Handler;
import android.util.AttributeSet;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.View.OnClickListener;
import android.view.View.OnFocusChangeListener;
import android.view.View.OnKeyListener;
import android.view.ViewGroup;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.RelativeLayout;
import android.widget.TextView;

public class XpraWindow extends RelativeLayout implements ClientWindow, OnKeyListener, OnFocusChangeListener, OnClickListener {

	// protected static Bitmap.Config bitmapConfig = Bitmap.Config.ARGB_8888;
	protected static Bitmap.Config bitmapConfig = Bitmap.Config.ARGB_4444;

	protected Handler handler = null;
	protected long drawCount = 0;

	protected XpraActivity activity = null;
	protected AndroidXpraClient client = null;

	protected RelativeLayout topBar = null;
	protected ImageView windowIcon = null;
	protected ImageButton maximise = null;
	protected ImageButton close = null;
	protected ImageView imageView = null;
	protected Bitmap backing = null;

	protected boolean maximized = false;
	protected AbsoluteLayoutParams unMaximizedLayoutParams = null;
	protected String title = "";
	protected int id = -1;

	protected int offsetX = 0;
	protected int offsetY = 20;
	protected AbsoluteLayoutParams layoutParams = null;
	protected Map<String, Object> metadata = null;
	protected boolean override_redirect = false;

	public final String TAG = this.getClass().getSimpleName();
	public static boolean DEBUG = false;

	protected void debug(String msg) {
		if (DEBUG)
			Log.i(this.TAG, msg);
	}

	protected void log(String msg) {
		Log.i(this.TAG, msg);
	}

	protected void error(String msg, Throwable t) {
		Log.e(this.TAG, msg, t);
	}

	public XpraWindow(Context context, AttributeSet attributes) {
		super(context, attributes);
	}

	protected XpraWindow(XpraActivity context, AndroidXpraClient client, int id, int x, int y, int w, int h, Map<String, Object> metadata,
			boolean override_redirect) {
		super(context);
		this.init(context, client, id, x, y, w, h, metadata, override_redirect);
	}

	protected void init(XpraActivity context, AndroidXpraClient _client, int _id, int x, int y, int w, int h, Map<String, Object> _metadata,
			boolean _override_redirect) {
		this.activity = context;
		this.handler = _client.context.handler;
		this.client = _client;
		this.id = _id;
		this.metadata = new HashMap<String, Object>();
		this.override_redirect = _override_redirect;
		this.topBar = (RelativeLayout) this.findViewById(R.id.xpra_window_top_bar);
		this.windowIcon = (ImageView) this.findViewById(R.id.xpra_window_icon);
		this.maximise = (ImageButton) this.findViewById(R.id.xpra_window_maximize);
		this.close = (ImageButton) this.findViewById(R.id.xpra_window_close);
		this.imageView = (ImageView) this.findViewById(R.id.xpra_window_contents);

		// adjust location so it is always shown:
		int min_margin = 32;
		if (x >= (this.client.getScreenWidth() - min_margin))
			x = this.client.getScreenWidth() - min_margin;
		if (y >= (this.client.getScreenHeight() - min_margin))
			y = this.client.getScreenHeight() - min_margin;
		if (this.override_redirect) {
			this.topBar.setVisibility(View.GONE);
			this.offsetY = 0;
		} else {
			this.topBar.setVisibility(View.VISIBLE);
			this.offsetY = 32; // TODO: measure bar!
		}
		this.setLayoutParams(new AbsoluteLayoutParams(w + this.offsetX, h + this.offsetY, x, y));
		this.maximise.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				maximize();
			}
		});
		this.close.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				close();
			}
		});
		if (!this.override_redirect) {
			// register the top bar as the area you can use to drag the whole
			// window:
			this.topBar.setOnLongClickListener(new OnLongClickListener() {
				@Override
				public boolean onLongClick(View v) {
					return XpraWindow.this.activity.onLongClick(XpraWindow.this);
				}
			});
		}

		this.new_backing(w, h);
		this.update_metadata(_metadata);

		this.setSoundEffectsEnabled(true);
		this.setLongClickable(true);
		this.setClickable(true);
		this.setFocusable(true);
		this.setFocusableInTouchMode(true);
		this.setOnKeyListener(this);
		this.setOnFocusChangeListener(this);

		// simulate that the window has been mapped (we are the display manager)
		this.do_map_event();
		if (!this.override_redirect)
			this.do_focus_event(true); // this.client.update_focus(this.id,
										// hasFocus);
	}

	public void do_map_event() {
		if (!this.override_redirect)
			this.client.send("map-window", this.id, this.layoutParams.x, this.layoutParams.y, this.layoutParams.width - this.offsetX, this.layoutParams.height
					- this.offsetY);
	}

	public void do_focus_event(boolean hasFocus) {
		this.client.update_focus(this.id, hasFocus);
	}

	@Override
	public void bringToFront() {
		super.bringToFront();
		this.do_focus_event(true);
	}

	@Override
	public AbsoluteLayoutParams getLayoutParams() {
		ViewGroup.LayoutParams lp = super.getLayoutParams();
		this.log("getLayoutParams() super=" + lp + ", local=" + this.layoutParams);
		return this.layoutParams;
	}

	@Override
	public void setLayoutParams(ViewGroup.LayoutParams layoutParams) {
		this.log("setLayoutParams(" + layoutParams + ")");
		super.setLayoutParams(layoutParams);
		this.layoutParams = (AbsoluteLayoutParams) layoutParams;
		if (!this.override_redirect)
			this.send_move();
	}

	@Override
	public String toString() {
		return this.getClass().getSimpleName() + "-" + this.id + "-" + this.title;
	}

	public void maximize() {
		log("maximize()");
		if (this.maximized) {
			this.setLayoutParams(this.unMaximizedLayoutParams);
		} else {
			this.unMaximizedLayoutParams = this.layoutParams;
			this.setLayoutParams(new AbsoluteLayoutParams(this.client.getScreenWidth(), this.client.getScreenHeight() - 20, 0, 20));
		}
		this.maximized = !this.maximized;
		this.new_backing(this.layoutParams.width, this.layoutParams.height);
		this.send_resize();
	}

	public void close() {
		this.log("close()");
		if (this.override_redirect)
			this.destroy();
		else
			this.client.send("close-window", this.id);
	}

	/*
	 * @Override protected void onMeasure(int widthMeasureSpec, int
	 * heightMeasureSpec) { this.setMeasuredDimension(this.w, this.h); }
	 */

	public void send_move() {
		this.client.send("move-window", this.id, this.layoutParams.x, this.layoutParams.y);
	}

	public void send_resize() {
		this.client.send("resize-window", this.id, this.layoutParams.width - this.offsetX, this.layoutParams.height - this.offsetY);
	}

	public void do_unmap_event() {
		this.log("unmap");
		if (!this.override_redirect)
			this.client.send("unmap-window", this.id);
	}

	@Override
	public boolean onKey(View v, int keyCode, KeyEvent event) {
		this.log("onKey(" + v + ", " + keyCode + ", " + event + ")");
		this.client.sendKeyAction(this.id, v, keyCode, event);
		return false;
	}

	@Override
	public boolean onKeyDown(int keyCode, KeyEvent event) {
		boolean b = super.onKeyDown(keyCode, event);
		this.log("onKeyDown(" + keyCode + ", " + event + ")=" + b);
		return b;
	}

	@Override
	public boolean onKeyUp(int keyCode, KeyEvent event) {
		boolean b = super.onKeyUp(keyCode, event);
		this.log("onKeyUp(" + keyCode + ", " + event + ")=" + b);
		return b;
	}

	protected void key_action(Object event, boolean depressed) {
		this.log("key_action(" + event + ", " + depressed + ")");
		char key = '?'; // event.getKeyChar();
		int keycode = 0; // event.getKeyCode();
		int location = 0; // event.getKeyLocation();
		String name = "?"; // KeyEvent.getKeyText(keycode);
		// String code = name;
		if (name.equals("Enter")) {
			// code = "return";
			name = "return";
		}
		if (name.equals("Alt"))
			name = "alt";
		String ks = "?";
		if (Character.isJavaIdentifierPart(key))
			ks = "" + key;
		this.log("key_action(" + event + ", " + depressed + ") key=" + key + ", keycode=" + keycode + ", location=" + location + ", name=" + name);
		List<String> modifiers = new ArrayList<String>(); // Keys.mask_to_names(mod);
		this.client.send("key-action", this.id, ks, boolint(depressed), modifiers, 0, name, 0);
	}

	protected int boolint(boolean b) {
		return b ? 1 : 0;
	}

	@Override
	public void onClick(View v) {
		// TODO Auto-generated method stub
		this.log("onClick(" + v + ")");
	}

	@Override
	public void onVisibilityChanged(View changedView, int visibility) {
		this.log("onVisibilityChanged(" + changedView + ", " + visibility + ")");
		super.onVisibilityChanged(changedView, visibility);
	}

	@Override
	public void onWindowFocusChanged(boolean hasWindowFocus) {
		this.log("onWindowFocusChanged(" + hasWindowFocus + ")");
		super.onWindowFocusChanged(hasWindowFocus);
	}

	@Override
	public void onSizeChanged(int _w, int _h, int oldw, int oldh) {
		this.log("onSizeChanged(" + _w + ", " + _h + ", " + oldw + ", " + oldh + ")");
		super.onSizeChanged(_w, _h, oldw, oldh);
	}

	@Override
	public void onFocusChanged(boolean gainFocus, int direction, Rect previouslyFocusedRect) {
		this.log("onFocusChange(" + gainFocus + ", " + direction + ", " + previouslyFocusedRect + ")");
		super.onFocusChanged(gainFocus, direction, previouslyFocusedRect);
	}

	@Override
	public void onFocusChange(View v, boolean hasFocus) {
		this.log("onFocusChange(" + v + ", " + hasFocus + ")");
		this.do_focus_event(hasFocus);
	}

	@Override
	public boolean onTouchEvent(MotionEvent ev) {
		this.debug("onTouchEvent(" + ev + ")");
		final int action = ev.getAction();
		if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
			DragLayer mDragLayer = this.client.context.mDragLayer;
			this.log("onTouchEvent(" + ev + ") rawX=" + ev.getRawX() + ", rawY=" + ev.getRawY() + ", dragLeft=" + mDragLayer.getLeft() + ", dragTop="
					+ mDragLayer.getTop() + ", offsetX=" + this.offsetX + ", offsetY=" + this.offsetY);
			// float ex = ev.getX()+mDragLayer.getLeft()+this.offsetX;
			// float ey = ev.getY()+mDragLayer.getTop()+this.offsetY;
			// ex = ev.getRawX()-mDragLayer.getLeft()-this.offsetX;
			// ey = ev.getRawY()-mDragLayer.getTop()-this.offsetY;
			float ex = ev.getX() + this.layoutParams.x - this.offsetX;
			float ey = ev.getY() + this.layoutParams.y - this.offsetY;
			// float ex = ev.getX();
			// float ey = ev.getY();
			Vector<Integer> pointer = new Vector<Integer>(2);
			pointer.add(new Float(ex).intValue());
			pointer.add(new Float(ey).intValue());
			// this.client.send_mouse_position("pointer-position", this.id,
			// pointer, "");
			int pressed = action == MotionEvent.ACTION_DOWN ? 1 : 0;
			this.client.send_positional("button-action", this.id, 1, pressed, pointer, "");
		}
		return super.onTouchEvent(ev);
	}

	@Override
	protected void onDraw(Canvas canvas) {
		this.log("onDraw(" + canvas + ")");
		super.onDraw(canvas);
	}

	public void new_backing(int _w, int _h) {
		if (this.backing != null) {
			Bitmap old = this.backing;
			if (old.getWidth() >= _w && old.getHeight() >= _h) {
				// we are shrinking the bitmap:
				this.backing = Bitmap.createBitmap(old, 0, 0, _w, _h);
			} else {
				this.backing = Bitmap.createBitmap(_w, _h, bitmapConfig);
				// draw the old bitmap onto it:
				Canvas canvas = new Canvas(this.backing);
				canvas.drawBitmap(old, 0.0f, 0.0f, null);
				this.invalidate();
			}
			old.recycle();
		} else
			this.backing = Bitmap.createBitmap(_w, _h, bitmapConfig);
		this.log("new_backing(" + _w + ", " + _h + ") backing=" + this.backing);
		this.imageView.setImageBitmap(this.backing);
	}

	@Override
	public void update_metadata(Map<String, Object> newMetadata) {
		this.log("update_metadata(" + newMetadata + ")");
		for (Map.Entry<String, Object> me : newMetadata.entrySet())
			this.metadata.put(me.getKey(), me.getValue());

		String t = this.client.cast(newMetadata.get("title"), String.class);
		if (t == null)
			t = "unknown";
		this.title = t;
		((TextView) this.findViewById(R.id.xpra_window_title)).setText(this.title);
		Object icon = newMetadata.get("icon");
		this.log("update_metadata(" + newMetadata + ") icon=" + icon + ", type=" + (icon == null ? null : icon.getClass()));
		if (icon != null) {
			List<?> iconData = (List<?>) icon;
			int w = ((BigInteger) iconData.get(0)).intValue();
			int h = ((BigInteger) iconData.get(1)).intValue();
			byte[] raw_format = (byte[]) iconData.get(2);
			String format = new String(raw_format);
			this.log("update_metadata(" + newMetadata + ") found " + w + "x" + h + " icon in " + format + " format");
			if (format.equals("png")) {
				byte[] blob = (byte[]) iconData.get(3);
				BitmapFactory.Options options = new BitmapFactory.Options();
				options.inSampleSize = 1;
				while (w > 64 || h > this.offsetY) {
					options.inSampleSize *= 2;
					w = w / 2;
					h = h / 2;
				}
				Bitmap bmp = BitmapFactory.decodeByteArray(blob, 0, blob.length, options);
				this.windowIcon.setImageBitmap(bmp);
			}
		}
		// Map<?,?> size_constraints = (Map<?,?>)
		// metadata.get("size-constraints");
	}

	@Override
	public void draw(final int _x, final int _y, final int width, final int height, String coding, byte[] img_data) {
		this.log("draw(" + _x + ", " + _y + ", " + width + ", " + height + ", " + coding + ", " + img_data + ")");
		Bitmap bitmap = null;
		if (img_data != null) {
			byte[] data = img_data;
			int l = img_data.length;
			try {
				bitmap = BitmapFactory.decodeByteArray(data, 0, l);
				// this.log("draw(...) bitmap=" + bitmap);
				synchronized (this.backing) {
					Canvas canvas = new Canvas(this.backing);
					canvas.drawBitmap(bitmap, null, new Rect(_x, _y, _x + width, _y + height), null);
					bitmap.recycle();
					bitmap = null;
					canvas = null;
				}
				this.handler.post(new Runnable() {
					@Override
					public void run() {
						int xs = _x + XpraWindow.this.offsetX;
						int ys = _y + XpraWindow.this.offsetY;
						invalidate(xs, ys, xs + width, ys + height);
					}
				});
				System.gc();
			} catch (Exception e) {
				this.error("draw(" + _x + ", " + _y + ", " + width + ", " + height + ", " + coding + ", " + img_data + ")", e);
			}
		}
	}

	@Override
	public void move_resize(int _x, int _y, int _w, int _h) {
		this.log("move_resize(" + _x + ", " + _y + ", " + _w + ", " + _h + ")");
		this.layoutParams.x = _x;
		this.layoutParams.y = _y;
		this.layoutParams.width = _w;
		this.layoutParams.height = _h;
		this.activity.mDragLayer.updateViewLayout(this, this.layoutParams);
	}

	@Override
	public void destroy() {
		this.log("destroy()");
		if (this.backing != null) {
			this.client.context.remove(this);
			this.backing.recycle();
			this.backing = null;
			/*
			 * this.handler.post(new Runnable() {
			 * 
			 * @Override public void run() { invalidate(getLeft(), getTop(),
			 * getLeft()+getWidth(), getTop()+getHeight()); } });
			 */
		}
	}

	@Override
	protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
		this.log("onLayout(" + changed + ", " + left + ", " + top + ", " + right + ", " + bottom + ")");
		super.onLayout(changed, left, top, right, bottom);
	}
}
