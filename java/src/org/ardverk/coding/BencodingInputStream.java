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

import java.io.DataInput;
import java.io.EOFException;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * An implementation of {@link InputStream} that can decode Bencoded
 * (Bee-Encoded) data.
 */
public class BencodingInputStream extends FilterInputStream implements DataInput {

	/**
	 * The charset that is being used for {@link String}s.
	 */
	private final String charset;

	/**
	 * Whether or not all byte-Arrays should be decoded as {@link String}s.
	 */
	private final boolean decodeAsString;

	/**
	 * Creates a {@link BencodingInputStream} with the default encoding.
	 */
	public BencodingInputStream(InputStream in) {
		this(in, BencodingUtils.UTF_8, false);
	}

	/**
	 * Creates a {@link BencodingInputStream} with the given encoding.
	 */
	public BencodingInputStream(InputStream in, String charset) {
		this(in, charset, false);
	}

	/**
	 * Creates a {@link BencodingInputStream} with the default encoding.
	 */
	public BencodingInputStream(InputStream in, boolean decodeAsString) {
		this(in, BencodingUtils.UTF_8, decodeAsString);
	}

	/**
	 * Creates a {@link BencodingInputStream} with the given encoding.
	 */
	public BencodingInputStream(InputStream in, String charset, boolean decodeAsString) {
		super(in);

		if (charset == null) {
			throw new NullPointerException("charset");
		}

		this.charset = charset;
		this.decodeAsString = decodeAsString;
	}

	/**
	 * Returns the charset that is used to decode {@link String}s. The default
	 * value is UTF-8.
	 */
	public String getCharset() {
		return this.charset;
	}

	/**
	 * Returns true if all byte-Arrays are being turned into {@link String}s.
	 */
	public boolean isDecodeAsString() {
		return this.decodeAsString;
	}

	/**
	 * Reads and returns an {@link Object}.
	 */
	public Object readObject() throws IOException {
		int token = read();
		if (token == -1) {
			throw new EOFException();
		}

		return readObject(token);
	}

	/**
	 * Reads and returns an Object of the given type
	 */
	protected Object readObject(int token) throws IOException {
		if (token == BencodingUtils.DICTIONARY) {
			return readMap0(Object.class);

		} else if (token == BencodingUtils.LIST) {
			return readList0(Object.class);

		} else if (token == BencodingUtils.NUMBER) {
			return readNumber0();

		} else if (isDigit(token)) {
			byte[] data = readBytes(token);
			return this.decodeAsString ? new String(data, this.charset) : data;

		} else {
			return readCustom(token);
		}
	}

	/**
	 * Override this method to read custom objects of the given type
	 */
	protected Object readCustom(int token) throws IOException {
		throw new IOException("Not implemented: " + token);
	}

	/**
	 * Reads and returns a byte-Array.
	 */
	public byte[] readBytes() throws IOException {
		int token = read();
		if (token == -1) {
			throw new EOFException();
		}

		return readBytes(token);
	}

	/**
	 *
	 */
	private byte[] readBytes(int token) throws IOException {
		StringBuilder buffer = new StringBuilder();
		buffer.append((char) token);

		while ((token = read()) != BencodingUtils.LENGTH_DELIMITER) {
			if (token == -1) {
				throw new EOFException();
			}

			buffer.append((char) token);
		}

		int length = Integer.parseInt(buffer.toString());
		byte[] data = new byte[length];
		readFully(data);
		return data;
	}

	/**
	 * Reads and returns a {@link String}.
	 */
	public String readString() throws IOException {
		return readString(this.charset);
	}

	/**
	 *
	 */
	private String readString(String encoding) throws IOException {
		return new String(readBytes(), encoding);
	}

	/**
	 * Reads and returns an {@link Enum}.
	 */
	public <T extends Enum<T>> T readEnum(Class<T> clazz) throws IOException {
		return Enum.valueOf(clazz, readString());
	}

	/**
	 * Reads and returns a char.
	 */
	@Override
	public char readChar() throws IOException {
		return readString().charAt(0);
	}

	/**
	 * Reads and returns a boolean.
	 */
	@Override
	public boolean readBoolean() throws IOException {
		return readInt() != 0;
	}

	/**
	 * Reads and returns a byte.
	 */
	@Override
	public byte readByte() throws IOException {
		return readNumber().byteValue();
	}

	/**
	 * Reads and returns a short.
	 */
	@Override
	public short readShort() throws IOException {
		return readNumber().shortValue();
	}

	/**
	 * Reads and returns an int.
	 */
	@Override
	public int readInt() throws IOException {
		return readNumber().intValue();
	}

	/**
	 * Reads and returns a float.
	 */
	@Override
	public float readFloat() throws IOException {
		return readNumber().floatValue();
	}

