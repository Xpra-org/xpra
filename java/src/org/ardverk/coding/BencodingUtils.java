/*
 * Copyright 2009 Roger Kapsi
 *
 *   Licensed under the Apache License, Version 2.0 (the "License");
 *   you may not use this file except in compliance with the License.
 *   You may obtain a copy of the License at
 *
 *	   http://www.apache.org/licenses/LICENSE-2.0
 *
 *   Unless required by applicable law or agreed to in writing, software
 *   distributed under the License is distributed on an "AS IS" BASIS,
 *   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *   See the License for the specific language governing permissions and
 *   limitations under the License.
 */

package org.ardverk.coding;

/**
 * Just a few constants and utility methods
 */
public interface BencodingUtils {

	/**
	 * Constant for UTF-8 String Encoding
	 */
	public static final String UTF_8 = "UTF-8";

	/**
	 * length:bytes
	 */
	public static final int LENGTH_DELIMITER = ':';

	/**
	 * d<key><value>e
	 */
	public static final int DICTIONARY = 'd';

	/**
	 * l<value>e
	 */
	public static final int LIST = 'l';

	/**
	 * i<number>e
	 */
	public static final int NUMBER = 'i';

	/**
	 * Marks the end of a {@link #DICTIONARY}, {@link #LIST} or {@link #NUMBER}.
	 */
	public static final int EOF = 'e';

	/**
	 * Boolean values are not really supported by Bencoding but we can write 1s
	 * for true.
	 */
	public static final Integer TRUE = Integer.valueOf(1);

	/**
	 * Boolean values are not really supported by Bencoding but we can write 0s
	 * for false.
	 */
	public static final Integer FALSE = Integer.valueOf(0);
}
