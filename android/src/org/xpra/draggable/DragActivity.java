package org.xpra.draggable;

import org.xpra.R;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.widget.Toast;

/**
 * This activity presents two images and a text view and allows them to be
 * dragged around. Press and hold on a view initiates a drag.
 *
 * <p>
 * This activity is derviced from the Android Launcher class.
 *
 */

public class DragActivity extends Activity implements View.OnLongClickListener, View.OnClickListener {

	// Object that sends out drag-drop events while a view is being moved.
	private DragController mDragController;
	private DragLayer mDragLayer; // The ViewGroup that supports drag-drop.

	public static boolean Debugging = false;

	/**
	 * onCreate - called when the activity is first created.
	 *
	 * Creates a drag controller and sets up three views so click and long click
	 * on the views are sent to this activity. The onLongClick method starts a
	 * drag sequence.
	 *
	 */

	@Override
	protected void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);
		this.mDragController = new DragController(this);

		this.setContentView(R.layout.draggable);
		this.setupViews();
	}

	/**
	 * Handle a click on a view.
	 *
	 */
	@Override
	public void onClick(View v) {
		this.toast("You clicked. Try a long click");
	}

	/**
	 * Handle a long click.
	 *
	 * @param v
	 *            View
	 * @return boolean - true indicates that the event was handled
	 */
	@Override
	public boolean onLongClick(View v) {
		this.trace("onLongClick in view: " + v);
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
		return this.startDrag(v);
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

	/**
	 * Finds all the views we need and configure them to send click events to
	 * the activity.
	 *
	 */
	private void setupViews() {
		this.mDragLayer = (DragLayer) findViewById(R.id.drag_layer);
		this.mDragLayer.setDragController(this.mDragController);
		this.mDragController.addDropTarget(this.mDragLayer);

		this.toast("Press and hold to drag a view");
	}

	/**
	 * Show a string on the screen via Toast.
	 *
	 * @param msg
	 *            String
	 * @return void
	 */

	public void toast(String msg) {
		Toast.makeText(getApplicationContext(), msg, Toast.LENGTH_SHORT).show();
	}

	/**
	 * Send a message to the debug log and display it using Toast.
	 */

	public void trace(String msg) {
		if (!Debugging)
			return;
		Log.d("DragActivity", msg);
		toast(msg);
	}
}
