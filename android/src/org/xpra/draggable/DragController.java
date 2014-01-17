/*
 * This is a modified version of a class from the Android
 * Open Source Project. The original copyright and license information follows.
 *
 * Copyright (C) 2008 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *	  http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.xpra.draggable;

import java.util.ArrayList;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.IBinder;
import android.os.Vibrator;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;

/**
 * This class is used to initiate a drag within a view or across multiple views.
 * When a drag starts it creates a special view (a DragView) that moves around
 * the screen until the user ends the drag. As feedback to the user, this object
 * causes the device to vibrate as the drag begins.
 *
 */

public class DragController {
	private static final String TAG = "DragController";

	/** Indicates the drag is a move. */
	public static int DRAG_ACTION_MOVE = 0;

	/** Indicates the drag is a copy. */
	public static int DRAG_ACTION_COPY = 1;

	private static final int VIBRATE_DURATION = 35;

	private static final boolean PROFILE_DRAWING_DURING_DRAG = false;

	private Context mContext;
	private Vibrator mVibrator;

	// temporaries to avoid gc thrash
	private Rect mRectTemp = new Rect();
	private final int[] mCoordinatesTemp = new int[2];

	/** Whether or not we're dragging. */
	private boolean mDragging;

	/** X coordinate of the down event. */
	private float mMotionDownX;

	/** Y coordinate of the down event. */
	private float mMotionDownY;

	/** Info about the screen for clamping. */
	private DisplayMetrics mDisplayMetrics = new DisplayMetrics();

	/** Original view that is being dragged. */
	private View mOriginator;

	/** X offset from the upper-left corner of the cell to where we touched. */
	private float mTouchOffsetX;

	/** Y offset from the upper-left corner of the cell to where we touched. */
	private float mTouchOffsetY;

	/** Where the drag originated */
	private DragSource mDragSource;

	/** The data associated with the object being dragged */
	private Object mDragInfo;

	/** The view that moves around while you drag. */
	private DragView mDragView;

	/** Who can receive drop events */
	private ArrayList<DropTarget> mDropTargets = new ArrayList<DropTarget>();

	private DragListener mListener;

	/** The window token used as the parent for the DragView. */
	private IBinder mWindowToken;

	private View mMoveTarget;

	private DropTarget mLastDropTarget;

	private InputMethodManager mInputMethodManager;

	/**
	 * Interface to receive notifications when a drag starts or stops
	 */
	interface DragListener {

		/**
		 * A drag has begun
		 *
		 * @param source
		 *            An object representing where the drag originated
		 * @param info
		 *            The data associated with the object that is being dragged
		 * @param dragAction
		 *            The drag action: either
		 *            {@link DragController#DRAG_ACTION_MOVE} or
		 *            {@link DragController#DRAG_ACTION_COPY}
		 */
		void onDragStart(DragSource source, Object info, int dragAction);

		/**
		 * The drag has eneded
		 */
		void onDragEnd();
	}

	/**
	 * Used to create a new DragLayer from XML.
	 *
	 * @param context
	 *            The application's context.
	 */
	public DragController(Context context) {
		this.mContext = context;
		this.mVibrator = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
	}

	/**
	 * Starts a drag. It creates a bitmap of the view being dragged. That bitmap
	 * is what you see moving. The actual view can be repositioned if that is
	 * what the onDrop handle chooses to do.
	 *
	 * @param v
	 *            The view that is being dragged
	 * @param source
	 *            An object representing where the drag originated
	 * @param dragInfo
	 *            The data associated with the object that is being dragged
	 * @param dragAction
	 *            The drag action: either {@link #DRAG_ACTION_MOVE} or
	 *            {@link #DRAG_ACTION_COPY}
	 */
	public void startDrag(View v, DragSource source, Object dragInfo, int dragAction) {
		this.mOriginator = v;

		Bitmap b = getViewBitmap(v);
		if (b == null)
			// out of memory?
			return;

		int[] loc = this.mCoordinatesTemp;
		v.getLocationOnScreen(loc);
		int screenX = loc[0];
		int screenY = loc[1];

		this.startDrag(b, screenX, screenY, 0, 0, b.getWidth(), b.getHeight(), source, dragInfo, dragAction);

		b.recycle();

		if (dragAction == DRAG_ACTION_MOVE)
			v.setVisibility(View.GONE);
	}

