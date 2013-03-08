package xpra.swing;

import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Toolkit;

import javax.swing.JComponent;
import javax.swing.JFrame;

public class SwingWindowTest {

	public static class MyCanvas extends JComponent {
		private static final long serialVersionUID = 1L;

		@Override
		public void paint(Graphics g) {
			Graphics2D g2 = (Graphics2D) g;
			Image img1 = Toolkit.getDefaultToolkit().getImage("test.gif");
			g2.drawImage(img1, 10, 10, this);
			g2.finalize();
		}
	}

	public static void main(String[] args) {
		JFrame window = new JFrame();
		window.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		window.setBounds(30, 30, 300, 300);
		window.getContentPane().add(new MyCanvas());
		window.setVisible(true);

		/*
		 * Client c = new Client() {
		 *
		 * @Override public void send(String type, Object... data) {
		 * System.out.println("send(" + type + ", " + Arrays.asList(data)); } };
		 * SwingWindow w = new SwingWindow(c, 1, 20, 60, 640, 480, new
		 * HashMap<String, Object>(0), false);
		 */
	}
}
