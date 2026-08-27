#!/bin/bash
# Display network info window, then launch pibooth.
# Display rotation is handled by firmware (display_hdmi_rotate=2 in config.txt).
# Touch is flipped 180° in pibooth's get_event_pos since SDL reads raw evdev.
# Forbid SDL from synthesising mouse events from touches (they would bypass the flip).
export SDL_TOUCH_MOUSE_EVENTS=0
/usr/bin/python3 /home/pi/wifi-info-display.py
exec /home/pi/pibooth/pibooth/bin/pibooth
