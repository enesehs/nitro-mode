#!/usr/bin/env python3
from evdev import InputDevice, ecodes
import subprocess
import sys
import os
import threading
import time
import glob
import json
import psutil
import logging
import traceback
from datetime import datetime
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

profiles = {
    "powersave": {"cpu_governor": "powersave", "cpu_max_freq": "1800000", "gpu_power": "low"},
    "balanced": {"cpu_governor": "schedutil", "cpu_max_freq": "3200000", "gpu_power": "auto"},
    "performance": {"cpu_governor": "performance", "cpu_max_freq": "4200000", "gpu_power": "high"}
}

CONFIG_FILE = os.path.expanduser("~/.config/mode/mode.json")
LOG_DIR = os.path.expanduser("~/.config/mode/logs")
THERMAL_THRESHOLD = 88

def get_log_file():
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"mode_{today}.log")

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = get_log_file()

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info("Performance Mode Switcher started")
    logging.info(f"Log file: {log_file}")

def cleanup_old_logs(days_to_keep=30):
    try:
        if not os.path.exists(LOG_DIR):
            return

        cutoff_date = datetime.now() - datetime.timedelta(days=days_to_keep)
        deleted_count = 0

        for filename in os.listdir(LOG_DIR):
            if filename.startswith("mode_") and filename.endswith(".log"):
                file_path = os.path.join(LOG_DIR, filename)
                try:
                    file_date_str = filename[5:15]  # Extract YYYY-MM-DD from mode_YYYY-MM-DD.log
                    file_date = datetime.strptime(file_date_str, "%Y-%m-%d")

                    if file_date < cutoff_date:
                        os.remove(file_path)
                        deleted_count += 1
                except (ValueError, OSError):
                    continue

        if deleted_count > 0:
            logging.info(f"Cleaned up {deleted_count} old log files (older than {days_to_keep} days)")
    except Exception as e:
        logging.warning(f"Failed to cleanup old logs: {e}")

def log_system_info():
    try:
        cpu_info = f"CPU Count: {os.cpu_count()}"
        available_govs = get_available_governors()
        gov_info = f"Available governors: {', '.join(available_govs) if available_govs else 'None'}"
        temp = get_cpu_temperature()
        temp_info = f"Current CPU temperature: {temp:.1f}°C" if temp else "Temperature: N/A"

        logging.info(f"System Info - {cpu_info}")
        logging.info(f"System Info - {gov_info}")
        logging.info(f"System Info - {temp_info}")
    except Exception as e:
        logging.error(f"Failed to log system info: {e}")

def send_notification(title, message, urgency="normal"):
    try:
        subprocess.run(["notify-send", "-u", urgency, title, message], capture_output=True)
        logging.info(f"Notification sent: {title} - {message}")
    except FileNotFoundError:
        logging.warning(f"notify-send not found, fallback: {title} - {message}")
        print(f"Notification: {title} - {message}")

def save_current_mode(mode):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump({"last_mode": mode, "last_save": datetime.now().isoformat()}, f)
        logging.info(f"Mode saved: {mode}")
    except Exception as e:
        logging.error(f"Failed to save mode: {e}")

def load_saved_mode():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                mode = data.get("last_mode", "balanced")
                last_save = data.get("last_save", "Unknown")
                logging.info(f"Loaded saved mode: {mode} (saved: {last_save})")
                return mode
    except Exception as e:
        logging.error(f"Failed to load saved mode: {e}")
    logging.info("Using default mode: balanced")
    return "balanced"

def get_cpu_temperature():
    try:
        temps = psutil.sensors_temperatures()
        if 'coretemp' in temps:
            return max(sensor.current for sensor in temps['coretemp'])
        elif 'k10temp' in temps:
            return max(sensor.current for sensor in temps['k10temp'])
        elif 'acpi' in temps:
            return max(sensor.current for sensor in temps['acpi'])
        for name, sensors in temps.items():
            if sensors:
                return max(sensor.current for sensor in sensors)
    except Exception as e:
        logging.warning(f"Failed to read temperature: {e}")
    return None

