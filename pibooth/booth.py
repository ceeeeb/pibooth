#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Pibooth main module.
"""

import os
import os.path as osp
import tempfile
import shutil
import logging
import argparse
import multiprocessing
from warnings import filterwarnings

import pygame
from gpiozero import Device, Button, ButtonBoard, LEDBoard, pi_info
from gpiozero.exc import BadPinFactory, PinFactoryFallback

import pibooth
from pibooth import fonts
from pibooth import language
from pibooth.counters import Counters
from pibooth.utils import (LOGGER, PoolingTimer, configure_logging, get_crash_message,
                           set_logging_level, get_event_pos)
from pibooth.states import StateMachine
from pibooth.plugins import create_plugin_manager
from pibooth.view import PiWindow
from pibooth.config import PiConfigParser, PiConfigMenu
from pibooth.printer import PRINTER_TASKS_UPDATED, Printer


# Set the default pin factory to a mock factory if pibooth is not started a Raspberry Pi
try:
    filterwarnings("ignore", category=PinFactoryFallback)
    GPIO_INFO = "on Raspberry pi {0}".format(pi_info().model)
except BadPinFactory:
    from gpiozero.pins.mock import MockFactory
    Device.pin_factory = MockFactory()
    GPIO_INFO = "without physical GPIO, fallback to GPIO mock"


BUTTONDOWN = pygame.USEREVENT + 1



# Workaround for ButtonBoard bug in gpiozero 2.0.1
class LgpioButton:
    """Simple button using lgpio directly with polling."""
    def __init__(self, gpio_num, hold_time=0.2):
        import lgpio
        import threading
        self._gpio = gpio_num
        self._hold_time = hold_time
        self._handle = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_input(self._handle, gpio_num, lgpio.SET_PULL_UP)
        self._callback = None
        self._running = True
        self._last_state = 1  # Not pressed
        self._press_start = 0
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
    
    def _monitor(self):
        import lgpio
        import time
        while self._running:
            try:
                current = lgpio.gpio_read(self._handle, self._gpio)
                if current == 0 and self._last_state == 1:
                    # Button just pressed
                    self._press_start = time.time()
                    LOGGER.debug("LgpioButton GPIO%s: PRESSED", self._gpio)
                elif current == 0 and self._last_state == 0:
                    # Button still pressed
                    if self._callback and (time.time() - self._press_start) >= self._hold_time:
                        LOGGER.debug("LgpioButton GPIO%s: HOLD triggered, calling callback", self._gpio)
                        self._callback()
                        self._press_start = time.time() + 999  # Prevent repeat
                self._last_state = current
            except Exception as e:
                LOGGER.debug("LgpioButton GPIO%s: error %s", self._gpio, e)
            time.sleep(0.05)
    
    @property
    def when_held(self):
        return self._callback
    
    @when_held.setter
    def when_held(self, callback):
        self._callback = callback
    
    @property
    def value(self):
        import lgpio
        # Return 1 when pressed (GPIO LOW), 0 when not pressed (GPIO HIGH)
        return 1 - lgpio.gpio_read(self._handle, self._gpio)
    
    def close(self):
        self._running = False
        import lgpio
        try:
            lgpio.gpiochip_close(self._handle)
        except:
            pass


class ButtonsWrapper:
    """Wrapper that uses individual Button objects."""
    def __init__(self, capture_pin, printer_pin, hold_time, pull_up):
        self.capture = Button(capture_pin, pull_up=pull_up, hold_time=hold_time)
        # Use lgpio directly for printer button due to gpiozero bug
        printer_gpio = int(printer_pin.replace("BOARD", ""))
        # Convert BOARD to BCM: BOARD32 = GPIO12
        board_to_bcm = {32: 12, 11: 17, 36: 16, 37: 26, 33: 13, 31: 6}
        self.printer = LgpioButton(board_to_bcm.get(printer_gpio, 12), hold_time=hold_time)
    
    @property
    def value(self):
        return (self.capture.value, self.printer.value)
    
    def close(self):
        self.capture.close()
        self.printer.close()


class PiApplication(object):

    """Main class representing the ``pibooth`` software.
    The following attributes are available for use in plugins:

    :attr capture_nbr: number of capture to be done in the current sequence
    :type capture_nbr: int
    :attr capture_date: date (%Y-%m-%d-%H-%M-%S) of the first capture of the current sequence
    :type capture_date: str
    :attr capture_choices: possible choices of captures numbers.
    :type capture_choices: tuple
    :attr previous_picture: picture generated during last sequence
    :type previous_picture: :py:class:`PIL.Image`
    :attr previous_animated: infinite list of picture to display during animation
    :type previous_animated: :py:func:`itertools.cycle`
    :attr previous_picture_file: file name of the picture generated during last sequence
    :type previous_picture_file: str
    :attr count: holder for counter values
    :type count: :py:class:`pibooth.counters.Counters`
    :attr camera: camera used
    :type camera: :py:class:`pibooth.camera.base.BaseCamera`
    :attr buttons: access to hardware buttons ``capture`` and ``printer``
    :type buttons: :py:class:`gpiozero.ButtonBoard`
    :attr leds: access to hardware LED ``capture`` and ``printer``
    :attr leds: :py:class:`gpiozero.LEDBoard`
    :attr printer: printer used
    :type printer: :py:class:`pibooth.printer.Printer`
    """

    def __init__(self, config, plugin_manager):
        self._pm = plugin_manager
        self._config = config

        # Create directories where pictures are saved
        for savedir in config.gettuple('GENERAL', 'directory', 'path'):
            if osp.isdir(savedir) and config.getboolean('GENERAL', 'debug'):
                shutil.rmtree(savedir)
            if not osp.isdir(savedir):
                os.makedirs(savedir)

        # Create window of (width, height)
        init_size = self._config.gettyped('WINDOW', 'size')
        init_debug = self._config.getboolean('GENERAL', 'debug')
        init_color = self._config.gettyped('WINDOW', 'background')
        init_text_color = self._config.gettyped('WINDOW', 'text_color')
        if not isinstance(init_color, (tuple, list)):
            init_color = self._config.getpath('WINDOW', 'background')

        title = 'Pibooth v{}'.format(pibooth.__version__)
        if not isinstance(init_size, str):
            self._window = PiWindow(title, init_size, color=init_color,
                                    text_color=init_text_color, debug=init_debug)
        else:
            self._window = PiWindow(title, color=init_color,
                                    text_color=init_text_color, debug=init_debug)

        self._menu = None
        self._multipress_timer = PoolingTimer(config.getfloat('CONTROLS', 'multi_press_delay'), False)
        self._fingerdown_events = []

        # Define states of the application
        self._machine = StateMachine(self._pm, self._config, self, self._window)
        self._machine.add_state('wait')
        self._machine.add_state('choose')
        self._machine.add_state('chosen')
        self._machine.add_state('preview')
        self._machine.add_state('capture')
        self._machine.add_state('processing')
        self._machine.add_state('print')
        self._machine.add_state('finish')

        # ---------------------------------------------------------------------
        # Variables shared with plugins
        # Change them may break plugins compatibility
        self.capture_nbr = None
        self.capture_date = None
        self.capture_choices = (4, 1)
        self.previous_picture = None
        self.previous_animated = None
        self.previous_picture_file = None

        self.count = Counters(self._config.join_path("counters.pickle"),
                              taken=0, printed=0, forgotten=0,
                              remaining_duplicates=self._config.getint('PRINTER', 'max_duplicates'))

        self.camera = self._pm.hook.pibooth_setup_camera(cfg=self._config)

        self.buttons = ButtonsWrapper(capture_pin="BOARD" + config.get('CONTROLS', 'picture_btn_pin'),
                                   printer_pin="BOARD" + config.get('CONTROLS', 'print_btn_pin'),
                                   hold_time=config.getfloat('CONTROLS', 'debounce_delay'),
                                   pull_up=True)
        self.buttons.capture.when_held = self._on_button_capture_held
        self.buttons.printer.when_held = self._on_button_printer_held
        LOGGER.info("Buttons initialized: capture.value=%s printer.value=%s", self.buttons.capture.value, self.buttons.printer.value)

        self.leds = LEDBoard(capture="BOARD" + config.get('CONTROLS', 'picture_led_pin'),
                             printer="BOARD" + config.get('CONTROLS', 'print_led_pin'))

        self.printer = Printer(config.get('PRINTER', 'printer_name'),
                               config.getint('PRINTER', 'max_pages'),
                               config.gettyped('PRINTER', 'printer_options'),
                               self.count)
        # ---------------------------------------------------------------------

    def _initialize(self):
        """Restore the application with initial parameters defined in the
        configuration file.
        Only parameters that can be changed at runtime are restored.
        """
        # Handle the language configuration
        language.CURRENT = self._config.get('GENERAL', 'language')
        fonts.CURRENT = fonts.get_filename(self._config.get('WINDOW', 'font'))

        # Set the captures choices
        choices = self._config.gettuple('PICTURE', 'captures', int)
        for chx in choices:
            if chx not in [1, 2, 3, 4]:
                LOGGER.warning("Invalid captures number '%s' in config, fallback to '%s'",
                               chx, self.capture_choices)
                choices = self.capture_choices
                break
        self.capture_choices = choices

        # Handle autostart of the application
        self._config.handle_autostart()

        self._window.arrow_location = self._config.get('WINDOW', 'arrows')
        self._window.arrow_offset = self._config.getint('WINDOW', 'arrows_x_offset')
        self._window.text_color = self._config.gettyped('WINDOW', 'text_color')
        self._window.drop_cache()

        # Handle window size
        size = self._config.gettyped('WINDOW', 'size')
        if isinstance(size, str) and size.lower() == 'fullscreen':
            if not self._window.is_fullscreen:
                self._window.toggle_fullscreen()
        else:
            if self._window.is_fullscreen:
                self._window.toggle_fullscreen()
        self._window.debug = self._config.getboolean('GENERAL', 'debug')

        # Handle debug mode
        if not self._config.getboolean('GENERAL', 'debug'):
            set_logging_level()  # Restore default level
            self._machine.add_failsafe_state('failsafe')
        else:
            set_logging_level(logging.DEBUG)
            self._machine.remove_state('failsafe')

        # Reset the print counter (in case of max_pages is reached)
        self.printer.max_pages = self._config.getint('PRINTER', 'max_pages')

    def _on_button_capture_held(self):
        """Called when the capture button is pressed.
        """
        if all(self.buttons.value):
            self.buttons.capture.hold_repeat = True
            if self._multipress_timer.elapsed() == 0:
                self._multipress_timer.start()
            if self._multipress_timer.is_timeout():
                # Capture was held while printer was pressed
                if self._menu and self._menu.is_shown():
                    # Convert HW button events to keyboard events for menu
                    event = self._menu.create_back_event()
                    LOGGER.debug("BUTTONDOWN: generate MENU-ESC event")
                else:
                    event = pygame.event.Event(BUTTONDOWN, capture=1, printer=1,
                                               button=self.buttons)
                    LOGGER.debug("BUTTONDOWN: generate DOUBLE buttons event")
                self.buttons.capture.hold_repeat = False
                self._multipress_timer.reset()
                pygame.event.post(event)
        else:
            # Capture was held but printer not pressed
            if self._menu and self._menu.is_shown():
                # Convert HW button events to keyboard events for menu
                event = self._menu.create_next_event()
                LOGGER.debug("BUTTONDOWN: generate MENU-NEXT event")
            else:
                event = pygame.event.Event(BUTTONDOWN, capture=1, printer=0,
                                           button=self.buttons.capture)
                LOGGER.debug("BUTTONDOWN: generate CAPTURE button event")
            self.buttons.capture.hold_repeat = False
            self._multipress_timer.reset()
            pygame.event.post(event)

    def _on_button_printer_held(self):
        """Called when the printer button is pressed."""
        if self._menu and self._menu.is_shown():
            # Convert HW button events to keyboard events for menu
            event = self._menu.create_click_event()
            LOGGER.debug("BUTTONDOWN: generate MENU-APPLY event")
        else:
            event = pygame.event.Event(BUTTONDOWN, capture=0, printer=1,
                                       button=self.buttons.printer)
            LOGGER.debug("BUTTONDOWN: generate PRINTER event")
        pygame.event.post(event)

    @property
    def picture_filename(self):
        """Return the final picture file name.
        """
        if not self.capture_date:
            raise EnvironmentError("The 'capture_date' attribute is not set yet")
        return "{}_pibooth.jpg".format(self.capture_date)

    def find_quit_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.QUIT:
                return event
        return None

    def find_settings_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return event
            if event.type == BUTTONDOWN and event.capture and event.printer:
                return event
            if event.type == pygame.FINGERDOWN:
                # Press but not release
                self._fingerdown_events.append(event)
            if event.type == pygame.FINGERUP:
                # Resetting touch_events
                self._fingerdown_events = []
            if len(self._fingerdown_events) > 3:
                # 4 fingers on the screen trigger the menu
                self._fingerdown_events = []
                return pygame.event.Event(BUTTONDOWN, capture=1, printer=1,
                                          button=self.buttons)
        return None

    def find_close_menu_event(self, events):
        """Return the first 4-finger gesture from the events.

        Used to trigger the save/discard confirmation popup while the
        config menu is open. Shares ``_fingerdown_events`` with
        ``find_settings_event``.
        """
        for event in events:
            if event.type == pygame.FINGERDOWN:
                self._fingerdown_events.append(event)
            if event.type == pygame.FINGERUP:
                self._fingerdown_events = []
            if len(self._fingerdown_events) > 3:
                self._fingerdown_events = []
                return event
        return None

    def find_fullscreen_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.KEYDOWN and \
                    event.key == pygame.K_f and pygame.key.get_mods() & pygame.KMOD_CTRL:
                return event
        return None

    def find_resize_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.VIDEORESIZE:
                return event
        return None

    def find_capture_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                return event
            if (event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2, 3)) or event.type == pygame.FINGERUP:
                pos = get_event_pos(self._window.display_size, event)
                rect = self._window.get_rect()
                if pygame.Rect(0, 0, rect.width // 2, rect.height).collidepoint(pos):
                    return event
            if event.type == BUTTONDOWN and event.capture:
                return event
        return None

    def find_print_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_e\
                    and pygame.key.get_mods() & pygame.KMOD_CTRL:
                return event
            if (event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2, 3)) or event.type == pygame.FINGERUP:
                pos = get_event_pos(self._window.display_size, event)
                rect = self._window.get_rect()
                if pygame.Rect(rect.width // 2, 0, rect.width // 2, rect.height).collidepoint(pos):
                    return event
            if event.type == BUTTONDOWN and event.printer:
                return event
        return None

    def find_print_status_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == PRINTER_TASKS_UPDATED:
                return event
        return None

    def find_choice_event(self, events):
        """Return the first found event if found in the list.
        """
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_LEFT:
                return event
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RIGHT:
                return event
            if (event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2, 3)) or event.type == pygame.FINGERUP:
                pos = get_event_pos(self._window.display_size, event)
                rect = self._window.get_rect()
                if pygame.Rect(0, 0, rect.width // 2, rect.height).collidepoint(pos):
                    event.key = pygame.K_LEFT
                else:
                    event.key = pygame.K_RIGHT
                return event
            if event.type == BUTTONDOWN:
                if event.capture:
                    event.key = pygame.K_LEFT
                else:
                    event.key = pygame.K_RIGHT
                return event
        return None

    def main_loop(self):
        try:
            fps = 40
            clock = pygame.time.Clock()
            self._initialize()
            self._pm.hook.pibooth_startup(cfg=self._config, app=self)
            self._machine.set_state('wait')

            while True:
                events = list(pygame.event.get())

                if self.find_quit_event(events):
                    break

                if self.find_fullscreen_event(events):
                    self._window.toggle_fullscreen()

                event = self.find_resize_event(events)
                if event:
                    self._window.resize(event.size)

                if not self._menu and self.find_settings_event(events):
                    self.camera.stop_preview()
                    self.leds.off()
                    self._menu = PiConfigMenu(self._pm, self._config, self, self._window)
                    self._menu.show()
                    self.leds.blink(on_time=0.1, off_time=1)
                elif self._menu and self._menu.is_shown():
                    if not self._menu.is_confirming() and self.find_close_menu_event(events):
                        self._menu.show_close_confirmation()
                    self._menu.process(events)
                elif self._menu and not self._menu.is_shown():
                    self.leds.off()
                    self._initialize()
                    self._machine.set_state('wait')
                    self._menu = None
                else:
                    self._machine.process(events)

                pygame.display.update()
                clock.tick(fps)  # Ensure the program will never run at more than <fps> frames per second

        except Exception as ex:
            LOGGER.error(str(ex), exc_info=True)
            LOGGER.error(get_crash_message())
        finally:
            self._pm.hook.pibooth_cleanup(app=self)
            pygame.quit()


def main():
    """Application entry point.
    """
    if hasattr(multiprocessing, 'set_start_method'):
        # Avoid use 'fork': safely forking a multithreaded process is problematic
        multiprocessing.set_start_method('spawn')

    parser = argparse.ArgumentParser(usage="%(prog)s [options]", description=pibooth.__doc__)

    parser.add_argument("config_directory", nargs='?', default="~/.config/pibooth",
                        help=u"path to configuration directory (default: %(default)s)")

    parser.add_argument('--version', action='version', version=pibooth.__version__,
                        help=u"show program's version number and exit")

    parser.add_argument("--config", action='store_true',
                        help=u"edit the current configuration and exit")

    parser.add_argument("--translate", action='store_true',
                        help=u"edit the GUI translations and exit")

    parser.add_argument("--reset", action='store_true',
                        help=u"restore the default configuration/translations and exit")

    parser.add_argument("--nolog", action='store_true', default=False,
                        help=u"don't save console output in a file (avoid filling the /tmp directory)")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-v", "--verbose", dest='logging', action='store_const', const=logging.DEBUG,
                       help=u"report more information about operations", default=logging.INFO)
    group.add_argument("-q", "--quiet", dest='logging', action='store_const', const=logging.WARNING,
                       help=u"report only errors and warnings", default=logging.INFO)

    options = parser.parse_args()

    if not options.nolog:
        filename = osp.join(tempfile.gettempdir(), 'pibooth.log')
    else:
        filename = None
    configure_logging(options.logging, '[ %(levelname)-8s] %(name)-18s: %(message)s', filename=filename)

    plugin_manager = create_plugin_manager()

    # Load the configuration
    config = PiConfigParser(osp.join(options.config_directory, "pibooth.cfg"), plugin_manager, not options.reset)

    # Register plugins
    plugin_manager.load_all_plugins(config.gettuple('GENERAL', 'plugins', 'path'),
                                    config.gettuple('GENERAL', 'plugins_disabled', str))
    LOGGER.info("Installed plugins: %s", ", ".join(
        [plugin_manager.get_friendly_name(p) for p in plugin_manager.list_external_plugins()]))

    # Load the languages
    language.init(config.join_path("translations.cfg"), options.reset)

    # Update configuration with plugins ones
    plugin_manager.hook.pibooth_configure(cfg=config)

    # Ensure config files are present in case of first pibooth launch
    if not options.reset:
        if not osp.isfile(config.filename):
            config.save(default=True)
        plugin_manager.hook.pibooth_reset(cfg=config, hard=False)

    if options.config:
        LOGGER.info("Editing the pibooth configuration...")
        config.edit()
    elif options.translate:
        LOGGER.info("Editing the GUI translations...")
        language.edit()
    elif options.reset:
        config.save(default=True)
        plugin_manager.hook.pibooth_reset(cfg=config, hard=True)
    else:
        LOGGER.info("Starting the photo booth application %s", GPIO_INFO)
        app = PiApplication(config, plugin_manager)
        app.main_loop()


if __name__ == '__main__':
    main()