	/**
	 * Starts a drag.
	 *
	 * @param b
	 *            The bitmap to display as the drag image. It will be re-scaled
	 *            to the enlarged size.
	 * @param screenX
	 *            The x position on screen of the left-top of the bitmap.
	 * @param screenY
	 *            The y position on screen of the left-top of the bitmap.
	 * @param textureLeft
	 *            The left edge of the region inside b to use.
	 * @param textureTop
	 *            The top edge of the region inside b to use.
	 * @param textureWidth
	 *            The width of the region inside b to use.
	 * @param textureHeight
	 *            The height of the region inside b to use.
	 * @param source
	 *            An object representing where the drag originated
	 * @param dragInfo
	 *            The data associated with the object that is being dragged
	 * @param dragAction
	 *            The drag action: either {@link #DRAG_ACTION_MOVE} or
	 *            {@link #DRAG_ACTION_COPY}
	 */
	public void startDrag(Bitmap b, int screenX, int screenY, int textureLeft, int textureTop, int textureWidth, int textureHeight, DragSource source,
			Object dragInfo, int dragAction) {
		if (PROFILE_DRAWING_DURING_DRAG) {
			android.os.Debug.startMethodTracing("Launcher");
		}

		// Hide soft keyboard, if visible
		if (this.mInputMethodManager == null) {
			this.mInputMethodManager = (InputMethodManager) this.mContext.getSystemService(Context.INPUT_METHOD_SERVICE);
		}
		this.mInputMethodManager.hideSoftInputFromWindow(this.mWindowToken, 0);

		if (this.mListener != null) {
			this.mListener.onDragStart(source, dragInfo, dragAction);
		}

		int registrationX = ((int) this.mMotionDownX) - screenX;
		int registrationY = ((int) this.mMotionDownY) - screenY;

		this.mTouchOffsetX = this.mMotionDownX - screenX;
		this.mTouchOffsetY = this.mMotionDownY - screenY;

		this.mDragging = true;
		this.mDragSource = source;
		this.mDragInfo = dragInfo;

		this.mVibrator.vibrate(VIBRATE_DURATION);
		DragView dragView = this.mDragView = new DragView(this.mContext, b, registrationX, registrationY, textureLeft, textureTop, textureWidth, textureHeight);
		dragView.show(this.mWindowToken, (int) this.mMotionDownX, (int) this.mMotionDownY);
	}

	/**
	 * Draw the view into a bitmap.
	 */
	private static Bitmap getViewBitmap(View v) {
		v.clearFocus();
		v.setPressed(false);

		boolean willNotCache = v.willNotCacheDrawing();
		v.setWillNotCacheDrawing(false);

		// Reset the drawing cache background color to fully transparent
		// for the duration of this operation
		int color = v.getDrawingCacheBackgroundColor();
		v.setDrawingCacheBackgroundColor(0);

		if (color != 0)
			v.destroyDrawingCache();

		v.buildDrawingCache();
		Bitmap cacheBitmap = v.getDrawingCache();
		if (cacheBitmap == null) {
			Log.e(TAG, "failed getViewBitmap(" + v + ")", new RuntimeException());
			return null;
		}

		Bitmap bitmap = Bitmap.createBitmap(cacheBitmap);
		// Restore the view
		v.destroyDrawingCache();
		v.setWillNotCacheDrawing(willNotCache);
		v.setDrawingCacheBackgroundColor(color);
		return bitmap;
	}

	/**
	 * Call this from a drag source view like this:
	 *
	 * <pre>
	 *  @Override
	 *  public boolean dispatchKeyEvent(KeyEvent event) {
	 *   return mDragController.dispatchKeyEvent(this, event)
	 * 		  || super.dispatchKeyEvent(event);
	 * </pre>
	 */
	public boolean dispatchKeyEvent(KeyEvent event) {
		Log.d(TAG, "dispatchKeyEvent(" + event + ") mDragging=" + this.mDragging);
		return this.mDragging;
	}

	/**
	 * Stop dragging without dropping.
	 */
	public void cancelDrag() {
		endDrag();
	}

	private void endDrag() {
		if (!this.mDragging)
			return;
		this.mDragging = false;
		if (this.mOriginator != null)
			this.mOriginator.setVisibility(View.VISIBLE);
		if (this.mListener != null)
			this.mListener.onDragEnd();
		if (this.mDragView != null) {
			this.mDragView.remove();
			this.mDragView = null;
		}
	}

	/**
	 * Call this from a drag source view.
	 */
	public boolean onInterceptTouchEvent(MotionEvent ev) {
		final int action = ev.getAction();
		Log.i(TAG, "onInterceptTouchEvent(" + ev + ")");

		if (action == MotionEvent.ACTION_DOWN)
			this.recordScreenSize();

		final int screenX = clamp((int) ev.getRawX(), 0, this.mDisplayMetrics.widthPixels);
		final int screenY = clamp((int) ev.getRawY(), 0, this.mDisplayMetrics.heightPixels);

		switch (action) {
		case MotionEvent.ACTION_MOVE:
			break;

		case MotionEvent.ACTION_DOWN:
			// Remember location of down touch
			this.mMotionDownX = screenX;
			this.mMotionDownY = screenY;
			this.mLastDropTarget = null;
			break;

		case MotionEvent.ACTION_CANCEL:
		case MotionEvent.ACTION_UP:
			if (this.mDragging)
				this.drop(screenX, screenY);
			this.endDrag();
			break;
		}
		return this.mDragging;
	}

	/**
	 * Sets the view that should handle move events.
	 */
	void setMoveTarget(View view) {
		this.mMoveTarget = view;
	}

	public boolean dispatchUnhandledMove(View focused, int direction) {
		return this.mMoveTarget != null && this.mMoveTarget.dispatchUnhandledMove(focused, direction);
	}

