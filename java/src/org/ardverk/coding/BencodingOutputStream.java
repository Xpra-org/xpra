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

import java.io.DataOutput;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Array;
import java.util.Collection;
import java.util.Map;
import java.util.SortedMap;
import java.util.TreeMap;

/**
 * An implementation of of {@link OutputStream} that can produce Bencoded
 * (Bee-Encoded) data.
 */
public class BencodingOutputStream extends FilterOutputStream implements DataOutput {

	/**
	 * The {@link String} charset.
	 */
	private final String charset;

	/**
	 * Creates a {@link BencodingOutputStream} with the default charset.
	 */
	public BencodingOutputStream(OutputStream out) {
		this(out, BencodingUtils.UTF_8);
	}

	/**
	 * Creates a {@link BencodingOutputStream} with the given encoding.
	 */
	public BencodingOutputStream(OutputStream out, String charset) {
		super(out);

		if (charset == null) {
			throw new NullPointerException("charset");
		}

		this.charset = charset;
	}

	/**
	 * Returns the charset that is used to encode {@link String}s. The default
	 * value is UTF-8.
	 */
	public String getCharset() {
		return this.charset;
	}

	/**
	 * Writes an {@link Object}.
	 */
	@SuppressWarnings("unchecked")
	public void writeObject(Object value) throws IOException {

		if (value == null) {
			writeNull();

		} else if (value instanceof byte[]) {
			writeBytes((byte[]) value);

		} else if (value instanceof Boolean) {
			writeBoolean((Boolean) value);

		} else if (value instanceof Character) {
			writeChar((Character) value);

		} else if (value instanceof Number) {
			writeNumber((Number) value);

		} else if (value instanceof String) {
			writeString((String) value);

		} else if (value instanceof Collection<?>) {
			writeCollection((Collection<?>) value);

		} else if (value instanceof Map<?, ?>) {
			writeMap((Map<String, ?>) value);

		} else if (value instanceof Enum<?>) {
			writeEnum((Enum<?>) value);

		} else if (value.getClass().isArray()) {
			writeArray(value);

		} else {
			writeCustom(value);
		}
	}

	/**
	 * Bencode does not support null but you may override this method to
	 * implement a custom version. The default implementation throws an
	 * {@link IOException}.
	 */
	public void writeNull() throws IOException {
		throw new IOException("Null is not supported");
	}

	/**
	 * Overwrite this method to write custom objects. The default implementation
	 * throws an {@link IOException}.
	 */
	protected void writeCustom(Object value) throws IOException {
		throw new IOException("Cannot bencode " + value);
	}

	/**
	 * Writes the given byte-Array
	 */
	public void writeBytes(byte[] value) throws IOException {
		writeBytes(value, 0, value.length);
	}

	/**
	 * Writes the given byte-Array
	 */
	public void writeBytes(byte[] value, int offset, int length) throws IOException {
		write(Integer.toString(length).getBytes(this.charset));
		write(BencodingUtils.LENGTH_DELIMITER);
		write(value, offset, length);
	}

	/**
	 * Writes a boolean
	 */
	@Override
	public void writeBoolean(boolean value) throws IOException {
		writeNumber(value ? BencodingUtils.TRUE : BencodingUtils.FALSE);
	}

	/**
	 * Writes a char
	 */
	@Override
	public void writeChar(int value) throws IOException {
		writeString(Character.toString((char) value));
	}

	/**
	 * Writes a byte
	 */
	@Override
	public void writeByte(int value) throws IOException {
		writeNumber(Byte.valueOf((byte) value));
	}

	/**
	 * Writes a short
	 */
	@Override
	public void writeShort(int value) throws IOException {
		writeNumber(Short.valueOf((short) value));
	}

	/**
	 * Writes an int
	 */
	@Override
	public void writeInt(int value) throws IOException {
		writeNumber(Integer.valueOf(value));
	}

	/**
	 * Writes a long
	 */
	@Override
	public void writeLong(long value) throws IOException {
		writeNumber(Long.valueOf(value));
	}

	/**
	 * Writes a float
	 */
	@Override
	public void writeFloat(float value) throws IOException {
		writeNumber(Float.valueOf(value));
	}

	/**
	 * Writes a double
	 */
	@Override
	public void writeDouble(double value) throws IOException {
		writeNumber(Double.valueOf(value));
	}

	/**
	 * Writes a {@link Number}
	 */
	public void writeNumber(Number value) throws IOException {
		String num = value.toString();
		write(BencodingUtils.NUMBER);
		write(num.getBytes(this.charset));
		write(BencodingUtils.EOF);
	}

	/**
	 * Writes a {@link String}
	 */
	public void writeString(String value) throws IOException {
		writeBytes(value.getBytes(this.charset));
	}

	/**
	 * Writes a {@link Collection}.
	 */
	public void writeCollection(Collection<?> value) throws IOException {
		write(BencodingUtils.LIST);
		for (Object element : value) {
			writeObject(element);
		}
		write(BencodingUtils.EOF);
	}

	/**
	 * Writes a {@link Map}.
	 */
	public void writeMap(Map<?, ?> map) throws IOException {
		if (!(map instanceof SortedMap<?, ?>)) {
			map = new TreeMap<Object, Object>(map);
		}

		write(BencodingUtils.DICTIONARY);
		for (Map.Entry<?, ?> entry : map.entrySet()) {
			Object key = entry.getKey();
			Object value = entry.getValue();

			if (key instanceof String) {
				writeString((String) key);
			} else {
				writeBytes((byte[]) key);
			}
			writeObject(value);
		}
		write(BencodingUtils.EOF);
	}

	/**
	 * Writes an {@link Enum}.
	 */
	public void writeEnum(Enum<?> value) throws IOException {
		writeString(value.name());
	}

	/**
	 * Writes an array
	 */
	public void writeArray(Object value) throws IOException {
		write(BencodingUtils.LIST);
		int length = Array.getLength(value);
		for (int i = 0; i < length; i++) {
			writeObject(Array.get(value, i));
		}
		write(BencodingUtils.EOF);
	}

	/**
	 * Writes the given {@link String}
	 */
	@Override
	public void writeBytes(String value) throws IOException {
		writeString(value);
	}

	/**
	 * Writes the given {@link String}
	 */
	@Override
	public void writeChars(String value) throws IOException {
		writeString(value);
	}

	/**
	 * Writes an UTF encoded {@link String}
	 */
	@Override
	public void writeUTF(String value) throws IOException {
		writeBytes(value.getBytes(BencodingUtils.UTF_8));
	}
}
