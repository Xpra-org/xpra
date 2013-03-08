package xpra;

import java.awt.event.KeyEvent;
import java.awt.im.InputContext;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import xpra.awt.Keys;

/**
 * Abstract utility superclass for all Xpra client implementations.
 * Adds InputContext / KeyCode support
 *
 */
public abstract class InputContextClient extends AbstractClient {

	public InputContextClient(InputStream is, OutputStream os) {
		super(is, os);
	}

	@Override
	protected String getKeyboardLayout() {
		InputContext ic = InputContext.getInstance();
		Locale locale = ic.getLocale();
		if (locale==null)
			locale = Locale.getDefault();
		return locale.getCountry().toLowerCase();
	}
	protected List<Object> makeKeySpec(int vk) {
		String keyname = Keys.codeToName.get(vk);
		int keycode = Keys.codeToKeycode.get(vk);
		if (keyname==null)
			throw new IllegalArgumentException("unknown key: "+vk);
		return this.makeKeySpec(vk, keyname, keycode, 0, 0);
	}
	protected List<Object> makeKeySpec(int keyval, String keyname, int keycode) {
		return this.makeKeySpec(keyval, keyname, keycode, 0, 0);
	}
	protected List<Object> makeKeySpec(int keyval, String keyname, int keycode, int group, int level) {
		List<Object> keySpec = new ArrayList<Object>(5);
		keySpec.add(keyval);
		keySpec.add(keyname);
		keySpec.add(keycode);
		keySpec.add(group);
		keySpec.add(level);
		return keySpec;
	}

	@Override
	protected List<?>[]	getKeycodes() {
		List<List<Object>> keycodes = new ArrayList<List<Object>>();
		Integer[] vks = new Integer[] {
				KeyEvent.VK_ESCAPE,
				KeyEvent.VK_1,KeyEvent.VK_2,KeyEvent.VK_3,KeyEvent.VK_4,KeyEvent.VK_5,KeyEvent.VK_6,KeyEvent.VK_7,KeyEvent.VK_8,KeyEvent.VK_9,KeyEvent.VK_0,
				KeyEvent.VK_MINUS,KeyEvent.VK_EQUALS,KeyEvent.VK_BACK_SPACE,KeyEvent.VK_TAB,
				KeyEvent.VK_Q,KeyEvent.VK_W,KeyEvent.VK_E,KeyEvent.VK_R,KeyEvent.VK_T,KeyEvent.VK_Y,KeyEvent.VK_U,KeyEvent.VK_I,KeyEvent.VK_O,KeyEvent.VK_P,
				KeyEvent.VK_BRACELEFT,KeyEvent.VK_BRACERIGHT,KeyEvent.VK_ENTER,
				KeyEvent.VK_CAPS_LOCK,
				KeyEvent.VK_A,KeyEvent.VK_S,KeyEvent.VK_D,KeyEvent.VK_F,KeyEvent.VK_G,KeyEvent.VK_H,KeyEvent.VK_J,KeyEvent.VK_K,KeyEvent.VK_L,
				KeyEvent.VK_COMMA,KeyEvent.VK_QUOTE,KeyEvent.VK_SHIFT,
				KeyEvent.VK_Z,KeyEvent.VK_X,KeyEvent.VK_C,KeyEvent.VK_V,KeyEvent.VK_B,KeyEvent.VK_N,KeyEvent.VK_M,
				KeyEvent.VK_PERIOD,KeyEvent.VK_SLASH,
				KeyEvent.VK_ALT,KeyEvent.VK_SPACE,KeyEvent.VK_PLUS,KeyEvent.VK_SCROLL_LOCK,
				KeyEvent.VK_NUM_LOCK,KeyEvent.VK_ASTERISK,
				KeyEvent.VK_NUMPAD7,KeyEvent.VK_NUMPAD8,KeyEvent.VK_NUMPAD9,
				KeyEvent.VK_NUMPAD4,KeyEvent.VK_NUMPAD5,KeyEvent.VK_NUMPAD6,
				KeyEvent.VK_NUMPAD1,KeyEvent.VK_NUMPAD2,KeyEvent.VK_NUMPAD3,
				KeyEvent.VK_NUMPAD0,KeyEvent.VK_DELETE};
		List<Integer> seen = new ArrayList<Integer>();
		int i = 0;
		for (int vk : vks) {
			if (seen.contains(vk))
				throw new IllegalArgumentException("already seen: "+vk+" at "+i+" / "+vks.length);
			seen.add(vk);
			keycodes.add(this.makeKeySpec(vk));
			i++;
		}
		return	keycodes.toArray(new List<?>[keycodes.size()]);
	}
}
