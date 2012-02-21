package org.xpra;

import java.io.IOException;
import java.io.UnsupportedEncodingException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketAddress;

import org.xpra.draggable.DragController;
import org.xpra.draggable.DragLayer;
import org.xpra.draggable.MyAbsoluteLayout.AbsoluteLayoutParams;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.ActivityManager.MemoryInfo;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.util.Log;
import android.view.View;
import android.view.View.OnClickListener;
import android.view.Window;
import android.widget.Toast;

public class XpraActivity extends Activity implements View.OnLongClickListener, View.OnClickListener {

	public static final String PARAM_HOST = "PARAM_HOST";
	public static final String PARAM_PORT = "PARAM_PORT";
	public static final String PARAM_PASSWORD = "PARAM_PASSWORD";

	// Object that sends out drag-drop events while a view is being moved.
	protected DragController mDragController;
	protected DragLayer mDragLayer; // The ViewGroup that supports drag-drop.

	protected final Handler handler = new Handler();
	protected AndroidXpraClient client = null;
	protected String host = null;
	protected int port = 0;
	protected byte[] password = null;

	protected String TAG = this.getClass().getSimpleName();

	@Override
	public void onConfigurationChanged(Configuration newConfig) {
		super.onConfigurationChanged(newConfig);
		this.client.checkOrientation();
	}

	@Override
	protected void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);
		this.requestWindowFeature(Window.FEATURE_NO_TITLE);
		this.setContentView(R.layout.draggable);
		this.mDragController = new DragController(this);
		this.setupViews();
		Log.i(this.TAG, "onCreate(" + savedInstanceState + ")");

		Intent intent = this.getIntent();
		Uri uri = intent.getData();
		if (uri != null) {
			Log.e(this.TAG, "onCreate(" + savedInstanceState + ") parsing uri: " + uri);
			this.host = uri.getHost();
			this.port = uri.getPort();
			String pwd = uri.getQueryParameter("password");
			try {
				this.password = pwd == null ? null : pwd.getBytes("UTF-8");
			} catch (UnsupportedEncodingException e) {
				Log.e(this.TAG, "onCreate(" + savedInstanceState + ") failed to parse password as UTF-8");
			}
		} else {
			Bundle extras = getIntent().getExtras();
			if (extras == null) {
				Log.e(this.TAG, "onCreate(" + savedInstanceState + ") missing extras");
				this.finish();
				return;
			}
			this.host = extras.getString(PARAM_HOST);
			this.port = extras.getInt(PARAM_PORT);
			this.password = extras.getByteArray(PARAM_PASSWORD);
		}
		Log.i(this.TAG, "onCreate(" + savedInstanceState + ") target: " + this.host + ":" + this.port);
		if (this.host == null || this.host.length() == 0 || this.port <= 0) {
			Log.e(this.TAG, "onCreate(" + savedInstanceState + ") invalid target: " + this.host + ":" + this.port);
			this.toast("Invalid target specified: " + this.host + ":" + this.port + ", cannot launch Xpra");
			this.finish();
			return;
		}
		MemoryInfo info = new MemoryInfo();
		ActivityManager activityManager = (ActivityManager) this.getApplicationContext().getSystemService(Context.ACTIVITY_SERVICE);
		if (activityManager != null) {
			activityManager.getMemoryInfo(info);
			Log.i(this.TAG, "onCreate(" + savedInstanceState + ") memory info=" + info);
		}
	}

	private void setupViews() {
		this.mDragLayer = (DragLayer) findViewById(R.id.drag_layer);
		this.mDragLayer.setDragController(this.mDragController);
		this.mDragController.addDropTarget(this.mDragLayer);

		this.mDragLayer.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				toast("invalidate()");
				XpraActivity.this.mDragLayer.invalidate();
			}
		});
		// Toast.makeText(getApplicationContext(),
		// "Press and hold to drag a view", Toast.LENGTH_LONG).show();
	}

	@Override
	public void onClick(View v) {
		Log.i(this.TAG, "onClick(" + v + ")");
		v.bringToFront();
	}

	@Override
	public boolean onLongClick(View v) {
		// Make sure the drag was started by a long press as opposed to a long
		// click.
		// (Note: I got this from the Workspace object in the Android Launcher
		// code.
		// I think it is here to ensure that the device is still in touch mode
		// as we start the drag operation.)
		if (!v.isInTouchMode()) {
			toast("isInTouchMode returned false. Try touching the view again.");
			return false;
		}
		return startDrag(v);
	}

	/**
	 * Start dragging a view.
	 * 
	 */

	public boolean startDrag(View v) {
		// Let the DragController initiate a drag-drop sequence.
		// I use the dragInfo to pass along the object being dragged.
		// I'm not sure how the Launcher designers do this.
		this.mDragController.startDrag(v, this.mDragLayer, v, DragController.DRAG_ACTION_MOVE);
		return true;
	}

	@Override
	protected void onResume() {
		super.onResume();
		Log.e(this.TAG, "onResume()");
		if (this.host != null && this.port > 0)
			this.connect();
	}

	protected void connect() {
		try {
			Log.e(this.TAG, "connect() to " + this.host + ":" + this.port);
			SocketAddress sockaddr = new InetSocketAddress(this.host, this.port);
			Socket sock = new Socket();
			int timeout = 5 * 1000;
			sock.connect(sockaddr, timeout);
			sock.setKeepAlive(true);
			this.client = new AndroidXpraClient(this, sock.getInputStream(), sock.getOutputStream());
			this.client.setPassword(this.password);
			this.client.setOnExit(new Runnable() {
				@Override
				public void run() {
					XpraActivity.this.handler.post(new Runnable() {
						@Override
						public void run() {
							toast("Xpra client disconnected");
							finish();
						}
					});
				}
			});
			new Thread(this.client).start();
		} catch (IOException e) {
			Log.e(this.TAG, "connect()", e);
			this.finish();
		}
	}

	@Override
	protected void onPause() {
		super.onPause();
		Log.e(this.TAG, "onPause() hasEnded=" + (this.client == null ? null : this.client.hasEnded()));
		if (!this.client.hasEnded()) {
			this.client.stop();
			this.client = null;
		}
	}

	public void add(final XpraWindow window) {
		this.handler.post(new Runnable() {
			@Override
			public void run() {
				AbsoluteLayoutParams lp = window.getLayoutParams();
				XpraActivity.this.mDragLayer.addView(window, lp);
				window.setOnClickListener(XpraActivity.this);
			}
		});
	}

	public void remove(final XpraWindow window) {
		this.handler.post(new Runnable() {
			@Override
			public void run() {
				XpraActivity.this.mDragLayer.removeView(window);
			}
		});
	}

	public void toast(String msg) {
		Toast.makeText(getApplicationContext(), msg, Toast.LENGTH_SHORT).show();
	}
}