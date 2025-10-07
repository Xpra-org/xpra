#!/usr/bin/env python3

"""
Example usage of the Wayland compositor Cython module
"""
from xpra.wayland.compositor import WaylandCompositor
import numpy as np


def pixel_callback(pixel_array, width, height):
    """Called whenever window pixels are captured"""
    # Convert memoryview to numpy array
    pixels = np.asarray(pixel_array)

    # Calculate average RGB values
    avg_r = pixels[:, :, 0].mean()
    avg_g = pixels[:, :, 1].mean()
    avg_b = pixels[:, :, 2].mean()

    print(f"Captured {width}x{height} frame - Avg RGB: ({avg_r:.1f}, {avg_g:.1f}, {avg_b:.1f})")

    # You could save to file, process, etc.
    # Example: save as PNG
    # from PIL import Image
    # img = Image.fromarray(pixels[:, :, :3], 'RGB')
    # img.save(f'frame_{time.time()}.png')


def main():
    # Create compositor instance
    compositor = WaylandCompositor()

    # Initialize the compositor
    socket = compositor.initialize()
    print(f"Compositor initialized on socket: {socket}")
    print(f"Run applications with: WAYLAND_DISPLAY={socket} <application>")
    print("Press Ctrl+C to stop")

    try:
        # Run the event loop
        compositor.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        compositor.cleanup()


if __name__ == '__main__':
    main()
