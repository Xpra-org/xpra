/*
 * This is a modified version of a class from the Android Open Source Project.

 * The original copyright and license information follows.
 *
 * Copyright (C) 2006 The Android Open Source Project
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
import android.util.AttributeSet;
import android.view.View;
import android.view.ViewGroup;
import android.widget.RemoteViews.RemoteView;

/**
 * A layout that lets you specify exact locations (x/y coordinates) of its
 * children. Absolute layouts are less flexible and harder to maintain than
 * other types of layouts without absolute positioning.
 *
 * <p>
 * <strong>XML attributes</strong>
 * </p>
 * <p>
 * See {@link android.R.styleable#ViewGroup ViewGroup Attributes},
 * {@link android.R.styleable#View View Attributes}
 * </p>
 *
 * <p>
 * Note: This class is a clone of AbsoluteLayout, which is now deprecated.
 */

@RemoteView
public class MyAbsoluteLayout extends ViewGroup {
	public MyAbsoluteLayout(Context context) {
		super(context);
	}

	public MyAbsoluteLayout(Context context, AttributeSet attrs) {
		super(context, attrs);
	}

	public MyAbsoluteLayout(Context context, AttributeSet attrs, int defStyle) {
		super(context, attrs, defStyle);
	}

	@Override
	protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
		int count = getChildCount();

		int maxHeight = 0;
		int maxWidth = 0;

		// Find out how big everyone wants to be
		measureChildren(widthMeasureSpec, heightMeasureSpec);

		// Find rightmost and bottom-most child
		for (int i = 0; i < count; i++) {
			View child = getChildAt(i);
			if (child.getVisibility() != GONE) {
				int childRight;
				int childBottom;

				MyAbsoluteLayout.AbsoluteLayoutParams lp = (MyAbsoluteLayout.AbsoluteLayoutParams) child.getLayoutParams();

				childRight = lp.x + child.getMeasuredWidth();
				childBottom = lp.y + child.getMeasuredHeight();

				maxWidth = Math.max(maxWidth, childRight);
				maxHeight = Math.max(maxHeight, childBottom);
			}
		}

		// Account for padding too
		maxWidth += getPaddingLeft() + getPaddingRight();
		maxHeight += getPaddingTop() + getPaddingBottom();
		/*
		 * original maxWidth += mPaddingLeft + mPaddingRight; maxHeight +=
		 * mPaddingTop + mPaddingBottom;
		 */

		// Check against minimum height and width
		maxHeight = Math.max(maxHeight, getSuggestedMinimumHeight());
		maxWidth = Math.max(maxWidth, getSuggestedMinimumWidth());

