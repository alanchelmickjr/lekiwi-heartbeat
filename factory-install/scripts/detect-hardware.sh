#!/bin/bash
# Hardware Detection Script for Lekiwi/XLE Robots
# Detects robot type, Raspberry Pi version, and peripherals

set -e

# Configuration
OUTPUT_FILE="/etc/lekiwi/hardware.conf"
LOG_FILE="/var/log/lekiwi-hardware-detect.log"
TEMP_DIR="/tmp/hw-detect-$$"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Initialize
mkdir -p $(dirname ${OUTPUT_FILE})
mkdir -p $(dirname ${LOG_FILE})
mkdir -p ${TEMP_DIR}

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a ${LOG_FILE}
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1" | tee -a ${LOG_FILE}
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a ${LOG_FILE}
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a ${LOG_FILE}
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1" >> ${LOG_FILE}
}

# Hardware detection functions
detect_raspberry_pi_version() {
    local pi_version="unknown"
    local pi_revision=""
    local pi_model=""
    
    # Read model from device tree
    if [ -f /proc/device-tree/model ]; then
        pi_model=$(tr -d '\0' < /proc/device-tree/model)
        log_debug "Device tree model: ${pi_model}"
        
        case "${pi_model}" in
            *"Pi 5"*)
                pi_version="5"
                ;;
            *"Pi 4"*)
                pi_version="4"
                ;;
            *"Pi 3"*)
                pi_version="3"
                ;;
            *)
                pi_version="unknown"
                ;;
        esac
    fi
    
    # Read CPU revision
    if [ -f /proc/cpuinfo ]; then
        pi_revision=$(grep "Revision" /proc/cpuinfo | awk '{print $3}')
        log_debug "CPU revision: ${pi_revision}"
        
        # Decode revision (https://www.raspberrypi.org/documentation/hardware/raspberrypi/revision-codes/)
        case "${pi_revision}" in
            a03111|b03111|b03112|b03114|c03111|c03112|c03114|d03114)
                [ "$pi_version" = "unknown" ] && pi_version="4"
                ;;
            c04170|d04170)
                [ "$pi_version" = "unknown" ] && pi_version="5"
                ;;
        esac
    fi
    
    echo "${pi_version}"
}

detect_memory_size() {
    local mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local mem_gb=$((mem_kb / 1024 / 1024))
    
    # Round to nearest GB
    if [ $mem_gb -le 1 ]; then
        echo "1GB"
    elif [ $mem_gb -le 2 ]; then
        echo "2GB"
    elif [ $mem_gb -le 4 ]; then
        echo "4GB"
    elif [ $mem_gb -le 8 ]; then
        echo "8GB"
    else
        echo "${mem_gb}GB"
    fi
}

detect_i2c_devices() {
    local i2c_devices=""
    
    # Check if I2C is available
    if [ ! -e /dev/i2c-1 ]; then
        log_warn "I2C interface not available"
        return 1
    fi
    
    # Scan I2C bus
    if command -v i2cdetect &>/dev/null; then
        log_debug "Scanning I2C bus..."
        i2cdetect -y 1 > ${TEMP_DIR}/i2c_scan.txt 2>&1
        
        # Check for PCA9685 servo controller at 0x40 (Lekiwi)
        if grep -q "40" ${TEMP_DIR}/i2c_scan.txt; then
            i2c_devices="${i2c_devices}PCA9685@0x40,"
            log_info "Found PCA9685 servo controller at 0x40"
        fi
        
        # Check for IMU at 0x68
        if grep -q "68" ${TEMP_DIR}/i2c_scan.txt; then
            i2c_devices="${i2c_devices}IMU@0x68,"
            log_info "Found IMU at 0x68"
        fi
        
        # Check for OLED display at 0x3C
        if grep -q "3c" ${TEMP_DIR}/i2c_scan.txt; then
            i2c_devices="${i2c_devices}OLED@0x3C,"
            log_info "Found OLED display at 0x3C"
        fi
    else
        log_warn "i2cdetect not found, skipping I2C scan"
    fi
    
    echo "${i2c_devices%,}"  # Remove trailing comma
}

