package xpra;

import java.io.UnsupportedEncodingException;
import java.math.BigInteger;

/**
 * Utility class for doing type casting
 *
 */
public class CastHelper {

	@SuppressWarnings("unchecked")
	public static <T extends Object> T cast(Object in, Class<T> desiredType) {
		if (in == null)
			return null;
		Class<?> t = in.getClass();
		if (t.equals(desiredType) || desiredType.isAssignableFrom(t))
			return (T) in;
		if ((desiredType.equals(int.class) || desiredType.equals(Integer.class)) && t.equals(BigInteger.class))
			return (T) new Integer(((BigInteger) in).intValue());
		if ((desiredType.equals(long.class) || desiredType.equals(Integer.class)) && t.equals(BigInteger.class))
			return (T) new Long(((BigInteger) in).longValue());
		if (desiredType.equals(String.class) && t.isArray() && t.getComponentType().equals(byte.class))
			try {
				return (T) new String((byte[]) in, "UTF-8");
			} catch (UnsupportedEncodingException e) {
				// if you don't have UTF-8... you're already in big trouble!
				return (T) new String((byte[]) in);
			}
		if (desiredType.equals(String.class))
			return (T) String.valueOf(in);
		throw new IllegalArgumentException("cast(" + in + ", " + desiredType + ") don't know how to handle " + t);
	}
}