		setMeasuredDimension(resolveSize(maxWidth, widthMeasureSpec), resolveSize(maxHeight, heightMeasureSpec));
	}

	/**
	 * Returns a set of layout parameters with a width of
	 * {@link android.view.ViewGroup.LayoutParams#WRAP_CONTENT}, a height of
	 * {@link android.view.ViewGroup.LayoutParams#WRAP_CONTENT} and with the
	 * coordinates (0, 0).
	 */
	@Override
	protected ViewGroup.LayoutParams generateDefaultLayoutParams() {
		return new AbsoluteLayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, 0, 0);
	}

	@Override
	protected void onLayout(boolean changed, int l, int t, int r, int b) {
		int count = getChildCount();

		int paddingL = getPaddingLeft();
		int paddingT = getPaddingTop();
		for (int i = 0; i < count; i++) {
			View child = getChildAt(i);
			if (child.getVisibility() != GONE) {

				MyAbsoluteLayout.AbsoluteLayoutParams lp = (MyAbsoluteLayout.AbsoluteLayoutParams) child.getLayoutParams();

				int childLeft = paddingL + lp.x;
				int childTop = paddingT + lp.y;
				/*
				 * int childLeft = mPaddingLeft + lp.x; int childTop =
				 * mPaddingTop + lp.y;
				 */
				child.layout(childLeft, childTop, childLeft + child.getMeasuredWidth(), childTop + child.getMeasuredHeight());

			}
		}
	}

	@Override
	public ViewGroup.LayoutParams generateLayoutParams(AttributeSet attrs) {
		return new MyAbsoluteLayout.AbsoluteLayoutParams(getContext(), attrs);
	}

	// Override to allow type-checking of LayoutParams.
	@Override
	protected boolean checkLayoutParams(ViewGroup.LayoutParams p) {
		return p instanceof MyAbsoluteLayout.AbsoluteLayoutParams;
	}

	@Override
	protected ViewGroup.LayoutParams generateLayoutParams(ViewGroup.LayoutParams p) {
		return new AbsoluteLayoutParams(p);
	}

	/**
	 * Per-child layout information associated with MyAbsoluteLayout. See
	 * {@link android.R.styleable#MyAbsoluteLayout_Layout Absolute Layout
	 * Attributes} for a list of all child view attributes that this class
	 * supports.
	 */
	public static class AbsoluteLayoutParams extends ViewGroup.LayoutParams {
		/**
		 * The horizontal, or X, location of the child within the view group.
		 */
		public int x;
		/**
		 * The vertical, or Y, location of the child within the view group.
		 */
		public int y;

		/**
		 * Creates a new set of layout parameters with the specified width,
		 * height and location.
		 *
		 * @param width
		 *			the width, either {@link #MATCH_PARENT},
		 *			{@link #WRAP_CONTENT} or a fixed size in pixels
		 * @param height
		 *			the height, either {@link #MATCH_PARENT},
		 *			{@link #WRAP_CONTENT} or a fixed size in pixels
		 * @param x
		 *			the X location of the child
		 * @param y
		 *			the Y location of the child
		 */
		public AbsoluteLayoutParams(int width, int height, int x, int y) {
			super(width, height);
			this.x = x;
			this.y = y;
		}

		/**
		 * Creates a new set of layout parameters. The values are extracted from
		 * the supplied attributes set and context. The XML attributes mapped to
		 * this set of layout parameters are:
		 *
		 * <ul>
		 * <li><code>layout_x</code>: the X location of the child</li>
		 * <li><code>layout_y</code>: the Y location of the child</li>
		 * <li>All the XML attributes from
		 * {@link android.view.ViewGroup.LayoutParams}</li>
		 * </ul>
		 *
		 * @param c
		 *			the application environment
		 * @param attrs
		 *			the set of attributes from which to extract the layout
		 *			parameters values
		 */
		public AbsoluteLayoutParams(Context c, AttributeSet attrs) {
			super(c, attrs);
			/*
			 * FIX THIS eventually. Without this, I don't think you can put x
			 * and y in layout xml files. TypedArray a =
			 * c.obtainStyledAttributes(attrs,
			 * com.android.internal.R.styleable.AbsoluteLayout_Layout); x =
			 * a.getDimensionPixelOffset(
			 * com.android.internal.R.styleable.AbsoluteLayout_Layout_layout_x,
			 * 0); y = a.getDimensionPixelOffset(
			 * com.android.internal.R.styleable.AbsoluteLayout_Layout_layout_y,
			 * 0); a.recycle();
			 */
		}

		/**
		 * {@inheritDoc}
		 */
		public AbsoluteLayoutParams(ViewGroup.LayoutParams source) {
			super(source);
		}

		public String debug(String output) {
			return output + "Absolute.LayoutParams={width=" + sizeToString(this.width) + ", height=" + sizeToString(this.height) + " x=" + this.x + " y="
					+ this.y + "}";
		}

		@Override
		public String toString() {
			return	this.getClass().getSimpleName()+"("+this.x+","+this.y+" - "+this.width+"x"+this.height+")";
		}

		/**
		 * Converts the specified size to a readable String.
		 *
		 * @param size
		 *			the size to convert
		 * @return a String instance representing the supplied size
		 *
		 * @hide
		 */
		protected static String sizeToString(int size) {
			if (size == WRAP_CONTENT) {
				return "wrap-content";
			}
			if (size == MATCH_PARENT) {
				return "match-parent";
			}
			return String.valueOf(size);
		}
	} // end class

} // end class