	/**
	 * Call this from a drag source view.
	 */
	public boolean onTouchEvent(MotionEvent ev) {
		Log.i(TAG, "onTouchEvent(" + ev + ") mDragging=" + this.mDragging);
		if (!this.mDragging)
			return false;

		final int action = ev.getAction();
		final int screenX = clamp((int) ev.getRawX(), 0, this.mDisplayMetrics.widthPixels);
		final int screenY = clamp((int) ev.getRawY(), 0, this.mDisplayMetrics.heightPixels);

		switch (action) {
		case MotionEvent.ACTION_DOWN:
			// Remember where the motion event started
			this.mMotionDownX = screenX;
			this.mMotionDownY = screenY;
			break;
		case MotionEvent.ACTION_MOVE:
			// Update the drag view. Don't use the clamped pos here so the
			// dragging looks like it goes off screen a little, intead of
			// bumping up against the edge.
			this.mDragView.move((int) ev.getRawX(), (int) ev.getRawY());
			// Drop on someone?
			final int[] coordinates = this.mCoordinatesTemp;
			DropTarget dropTarget = findDropTarget(screenX, screenY, coordinates);
			if (dropTarget != null) {
				if (this.mLastDropTarget == dropTarget) {
					dropTarget.onDragOver(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY, this.mDragView,
							this.mDragInfo);
				} else {
					if (this.mLastDropTarget != null) {
						this.mLastDropTarget.onDragExit(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY,
								this.mDragView, this.mDragInfo);
					}
					dropTarget.onDragEnter(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY,
							this.mDragView, this.mDragInfo);
				}
			} else {
				if (this.mLastDropTarget != null) {
					this.mLastDropTarget.onDragExit(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY,
							this.mDragView, this.mDragInfo);
				}
			}
			this.mLastDropTarget = dropTarget;
			break;
		case MotionEvent.ACTION_UP:
			if (this.mDragging)
				this.drop(screenX, screenY);
			this.endDrag();
			break;
		case MotionEvent.ACTION_CANCEL:
			this.cancelDrag();
		}
		return true;
	}

	private boolean drop(float x, float y) {
		final int[] coordinates = this.mCoordinatesTemp;
		DropTarget dropTarget = findDropTarget((int) x, (int) y, coordinates);

		if (dropTarget != null) {
			dropTarget.onDragExit(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY, this.mDragView,
					this.mDragInfo);
			if (dropTarget.acceptDrop(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY, this.mDragView,
					this.mDragInfo)) {
				dropTarget.onDrop(this.mDragSource, coordinates[0], coordinates[1], (int) this.mTouchOffsetX, (int) this.mTouchOffsetY, this.mDragView,
						this.mDragInfo);
				this.mDragSource.onDropCompleted((View) dropTarget, true);
				return true;
			}
			this.mDragSource.onDropCompleted((View) dropTarget, false);
			return true;
		}
		return false;
	}

	private DropTarget findDropTarget(int x, int y, int[] dropCoordinates) {
		final Rect r = this.mRectTemp;

		final ArrayList<DropTarget> dropTargets = this.mDropTargets;
		final int count = dropTargets.size();
		for (int i = count - 1; i >= 0; i--) {
			final DropTarget target = dropTargets.get(i);
			target.getHitRect(r);
			target.getLocationOnScreen(dropCoordinates);
			r.offset(dropCoordinates[0] - target.getLeft(), dropCoordinates[1] - target.getTop());
			if (r.contains(x, y)) {
				dropCoordinates[0] = x - dropCoordinates[0];
				dropCoordinates[1] = y - dropCoordinates[1];
				return target;
			}
		}
		return null;
	}

	/**
	 * Get the screen size so we can clamp events to the screen size so even if
	 * you drag off the edge of the screen, we find something.
	 */
	private void recordScreenSize() {
		((WindowManager) this.mContext.getSystemService(Context.WINDOW_SERVICE)).getDefaultDisplay().getMetrics(this.mDisplayMetrics);
	}

	/**
	 * Clamp val to be &gt;= min and &lt; max.
	 */
	private static int clamp(int val, int min, int max) {
		if (val < min)
			return min;
		else if (val >= max)
			return max - 1;
		else
			return val;
	}

	public void setWindowToken(IBinder token) {
		this.mWindowToken = token;
	}

	/**
	 * Sets the drag listner which will be notified when a drag starts or ends.
	 */
	public void setDragListener(DragListener l) {
		this.mListener = l;
	}

	/**
	 * Remove a previously installed drag listener.
	 */
	public void removeDragListener(DragListener l) {
		this.mListener = null;
	}

	/**
	 * Add a DropTarget to the list of potential places to receive drop events.
	 */
	public void addDropTarget(DropTarget target) {
		this.mDropTargets.add(target);
	}

	/**
	 * Don't send drop events to <em>target</em> any more.
	 */
	public void removeDropTarget(DropTarget target) {
		this.mDropTargets.remove(target);
	}
}
