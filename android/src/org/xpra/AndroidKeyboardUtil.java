package org.xpra;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import android.view.KeyCharacterMap;
import android.view.KeyEvent;

/**
 * We have to duplicate a lot of values from the android 4.x source since
 * they are not accessible in android 2.x
 */
public class AndroidKeyboardUtil {

	/** Key code constant: Escape key. */
    public static final int KEYCODE_ESCAPE          = 111;
    /** Key code constant: Forward Delete key.
     * Deletes characters ahead of the insertion point, unlike {@link #KEYCODE_DEL}. */
    public static final int KEYCODE_FORWARD_DEL     = 112;
    /** Key code constant: Left Control modifier key. */
    public static final int KEYCODE_CTRL_LEFT       = 113;
    /** Key code constant: Right Control modifier key. */
    public static final int KEYCODE_CTRL_RIGHT      = 114;
    /** Key code constant: Caps Lock key. */
    public static final int KEYCODE_CAPS_LOCK       = 115;
    /** Key code constant: Scroll Lock key. */
    public static final int KEYCODE_SCROLL_LOCK     = 116;
    /** Key code constant: Left Meta modifier key. */
    public static final int KEYCODE_META_LEFT       = 117;
    /** Key code constant: Right Meta modifier key. */
    public static final int KEYCODE_META_RIGHT      = 118;
    /** Key code constant: Function modifier key. */
    public static final int KEYCODE_FUNCTION        = 119;
    /** Key code constant: System Request / Print Screen key. */
    public static final int KEYCODE_SYSRQ           = 120;
    /** Key code constant: Break / Pause key. */
    public static final int KEYCODE_BREAK           = 121;
    /** Key code constant: Home Movement key.
     * Used for scrolling or moving the cursor around to the start of a line
     * or to the top of a list. */
    public static final int KEYCODE_MOVE_HOME       = 122;
    /** Key code constant: End Movement key.
     * Used for scrolling or moving the cursor around to the end of a line
     * or to the bottom of a list. */
    public static final int KEYCODE_MOVE_END        = 123;
    /** Key code constant: Insert key.
     * Toggles insert / overwrite edit mode. */
    public static final int KEYCODE_INSERT          = 124;
    /** Key code constant: Forward key.
     * Navigates forward in the history stack.  Complement of {@link #KEYCODE_BACK}. */
    public static final int KEYCODE_FORWARD         = 125;
    /** Key code constant: Play media key. */
    public static final int KEYCODE_MEDIA_PLAY      = 126;
    /** Key code constant: Pause media key. */
    public static final int KEYCODE_MEDIA_PAUSE     = 127;
    /** Key code constant: Close media key.
     * May be used to close a CD tray, for example. */
    public static final int KEYCODE_MEDIA_CLOSE     = 128;
    /** Key code constant: Eject media key.
     * May be used to eject a CD tray, for example. */
    public static final int KEYCODE_MEDIA_EJECT     = 129;
    /** Key code constant: Record media key. */
    public static final int KEYCODE_MEDIA_RECORD    = 130;
    /** Key code constant: F1 key. */
    public static final int KEYCODE_F1              = 131;
    /** Key code constant: F2 key. */
    public static final int KEYCODE_F2              = 132;
    /** Key code constant: F3 key. */
    public static final int KEYCODE_F3              = 133;
    /** Key code constant: F4 key. */
    public static final int KEYCODE_F4              = 134;
    /** Key code constant: F5 key. */
    public static final int KEYCODE_F5              = 135;
    /** Key code constant: F6 key. */
    public static final int KEYCODE_F6              = 136;
    /** Key code constant: F7 key. */
    public static final int KEYCODE_F7              = 137;
    /** Key code constant: F8 key. */
    public static final int KEYCODE_F8              = 138;
    /** Key code constant: F9 key. */
    public static final int KEYCODE_F9              = 139;
    /** Key code constant: F10 key. */
    public static final int KEYCODE_F10             = 140;
    /** Key code constant: F11 key. */
    public static final int KEYCODE_F11             = 141;
    /** Key code constant: F12 key. */
    public static final int KEYCODE_F12             = 142;
    /** Key code constant: Num Lock key.
     * This is the Num Lock key; it is different from {@link #KEYCODE_NUM}.
     * This key alters the behavior of other keys on the numeric keypad. */
    public static final int KEYCODE_NUM_LOCK        = 143;
    /** Key code constant: Numeric keypad '0' key. */
    public static final int KEYCODE_NUMPAD_0        = 144;
    /** Key code constant: Numeric keypad '1' key. */
    public static final int KEYCODE_NUMPAD_1        = 145;
    /** Key code constant: Numeric keypad '2' key. */
    public static final int KEYCODE_NUMPAD_2        = 146;
    /** Key code constant: Numeric keypad '3' key. */
    public static final int KEYCODE_NUMPAD_3        = 147;
    /** Key code constant: Numeric keypad '4' key. */
    public static final int KEYCODE_NUMPAD_4        = 148;
    /** Key code constant: Numeric keypad '5' key. */
    public static final int KEYCODE_NUMPAD_5        = 149;
    /** Key code constant: Numeric keypad '6' key. */
    public static final int KEYCODE_NUMPAD_6        = 150;
    /** Key code constant: Numeric keypad '7' key. */
    public static final int KEYCODE_NUMPAD_7        = 151;
    /** Key code constant: Numeric keypad '8' key. */
    public static final int KEYCODE_NUMPAD_8        = 152;
    /** Key code constant: Numeric keypad '9' key. */
    public static final int KEYCODE_NUMPAD_9        = 153;
    /** Key code constant: Numeric keypad '/' key (for division). */
    public static final int KEYCODE_NUMPAD_DIVIDE   = 154;
    /** Key code constant: Numeric keypad '*' key (for multiplication). */
    public static final int KEYCODE_NUMPAD_MULTIPLY = 155;
    /** Key code constant: Numeric keypad '-' key (for subtraction). */
    public static final int KEYCODE_NUMPAD_SUBTRACT = 156;
    /** Key code constant: Numeric keypad '+' key (for addition). */
    public static final int KEYCODE_NUMPAD_ADD      = 157;
    /** Key code constant: Numeric keypad '.' key (for decimals or digit grouping). */
    public static final int KEYCODE_NUMPAD_DOT      = 158;
    /** Key code constant: Numeric keypad ',' key (for decimals or digit grouping). */
    public static final int KEYCODE_NUMPAD_COMMA    = 159;
    /** Key code constant: Numeric keypad Enter key. */
    public static final int KEYCODE_NUMPAD_ENTER    = 160;
    /** Key code constant: Numeric keypad '=' key. */
    public static final int KEYCODE_NUMPAD_EQUALS   = 161;
    /** Key code constant: Numeric keypad '(' key. */
    public static final int KEYCODE_NUMPAD_LEFT_PAREN = 162;
    /** Key code constant: Numeric keypad ')' key. */
    public static final int KEYCODE_NUMPAD_RIGHT_PAREN = 163;
    /** Key code constant: Volume Mute key.
     * Mutes the speaker, unlike {@link #KEYCODE_MUTE}.
     * This key should normally be implemented as a toggle such that the first press
     * mutes the speaker and the second press restores the original volume. */
    public static final int KEYCODE_VOLUME_MUTE     = 164;
    /** Key code constant: Info key.
     * Common on TV remotes to show additional information related to what is
     * currently being viewed. */
    public static final int KEYCODE_INFO            = 165;
    /** Key code constant: Channel up key.
     * On TV remotes, increments the television channel. */
    public static final int KEYCODE_CHANNEL_UP      = 166;
    /** Key code constant: Channel down key.
     * On TV remotes, decrements the television channel. */
    public static final int KEYCODE_CHANNEL_DOWN    = 167;
    /** Key code constant: Zoom in key. */
    public static final int KEYCODE_ZOOM_IN         = 168;
    /** Key code constant: Zoom out key. */
    public static final int KEYCODE_ZOOM_OUT        = 169;
    /** Key code constant: TV key.
     * On TV remotes, switches to viewing live TV. */
    public static final int KEYCODE_TV              = 170;
    /** Key code constant: Window key.
     * On TV remotes, toggles picture-in-picture mode or other windowing functions. */
    public static final int KEYCODE_WINDOW          = 171;
    /** Key code constant: Guide key.
     * On TV remotes, shows a programming guide. */
    public static final int KEYCODE_GUIDE           = 172;
    /** Key code constant: DVR key.
     * On some TV remotes, switches to a DVR mode for recorded shows. */
    public static final int KEYCODE_DVR             = 173;
    /** Key code constant: Bookmark key.
     * On some TV remotes, bookmarks content or web pages. */
    public static final int KEYCODE_BOOKMARK        = 174;
    /** Key code constant: Toggle captions key.
     * Switches the mode for closed-captioning text, for example during television shows. */
    public static final int KEYCODE_CAPTIONS        = 175;
    /** Key code constant: Settings key.
     * Starts the system settings activity. */
    public static final int KEYCODE_SETTINGS        = 176;
    /** Key code constant: TV power key.
     * On TV remotes, toggles the power on a television screen. */
    public static final int KEYCODE_TV_POWER        = 177;
    /** Key code constant: TV input key.
     * On TV remotes, switches the input on a television screen. */
    public static final int KEYCODE_TV_INPUT        = 178;
    /** Key code constant: Set-top-box power key.
     * On TV remotes, toggles the power on an external Set-top-box. */
    public static final int KEYCODE_STB_POWER       = 179;
    /** Key code constant: Set-top-box input key.
     * On TV remotes, switches the input mode on an external Set-top-box. */
    public static final int KEYCODE_STB_INPUT       = 180;
    /** Key code constant: A/V Receiver power key.
     * On TV remotes, toggles the power on an external A/V Receiver. */
    public static final int KEYCODE_AVR_POWER       = 181;
    /** Key code constant: A/V Receiver input key.
     * On TV remotes, switches the input mode on an external A/V Receiver. */
    public static final int KEYCODE_AVR_INPUT       = 182;
    /** Key code constant: Red "programmable" key.
     * On TV remotes, acts as a contextual/programmable key. */
    public static final int KEYCODE_PROG_RED        = 183;
    /** Key code constant: Green "programmable" key.
     * On TV remotes, actsas a contextual/programmable key. */
    public static final int KEYCODE_PROG_GREEN      = 184;
    /** Key code constant: Yellow "programmable" key.
     * On TV remotes, acts as a contextual/programmable key. */
    public static final int KEYCODE_PROG_YELLOW     = 185;
    /** Key code constant: Blue "programmable" key.
     * On TV remotes, acts as a contextual/programmable key. */
    public static final int KEYCODE_PROG_BLUE       = 186;
    /** Key code constant: App switch key.
     * Should bring up the application switcher dialog. */
    public static final int KEYCODE_APP_SWITCH      = 187;
    /** Key code constant: Generic Game Pad Button #1.*/
    public static final int KEYCODE_BUTTON_1        = 188;
    /** Key code constant: Generic Game Pad Button #2.*/
    public static final int KEYCODE_BUTTON_2        = 189;
    /** Key code constant: Generic Game Pad Button #3.*/
    public static final int KEYCODE_BUTTON_3        = 190;
    /** Key code constant: Generic Game Pad Button #4.*/
    public static final int KEYCODE_BUTTON_4        = 191;
    /** Key code constant: Generic Game Pad Button #5.*/
    public static final int KEYCODE_BUTTON_5        = 192;
    /** Key code constant: Generic Game Pad Button #6.*/
    public static final int KEYCODE_BUTTON_6        = 193;
    /** Key code constant: Generic Game Pad Button #7.*/
    public static final int KEYCODE_BUTTON_7        = 194;
    /** Key code constant: Generic Game Pad Button #8.*/
    public static final int KEYCODE_BUTTON_8        = 195;
    /** Key code constant: Generic Game Pad Button #9.*/
    public static final int KEYCODE_BUTTON_9        = 196;
    /** Key code constant: Generic Game Pad Button #10.*/
    public static final int KEYCODE_BUTTON_10       = 197;
    /** Key code constant: Generic Game Pad Button #11.*/
    public static final int KEYCODE_BUTTON_11       = 198;
    /** Key code constant: Generic Game Pad Button #12.*/
    public static final int KEYCODE_BUTTON_12       = 199;
    /** Key code constant: Generic Game Pad Button #13.*/
    public static final int KEYCODE_BUTTON_13       = 200;
    /** Key code constant: Generic Game Pad Button #14.*/
    public static final int KEYCODE_BUTTON_14       = 201;
    /** Key code constant: Generic Game Pad Button #15.*/
    public static final int KEYCODE_BUTTON_15       = 202;
    /** Key code constant: Generic Game Pad Button #16.*/
    public static final int KEYCODE_BUTTON_16       = 203;
    /** Key code constant: Language Switch key.
     * Toggles the current input language such as switching between English and Japanese on
     * a QWERTY keyboard.  On some devices, the same function may be performed by
     * pressing Shift+Spacebar. */
    public static final int KEYCODE_LANGUAGE_SWITCH = 204;
    /** Key code constant: Manner Mode key.
     * Toggles silent or vibrate mode on and off to make the device behave more politely
     * in certain settings such as on a crowded train.  On some devices, the key may only
     * operate when long-pressed. */
    public static final int KEYCODE_MANNER_MODE     = 205;
    /** Key code constant: 3D Mode key.
     * Toggles the display between 2D and 3D mode. */
    public static final int KEYCODE_3D_MODE         = 206;
    /** Key code constant: Contacts special function key.
     * Used to launch an address book application. */
    public static final int KEYCODE_CONTACTS        = 207;
    /** Key code constant: Calendar special function key.
     * Used to launch a calendar application. */
    public static final int KEYCODE_CALENDAR        = 208;
    /** Key code constant: Music special function key.
     * Used to launch a music player application. */
    public static final int KEYCODE_MUSIC           = 209;
    /** Key code constant: Calculator special function key.
     * Used to launch a calculator application. */
    public static final int KEYCODE_CALCULATOR      = 210;