	/**
	 * Reads and returns a long.
	 */
	@Override
	public long readLong() throws IOException {
		return readNumber().longValue();
	}

	/**
	 * Reads and returns a double.
	 */
	@Override
	public double readDouble() throws IOException {
		return readNumber().doubleValue();
	}

	/**
	 * Reads and returns a {@link Number}.
	 */
	public Number readNumber() throws IOException {
		int token = read();
		if (token == -1) {
			throw new EOFException();
		}

		if (token != BencodingUtils.NUMBER) {
			throw new IOException();
		}

		return readNumber0();
	}

	/**
	 *
	 */
	private Number readNumber0() throws IOException {
		StringBuilder buffer = new StringBuilder();

		boolean decimal = false;
		int token = -1;

		while ((token = read()) != BencodingUtils.EOF) {
			if (token == -1) {
				throw new EOFException();
			}

			if (token == '.') {
				decimal = true;
			}

			buffer.append((char) token);
		}

		try {
			if (decimal)
				return new BigDecimal(buffer.toString());
			return new BigInteger(buffer.toString());
		} catch (NumberFormatException err) {
			throw new IOException("NumberFormatException", err);
		}
	}

	/**
	 * Reads and returns an array of {@link Object}s
	 */
	public Object[] readArray() throws IOException {
		return readList().toArray();
	}

	/**
	 * Reads and returns an array of {@link Object}s
	 */
	public <T> T[] readArray(T[] a) throws IOException {
		return readList().toArray(a);
	}

	/**
	 * Reads and returns a {@link List}.
	 */
	public List<Object> readList() throws IOException {
		return readList(Object.class);
	}

	/**
	 * Reads and returns a {@link List}.
	 */
	public <T> List<T> readList(Class<T> clazz) throws IOException {
		int token = read();
		if (token == -1) {
			throw new EOFException();
		}

		if (token != BencodingUtils.LIST) {
			throw new IOException();
		}

		return readList0(clazz);
	}

	/**
	 *
	 */
	private <T> List<T> readList0(Class<T> clazz) throws IOException {
		List<T> list = new ArrayList<T>();
		int token = -1;
		while ((token = read()) != BencodingUtils.EOF) {
			if (token == -1) {
				throw new EOFException();
			}

			list.add(clazz.cast(readObject(token)));
		}
		return list;
	}

	/**
	 * Reads and returns a {@link Map}.
	 */
	public Map<String, ?> readMap() throws IOException {
		return readMap(Object.class);
	}

	/**
	 * Reads and returns a {@link Map}.
	 */
	public <T> Map<String, T> readMap(Class<T> clazz) throws IOException {
		int token = read();
		if (token == -1) {
			throw new EOFException();
		}

		if (token != BencodingUtils.DICTIONARY) {
			throw new IOException();
		}

		return readMap0(clazz);
	}

	/**
	 *
	 */
	private <T> Map<String, T> readMap0(Class<T> clazz) throws IOException {
		Map<String, T> map = new TreeMap<String, T>();
		int token = -1;
		while ((token = read()) != BencodingUtils.EOF) {
			if (token == -1) {
				throw new EOFException();
			}

			String key = new String(readBytes(token), this.charset);
			T value = clazz.cast(readObject());

			map.put(key, value);
		}

		return map;
	}

	/**
	 *
	 */
	@Override
	public void readFully(byte[] dst) throws IOException {
		readFully(dst, 0, dst.length);
	}

	/**
	 *
	 */
	@Override
	public void readFully(byte[] dst, int off, int len) throws IOException {
		int total = 0;

		while (total < len) {
			int r = read(dst, total, len - total);
			if (r == -1) {
				throw new EOFException();
			}

			total += r;
		}
	}

	/**
	 * Reads and returns a {@link String}.
	 *
	 * @see #readString().
	 */
	@Override
	public String readLine() throws IOException {
		return readString();
	}

	/**
	 * Reads and returns an unsigned byte.
	 */
	@Override
	public int readUnsignedByte() throws IOException {
		return readByte() & 0xFF;
	}

	/**
	 * Reads and returns an unsigned short.
	 */
	@Override
	public int readUnsignedShort() throws IOException {
		return readShort() & 0xFFFF;
	}

	/**
	 * Reads and returns an UTF encoded {@link String}.
	 */
	@Override
	public String readUTF() throws IOException {
		return readString(BencodingUtils.UTF_8);
	}

	/**
	 * Skips the given number of bytes.
	 */
	@Override
	public int skipBytes(int n) throws IOException {
		return (int) skip(n);
	}

	/**
	 * Returns true if the given token is a digit.
	 */
	private static boolean isDigit(int token) {
		return '0' <= token && token <= '9';
	}
}
