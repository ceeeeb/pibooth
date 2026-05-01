# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pibooth is a photo booth application in pure Python for Raspberry Pi. This is a **custom fork** (v2.0.8.1) of [pibooth/pibooth](https://github.com/pibooth/pibooth) with additional plugins (Nextcloud upload, chroma key, background changer, forget button).

**Target hardware**: Raspberry Pi with GPIO buttons/LEDs, camera module or DSLR, optional CUPS printer.
**Deployment**: installed via `pip install -e .` on a Raspberry Pi at `pi@192.168.68.24` in `/home/pi/pibooth-custom/`.

## Commands

```bash
# Install (development, on the Pi)
pip install -e .

# Run the application
pibooth                    # uses default config dir (~/.config/pibooth/)
pibooth /path/to/config    # custom config directory

# CLI tools
pibooth-count              # show photo/print counters
pibooth-diag               # hardware diagnostics
pibooth-fonts              # list available fonts
pibooth-printcfg           # configure CUPS printer
pibooth-regen              # regenerate picture composites

# Configuration
pibooth --config           # edit config in external editor
pibooth --reset            # reset config to defaults
pibooth --translate        # edit translation file
```

No test suite or linter is configured in this fork.

## Architecture

### State Machine

The application is a finite state machine (`PiApplication` in `booth.py` extends `StateMachine` from `states.py`). Each state has 4 plugin hooks: `enter`, `do` (loop), `validate` (returns next state or None), `exit`.

```
wait → choose → chosen → preview → capture → processing → print → finish → wait
                                                                 ↗
                                              (failsafe on error)
```

- **wait**: idle screen, shows previous picture or intro animation
- **choose**: user selects number of captures (1-4), skipped if only one option
- **chosen**: briefly displays selected layout
- **preview**: live camera feed with countdown
- **capture**: takes photographs (1-4 sequential captures)
- **processing**: composites captures into final picture, saves to disk
- **print**: print confirmation screen (button or timeout)
- **finish**: success display before returning to wait

### Plugin System (pluggy)

All application logic lives in plugins registered via `pluggy`. Core plugins are loaded in this order (LIFO, so CameraPlugin is called first):

1. `CameraPlugin` (`plugins/camera_plugin.py`) - camera init, capture, preview
2. `PicturePlugin` (`plugins/picture_plugin.py`) - picture composition and save
3. `PrinterPlugin` (`plugins/printer_plugin.py`) - CUPS printing
4. `ViewPlugin` (`plugins/view_plugin.py`) - pygame window rendering
5. `LightsPlugin` (`plugins/lights_plugin.py`) - GPIO LED control

External plugins are loaded from paths in config `[GENERAL] plugins` and can hook into any state or lifecycle event. Hook specs are defined in `plugins/hookspecs.py`.

Key lifecycle hooks: `pibooth_configure`, `pibooth_startup`, `pibooth_cleanup`, `pibooth_setup_camera`, `pibooth_setup_picture_factory`.

### Camera Backends

Camera detection priority (in `camera/__init__.py:find_camera()`):

1. **HybridRpiCamera** - Pi Camera + gPhoto2 DSLR
2. **HybridCvCamera** - OpenCV + gPhoto2 DSLR
3. **GpCamera** - gPhoto2 only (DSLR/mirrorless)
4. **RpiCamera** - Pi Camera Module (picamera)
5. **CvCamera** - OpenCV webcam

All inherit from `BaseCamera` (`camera/base.py`). Custom cameras can be provided via the `pibooth_setup_camera` hook.

### Picture Pipeline

1. Raw captures saved to `{savedir}/raw/{date}/pibooth{00-03}.jpg`
2. `PictureFactory` (PIL or OpenCV) composites captures into a layout
3. Footer text, overlays (PNG), and backgrounds applied
4. Final picture saved as `{savedir}/{date}_pibooth.jpg`

Two factory implementations in `pictures/factory.py`: `PilPictureFactory` (default) and `OpenCvPictureFactory`.

### Configuration

INI format via `PiConfigParser` (`config/parser.py`), stored at `~/.config/pibooth/pibooth.cfg`. Sections: `GENERAL`, `WINDOW`, `PICTURE`, `CAMERA`, `PRINTER`, `CONTROLS`. Plugins add their own sections via `pibooth_configure`.

## Key Terminology

- **capture**: a single raw photograph from the camera
- **picture**: the final composite image (1-4 captures + text + overlay + background)
- **image**: generic PIL/OpenCV image object or UI pictogram

## Key Application Attributes (available to plugins via `app`)

`capture_nbr`, `capture_date`, `capture_choices`, `previous_picture`, `previous_picture_file`, `count` (counters: taken/printed/forgotten/remaining_duplicates), `camera`, `buttons`, `leds`, `printer`.

## Custom Extensions (vs upstream pibooth)

This fork includes additional plugin sections in config:
- **[NEXTCLOUD]** - auto-upload to Nextcloud with QR code generation
- **[BACKGROUND_CHANGER]** - AI background replacement (silueta model)
- **[CHROMAKEY]** - green/blue screen replacement
- **[FORGET_BUTTON]** - hardware button to discard photos (GPIO 36/37)
- **Extra LED pins** - startup, preview, flash LEDs

## Hardware Notes

- GPIO uses BOARD numbering (gpiozero)
- Custom `LgpioButton` class in `booth.py` works around gpiozero 2.0.1 bug for printer button
- Falls back to `MockFactory` on non-Raspberry Pi systems
- Window shortcuts: ESC + both buttons = settings, Ctrl+F = fullscreen, 4-finger touch = settings