    //private static final int LAST_KEYCODE           = KEYCODE_CALCULATOR;


	public static List<List<Object>> getAllKeycodes() {
		List<List<Object>> keycodes = new ArrayList<List<Object>>(256);
		for (int keyCode = 0; keyCode < KeyEvent.getMaxKeyCode(); keyCode++) {
			if (!KeyCharacterMap.deviceHasKey(keyCode))
				continue;
			// int state = 0;
			// int n = this.keyCharacterMap.get(keyCode, state);
			String name = keyCodeName(keyCode);
			if (name == null)
				continue;
			String x11Name = x11KeyName(name);
			if (x11Name.length()==0)
				continue;
			// char c = this.keyCharacterMap.getDisplayLabel(keyCode);
			List<Object> keycodeInfo = new ArrayList<Object>(5);
			keycodeInfo.add(0); // don't know keyval here..
			keycodeInfo.add(x11Name);
			keycodeInfo.add(keyCode);
			keycodeInfo.add(0); // only group=0 for now
			keycodeInfo.add(0); // only level=0 for now
			keycodes.add(keycodeInfo);
		}
		return keycodes;
	}

	public List<String> getModifiers(KeyEvent event) {
		List<String> modifiers = new ArrayList<String>(8);
		// int mask = event.getMetaState();
		if (event.isShiftPressed())
			modifiers.add("shift");
		// if ((mask & KeyEvent.META_CTRL_ON) != 0) //if (event.isCtrlPressed())
		// modifiers.add("control");
		if (event.isSymPressed())
			modifiers.add("mod2");
		if (event.isAltPressed())
			modifiers.add("mod1");
		/*
		 * if (event.isMetaPressed()) modifiers.add("mod2"); if
		 * (event.isFunctionPressed()) modifiers.add("mod3"); if
		 * (event.isCapsLockOn()) modifiers.add("mod4"); if
		 * (event.isNumLockOn()) modifiers.add("mod5"); if
		 * (event.isScrollLockOn()) modifiers.add("mod5");
		 */
		return modifiers;
	}

