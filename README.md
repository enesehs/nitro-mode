# Acer Nitro Performance Mode Switcher

A Linux system performance mode switcher that allows real-time switching between power profiles using a hardware key. The application monitors CPU temperature, manages power governors, and provides visual feedback through GTK popups.

## Features

- **Three Performance Modes**:
  - **Powersave**: Low power consumption with conservative CPU settings
  - **Balanced**: Optimal balance between performance and power efficiency  
  - **Performance**: Maximum performance with high CPU frequencies

- **Hardware Key Control**: Switch modes using a Acer Nitro Key (key code 425)
- **Visual Feedback**: GTK-based popup notifications showing current mode
- **Thermal Monitoring**: Automatic temperature monitoring with warnings
- **Governor Monitoring**: Ensures power settings persist across system changes
- **Automatic Logging**: Daily log files with system information and events
- **Persistent Settings**: Remembers last used mode across reboots

## Performance Profiles

| Mode | CPU Governor | Max Frequency | GPU Power |
|------|-------------|---------------|-----------|
| Powersave | powersave | 1.8 GHz | low |
| Balanced | schedutil | 3.2 GHz | auto |
| Performance | performance | 4.2 GHz | high |

## Prerequisites

### Required System Tools
- `cpupower` - CPU frequency management
- `systemctl` - Service management (optional for TLP integration)
- `notify-send` - Desktop notifications (optional)

### Python Dependencies
```bash
pip install evdev psutil PyGObject
```

### System Packages (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install python3-evdev python3-psutil python3-gi gir1.2-gtk-3.0 linux-tools-generic
```

### System Packages (Fedora/RHEL)
```bash
sudo dnf install python3-evdev python3-psutil python3-gobject gtk3-devel kernel-tools
```

### System Packages (Arch Linux)
```bash
sudo pacman -S python-evdev python-psutil python-gobject gtk3 cpupower
```

## Installation

1. **Clone or download the script**:
   ```bash
   wget https://github.com/enesehs/nitro-mode/mode.py
   chmod +x mode.py
   ```

2. **Set up permissions for input devices**:
   ```bash
   sudo usermod -a -G input $USER
   # Log out and back in for group changes to take effect
   ```

3. **Optional: Create a systemd service for auto-start**:
   ```bash
   sudo tee /etc/systemd/system/performance-mode-switcher.service > /dev/null <<EOF
   [Unit]
   Description=Performance Mode Switcher
   After=graphical-session.target
   
   [Service]
   Type=simple
   User=$USER
   ExecStart=/usr/bin/python3 /path/to/mode.py
   Restart=always
   RestartSec=5
   
   [Install]
   WantedBy=graphical-session.target
   EOF
   
   sudo systemctl enable performance-mode-switcher.service
   sudo systemctl start performance-mode-switcher.service
   ```

## Usage

### Running the Application
```bash
python3 mode.py
```

### Controls
- Press the designated hardware key (typically a function key or special button) to cycle through modes
- The application will display a popup notification showing the current mode
- Modes cycle in order: Powersave → Balanced → Performance → Powersave

### Monitoring
- View real-time logs in the terminal
- Check log files in `~/.config/mode/logs/mode_YYYY-MM-DD.log`
- Monitor CPU temperature warnings (threshold: 88°C)

## Configuration

### Custom Profiles
Edit the `profiles` dictionary in the script to customize settings:

```python
profiles = {
    "powersave": {
        "cpu_governor": "powersave", 
        "cpu_max_freq": "1800000", 
        "gpu_power": "low"
    },
    "balanced": {
        "cpu_governor": "schedutil", 
        "cpu_max_freq": "3200000", 
        "gpu_power": "auto"
    },
    "performance": {
        "cpu_governor": "performance", 
        "cpu_max_freq": "4200000", 
        "gpu_power": "high"
    }
}
```

### Thermal Threshold
Modify the `THERMAL_THRESHOLD` constant to change the temperature warning level:
```python
THERMAL_THRESHOLD = 88  # Temperature in Celsius
```

### Log Retention
Change log file retention period:
```python
cleanup_old_logs(days_to_keep=30)  # Keep logs for 30 days
```

## File Structure

```
~/.config/mode/
├── mode.json           # Stores last used mode
└── logs/
    └── mode_YYYY-MM-DD.log  # Daily log files
```

## Troubleshooting

### Common Issues

1. **"Could not find suitable input device"**
   - Check if you're in the `input` group: `groups $USER`
   - Verify device permissions: `ls -la /dev/input/event*`
   - Try running with `sudo` temporarily to test

2. **"cpupower command failed"**
   - Install cpupower: `sudo apt install linux-tools-generic`
   - Check if governors are available: `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors`

3. **GTK popup not showing**
   - Ensure you're running in a desktop environment
   - Check if PyGObject is installed: `python3 -c "import gi"`
   - Try running from a terminal within the desktop session

4. **Governor settings not persisting**
   - The application includes automatic monitoring to restore settings
   - Check if TLP or other power management services are conflicting
   - Review logs for conflict warnings

### Debug Mode
Run with verbose logging to diagnose issues:
```bash
python3 mode.py 2>&1 | tee debug.log
```

### Manual Testing
Test individual components:
```bash
# Check available governors
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors

# Test input device detection
python3 -c "from evdev import InputDevice; import glob; [print(f'{path}: {InputDevice(path).name}') for path in glob.glob('/dev/input/event*')]"

# Test temperature reading
python3 -c "import psutil; print(psutil.sensors_temperatures())"
```

## Compatibility

- **Linux Distributions**: Ubuntu, Debian, Fedora, Arch Linux, openSUSE
- **CPU Architectures**: x86_64, ARM64 (with compatible governors)
- **Desktop Environments**: GNOME, KDE, XFCE, MATE (any with GTK support)
- **Python Versions**: 3.6+

## Power Management Integration

The application automatically handles conflicts with:
- **TLP**: Temporarily disabled during governor changes, restored for schedutil
- **power-profiles-daemon**: Temporarily stopped during mode switching
- **tuned**: Temporarily stopped during mode switching
- **auto-cpufreq**: Temporarily stopped during mode switching

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test on multiple distributions
4. Submit a pull request

## License

This project is open source. Please check the repository for license details.

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review log files in `~/.config/mode/logs/`
3. Open an issue on the project repository

---

**Note**: This application requires root privileges for CPU frequency management. The script uses `sudo` commands for system-level changes. Ensure your user has appropriate sudo permissions for cpupower and systemctl commands.
