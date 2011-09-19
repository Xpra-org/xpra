package org.xpra;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

import xpra.AbstractClient;
import xpra.ClientWindow;
import android.view.Display;
import android.view.LayoutInflater;

public class AndroidXpraClient extends AbstractClient {
	
	protected	XpraActivity context = null;
	protected	LayoutInflater inflater = null;

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
	protected ClientWindow	createWindow(int id, int x, int y, int w, int h, Map<String,Object> metadata, boolean override_redirect) {
		//XpraWindow window = new XpraWindow(this.context, this, id, x, y, w, h, metadata, override_redirect);
		XpraWindow window = (XpraWindow) this.inflater.inflate(R.layout.xpra_window, null);	//this.context.mDragLayer);
		window.init(this.context, this, id, x, y, w, h, metadata, override_redirect);
		this.log("createWindow("+id+", "+x+", "+y+", "+w+", "+h+", "+metadata+", "+override_redirect+")="+window);
		this.context.add(window);
		//this.context.mDragLayer.addView(window);
		return	window;
    }
}