	public static String x11KeyName(String in) {
		String x11 = NAME_TO_X11_NAME.get(in);
		if (x11==null)
			x11 = in;
		return x11;
	}

	public static Map<String,String> NAME_TO_X11_NAME = new HashMap<String,String>();
	static {
		Map<String,String> names = NAME_TO_X11_NAME;
		names.put("ENTER", "Return");
		names.put("HOME", "Super_R");		//"Windows" key
		names.put("BACK", "XF86Back");
		names.put("CALL", "");				//ignore
		names.put("ENDCALL", "");			//ignore
		names.put("STAR", "asterisk");
		names.put("POUND", "sterling");
		names.put("SOFT_LEFT", "Left");
		names.put("SOFT_RIGHT", "Right");
		names.put("DPAD_UP", "Up");
		names.put("DPAD_DOWN", "Down");
		names.put("DPAD_LEFT", "Left");
		names.put("DPAD_RIGHT", "Right");
		names.put("DPAD_CENTER", "");		//ignore
		names.put("VOLUME_UP", "XF86AudioRaiseVolume");
		names.put("VOLUME_DOWN", "XF86AudioLowerVolume");
		names.put("POWER", "XF86PowerOff");
		names.put("CAMERA", "");			//ignore
		names.put("COMMA", "comma");
		names.put("PERIOD", "period");
		names.put("ALT_LEFT", "Alt_L");
		names.put("ALT_RIGHT", "Alt_R");
		names.put("SHIFT_LEFT", "Shift_L");
		names.put("SHIFT_RIGHT", "Shift_R");
		names.put("TAB", "Tab");
		names.put("SPACE", "space");
		names.put("EXPLORER", "XF86MyComputer");
		names.put("ENVELOPE", "XF86Mail");
		names.put("FORWARD_DEL", "Delete");
		names.put("DEL", "BackSpace");
		names.put("GRAVE", "grave");
		names.put("MINUS", "minus");
		names.put("EQUALS", "equal");
		names.put("LEFT_BRACKET", "parenleft");
		names.put("RIGHT_BRACKET", "parenright");
		names.put("BACKSLASH", "backslash");
		names.put("SEMICOLON", "semicolon");
		names.put("APOSTROPHE", "apostrophe");
		names.put("SLASH", "slash");
		names.put("AT", "at");
		names.put("MENU", "Super_L");		//"Windows" key
		names.put("SEARCH", "XF86Search");
		names.put("MEDIA_REWIND", "");		//no match
		names.put("MEDIA_PREVIOUS", "XF86AudioPrev");
		names.put("MEDIA_PLAY_PAUSE", "XF86AudioPlay");
		names.put("MEDIA_STOP", "XF86AudioStop");
		names.put("MEDIA_NEXT", "XF86AudioNext");
		names.put("MEDIA_FAST_FORWARD", "");//no match
		names.put("PLUS", "plus");
		names.put("PAGE_UP", "Page_Up");
		names.put("PAGE_DOWN", "Page_Down");
	}