def monitor_thermal():
    global should_monitor, current_mode
    last_warning = 0
    logging.info("Thermal monitoring started")
    while should_monitor:
        try:
            temp = get_cpu_temperature()
            if temp and temp > THERMAL_THRESHOLD:
                current_time = time.time()
                if current_time - last_warning > 30:
                    send_notification("Thermal Warning", f"CPU temperature: {temp:.1f}°C", "critical")
                    logging.warning(f"High CPU temperature: {temp:.1f}°C")
                    last_warning = current_time
            time.sleep(5)
        except Exception as e:
            logging.error(f"Error in thermal monitoring: {e}")
            break
    logging.info("Thermal monitoring stopped")

def get_available_governors():
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors", "r") as f:
            return f.read().strip().split()
    except (FileNotFoundError, PermissionError):
        return []

def check_dependencies():
    logging.info("Checking system dependencies...")
    missing_tools = []
    try:
        subprocess.run(["which", "cpupower"], check=True, capture_output=True)
        logging.info("cpupower: Available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing_tools.append("cpupower")
        logging.warning("cpupower: Not found")

    try:
        subprocess.run(["which", "systemctl"], check=True, capture_output=True)
        logging.info("systemctl: Available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        logging.warning("systemctl not found - TLP management will be skipped")

    if missing_tools:
        logging.error(f"Missing required tools: {', '.join(missing_tools)}")
        print(f"Warning: Missing required tools: {', '.join(missing_tools)}")

    available_govs = get_available_governors()
    if available_govs:
        logging.info(f"Available CPU governors: {', '.join(available_govs)}")
        for mode, profile in profiles.items():
            if profile["cpu_governor"] not in available_govs:
                logging.warning(f"Governor '{profile['cpu_governor']}' for {mode} mode not available")
    else:
        logging.error("Could not read available governors")

    return len(missing_tools) == 0

def find_input_device():
    logging.info("Searching for input device...")
    
    try:
        device = InputDevice('/dev/input/event4')
        if ecodes.EV_KEY in device.capabilities():
            key_codes = device.capabilities()[ecodes.EV_KEY]
            if 425 in key_codes:
                logging.info(f"Found target device: {device.path} with key code 425 support")
                return device
            else:
                logging.info(f"Device {device.path} found but doesn't support key code 425")
        else:
            logging.info(f"Device {device.path} found but doesn't support key events")
    except (FileNotFoundError, PermissionError) as e:
        logging.warning(f"Default device /dev/input/event4 not accessible: {e}")

    logging.info("Searching all input devices for key code 425 support...")
    
    for device_path in sorted(glob.glob('/dev/input/event*')):
        try:
            device = InputDevice(device_path)
            
            if ecodes.EV_KEY in device.capabilities():
                key_codes = device.capabilities()[ecodes.EV_KEY]
                if 425 in key_codes:
                    logging.info(f"Found device with key code 425: {device_path} - {device.name}")
                    return device
        except (FileNotFoundError, PermissionError) as e:
            logging.warning(f"Cannot access {device_path}: {e}")
            continue
    logging.warning("No device found with key code 425, looking for any keyboard device...")
    
    for device_path in sorted(glob.glob('/dev/input/event*')):
        try:
            device = InputDevice(device_path)
            if ecodes.EV_KEY in device.capabilities():
                key_codes = device.capabilities()[ecodes.EV_KEY]
                if any(code in key_codes for code in [ecodes.KEY_A, ecodes.KEY_SPACE, ecodes.KEY_ENTER]):
                    logging.info(f"Found keyboard device as fallback: {device_path} - {device.name}")
                    return device
        except (FileNotFoundError, PermissionError):
            continue

    logging.error("No suitable input device found")
    return None

setup_logging()
cleanup_old_logs()
check_dependencies()
log_system_info()

Gtk.init(None)

def gtk_main_loop():
    Gtk.main()

gtk_thread = threading.Thread(target=gtk_main_loop, daemon=True)
gtk_thread.start()
logging.info("GTK main loop started")

device = find_input_device()
if device is None:
    logging.critical("Could not find suitable input device")
    print("Error: Could not find suitable input device")
    print("Make sure you have proper permissions to access input devices.")
    sys.exit(1)

modes = ["powersave", "balanced", "performance"]
saved_mode = load_saved_mode()
current = modes.index(saved_mode) if saved_mode in modes else 1
current_popup = None
current_mode = None
monitoring_thread = None
thermal_thread = None
should_monitor = False

logging.info(f"Input device: {device.path}")
logging.info(f"Available modes: {', '.join(modes)}")
logging.info(f"Starting with mode: {modes[current]}")

def apply_cpu_settings(profile):
    logging.info(f"Applying CPU settings: governor={profile['cpu_governor']}, max_freq={profile['cpu_max_freq']}")
    tlp_was_active = False
    available_govs = get_available_governors()
    desired_governor = profile["cpu_governor"]

    if available_govs and desired_governor not in available_govs:
        logging.warning(f"Governor '{desired_governor}' not available, searching for fallback")
        fallback_map = {
            "schedutil": ["ondemand", "powersave", "performance"],
            "powersave": ["powersave", "ondemand", "conservative"],
            "performance": ["performance", "ondemand", "schedutil"]
        }

        fallbacks = fallback_map.get(desired_governor, available_govs)
        for fallback in fallbacks:
            if fallback in available_govs:
                logging.info(f"Using fallback governor: {fallback}")
                desired_governor = fallback
                break
        else:
            if available_govs:
                desired_governor = available_govs[0]
                logging.info(f"Using first available governor: {desired_governor}")

    try:
        try:
            result = subprocess.run(["systemctl", "is-active", "tlp"], capture_output=True, text=True)
            tlp_was_active = result.returncode == 0
            if tlp_was_active:
                logging.info("TLP service is active, will be managed during governor change")
        except FileNotFoundError:
            logging.info("systemctl not found - skipping TLP management")
            tlp_was_active = False

        if tlp_was_active:
            try:
                subprocess.run(["sudo", "systemctl", "stop", "tlp"], capture_output=True)
                subprocess.run(["sudo", "systemctl", "mask", "tlp"], capture_output=True)
                logging.info("TLP service stopped and masked")
                time.sleep(0.5)
            except FileNotFoundError:
                logging.error("systemctl not found - cannot manage TLP service")
                tlp_was_active = False

        power_services = ["power-profiles-daemon", "tuned", "auto-cpufreq"]
        stopped_services = []

        for service in power_services:
            try:
                result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True)
                if result.returncode == 0:
                    try:
                        subprocess.run(["sudo", "systemctl", "stop", service], capture_output=True)
                        stopped_services.append(service)
                        logging.info(f"Temporarily stopped {service}")
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                pass

        for attempt in range(5):
            cpupower_success = False
            try:
                subprocess.run(["sudo", "cpupower", "frequency-set", "-g", desired_governor], check=True, capture_output=True, text=True)
                cpupower_success = True
            except FileNotFoundError as e:
                if "sudo" in str(e):
                    try:
                        subprocess.run(["cpupower", "frequency-set", "-g", desired_governor], check=True, capture_output=True, text=True)
                        cpupower_success = True
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        print("cpupower not available or insufficient permissions")
                else:
                    print(f"cpupower command failed: {e}")
            except subprocess.CalledProcessError as e:
                print(f"cpupower command failed: {e}")

            sysfs_success = True
            cpu_count = os.cpu_count()
            for cpu in range(cpu_count):
                governor_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
                if os.path.exists(governor_path):
                    try:
                        with open(governor_path, "w") as f:
                            f.write(desired_governor)
                    except (PermissionError, OSError) as e:
                        logging.error(f"Failed to write governor for CPU {cpu}: {e}")
                        sysfs_success = False

            if desired_governor == "performance":
                for gov_service in ["ondemand", "conservative"]:
                    try:
                        subprocess.run(["sudo", "systemctl", "stop", f"cpufreq-{gov_service}"], capture_output=True)
                    except FileNotFoundError:
                        pass

            try:
                with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "r") as f:
                    current_gov = f.read().strip()
                    if current_gov == desired_governor:
                        logging.info(f"Successfully set governor to {current_gov}")
                        break
                    else:
                        logging.warning(f"Attempt {attempt + 1}: Governor is {current_gov}, want {desired_governor}")
            except (FileNotFoundError, PermissionError, OSError) as e:
                logging.error(f"Failed to read governor status: {e}")

            time.sleep(0.3)

        freq_success = False
        try:
            subprocess.run(["sudo", "cpupower", "frequency-set", "-u", profile["cpu_max_freq"]], check=True, capture_output=True, text=True)
            freq_success = True
        except FileNotFoundError as e:
            if "sudo" in str(e):
                try:
                    subprocess.run(["cpupower", "frequency-set", "-u", profile["cpu_max_freq"]], check=True, capture_output=True, text=True)
                    freq_success = True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    logging.warning("cpupower frequency setting not available")
            else:
                logging.error(f"cpupower frequency setting failed: {e}")
        except subprocess.CalledProcessError as e:
            logging.error(f"cpupower frequency setting failed: {e}")

        cpu_count = os.cpu_count()
        for cpu in range(cpu_count):
            max_freq_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_max_freq"
            if os.path.exists(max_freq_path):
                try:
                    with open(max_freq_path, "w") as f:
                        f.write(profile["cpu_max_freq"])
                except (PermissionError, OSError) as e:
                    logging.error(f"Failed to set max frequency for CPU {cpu}: {e}")

        if tlp_was_active and profile["cpu_governor"] == "schedutil":
            time.sleep(2)
            try:
                subprocess.run(["sudo", "systemctl", "unmask", "tlp"], capture_output=True)
                subprocess.run(["sudo", "systemctl", "start", "tlp"], capture_output=True)
            except FileNotFoundError:
                print("systemctl not found - cannot restore TLP service")
        elif tlp_was_active:
            try:
                subprocess.run(["sudo", "systemctl", "unmask", "tlp"], capture_output=True)
                logging.info("TLP unmasked but not restarted to prevent conflicts")
            except FileNotFoundError:
                pass

        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "r") as f:
                current_gov = f.read().strip()
                logging.info(f"Final governor: {current_gov} (wanted: {desired_governor})")
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.error(f"Failed to verify governor setting: {e}")

    except Exception as e:
        logging.error(f"Error in apply_cpu_settings: {e}")

        if tlp_was_active:
            try:
                subprocess.run(["sudo", "systemctl", "unmask", "tlp"], capture_output=True)
                subprocess.run(["sudo", "systemctl", "start", "tlp"], capture_output=True)
            except (Exception, FileNotFoundError):
                pass

        try:
            cpu_count = os.cpu_count()
            for cpu in range(cpu_count):
                governor_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
                if os.path.exists(governor_path):
                    try:
                        with open(governor_path, "w") as f:
                            f.write(desired_governor)
                    except (PermissionError, OSError):
                        pass
        except Exception:
            pass

