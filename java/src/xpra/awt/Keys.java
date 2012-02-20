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

	static {
		codeToName.put(KeyEvent.VK_F1, "F1");
		codeToName.put(KeyEvent.VK_F2, "F2");
		codeToName.put(KeyEvent.VK_F3, "F3");
		codeToName.put(KeyEvent.VK_F4, "F4");
		codeToName.put(KeyEvent.VK_F5, "F5");
		codeToName.put(KeyEvent.VK_F6, "F6");
		codeToName.put(KeyEvent.VK_F7, "F7");
		codeToName.put(KeyEvent.VK_F8, "F8");
		codeToName.put(KeyEvent.VK_F9, "F9");
		codeToName.put(KeyEvent.VK_F10, "F10");
		codeToName.put(KeyEvent.VK_F11, "F11");
		codeToName.put(KeyEvent.VK_F12, "F12");
		codeToName.put(KeyEvent.VK_F13, "F13");
		codeToName.put(KeyEvent.VK_F14, "F14");
		codeToName.put(KeyEvent.VK_F15, "F15");
		codeToName.put(KeyEvent.VK_F16, "F16");
		codeToName.put(KeyEvent.VK_F17, "F17");
		codeToName.put(KeyEvent.VK_F18, "F18");
		codeToName.put(KeyEvent.VK_F19, "F19");
		codeToName.put(KeyEvent.VK_F20, "F20");
		codeToName.put(KeyEvent.VK_F21, "F21");
		codeToName.put(KeyEvent.VK_F22, "F22");
		codeToName.put(KeyEvent.VK_F23, "F23");
		codeToName.put(KeyEvent.VK_F24, "F24");
		codeToName.put(KeyEvent.VK_SPACE, "space");
		codeToName.put(KeyEvent.VK_BACK_SPACE, "BackSpace");
		codeToName.put(KeyEvent.VK_ENTER, "Return");

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
