package xpra.gtk;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.gnome.gdk.ModifierType;

public class Keys {

	public static final String SHIFT = "shift";
	public static final String CONTROL = "control";
	public static final String META = "meta";
	public static final String SUPER = "super";
	public static final String HYPER = "hyper";
	public static final String ALT = "alt";

	public static final Map<ModifierType, String> mappings = new HashMap<ModifierType, String>();
	static {
		mappings.put(ModifierType.SHIFT_MASK, SHIFT);
		mappings.put(ModifierType.CONTROL_MASK, CONTROL);
		mappings.put(ModifierType.WINDOW_MASK, META);
		mappings.put(ModifierType.SUPER_MASK, SUPER);
		mappings.put(ModifierType.HYPER_MASK, HYPER);
		mappings.put(ModifierType.ALT_MASK, ALT);
	}

	public static List<String> mask_to_names(ModifierType mod) {
		List<String> modifiers = new ArrayList<String>(5);
		for (Map.Entry<ModifierType, String> me : mappings.entrySet())
			if (mod.contains(me.getKey()))
				modifiers.add(me.getValue());
		return modifiers;
	}
}
