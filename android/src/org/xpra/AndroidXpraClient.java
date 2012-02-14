package org.xpra;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import xpra.AbstractClient;
import xpra.ClientWindow;
import android.view.Display;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.LayoutInflater;
import android.view.View;

public class AndroidXpraClient extends AbstractClient {
	
	protected	XpraActivity context = null;
	protected	LayoutInflater inflater = null;
	protected	KeyCharacterMap keyCharacterMap = null;
	protected	int keymapId = -1;

	public AndroidXpraClient(XpraActivity context, InputStream is, OutputStream os) {
		super(is, os);
		this.context = context;
		this.inflater = LayoutInflater.from(context);
	}

    @Override
	public int getScreenWidth() {
    	Display display = this.context.getWindowManager().getDefaultDisplay(); 
    	return	display.getWidth();
    }
    @Override
	public int getScreenHeight() {
    	Display display = this.context.getWindowManager().getDefaultDisplay(); 
    	return	display.getHeight();
    }
	
	@Override
	public void run(String[] args) {
		new Thread(this).start();
	}
	
	@Override
	public void cleanup() {
		super.cleanup();
		//
	}
	@Override
	public Object	getLock() {
		return	this;
	}


	@Override
	public Map<String,Object>	make_hello(String enc_pass) {
		Map<String,Object> caps = super.make_hello(enc_pass);
		if (this.keyCharacterMap==null) {
			this.loadCharacterMap(KeyCharacterMap.BUILT_IN_KEYBOARD);	//VIRTUAL_KEYBOARD);
			this.add_keymap_props(caps);
		}
		return caps;
	}

	public void loadCharacterMap(int deviceId) {
		this.keyCharacterMap = KeyCharacterMap.load(deviceId);
		this.keymapId = deviceId;
	}

	public void send_keymap() {
		Map<String,Object> props = new HashMap<String,Object>(10);
		this.add_keymap_props(props);
        this.send("keymap-changed", props);
	}
	public void add_keymap_props(Map<String,Object>	props) {
        props.put("modifiers", new String[0]);
        props.put("xkbmap_keycodes", get_keycodes());
        //["xkbmap_print", "xkbmap_query", "xmodmap_data",
        //"xkbmap_mod_clear", "xkbmap_mod_add", "xkbmap_mod_meanings",
        //"xkbmap_mod_managed", "xkbmap_mod_pointermissing", "xkbmap_keycodes"]:
	}
	public List<List<Object>> get_keycodes() {
		List<List<Object>> keycodes = new ArrayList<List<Object>>(256);
		for (int keyCode=0; keyCode<KeyEvent.getMaxKeyCode(); keyCode++) {
			if (!KeyCharacterMap.deviceHasKey(keyCode))
				continue;
			//int state = 0;
			//int n = this.keyCharacterMap.get(keyCode, state);
			String name = keyCodeToString(keyCode);
			if (name==null)
				continue;
			if (name.startsWith("KEYCODE_"))
				name = name.substring("KEYCODE_".length());
			if (name.equals("ENTER"))
				name = "Return";
			//char c = this.keyCharacterMap.getDisplayLabel(keyCode);
			List<Object> keycodeInfo = new ArrayList<Object>(5);
			keycodeInfo.add(0);		//don't know keyval here..
			keycodeInfo.add(name);
			keycodeInfo.add(keyCode);
			keycodeInfo.add(0);		//only group=0 for now
			keycodeInfo.add(0);		//only level=0 for now
			keycodes.add(keycodeInfo);
		}
		this.log("get_keycodes()="+keycodes);
		return	keycodes;
	}

	public List<String> getModifiers(KeyEvent event) {
		List<String> modifiers = new ArrayList<String>(8);
		//int mask = event.getMetaState();
		if (event.isShiftPressed())
			modifiers.add("shift");
        //if ((mask & KeyEvent.META_CTRL_ON) != 0)	//if (event.isCtrlPressed())
		//	modifiers.add("control");
		if (event.isSymPressed())
			modifiers.add("mod2");
		if (event.isAltPressed())
			modifiers.add("mod1");
		/*if (event.isMetaPressed())
			modifiers.add("mod2");
		if (event.isFunctionPressed())
			modifiers.add("mod3");
		if (event.isCapsLockOn())
			modifiers.add("mod4");
		if (event.isNumLockOn())
			modifiers.add("mod5");
		if (event.isScrollLockOn())
			modifiers.add("mod5");
			*/
		return modifiers;
	}
	
