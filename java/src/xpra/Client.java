package xpra;

public interface Client {

	public void send(String type, Object... data);

	public void send_positional(String type, Object... data);

	public void send_mouse_position(String type, Object... data);

	public void update_focus(int id, boolean gotit, boolean forceit);
}