	public static String keyCodeName(int keycode) {
		return KEYCODE_SYMBOLIC_NAMES.get(keycode);
	}

	/**
	 * Have to duplicate these values from 4.x source since this is not
	 * accessible in android 2.x
	 */
	public static Map<Integer, String> KEYCODE_SYMBOLIC_NAMES = new HashMap<Integer, String>();
	static {
		Map<Integer, String> names = KEYCODE_SYMBOLIC_NAMES;
		names.put(KeyEvent.KEYCODE_UNKNOWN, "UNKNOWN");
		names.put(KeyEvent.KEYCODE_SOFT_LEFT, "SOFT_LEFT");
		names.put(KeyEvent.KEYCODE_SOFT_RIGHT, "SOFT_RIGHT");
		names.put(KeyEvent.KEYCODE_HOME, "HOME");
		names.put(KeyEvent.KEYCODE_BACK, "BACK");
		names.put(KeyEvent.KEYCODE_CALL, "CALL");
		names.put(KeyEvent.KEYCODE_ENDCALL, "ENDCALL");
		names.put(KeyEvent.KEYCODE_0, "0");
		names.put(KeyEvent.KEYCODE_1, "1");
		names.put(KeyEvent.KEYCODE_2, "2");
		names.put(KeyEvent.KEYCODE_3, "3");
		names.put(KeyEvent.KEYCODE_4, "4");
		names.put(KeyEvent.KEYCODE_5, "5");
		names.put(KeyEvent.KEYCODE_6, "6");
		names.put(KeyEvent.KEYCODE_7, "7");
		names.put(KeyEvent.KEYCODE_8, "8");
		names.put(KeyEvent.KEYCODE_9, "9");
		names.put(KeyEvent.KEYCODE_STAR, "STAR");
		names.put(KeyEvent.KEYCODE_POUND, "POUND");
		names.put(KeyEvent.KEYCODE_DPAD_UP, "DPAD_UP");
		names.put(KeyEvent.KEYCODE_DPAD_DOWN, "DPAD_DOWN");
		names.put(KeyEvent.KEYCODE_DPAD_LEFT, "DPAD_LEFT");
		names.put(KeyEvent.KEYCODE_DPAD_RIGHT, "DPAD_RIGHT");
		names.put(KeyEvent.KEYCODE_DPAD_CENTER, "DPAD_CENTER");
		names.put(KeyEvent.KEYCODE_VOLUME_UP, "VOLUME_UP");
		names.put(KeyEvent.KEYCODE_VOLUME_DOWN, "VOLUME_DOWN");
		names.put(KeyEvent.KEYCODE_POWER, "POWER");
		names.put(KeyEvent.KEYCODE_CAMERA, "CAMERA");
		names.put(KeyEvent.KEYCODE_CLEAR, "CLEAR");
		names.put(KeyEvent.KEYCODE_A, "A");
		names.put(KeyEvent.KEYCODE_B, "B");
		names.put(KeyEvent.KEYCODE_C, "C");
		names.put(KeyEvent.KEYCODE_D, "D");
		names.put(KeyEvent.KEYCODE_E, "E");
		names.put(KeyEvent.KEYCODE_F, "F");
		names.put(KeyEvent.KEYCODE_G, "G");
		names.put(KeyEvent.KEYCODE_H, "H");
		names.put(KeyEvent.KEYCODE_I, "I");
		names.put(KeyEvent.KEYCODE_J, "J");
		names.put(KeyEvent.KEYCODE_K, "K");
		names.put(KeyEvent.KEYCODE_L, "L");
		names.put(KeyEvent.KEYCODE_M, "M");
		names.put(KeyEvent.KEYCODE_N, "N");
		names.put(KeyEvent.KEYCODE_O, "O");
		names.put(KeyEvent.KEYCODE_P, "P");
		names.put(KeyEvent.KEYCODE_Q, "Q");
		names.put(KeyEvent.KEYCODE_R, "R");
		names.put(KeyEvent.KEYCODE_S, "S");
		names.put(KeyEvent.KEYCODE_T, "T");
		names.put(KeyEvent.KEYCODE_U, "U");
		names.put(KeyEvent.KEYCODE_V, "V");
		names.put(KeyEvent.KEYCODE_W, "W");
		names.put(KeyEvent.KEYCODE_X, "X");
		names.put(KeyEvent.KEYCODE_Y, "Y");
		names.put(KeyEvent.KEYCODE_Z, "Z");
		names.put(KeyEvent.KEYCODE_COMMA, "COMMA");
		names.put(KeyEvent.KEYCODE_PERIOD, "PERIOD");
		names.put(KeyEvent.KEYCODE_ALT_LEFT, "ALT_LEFT");
		names.put(KeyEvent.KEYCODE_ALT_RIGHT, "ALT_RIGHT");
		names.put(KeyEvent.KEYCODE_SHIFT_LEFT, "SHIFT_LEFT");
		names.put(KeyEvent.KEYCODE_SHIFT_RIGHT, "SHIFT_RIGHT");
		names.put(KeyEvent.KEYCODE_TAB, "TAB");
		names.put(KeyEvent.KEYCODE_SPACE, "SPACE");
		names.put(KeyEvent.KEYCODE_SYM, "SYM");
		names.put(KeyEvent.KEYCODE_EXPLORER, "EXPLORER");
		names.put(KeyEvent.KEYCODE_ENVELOPE, "ENVELOPE");
		names.put(KeyEvent.KEYCODE_ENTER, "ENTER");
		names.put(KeyEvent.KEYCODE_DEL, "DEL");
		names.put(KeyEvent.KEYCODE_GRAVE, "GRAVE");
		names.put(KeyEvent.KEYCODE_MINUS, "MINUS");
		names.put(KeyEvent.KEYCODE_EQUALS, "EQUALS");
		names.put(KeyEvent.KEYCODE_LEFT_BRACKET, "LEFT_BRACKET");
		names.put(KeyEvent.KEYCODE_RIGHT_BRACKET, "RIGHT_BRACKET");
		names.put(KeyEvent.KEYCODE_BACKSLASH, "BACKSLASH");
		names.put(KeyEvent.KEYCODE_SEMICOLON, "SEMICOLON");
		names.put(KeyEvent.KEYCODE_APOSTROPHE, "APOSTROPHE");
		names.put(KeyEvent.KEYCODE_SLASH, "SLASH");
		names.put(KeyEvent.KEYCODE_AT, "AT");
		names.put(KeyEvent.KEYCODE_NUM, "NUM");
		names.put(KeyEvent.KEYCODE_HEADSETHOOK, "HEADSETHOOK");
		names.put(KeyEvent.KEYCODE_FOCUS, "FOCUS");
		names.put(KeyEvent.KEYCODE_PLUS, "PLUS");
		names.put(KeyEvent.KEYCODE_MENU, "MENU");
		names.put(KeyEvent.KEYCODE_NOTIFICATION, "NOTIFICATION");
		names.put(KeyEvent.KEYCODE_SEARCH, "SEARCH");
		names.put(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, "MEDIA_PLAY_PAUSE");
		names.put(KeyEvent.KEYCODE_MEDIA_STOP, "MEDIA_STOP");
		names.put(KeyEvent.KEYCODE_MEDIA_NEXT, "MEDIA_NEXT");
		names.put(KeyEvent.KEYCODE_MEDIA_PREVIOUS, "MEDIA_PREVIOUS");
		names.put(KeyEvent.KEYCODE_MEDIA_REWIND, "MEDIA_REWIND");
		names.put(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, "MEDIA_FAST_FORWARD");
		names.put(KeyEvent.KEYCODE_MUTE, "MUTE");
		names.put(KeyEvent.KEYCODE_PAGE_UP, "PAGE_UP");
		names.put(KeyEvent.KEYCODE_PAGE_DOWN, "PAGE_DOWN");
		names.put(KeyEvent.KEYCODE_PICTSYMBOLS, "PICTSYMBOLS");
		names.put(KeyEvent.KEYCODE_SWITCH_CHARSET, "SWITCH_CHARSET");
		names.put(KeyEvent.KEYCODE_BUTTON_A, "BUTTON_A");
		names.put(KeyEvent.KEYCODE_BUTTON_B, "BUTTON_B");
		names.put(KeyEvent.KEYCODE_BUTTON_C, "BUTTON_C");
		names.put(KeyEvent.KEYCODE_BUTTON_X, "BUTTON_X");
		names.put(KeyEvent.KEYCODE_BUTTON_Y, "BUTTON_Y");
		names.put(KeyEvent.KEYCODE_BUTTON_Z, "BUTTON_Z");
		names.put(KeyEvent.KEYCODE_BUTTON_L1, "BUTTON_L1");
		names.put(KeyEvent.KEYCODE_BUTTON_R1, "BUTTON_R1");
		names.put(KeyEvent.KEYCODE_BUTTON_L2, "BUTTON_L2");
		names.put(KeyEvent.KEYCODE_BUTTON_R2, "BUTTON_R2");
		names.put(KeyEvent.KEYCODE_BUTTON_THUMBL, "BUTTON_THUMBL");
		names.put(KeyEvent.KEYCODE_BUTTON_THUMBR, "BUTTON_THUMBR");
		names.put(KeyEvent.KEYCODE_BUTTON_START, "BUTTON_START");
		names.put(KeyEvent.KEYCODE_BUTTON_SELECT, "BUTTON_SELECT");
		names.put(KeyEvent.KEYCODE_BUTTON_MODE, "BUTTON_MODE");
		//below are codes we duplicated (not available in 2.x):
		names.put(KEYCODE_ESCAPE, "ESCAPE");
		names.put(KEYCODE_FORWARD_DEL, "FORWARD_DEL");
		names.put(KEYCODE_CTRL_LEFT, "CTRL_LEFT");
		names.put(KEYCODE_CTRL_RIGHT, "CTRL_RIGHT");
		names.put(KEYCODE_CAPS_LOCK, "CAPS_LOCK");
		names.put(KEYCODE_SCROLL_LOCK, "SCROLL_LOCK");
		names.put(KEYCODE_META_LEFT, "META_LEFT");
		names.put(KEYCODE_META_RIGHT, "META_RIGHT");
		names.put(KEYCODE_FUNCTION, "FUNCTION");
		names.put(KEYCODE_SYSRQ, "SYSRQ");
		names.put(KEYCODE_BREAK, "BREAK");
		names.put(KEYCODE_MOVE_HOME, "MOVE_HOME");
		names.put(KEYCODE_MOVE_END, "MOVE_END");
		names.put(KEYCODE_INSERT, "INSERT");
		names.put(KEYCODE_FORWARD, "FORWARD");
		names.put(KEYCODE_MEDIA_PLAY, "MEDIA_PLAY");
		names.put(KEYCODE_MEDIA_PAUSE, "MEDIA_PAUSE");
		names.put(KEYCODE_MEDIA_CLOSE, "MEDIA_CLOSE");
		names.put(KEYCODE_MEDIA_EJECT, "MEDIA_EJECT");
		names.put(KEYCODE_MEDIA_RECORD, "MEDIA_RECORD");
		names.put(KEYCODE_F1, "F1");
		names.put(KEYCODE_F2, "F2");
		names.put(KEYCODE_F3, "F3");
		names.put(KEYCODE_F4, "F4");
		names.put(KEYCODE_F5, "F5");
		names.put(KEYCODE_F6, "F6");
		names.put(KEYCODE_F7, "F7");
		names.put(KEYCODE_F8, "F8");
		names.put(KEYCODE_F9, "F9");
		names.put(KEYCODE_F10, "F10");
		names.put(KEYCODE_F11, "F11");
		names.put(KEYCODE_F12, "F12");
		names.put(KEYCODE_NUM_LOCK, "NUM_LOCK");
		names.put(KEYCODE_NUMPAD_0, "NUMPAD_0");
		names.put(KEYCODE_NUMPAD_1, "NUMPAD_1");
		names.put(KEYCODE_NUMPAD_2, "NUMPAD_2");
		names.put(KEYCODE_NUMPAD_3, "NUMPAD_3");
		names.put(KEYCODE_NUMPAD_4, "NUMPAD_4");
		names.put(KEYCODE_NUMPAD_5, "NUMPAD_5");
		names.put(KEYCODE_NUMPAD_6, "NUMPAD_6");
		names.put(KEYCODE_NUMPAD_7, "NUMPAD_7");
		names.put(KEYCODE_NUMPAD_8, "NUMPAD_8");
		names.put(KEYCODE_NUMPAD_9, "NUMPAD_9");
		names.put(KEYCODE_NUMPAD_DIVIDE, "NUMPAD_DIVIDE");
		names.put(KEYCODE_NUMPAD_MULTIPLY,"NUMPAD_MULTIPLY");
		names.put(KEYCODE_NUMPAD_SUBTRACT, "NUMPAD_SUBTRACT");
		names.put(KEYCODE_NUMPAD_ADD, "NUMPAD_ADD");
		names.put(KEYCODE_NUMPAD_DOT, "NUMPAD_DOT");
		names.put(KEYCODE_NUMPAD_COMMA, "NUMPAD_COMMA");
		names.put(KEYCODE_NUMPAD_ENTER, "NUMPAD_ENTER");
		names.put(KEYCODE_NUMPAD_EQUALS, "NUMPAD_EQUALS");
		names.put(KEYCODE_NUMPAD_LEFT_PAREN, "NUMPAD_LEFT_PAREN");
		names.put(KEYCODE_NUMPAD_RIGHT_PAREN, "NUMPAD_RIGHT_PAREN");
		names.put(KEYCODE_VOLUME_MUTE, "VOLUME_MUTE");
		names.put(KEYCODE_INFO, "INFO");
		names.put(KEYCODE_CHANNEL_UP, "CHANNEL_UP");
		names.put(KEYCODE_CHANNEL_DOWN, "CHANNEL_DOWN");
		names.put(KEYCODE_ZOOM_IN, "ZOOM_IN");
		names.put(KEYCODE_ZOOM_OUT, "ZOOM_OUT");
		names.put(KEYCODE_TV, "TV");
		names.put(KEYCODE_WINDOW, "WINDOW");
		names.put(KEYCODE_GUIDE, "GUIDE");
		names.put(KEYCODE_DVR, "DVR");
		names.put(KEYCODE_BOOKMARK, "BOOKMARK");
		names.put(KEYCODE_CAPTIONS, "CAPTIONS");
		names.put(KEYCODE_SETTINGS, "SETTINGS");
		names.put(KEYCODE_TV_POWER, "TV_POWER");
		names.put(KEYCODE_TV_INPUT, "TV_INPUT");
		names.put(KEYCODE_STB_INPUT, "STB_INPUT");
		names.put(KEYCODE_STB_POWER, "STB_POWER");
		names.put(KEYCODE_AVR_POWER, "AVR_POWER");
		names.put(KEYCODE_AVR_INPUT, "AVR_INPUT");
		names.put(KEYCODE_PROG_RED, "PROG_RED");
		names.put(KEYCODE_PROG_GREEN, "PROG_GREEN");
		names.put(KEYCODE_PROG_YELLOW, "PROG_YELLOW");
		names.put(KEYCODE_PROG_BLUE, "PROG_BLUE");
		names.put(KEYCODE_APP_SWITCH, "APP_SWITCH");
		names.put(KEYCODE_BUTTON_1, "BUTTON_1");
		names.put(KEYCODE_BUTTON_2, "BUTTON_2");
		names.put(KEYCODE_BUTTON_3, "BUTTON_3");
		names.put(KEYCODE_BUTTON_4, "BUTTON_4");
		names.put(KEYCODE_BUTTON_5, "BUTTON_5");
		names.put(KEYCODE_BUTTON_6, "BUTTON_6");
		names.put(KEYCODE_BUTTON_7, "BUTTON_7");
		names.put(KEYCODE_BUTTON_8, "BUTTON_8");
		names.put(KEYCODE_BUTTON_9, "BUTTON_9");
		names.put(KEYCODE_BUTTON_10, "BUTTON_10");
		names.put(KEYCODE_BUTTON_11, "BUTTON_11");
		names.put(KEYCODE_BUTTON_12, "BUTTON_12");
		names.put(KEYCODE_BUTTON_13, "BUTTON_13");
		names.put(KEYCODE_BUTTON_14, "BUTTON_14");
		names.put(KEYCODE_BUTTON_15, "BUTTON_15");
		names.put(KEYCODE_BUTTON_16, "BUTTON_16");
		names.put(KEYCODE_LANGUAGE_SWITCH, "LANGUAGE_SWITCH");
		names.put(KEYCODE_MANNER_MODE, "MANNER_MODE");
		names.put(KEYCODE_3D_MODE, "3D_MODE");
		names.put(KEYCODE_CONTACTS, "CONTACTS");
		names.put(KEYCODE_CALENDAR, "CALENDAR");
		names.put(KEYCODE_MUSIC, "MUSIC");
		names.put(KEYCODE_CALCULATOR, "CALCULATOR");
	}
}