	public void	sendKeyAction(int wid, View v, int keyCode, KeyEvent event) {
		this.log("sendKeyAction("+wid+", "+v+", "+keyCode+", "+event+")");
		if (this.keymapId!=event.getDeviceId()) {
			this.log("sendKeyAction("+wid+", "+v+", "+keyCode+", "+event+") keymap has changed - updating server");
			this.loadCharacterMap(event.getDeviceId());
			this.send_keymap();
		}
		List<String> modifiers = this.getModifiers(event);
		int keyval = event.getScanCode();
		char c = this.keyCharacterMap.getDisplayLabel(keyCode);
		String keyname = ""+c;
		this.log("sendKeyAction("+wid+", "+v+", "+keyCode+", "+event+") keyname="+keyname);
		this.send("key-action", wid, keyname, event.getAction()==KeyEvent.ACTION_DOWN, modifiers, keyval, "", event.getKeyCode());
	}

	
	@Override
	protected ClientWindow	createWindow(int id, int x, int y, int w, int h, Map<String,Object> metadata, boolean override_redirect) {
		//XpraWindow window = new XpraWindow(this.context, this, id, x, y, w, h, metadata, override_redirect);
		XpraWindow window = (XpraWindow) this.inflater.inflate(R.layout.xpra_window, null);	//this.context.mDragLayer);
		window.init(this.context, this, id, x, y, w, h, metadata, override_redirect);
		this.log("createWindow("+id+", "+x+", "+y+", "+w+", "+h+", "+metadata+", "+override_redirect+")="+window);
		this.context.add(window);
		//this.context.mDragLayer.addView(window);
		return	window;
    }


    public static String	keyCodeToString(int keycode) {
    	return	KEYCODE_SYMBOLIC_NAMES.get(keycode);
    }
    
