package xpra;

import junit.framework.TestCase;
import junit.framework.TestSuite;

public abstract class AbstractTest extends TestCase {

	public static boolean DEBUG = false;
	public String TAG = this.getClass().getSimpleName();

	public String nn(String in) {
		if (in == null || in.length() == 0)
			return "";
		return in.replaceAll("\r", "\\r").replaceAll("\n", "\\n");
	}

	public void debug(String str) {
		if (DEBUG)
			log(str);
	}

	public void log(String str) {
		System.out.println(this.TAG + "." + nn(str));
	}

	public void error(String str) {
		this.log(str);
	}

	public void error(String str, Exception e) {
		this.error(str);
		e.printStackTrace(System.out);
	}

	public static TestSuite suite(Class<?>... tests) {
		TestSuite result = new TestSuite();
		for (Class<?> test : tests)
			result.addTest(new TestSuite(test));
		return result;
	}

	public static void run(Class<?>... tests) {
		junit.textui.TestRunner.run(suite(tests));
	}
}