def apply_gpu_settings(profile):
    try:
        power_level = profile["gpu_power"]
        amd_path = "/sys/class/drm/card0/device/power_dpm_force_performance_level"
        if os.path.exists(amd_path):
            try:
                with open(amd_path, "w") as f:
                    if power_level == "low":
                        f.write("low")
                    elif power_level == "high":
                        f.write("high")
                    else:
                        f.write("auto")
            except PermissionError:
                pass

        for card in range(4):
            alt_path = f"/sys/class/drm/card{card}/device/power_dpm_force_performance_level"
            if os.path.exists(alt_path):
                try:
                    with open(alt_path, "w") as f:
                        if power_level == "low":
                            f.write("low")
                        elif power_level == "high":
                            f.write("high")
                        else:
                            f.write("auto")
                except PermissionError:
                    pass
    except Exception:
        pass

def monitor_governor():
    global should_monitor, current_mode
    while should_monitor and current_mode:
        try:
            time.sleep(3)
            if not should_monitor or not current_mode:
                break

            profile = profiles.get(current_mode)
            if not profile:
                continue

            available_govs = get_available_governors()
            desired_governor = profile["cpu_governor"]

            if available_govs and desired_governor not in available_govs:
                fallback_map = {
                    "schedutil": ["ondemand", "powersave", "performance"],
                    "powersave": ["powersave", "ondemand", "conservative"],
                    "performance": ["performance", "ondemand", "schedutil"]
                }

                fallbacks = fallback_map.get(desired_governor, available_govs)
                for fallback in fallbacks:
                    if fallback in available_govs:
                        desired_governor = fallback
                        break
                else:
                    if available_govs:
                        desired_governor = available_govs[0]

            try:
                with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "r") as f:
                    current_gov = f.read().strip()

                if current_gov != desired_governor:
                    logging.info(f"Governor changed to {current_gov}, restoring {desired_governor}")

                    cpu_count = os.cpu_count()
                    for cpu in range(cpu_count):
                        governor_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
                        if os.path.exists(governor_path):
                            try:
                                with open(governor_path, "w") as f:
                                    f.write(desired_governor)
                            except (PermissionError, OSError):
                                pass

                    for cpu in range(cpu_count):
                        max_freq_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_max_freq"
                        if os.path.exists(max_freq_path):
                            try:
                                with open(max_freq_path, "w") as f:
                                    f.write(profile["cpu_max_freq"])
                            except (PermissionError, OSError):
                                pass

            except (FileNotFoundError, PermissionError, OSError):
                pass

        except Exception as e:
            logging.error(f"Error in monitoring: {e}")

    logging.info("Governor monitoring stopped")