detect_usb_devices() {
    local usb_devices=""
    
    if command -v lsusb &>/dev/null; then
        lsusb > ${TEMP_DIR}/usb_devices.txt 2>&1
        
        # Check for Intel RealSense
        if grep -qi "Intel.*RealSense" ${TEMP_DIR}/usb_devices.txt; then
            usb_devices="${usb_devices}RealSense,"
            log_info "Found Intel RealSense camera"
            
            # Get RealSense serial number if possible
            if [ -d /sys/class/video4linux ]; then
                for dev in /sys/class/video4linux/video*; do
                    if [ -f "${dev}/name" ]; then
                        name=$(cat "${dev}/name")
                        if [[ "$name" == *"RealSense"* ]]; then
                            serial=$(cat "${dev}/device/serial" 2>/dev/null || echo "unknown")
                            log_debug "RealSense serial: ${serial}"
                        fi
                    fi
                done
            fi
        fi
        
        # Check for STM32 (XLE arm controller)
        if grep -qi "STMicroelectronics" ${TEMP_DIR}/usb_devices.txt; then
            usb_devices="${usb_devices}STM32,"
            log_info "Found STM32 controller"
        fi
        
        # Check for FTDI (Serial adapter for XLE)
        if grep -qi "FTDI" ${TEMP_DIR}/usb_devices.txt; then
            usb_devices="${usb_devices}FTDI,"
            log_info "Found FTDI serial adapter"
        fi
        
        # Check for Dynamixel (XLE servo controller)
        if grep -qi "Robotis\|Dynamixel" ${TEMP_DIR}/usb_devices.txt; then
            usb_devices="${usb_devices}Dynamixel,"
            log_info "Found Dynamixel servo controller"
        fi
        
        # Check for Arduino
        if grep -qi "Arduino" ${TEMP_DIR}/usb_devices.txt; then
            usb_devices="${usb_devices}Arduino,"
            log_info "Found Arduino"
        fi
    else
        log_warn "lsusb not found, skipping USB scan"
    fi
    
    echo "${usb_devices%,}"  # Remove trailing comma
}

detect_gpio_state() {
    local gpio_available="no"
    
    if [ -e /dev/gpiomem ] || [ -e /sys/class/gpio ]; then
        gpio_available="yes"
        log_info "GPIO interface available"
        
        # Check if any GPIOs are exported
        if [ -d /sys/class/gpio ]; then
            local exported_count=$(ls /sys/class/gpio/ | grep -c "gpio[0-9]" || echo "0")
            log_debug "Exported GPIO count: ${exported_count}"
        fi
    fi
    
    echo "${gpio_available}"
}

detect_camera() {
    local camera_type="none"
    
    # Check for RealSense (already detected in USB)
    if [ -d /sys/class/video4linux ]; then
        for dev in /sys/class/video4linux/video*; do
            if [ -f "${dev}/name" ]; then
                name=$(cat "${dev}/name")
                case "${name}" in
                    *"RealSense"*)
                        camera_type="realsense"
                        ;;
                    *"mmal"*|*"bcm2835"*)
                        camera_type="raspicam"
                        ;;
                esac
            fi
        done
    fi
    
    # Check for Raspberry Pi Camera via vcgencmd
    if command -v vcgencmd &>/dev/null; then
        if vcgencmd get_camera 2>/dev/null | grep -q "detected=1"; then
            camera_type="raspicam"
            log_info "Found Raspberry Pi Camera"
        fi
    fi
    
    echo "${camera_type}"
}

detect_servo_count() {
    local servo_count=0
    
    # For Lekiwi, check PCA9685
    if detect_i2c_devices | grep -q "PCA9685"; then
        servo_count=9  # Lekiwi has 9 servos
        log_info "Detected Lekiwi servo configuration (9 servos)"
    fi
    
    # For XLE, check for Dynamixel
    if detect_usb_devices | grep -q "Dynamixel"; then
        # XLE has dual arms, typically 12-16 servos total
        servo_count=12  # Default for XLE
        log_info "Detected XLE servo configuration"
        
        # Try to get actual count from Dynamixel scan
        if command -v dynamixel_workbench &>/dev/null; then
            # This would require actual Dynamixel tools
            log_debug "Dynamixel workbench available for servo scan"
        fi
    fi
    
    echo "${servo_count}"
}

determine_robot_type() {
    local i2c_devices="$1"
    local usb_devices="$2"
    local camera_type="$3"
    local servo_count="$4"
    
    local robot_type="unknown"
    local confidence=0
    
    # Check for XLE indicators
    if [[ "${usb_devices}" == *"RealSense"* ]]; then
        robot_type="xle"
        confidence=$((confidence + 40))
        log_debug "RealSense detected, likely XLE (confidence: +40)"
    fi
    
    if [[ "${usb_devices}" == *"Dynamixel"* ]] || [[ "${usb_devices}" == *"STM32"* ]]; then
        robot_type="xle"
        confidence=$((confidence + 30))
        log_debug "XLE controller detected (confidence: +30)"
    fi
    
    # Check for Lekiwi indicators
    if [[ "${i2c_devices}" == *"PCA9685"* ]]; then
        if [ "$robot_type" != "xle" ] || [ $confidence -lt 50 ]; then
            robot_type="lekiwi"
            confidence=70
            log_debug "PCA9685 detected, likely Lekiwi (confidence: 70)"
        fi
    fi
    
    if [ $servo_count -eq 9 ]; then
        robot_type="lekiwi"
        confidence=$((confidence + 20))
        log_debug "9 servos detected, likely Lekiwi (confidence: +20)"
    fi
    
    # Final determination
    if [ $confidence -lt 50 ]; then
        robot_type="unknown"
        log_warn "Could not determine robot type with confidence (score: ${confidence})"
    else
        log_info "Robot type determined: ${robot_type} (confidence: ${confidence})"
    fi
    
    echo "${robot_type}"
}

