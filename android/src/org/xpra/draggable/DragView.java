/*
 * This is a modified version of a class from the Android Open Source Project.
 * The original copyright and license information follows.
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

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.os.IBinder;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;

/**
 * A DragView is a special view used by a DragController. During a drag
 * operation, what is actually moving on the screen is a DragView. A DragView is
 * constructed using a bitmap of the view the user really wants to move.
 *
 */

public class DragView extends View {

	// Number of pixels to add to the dragged item for scaling. Should be even
	// for pixel alignment.
	private static final int DRAG_SCALE = 0; // In Launcher, value is 40

	private Bitmap mBitmap;
	private Paint mPaint;
	private int mRegistrationX;
	private int mRegistrationY;

	private float mAnimationScale = 1.0f;

	private WindowManager.LayoutParams mLayoutParams;
	private WindowManager mWindowManager;

	/**
	 * Construct the drag view.
	 * <p>
	 * The registration point is the point inside our view that the touch events
	 * should be centered upon.
	 *
	 * @param context
	 *            A context
	 * @param bitmap
	 *            The view that we're dragging around. We scale it up when we
	 *            draw it.
	 * @param registrationX
	 *            The x coordinate of the registration point.
	 * @param registrationY
	 *            The y coordinate of the registration point.
	 */
	public DragView(Context context, Bitmap bitmap, int registrationX, int registrationY, int left, int top, int width, int height) {
		super(context);

		// mWindowManager = WindowManagerImpl.getDefault();
		this.mWindowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);

		Matrix scale = new Matrix();
		float scaleFactor = width;
		scaleFactor = (scaleFactor + DRAG_SCALE) / scaleFactor;
		scale.setScale(scaleFactor, scaleFactor);
		this.mBitmap = Bitmap.createBitmap(bitmap, left, top, width, height, scale, true);

		// The point in our scaled bitmap that the touch events are located
		this.mRegistrationX = registrationX + (DRAG_SCALE / 2);
		this.mRegistrationY = registrationY + (DRAG_SCALE / 2);
	}

	@Override
	protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
		setMeasuredDimension(this.mBitmap.getWidth(), this.mBitmap.getHeight());
	}

	@Override
	protected void onDraw(Canvas canvas) {
		float scale = this.mAnimationScale;
		if (scale < 0.999f) { // allow for some float error
			float width = this.mBitmap.getWidth();
			float offset = (width - (width * scale)) / 2;
			canvas.translate(offset, offset);
			canvas.scale(scale, scale);
		}
		canvas.drawBitmap(this.mBitmap, 0.0f, 0.0f, this.mPaint);
	}

	@Override
	protected void onDetachedFromWindow() {
		super.onDetachedFromWindow();
		this.mBitmap.recycle();
	}

	public void setPaint(Paint paint) {
		this.mPaint = paint;
		invalidate();
	}

	/**
	 * Create a window containing this view and show it.
	 *
	 * @param windowToken
	 *            obtained from v.getWindowToken() from one of your views
	 * @param touchX
	 *            the x coordinate the user touched in screen coordinates
	 * @param touchY
	 *            the y coordinate the user touched in screen coordinates
	 */
	public void show(IBinder windowToken, int touchX, int touchY) {
		WindowManager.LayoutParams lp;
		int pixelFormat = PixelFormat.TRANSLUCENT;

		lp = new WindowManager.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, touchX - this.mRegistrationX, touchY
				- this.mRegistrationY, WindowManager.LayoutParams.TYPE_APPLICATION_SUB_PANEL, WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
				| WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
		/* | WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM */, pixelFormat);
		// lp.token = mStatusBarView.getWindowToken();
		lp.gravity = Gravity.LEFT | Gravity.TOP;
		lp.token = windowToken;
		lp.setTitle("DragView");
		this.mLayoutParams = lp;

		this.mWindowManager.addView(this, lp);
	}

	/**
	 * Move the window containing this view.
	 *
	 * @param touchX
	 *            the x coordinate the user touched in screen coordinates
	 * @param touchY
	 *            the y coordinate the user touched in screen coordinates
	 */
	void move(int touchX, int touchY) {
		// This is what was done in the Launcher code.
		WindowManager.LayoutParams lp = this.mLayoutParams;
		lp.x = touchX - this.mRegistrationX;
		lp.y = touchY - this.mRegistrationY;
		this.mWindowManager.updateViewLayout(this, lp);
	}

	void remove() {
		this.mWindowManager.removeView(this);
	}
}