def apply_mode(mode):
    global current_mode, should_monitor, monitoring_thread, thermal_thread
    logging.info(f"Applying mode: {mode}")
    if mode in profiles:
        current_mode = mode
        profile = profiles[mode]
        apply_cpu_settings(profile)
        apply_gpu_settings(profile)
        save_current_mode(mode)
        send_notification("Performance Mode", f"{mode.upper()} profili uygulandı")

        should_monitor = True
        if monitoring_thread and monitoring_thread.is_alive():
            should_monitor = False
            monitoring_thread.join(timeout=1)

        if thermal_thread and thermal_thread.is_alive():
            thermal_thread.join(timeout=1)

        if mode in ["performance", "powersave"]:
            should_monitor = True
            monitoring_thread = threading.Thread(target=monitor_governor, daemon=True)
            monitoring_thread.start()
            logging.info(f"Started governor monitoring for {mode} mode")

        should_monitor = True
        thermal_thread = threading.Thread(target=monitor_thermal, daemon=True)
        thermal_thread.start()
        logging.info(f"Mode {mode} applied successfully")
    else:
        logging.error(f"Unknown mode: {mode}")

def show_popup(mode):
    global current_popup

    if current_popup:
        try:
            current_popup.destroy()
            current_popup = None
        except:
            pass

    def create_popup():
        global current_popup
        try:
            window = Gtk.Window()
            current_popup = window
            window.set_decorated(False)
            window.set_keep_above(True)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
            window.set_default_size(220, 100)
            window.set_resizable(False)
            window.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
            css_provider = Gtk.CssProvider()
            color_map = {
                'powersave': '#48bb78',
                'balanced': '#ed8936',
                'performance': '#f56565'
            }
            text_color = color_map.get(mode, '#ffffff')

            css = f"""
            window {{
                background-color: #23272e;
                border: 2px solid #4a5568;
                border-radius: 12px;
            }}
            .mode-label {{
                color: {text_color};
                font-size: 18px;
                font-weight: bold;
                font-family: "Segoe UI", sans-serif;
            }}
            .status-label {{
                color: #a0aec0;
                font-size: 12px;
                font-family: "Segoe UI", sans-serif;
            }}
            .separator {{
                background-color: #4a5568;
                min-height: 2px;
            }}
            """

            css_provider.load_from_data(css.encode())
            screen = Gdk.Screen.get_default()
            style_context = window.get_style_context()
            style_context.add_provider_for_screen(
                screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            vbox.set_margin_top(20)
            vbox.set_margin_bottom(20)
            vbox.set_margin_start(20)
            vbox.set_margin_end(20)

            mode_label = Gtk.Label(label=mode.upper())
            mode_label.set_halign(Gtk.Align.CENTER)
            mode_context = mode_label.get_style_context()
            mode_context.add_class('mode-label')
            vbox.pack_start(mode_label, False, False, 0)

            status_label = Gtk.Label(label="Profil uygulandı")
            status_label.set_halign(Gtk.Align.CENTER)
            status_context = status_label.get_style_context()
            status_context.add_class('status-label')
            vbox.pack_start(status_label, False, False, 0)

            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep_context = separator.get_style_context()
            sep_context.add_class('separator')
            vbox.pack_start(separator, False, False, 4)

            window.add(vbox)
            window.show_all()

            def close_popup():
                global current_popup
                try:
                    if current_popup:
                        current_popup.destroy()
                        current_popup = None
                except:
                    pass
                return False

            GLib.timeout_add(1500, close_popup)
            logging.info(f"GTK popup created for mode: {mode}")

        except Exception as e:
            logging.error(f"Error creating GTK popup: {e}")
            print(f"Mode changed to: {mode.upper()}")

    GLib.idle_add(create_popup)

print("Performance Mode Switcher active...")
print(f"Using device: {device.path}")
print("Press the special key to cycle between modes")
print("Modes: powersave → balanced → performance")

saved_mode = modes[current]
print(f"Restored last mode: {saved_mode}")
logging.info(f"Restoring last mode: {saved_mode}")
apply_mode(saved_mode)

try:
    logging.info("Entering main event loop")

    if ecodes.EV_KEY in device.capabilities():
        key_codes = device.capabilities()[ecodes.EV_KEY]
        if 425 in key_codes:
            logging.info("Key code 425 is supported by this device")
        else:
            logging.info("Key code 425 is NOT supported by this device")

    for event in device.read_loop():
        if event.type == ecodes.EV_KEY:            
            if event.code == 425:
                if event.value == 0:
                    current = (current + 1) % len(modes)
                    mode = modes[current].strip()
                    logging.info(f"Key pressed - switching to {mode} mode")
                    print(f"Switching to {mode} mode...")
                    threading.Thread(target=apply_mode, args=(mode,), daemon=True).start()
                    show_popup(mode)

except KeyboardInterrupt:
    logging.info("Received keyboard interrupt, shutting down...")
    print("\nExiting mode switcher...")
    should_monitor = False
    if monitoring_thread and monitoring_thread.is_alive():
        monitoring_thread.join(timeout=2)
    if thermal_thread and thermal_thread.is_alive():
        thermal_thread.join(timeout=2)

    if current_popup:
        try:
            current_popup.destroy()
        except:
            pass
    logging.info("Performance Mode Switcher shutdown complete")
    sys.exit(0)
except Exception as e:
    logging.critical(f"Unexpected error: {e}")
    print(f"Unexpected error: {e}")
    traceback.print_exc()
    logging.error(f"Traceback: {traceback.format_exc()}")
    sys.exit(1)

