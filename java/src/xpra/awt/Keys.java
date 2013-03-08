package xpra.awt;

import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class Keys {

	public static final Map<Integer, String> codeToName = new ConcurrentHashMap<Integer, String>();
	public static final Map<Character, String> charsToName = new ConcurrentHashMap<Character, String>();
	public static final Map<Character, String> numpadToName = new ConcurrentHashMap<Character, String>();
	public static final Map<Integer, Integer> codeToKeycode = new ConcurrentHashMap<Integer, Integer>();
	public static int _keycode = 8;

	public static final void addKey(int vk, String name) {
		codeToName.put(vk, name);
		codeToKeycode.put(vk, _keycode++);
	}

	static {
		addKey(KeyEvent.VK_ESCAPE, "Escape");

		addKey(KeyEvent.VK_F1, "F1");
		addKey(KeyEvent.VK_F2, "F2");
		addKey(KeyEvent.VK_F3, "F3");
		addKey(KeyEvent.VK_F4, "F4");
		addKey(KeyEvent.VK_F5, "F5");
		addKey(KeyEvent.VK_F6, "F6");
		addKey(KeyEvent.VK_F7, "F7");
		addKey(KeyEvent.VK_F8, "F8");
		addKey(KeyEvent.VK_F9, "F9");
		addKey(KeyEvent.VK_F10, "F10");
		addKey(KeyEvent.VK_F11, "F11");
		addKey(KeyEvent.VK_F12, "F12");
		addKey(KeyEvent.VK_F13, "F13");
		addKey(KeyEvent.VK_F14, "F14");
		addKey(KeyEvent.VK_F15, "F15");
		addKey(KeyEvent.VK_F16, "F16");
		addKey(KeyEvent.VK_F17, "F17");
		addKey(KeyEvent.VK_F18, "F18");
		addKey(KeyEvent.VK_F19, "F19");
		addKey(KeyEvent.VK_F20, "F20");
		addKey(KeyEvent.VK_F21, "F21");
		addKey(KeyEvent.VK_F22, "F22");
		addKey(KeyEvent.VK_F23, "F23");
		addKey(KeyEvent.VK_F24, "F24");

		addKey(KeyEvent.VK_SPACE, "Space");
		addKey(KeyEvent.VK_BACK_SPACE, "BackSpace");
		addKey(KeyEvent.VK_DELETE, "Delete");
		addKey(KeyEvent.VK_ENTER, "Return");
		addKey(KeyEvent.VK_TAB, "Tab");
		addKey(KeyEvent.VK_ALT, "Alt");
		addKey(KeyEvent.VK_SCROLL_LOCK, "ScrollLock");
		addKey(KeyEvent.VK_NUM_LOCK, "NumLock");
		addKey(KeyEvent.VK_ASTERISK, "*");

		addKey(KeyEvent.VK_NUMPAD1, "1");
		addKey(KeyEvent.VK_NUMPAD2, "2");
		addKey(KeyEvent.VK_NUMPAD3, "3");
		addKey(KeyEvent.VK_NUMPAD4, "4");
		addKey(KeyEvent.VK_NUMPAD5, "5");
		addKey(KeyEvent.VK_NUMPAD6, "6");
		addKey(KeyEvent.VK_NUMPAD7, "7");
		addKey(KeyEvent.VK_NUMPAD8, "8");
		addKey(KeyEvent.VK_NUMPAD9, "9");
		addKey(KeyEvent.VK_NUMPAD0, "0");

		addKey(KeyEvent.VK_0, "0");
		addKey(KeyEvent.VK_1, "1");
		addKey(KeyEvent.VK_2, "2");
		addKey(KeyEvent.VK_3, "3");
		addKey(KeyEvent.VK_4, "4");
		addKey(KeyEvent.VK_5, "5");
		addKey(KeyEvent.VK_6, "6");
		addKey(KeyEvent.VK_7, "7");
		addKey(KeyEvent.VK_8, "8");
		addKey(KeyEvent.VK_9, "9");

		addKey(KeyEvent.VK_MINUS, "-");
		addKey(KeyEvent.VK_UNDERSCORE, "_");
		addKey(KeyEvent.VK_EQUALS, "=");
		addKey(KeyEvent.VK_PLUS, "+");
		addKey(KeyEvent.VK_BRACELEFT, "[");
		addKey(KeyEvent.VK_BRACERIGHT, "]");
		addKey(KeyEvent.VK_CAPS_LOCK, "CapsLock");

		addKey(KeyEvent.VK_COMMA, ",");
		addKey(KeyEvent.VK_QUOTE, "'");
		addKey(KeyEvent.VK_SHIFT, "Shift");
		addKey(KeyEvent.VK_PERIOD, ".");
		addKey(KeyEvent.VK_SLASH, "/");

		addKey(KeyEvent.VK_A, "A");
		addKey(KeyEvent.VK_B, "B");
		addKey(KeyEvent.VK_C, "C");
		addKey(KeyEvent.VK_D, "D");
		addKey(KeyEvent.VK_E, "E");
		addKey(KeyEvent.VK_F, "F");
		addKey(KeyEvent.VK_G, "G");
		addKey(KeyEvent.VK_H, "H");
		addKey(KeyEvent.VK_I, "I");
		addKey(KeyEvent.VK_J, "J");
		addKey(KeyEvent.VK_K, "K");
		addKey(KeyEvent.VK_L, "L");
		addKey(KeyEvent.VK_M, "M");
		addKey(KeyEvent.VK_N, "N");
		addKey(KeyEvent.VK_O, "O");
		addKey(KeyEvent.VK_P, "P");
		addKey(KeyEvent.VK_Q, "Q");
		addKey(KeyEvent.VK_R, "R");
		addKey(KeyEvent.VK_S, "S");
		addKey(KeyEvent.VK_T, "T");
		addKey(KeyEvent.VK_U, "U");
		addKey(KeyEvent.VK_V, "V");
		addKey(KeyEvent.VK_W, "W");
		addKey(KeyEvent.VK_X, "X");
		addKey(KeyEvent.VK_Y, "Y");
		addKey(KeyEvent.VK_Z, "Z");

		charsToName.put('`', "grave");
		charsToName.put('¬', "notsign");
		charsToName.put('!', "exclam");
		charsToName.put('"', "quotedbl");
		charsToName.put('£', "sterling");
		charsToName.put('$', "dollar");
		charsToName.put('%', "percent");
		charsToName.put('^', "asciicircum");
		charsToName.put('&', "ampersand");
		charsToName.put('*', "asterisk");
		charsToName.put('(', "parenleft");
		charsToName.put('_', "underscore");
		charsToName.put('+', "plus");
		charsToName.put('=', "equal");
		charsToName.put('\\', "backslash");
		charsToName.put('|', "bar");
		charsToName.put(',', "coma");
		charsToName.put('.', "period");
		charsToName.put('/', "slash");
		charsToName.put('<', "less");
		charsToName.put('>', "greater");
		charsToName.put('?', "question");
		charsToName.put(';', "semicolon");
		charsToName.put('\'', "apostrophe");
		charsToName.put('#', "numbersign");
		charsToName.put(':', "colon");
		charsToName.put('@', "at");
		charsToName.put('~', "ascitilde");
		charsToName.put('[', "bracketleft");
		charsToName.put(']', "bracketright");
		charsToName.put('{', "braceleft");
		charsToName.put('}', "braceright");

		numpadToName.put('/', "KP_Divide");
		numpadToName.put('*', "KP_Multiply");
		numpadToName.put('-', "KP_Substract");
		numpadToName.put('+', "KP_Add");
		numpadToName.put(' ', "KP_Enter");
	}

	protected static List<String> mask_to_names(int mod) {
		List<String> modifiers = new ArrayList<String>(5);
		if ((mod & InputEvent.META_MASK) != 0)
			modifiers.add("meta");
		if ((mod & InputEvent.CTRL_MASK) != 0)
			modifiers.add("control");
		if ((mod & InputEvent.ALT_MASK) != 0)
			modifiers.add("alt");
		if ((mod & InputEvent.SHIFT_MASK) != 0)
			modifiers.add("shift");
		if ((mod & InputEvent.ALT_GRAPH_MASK) != 0)
			modifiers.add("super");
		// this.log("mask_to_names("+mod+")="+modifiers);
		return modifiers;
	}
}