    /**
     * Have to duplicate these values from 4.x source since this is not accessible in android 2.x
     */
    public static Map<Integer,String> KEYCODE_SYMBOLIC_NAMES =  new HashMap<Integer,String>();
    static {
    	Map<Integer,String> names = KEYCODE_SYMBOLIC_NAMES;
        names.put(KeyEvent.KEYCODE_UNKNOWN, "KEYCODE_UNKNOWN");
        names.put(KeyEvent.KEYCODE_SOFT_LEFT, "KEYCODE_SOFT_LEFT");
        names.put(KeyEvent.KEYCODE_SOFT_RIGHT, "KEYCODE_SOFT_RIGHT");
        names.put(KeyEvent.KEYCODE_HOME, "KEYCODE_HOME");
        names.put(KeyEvent.KEYCODE_BACK, "KEYCODE_BACK");
        names.put(KeyEvent.KEYCODE_CALL, "KEYCODE_CALL");
        names.put(KeyEvent.KEYCODE_ENDCALL, "KEYCODE_ENDCALL");
        names.put(KeyEvent.KEYCODE_0, "KEYCODE_0");
        names.put(KeyEvent.KEYCODE_1, "KEYCODE_1");
        names.put(KeyEvent.KEYCODE_2, "KEYCODE_2");
        names.put(KeyEvent.KEYCODE_3, "KEYCODE_3");
        names.put(KeyEvent.KEYCODE_4, "KEYCODE_4");
        names.put(KeyEvent.KEYCODE_5, "KEYCODE_5");
        names.put(KeyEvent.KEYCODE_6, "KEYCODE_6");
        names.put(KeyEvent.KEYCODE_7, "KEYCODE_7");
        names.put(KeyEvent.KEYCODE_8, "KEYCODE_8");
        names.put(KeyEvent.KEYCODE_9, "KEYCODE_9");
        names.put(KeyEvent.KEYCODE_STAR, "KEYCODE_STAR");
        names.put(KeyEvent.KEYCODE_POUND, "KEYCODE_POUND");
        names.put(KeyEvent.KEYCODE_DPAD_UP, "KEYCODE_DPAD_UP");
        names.put(KeyEvent.KEYCODE_DPAD_DOWN, "KEYCODE_DPAD_DOWN");
        names.put(KeyEvent.KEYCODE_DPAD_LEFT, "KEYCODE_DPAD_LEFT");
        names.put(KeyEvent.KEYCODE_DPAD_RIGHT, "KEYCODE_DPAD_RIGHT");
        names.put(KeyEvent.KEYCODE_DPAD_CENTER, "KEYCODE_DPAD_CENTER");
        names.put(KeyEvent.KEYCODE_VOLUME_UP, "KEYCODE_VOLUME_UP");
        names.put(KeyEvent.KEYCODE_VOLUME_DOWN, "KEYCODE_VOLUME_DOWN");
        names.put(KeyEvent.KEYCODE_POWER, "KEYCODE_POWER");
        names.put(KeyEvent.KEYCODE_CAMERA, "KEYCODE_CAMERA");
        names.put(KeyEvent.KEYCODE_CLEAR, "KEYCODE_CLEAR");
        names.put(KeyEvent.KEYCODE_A, "KEYCODE_A");
        names.put(KeyEvent.KEYCODE_B, "KEYCODE_B");
        names.put(KeyEvent.KEYCODE_C, "KEYCODE_C");
        names.put(KeyEvent.KEYCODE_D, "KEYCODE_D");
        names.put(KeyEvent.KEYCODE_E, "KEYCODE_E");
        names.put(KeyEvent.KEYCODE_F, "KEYCODE_F");
        names.put(KeyEvent.KEYCODE_G, "KEYCODE_G");
        names.put(KeyEvent.KEYCODE_H, "KEYCODE_H");
        names.put(KeyEvent.KEYCODE_I, "KEYCODE_I");
        names.put(KeyEvent.KEYCODE_J, "KEYCODE_J");
        names.put(KeyEvent.KEYCODE_K, "KEYCODE_K");
        names.put(KeyEvent.KEYCODE_L, "KEYCODE_L");
        names.put(KeyEvent.KEYCODE_M, "KEYCODE_M");
        names.put(KeyEvent.KEYCODE_N, "KEYCODE_N");
        names.put(KeyEvent.KEYCODE_O, "KEYCODE_O");
        names.put(KeyEvent.KEYCODE_P, "KEYCODE_P");
        names.put(KeyEvent.KEYCODE_Q, "KEYCODE_Q");
        names.put(KeyEvent.KEYCODE_R, "KEYCODE_R");
        names.put(KeyEvent.KEYCODE_S, "KEYCODE_S");
        names.put(KeyEvent.KEYCODE_T, "KEYCODE_T");
        names.put(KeyEvent.KEYCODE_U, "KEYCODE_U");
        names.put(KeyEvent.KEYCODE_V, "KEYCODE_V");
        names.put(KeyEvent.KEYCODE_W, "KEYCODE_W");
        names.put(KeyEvent.KEYCODE_X, "KEYCODE_X");
        names.put(KeyEvent.KEYCODE_Y, "KEYCODE_Y");
        names.put(KeyEvent.KEYCODE_Z, "KEYCODE_Z");
        names.put(KeyEvent.KEYCODE_COMMA, "KEYCODE_COMMA");
        names.put(KeyEvent.KEYCODE_PERIOD, "KEYCODE_PERIOD");
        names.put(KeyEvent.KEYCODE_ALT_LEFT, "KEYCODE_ALT_LEFT");
        names.put(KeyEvent.KEYCODE_ALT_RIGHT, "KEYCODE_ALT_RIGHT");
        names.put(KeyEvent.KEYCODE_SHIFT_LEFT, "KEYCODE_SHIFT_LEFT");
        names.put(KeyEvent.KEYCODE_SHIFT_RIGHT, "KEYCODE_SHIFT_RIGHT");
        names.put(KeyEvent.KEYCODE_TAB, "KEYCODE_TAB");
        names.put(KeyEvent.KEYCODE_SPACE, "KEYCODE_SPACE");
        names.put(KeyEvent.KEYCODE_SYM, "KEYCODE_SYM");
        names.put(KeyEvent.KEYCODE_EXPLORER, "KEYCODE_EXPLORER");
        names.put(KeyEvent.KEYCODE_ENVELOPE, "KEYCODE_ENVELOPE");
        names.put(KeyEvent.KEYCODE_ENTER, "KEYCODE_ENTER");
        names.put(KeyEvent.KEYCODE_DEL, "KEYCODE_DEL");
        names.put(KeyEvent.KEYCODE_GRAVE, "KEYCODE_GRAVE");
        names.put(KeyEvent.KEYCODE_MINUS, "KEYCODE_MINUS");
        names.put(KeyEvent.KEYCODE_EQUALS, "KEYCODE_EQUALS");
        names.put(KeyEvent.KEYCODE_LEFT_BRACKET, "KEYCODE_LEFT_BRACKET");
        names.put(KeyEvent.KEYCODE_RIGHT_BRACKET, "KEYCODE_RIGHT_BRACKET");
        names.put(KeyEvent.KEYCODE_BACKSLASH, "KEYCODE_BACKSLASH");
        names.put(KeyEvent.KEYCODE_SEMICOLON, "KEYCODE_SEMICOLON");
        names.put(KeyEvent.KEYCODE_APOSTROPHE, "KEYCODE_APOSTROPHE");
        names.put(KeyEvent.KEYCODE_SLASH, "KEYCODE_SLASH");
        names.put(KeyEvent.KEYCODE_AT, "KEYCODE_AT");
        names.put(KeyEvent.KEYCODE_NUM, "KEYCODE_NUM");
        names.put(KeyEvent.KEYCODE_HEADSETHOOK, "KEYCODE_HEADSETHOOK");
        names.put(KeyEvent.KEYCODE_FOCUS, "KEYCODE_FOCUS");
        names.put(KeyEvent.KEYCODE_PLUS, "KEYCODE_PLUS");
        names.put(KeyEvent.KEYCODE_MENU, "KEYCODE_MENU");
        names.put(KeyEvent.KEYCODE_NOTIFICATION, "KEYCODE_NOTIFICATION");
        names.put(KeyEvent.KEYCODE_SEARCH, "KEYCODE_SEARCH");
        names.put(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, "KEYCODE_MEDIA_PLAY_PAUSE");
        names.put(KeyEvent.KEYCODE_MEDIA_STOP, "KEYCODE_MEDIA_STOP");
        names.put(KeyEvent.KEYCODE_MEDIA_NEXT, "KEYCODE_MEDIA_NEXT");
        names.put(KeyEvent.KEYCODE_MEDIA_PREVIOUS, "KEYCODE_MEDIA_PREVIOUS");
        names.put(KeyEvent.KEYCODE_MEDIA_REWIND, "KEYCODE_MEDIA_REWIND");
        names.put(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, "KEYCODE_MEDIA_FAST_FORWARD");
        names.put(KeyEvent.KEYCODE_MUTE, "KEYCODE_MUTE");
        names.put(KeyEvent.KEYCODE_PAGE_UP, "KEYCODE_PAGE_UP");
        names.put(KeyEvent.KEYCODE_PAGE_DOWN, "KEYCODE_PAGE_DOWN");
        names.put(KeyEvent.KEYCODE_PICTSYMBOLS, "KEYCODE_PICTSYMBOLS");
        names.put(KeyEvent.KEYCODE_SWITCH_CHARSET, "KEYCODE_SWITCH_CHARSET");
        names.put(KeyEvent.KEYCODE_BUTTON_A, "KEYCODE_BUTTON_A");
        names.put(KeyEvent.KEYCODE_BUTTON_B, "KEYCODE_BUTTON_B");
        names.put(KeyEvent.KEYCODE_BUTTON_C, "KEYCODE_BUTTON_C");
        names.put(KeyEvent.KEYCODE_BUTTON_X, "KEYCODE_BUTTON_X");
        names.put(KeyEvent.KEYCODE_BUTTON_Y, "KEYCODE_BUTTON_Y");
        names.put(KeyEvent.KEYCODE_BUTTON_Z, "KEYCODE_BUTTON_Z");
        names.put(KeyEvent.KEYCODE_BUTTON_L1, "KEYCODE_BUTTON_L1");
        names.put(KeyEvent.KEYCODE_BUTTON_R1, "KEYCODE_BUTTON_R1");
        names.put(KeyEvent.KEYCODE_BUTTON_L2, "KEYCODE_BUTTON_L2");
        names.put(KeyEvent.KEYCODE_BUTTON_R2, "KEYCODE_BUTTON_R2");
        names.put(KeyEvent.KEYCODE_BUTTON_THUMBL, "KEYCODE_BUTTON_THUMBL");
        names.put(KeyEvent.KEYCODE_BUTTON_THUMBR, "KEYCODE_BUTTON_THUMBR");
        names.put(KeyEvent.KEYCODE_BUTTON_START, "KEYCODE_BUTTON_START");
        names.put(KeyEvent.KEYCODE_BUTTON_SELECT, "KEYCODE_BUTTON_SELECT");
        names.put(KeyEvent.KEYCODE_BUTTON_MODE, "KEYCODE_BUTTON_MODE");
        /*names.put(KeyEvent.KEYCODE_ESCAPE, "KEYCODE_ESCAPE");
        names.put(KeyEvent.KEYCODE_FORWARD_DEL, "KEYCODE_FORWARD_DEL");
        names.put(KeyEvent.KEYCODE_CTRL_LEFT, "KEYCODE_CTRL_LEFT");
        names.put(KeyEvent.KEYCODE_CTRL_RIGHT, "KEYCODE_CTRL_RIGHT");
        names.put(KeyEvent.KEYCODE_CAPS_LOCK, "KEYCODE_CAPS_LOCK");
        names.put(KeyEvent.KEYCODE_SCROLL_LOCK, "KEYCODE_SCROLL_LOCK");
        names.put(KeyEvent.KEYCODE_META_LEFT, "KEYCODE_META_LEFT");
        names.put(KeyEvent.KEYCODE_META_RIGHT, "KEYCODE_META_RIGHT");
        names.put(KeyEvent.KEYCODE_FUNCTION, "KEYCODE_FUNCTION");
        names.put(KeyEvent.KEYCODE_SYSRQ, "KEYCODE_SYSRQ");
        names.put(KeyEvent.KEYCODE_BREAK, "KEYCODE_BREAK");
        names.put(KeyEvent.KEYCODE_MOVE_HOME, "KEYCODE_MOVE_HOME");
        names.put(KeyEvent.KEYCODE_MOVE_END, "KEYCODE_MOVE_END");
        names.put(KeyEvent.KEYCODE_INSERT, "KEYCODE_INSERT");
        names.put(KeyEvent.KEYCODE_FORWARD, "KEYCODE_FORWARD");
        names.put(KeyEvent.KEYCODE_MEDIA_PLAY, "KEYCODE_MEDIA_PLAY");
        names.put(KeyEvent.KEYCODE_MEDIA_PAUSE, "KEYCODE_MEDIA_PAUSE");
        names.put(KeyEvent.KEYCODE_MEDIA_CLOSE, "KEYCODE_MEDIA_CLOSE");
        names.put(KeyEvent.KEYCODE_MEDIA_EJECT, "KEYCODE_MEDIA_EJECT");
        names.put(KeyEvent.KEYCODE_MEDIA_RECORD, "KEYCODE_MEDIA_RECORD");
        names.put(KeyEvent.KEYCODE_F1, "KEYCODE_F1");
        names.put(KeyEvent.KEYCODE_F2, "KEYCODE_F2");
        names.put(KeyEvent.KEYCODE_F3, "KEYCODE_F3");
        names.put(KeyEvent.KEYCODE_F4, "KEYCODE_F4");
        names.put(KeyEvent.KEYCODE_F5, "KEYCODE_F5");
        names.put(KeyEvent.KEYCODE_F6, "KEYCODE_F6");
        names.put(KeyEvent.KEYCODE_F7, "KEYCODE_F7");
        names.put(KeyEvent.KEYCODE_F8, "KEYCODE_F8");
        names.put(KeyEvent.KEYCODE_F9, "KEYCODE_F9");
        names.put(KeyEvent.KEYCODE_F10, "KEYCODE_F10");
        names.put(KeyEvent.KEYCODE_F11, "KEYCODE_F11");
        names.put(KeyEvent.KEYCODE_F12, "KEYCODE_F12");
        names.put(KeyEvent.KEYCODE_NUM_LOCK, "KEYCODE_NUM_LOCK");
        names.put(KeyEvent.KEYCODE_NUMPAD_0, "KEYCODE_NUMPAD_0");
        names.put(KeyEvent.KEYCODE_NUMPAD_1, "KEYCODE_NUMPAD_1");
        names.put(KeyEvent.KEYCODE_NUMPAD_2, "KEYCODE_NUMPAD_2");
        names.put(KeyEvent.KEYCODE_NUMPAD_3, "KEYCODE_NUMPAD_3");
        names.put(KeyEvent.KEYCODE_NUMPAD_4, "KEYCODE_NUMPAD_4");
        names.put(KeyEvent.KEYCODE_NUMPAD_5, "KEYCODE_NUMPAD_5");
        names.put(KeyEvent.KEYCODE_NUMPAD_6, "KEYCODE_NUMPAD_6");
        names.put(KeyEvent.KEYCODE_NUMPAD_7, "KEYCODE_NUMPAD_7");
        names.put(KeyEvent.KEYCODE_NUMPAD_8, "KEYCODE_NUMPAD_8");
        names.put(KeyEvent.KEYCODE_NUMPAD_9, "KEYCODE_NUMPAD_9");
        names.put(KeyEvent.KEYCODE_NUMPAD_DIVIDE, "KEYCODE_NUMPAD_DIVIDE");
        names.put(KeyEvent.KEYCODE_NUMPAD_MULTIPLY, "KEYCODE_NUMPAD_MULTIPLY");
        names.put(KeyEvent.KEYCODE_NUMPAD_SUBTRACT, "KEYCODE_NUMPAD_SUBTRACT");
        names.put(KeyEvent.KEYCODE_NUMPAD_ADD, "KEYCODE_NUMPAD_ADD");
        names.put(KeyEvent.KEYCODE_NUMPAD_DOT, "KEYCODE_NUMPAD_DOT");
        names.put(KeyEvent.KEYCODE_NUMPAD_COMMA, "KEYCODE_NUMPAD_COMMA");
        names.put(KeyEvent.KEYCODE_NUMPAD_ENTER, "KEYCODE_NUMPAD_ENTER");
        names.put(KeyEvent.KEYCODE_NUMPAD_EQUALS, "KEYCODE_NUMPAD_EQUALS");
        names.put(KeyEvent.KEYCODE_NUMPAD_LEFT_PAREN, "KEYCODE_NUMPAD_LEFT_PAREN");
        names.put(KeyEvent.KEYCODE_NUMPAD_RIGHT_PAREN, "KEYCODE_NUMPAD_RIGHT_PAREN");
        names.put(KeyEvent.KEYCODE_VOLUME_MUTE, "KEYCODE_VOLUME_MUTE");
        names.put(KeyEvent.KEYCODE_INFO, "KEYCODE_INFO");
        names.put(KeyEvent.KEYCODE_CHANNEL_UP, "KEYCODE_CHANNEL_UP");
        names.put(KeyEvent.KEYCODE_CHANNEL_DOWN, "KEYCODE_CHANNEL_DOWN");
        names.put(KeyEvent.KEYCODE_ZOOM_IN, "KEYCODE_ZOOM_IN");
        names.put(KeyEvent.KEYCODE_ZOOM_OUT, "KEYCODE_ZOOM_OUT");
        names.put(KeyEvent.KEYCODE_TV, "KEYCODE_TV");
        names.put(KeyEvent.KEYCODE_WINDOW, "KEYCODE_WINDOW");
        names.put(KeyEvent.KEYCODE_GUIDE, "KEYCODE_GUIDE");
        names.put(KeyEvent.KEYCODE_DVR, "KEYCODE_DVR");
        names.put(KeyEvent.KEYCODE_BOOKMARK, "KEYCODE_BOOKMARK");
        names.put(KeyEvent.KEYCODE_CAPTIONS, "KEYCODE_CAPTIONS");
        names.put(KeyEvent.KEYCODE_SETTINGS, "KEYCODE_SETTINGS");
        names.put(KeyEvent.KEYCODE_TV_POWER, "KEYCODE_TV_POWER");
        names.put(KeyEvent.KEYCODE_TV_INPUT, "KEYCODE_TV_INPUT");
        names.put(KeyEvent.KEYCODE_STB_INPUT, "KEYCODE_STB_INPUT");
        names.put(KeyEvent.KEYCODE_STB_POWER, "KEYCODE_STB_POWER");
        names.put(KeyEvent.KEYCODE_AVR_POWER, "KEYCODE_AVR_POWER");
        names.put(KeyEvent.KEYCODE_AVR_INPUT, "KEYCODE_AVR_INPUT");
        names.put(KeyEvent.KEYCODE_PROG_RED, "KEYCODE_PROG_RED");
        names.put(KeyEvent.KEYCODE_PROG_GREEN, "KEYCODE_PROG_GREEN");
        names.put(KeyEvent.KEYCODE_PROG_YELLOW, "KEYCODE_PROG_YELLOW");
        names.put(KeyEvent.KEYCODE_PROG_BLUE, "KEYCODE_PROG_BLUE");
        names.put(KeyEvent.KEYCODE_APP_SWITCH, "KEYCODE_APP_SWITCH");
        names.put(KeyEvent.KEYCODE_BUTTON_1, "KEYCODE_BUTTON_1");
        names.put(KeyEvent.KEYCODE_BUTTON_2, "KEYCODE_BUTTON_2");
        names.put(KeyEvent.KEYCODE_BUTTON_3, "KEYCODE_BUTTON_3");
        names.put(KeyEvent.KEYCODE_BUTTON_4, "KEYCODE_BUTTON_4");
        names.put(KeyEvent.KEYCODE_BUTTON_5, "KEYCODE_BUTTON_5");
        names.put(KeyEvent.KEYCODE_BUTTON_6, "KEYCODE_BUTTON_6");
        names.put(KeyEvent.KEYCODE_BUTTON_7, "KEYCODE_BUTTON_7");
        names.put(KeyEvent.KEYCODE_BUTTON_8, "KEYCODE_BUTTON_8");
        names.put(KeyEvent.KEYCODE_BUTTON_9, "KEYCODE_BUTTON_9");
        names.put(KeyEvent.KEYCODE_BUTTON_10, "KEYCODE_BUTTON_10");
        names.put(KeyEvent.KEYCODE_BUTTON_11, "KEYCODE_BUTTON_11");
        names.put(KeyEvent.KEYCODE_BUTTON_12, "KEYCODE_BUTTON_12");
        names.put(KeyEvent.KEYCODE_BUTTON_13, "KEYCODE_BUTTON_13");
        names.put(KeyEvent.KEYCODE_BUTTON_14, "KEYCODE_BUTTON_14");
        names.put(KeyEvent.KEYCODE_BUTTON_15, "KEYCODE_BUTTON_15");
        names.put(KeyEvent.KEYCODE_BUTTON_16, "KEYCODE_BUTTON_16");
        names.put(KeyEvent.KEYCODE_LANGUAGE_SWITCH, "KEYCODE_LANGUAGE_SWITCH");
        names.put(KeyEvent.KEYCODE_MANNER_MODE, "KEYCODE_MANNER_MODE");
        names.put(KeyEvent.KEYCODE_3D_MODE, "KEYCODE_3D_MODE");
        names.put(KeyEvent.KEYCODE_CONTACTS, "KEYCODE_CONTACTS");
        names.put(KeyEvent.KEYCODE_CALENDAR, "KEYCODE_CALENDAR");
        names.put(KeyEvent.KEYCODE_MUSIC, "KEYCODE_MUSIC");
        names.put(KeyEvent.KEYCODE_CALCULATOR, "KEYCODE_CALCULATOR");
        */
    }
}