# Network detection
detect_network_interfaces() {
    local interfaces=""
    
    # Ethernet
    if ip link show eth0 &>/dev/null; then
        interfaces="${interfaces}eth0,"
        local eth0_mac=$(ip link show eth0 | awk '/ether/ {print $2}')
        log_debug "eth0 MAC: ${eth0_mac}"
    fi
    
    # WiFi
    if ip link show wlan0 &>/dev/null; then
        interfaces="${interfaces}wlan0,"
        local wlan0_mac=$(ip link show wlan0 | awk '/ether/ {print $2}')
        log_debug "wlan0 MAC: ${wlan0_mac}"
    fi
    
    echo "${interfaces%,}"
}

# Main detection flow
main() {
    log_info "Starting hardware detection..."
    log_info "System: $(uname -a)"
    
    # Detect Raspberry Pi version
    PI_VERSION=$(detect_raspberry_pi_version)
    log_info "Raspberry Pi version: ${PI_VERSION}"
    
    # Detect memory
    MEMORY_SIZE=$(detect_memory_size)
    log_info "Memory size: ${MEMORY_SIZE}"
    
    # Detect I2C devices
    I2C_DEVICES=$(detect_i2c_devices)
    [ -n "${I2C_DEVICES}" ] && log_info "I2C devices: ${I2C_DEVICES}"
    
    # Detect USB devices
    USB_DEVICES=$(detect_usb_devices)
    [ -n "${USB_DEVICES}" ] && log_info "USB devices: ${USB_DEVICES}"
    
    # Detect GPIO
    GPIO_AVAILABLE=$(detect_gpio_state)
    log_info "GPIO available: ${GPIO_AVAILABLE}"
    
    # Detect camera
    CAMERA_TYPE=$(detect_camera)
    log_info "Camera type: ${CAMERA_TYPE}"
    
    # Detect servo count
    SERVO_COUNT=$(detect_servo_count)
    log_info "Servo count: ${SERVO_COUNT}"
    
    # Detect network interfaces
    NETWORK_INTERFACES=$(detect_network_interfaces)
    log_info "Network interfaces: ${NETWORK_INTERFACES}"
    
    # Determine robot type
    ROBOT_TYPE=$(determine_robot_type "${I2C_DEVICES}" "${USB_DEVICES}" "${CAMERA_TYPE}" "${SERVO_COUNT}")
    log_info "ROBOT TYPE DETECTED: ${ROBOT_TYPE}"
    
    # Generate configuration file
    log_info "Writing configuration to ${OUTPUT_FILE}"
    cat > ${OUTPUT_FILE} <<EOF
# Hardware Configuration
# Generated: $(date -Iseconds)
# Detection script version: 1.0.0

# System Information
ROBOT_TYPE="${ROBOT_TYPE}"
RASPBERRY_PI_VERSION="${PI_VERSION}"
MEMORY_SIZE="${MEMORY_SIZE}"
HOSTNAME="$(hostname)"
KERNEL_VERSION="$(uname -r)"

# Hardware Devices
I2C_DEVICES="${I2C_DEVICES}"
USB_DEVICES="${USB_DEVICES}"
GPIO_AVAILABLE="${GPIO_AVAILABLE}"
CAMERA_TYPE="${CAMERA_TYPE}"
SERVO_COUNT="${SERVO_COUNT}"

# Network
NETWORK_INTERFACES="${NETWORK_INTERFACES}"
PRIMARY_MAC="$(ip link show | awk '/ether/ {print $2}' | head -1)"

# Robot-specific configuration
case "${ROBOT_TYPE}" in
    lekiwi)
        # Lekiwi with 9 servos
        SERVO_CONTROLLER="PCA9685"
        SERVO_I2C_ADDRESS="0x40"
        MAX_SERVOS="9"
        ;;
    xle)
        # XLE with dual arms
        SERVO_CONTROLLER="Dynamixel"
        CAMERA_TYPE="realsense"
        ARM_COUNT="2"
        ;;
    *)
        # Unknown configuration
        REQUIRES_MANUAL_CONFIG="yes"
        ;;
esac

# Detection confidence and metadata
DETECTION_TIMESTAMP="$(date -Iseconds)"
DETECTION_METHOD="automatic"
EOF
    
    # Set appropriate permissions
    chmod 644 ${OUTPUT_FILE}
    
    # Create symlink for compatibility
    ln -sf ${OUTPUT_FILE} /etc/robot-hardware.conf 2>/dev/null || true
    
    # Cleanup
    rm -rf ${TEMP_DIR}
    
    # Summary
    echo ""
    echo "====================================="
    echo -e "${GREEN}Hardware Detection Complete!${NC}"
    echo "====================================="
    echo "Robot Type: ${ROBOT_TYPE}"
    echo "Raspberry Pi: Version ${PI_VERSION}"
    echo "Memory: ${MEMORY_SIZE}"
    echo "Configuration: ${OUTPUT_FILE}"
    echo "====================================="
    
    # Exit with appropriate code
    if [ "${ROBOT_TYPE}" = "unknown" ]; then
        log_warn "Robot type could not be determined"
        exit 1
    fi
    
    exit 0
}

# Run main function
main "$@"