package xpra;

import java.util.Map;

public interface ClientWindow {

	public void update_metadata(Map<String, Object> metadata);

	public void draw(int x, int y, int width, int height, String coding, byte[] img_data);

	public void move_resize(int x, int y, int w, int h);

	public void destroy();

}
