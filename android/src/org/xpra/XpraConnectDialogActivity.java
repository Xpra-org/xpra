package org.xpra;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.View.OnClickListener;
import android.widget.Button;
import android.widget.TextView;

public class XpraConnectDialogActivity extends Activity {

	protected TextView hostname = null;
	protected TextView port = null;
	protected TextView password = null;

	protected Button connect = null;

	@Override
	protected void onCreate(Bundle savedInstanceState) {
		super.onCreate(savedInstanceState);
		Log.i(this.getClass().getSimpleName(), "onCreate(" + savedInstanceState + ")");
		this.setTitle("Xpra Connection Settings");
		setContentView(R.layout.xpra_connect);

		this.hostname = (TextView) this.findViewById(R.id.xpra_connect_hostname);
		this.port = (TextView) this.findViewById(R.id.xpra_connect_port);
		this.password = (TextView) this.findViewById(R.id.xpra_connect_password);
		this.connect = (Button) this.findViewById(R.id.xpra_connect_button);

		this.connect.setOnClickListener(new OnClickListener() {
			@Override
			public void onClick(View v) {
				connect();
			}
		});
	}

	protected void connect() {
		String host = this.hostname.getText().toString();
		int portNo = -1;
		try {
			portNo = Integer.parseInt(this.port.getText().toString());
		} catch (NumberFormatException e) {
			return;
		}
		String pass = this.password.getText().toString();
		Intent intent = new Intent(this, XpraActivity.class);
		intent.putExtra(XpraActivity.PARAM_HOST, host);
		intent.putExtra(XpraActivity.PARAM_PORT, portNo);
		intent.putExtra(XpraActivity.PARAM_PASSWORD, pass == null ? null : pass.getBytes());
		this.startActivity(intent);
	}
}