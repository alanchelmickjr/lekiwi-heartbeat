use axum::{extract::State, routing::get, Json, Router};
use chrono::{DateTime, Utc};
use clap::Parser;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use sysinfo::{System, SystemExt, CpuExt, DiskExt, NetworkExt};
use tokio::sync::RwLock;
use tokio::time;
use tracing::{info, warn, error};
use uuid::Uuid;

const AGENT_VERSION: &str = "1.0.0";
const STATE_FILE: &str = "/var/lib/lekiwi-agent/state.json";
const SERVO_COUNT_LEKIWI: usize = 9;
const POLL_INTERVAL_MS: u64 = 5000;
const MAX_MEMORY_MB: usize = 50;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Server endpoint for heartbeat
    #[arg(short, long, default_value = "https://control.lekiwi.local:8443")]
    server: String,
    
    /// Robot ID (auto-generated if not provided)
    #[arg(short, long)]
    robot_id: Option<String>,
    
    /// Enable mTLS
    #[arg(short, long)]
    mtls: bool,
    
    /// Certificate path for mTLS
    #[arg(short, long, default_value = "/etc/lekiwi/certs")]
    cert_path: String,
    
    /// Local API port
    #[arg(short, long, default_value = "8080")]
    port: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
enum RobotType {
    Lekiwi,      // 9 servos
    XLE,         // Dual arms + RealSense
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SystemInfo {
    robot_id: String,
    robot_type: RobotType,
    hostname: String,
    kernel_version: String,
    cpu_model: String,
    cpu_cores: usize,
    total_memory_mb: u64,
    total_disk_gb: u64,
    mac_addresses: Vec<String>,
    pi_version: String,  // Pi 4 or Pi 5
    agent_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DynamicInfo {
    timestamp: DateTime<Utc>,
    uptime_seconds: u64,
    cpu_usage_percent: f32,
    memory_used_mb: u64,
    memory_free_mb: u64,
    disk_used_gb: f64,
    disk_free_gb: f64,
    temperature_celsius: Option<f32>,
    network_rx_bytes: u64,
    network_tx_bytes: u64,
    video_active: bool,
    teleop_active: bool,
    servo_positions: Option<Vec<i32>>,
    realsense_connected: Option<bool>,
    process_count: usize,
    boot_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RobotState {
    system_info: SystemInfo,
    dynamic_info: DynamicInfo,
    first_seen: DateTime<Utc>,
    last_boot: DateTime<Utc>,
    boot_count: u32,
}

#[derive(Clone)]
struct AgentState {
    robot_state: Arc<RwLock<RobotState>>,
    args: Arc<Args>,
}

impl RobotType {
    fn detect() -> Self {
        // Check for RealSense camera (XLE indicator)
        if Path::new("/dev/realsense2").exists() || 
           Path::new("/sys/class/video4linux").exists() {
            if let Ok(entries) = fs::read_dir("/sys/class/video4linux") {
                for entry in entries.flatten() {
                    if let Ok(name) = fs::read_to_string(entry.path().join("name")) {
                        if name.contains("RealSense") {
                            return RobotType::XLE;
                        }
                    }
                }
            }
        }
        
        // Check for servo controller (Lekiwi indicator)
        if Path::new("/dev/i2c-1").exists() {
            // Try to detect PCA9685 servo controller at address 0x40
            if let Ok(output) = std::process::Command::new("i2cdetect")
                .args(&["-y", "1", "0x40", "0x40"])
                .output() {
                if String::from_utf8_lossy(&output.stdout).contains("40") {
                    return RobotType::Lekiwi;
                }
            }
        }
        
        // Check USB devices for XLE arm controllers
        if let Ok(output) = std::process::Command::new("lsusb").output() {
            let usb_output = String::from_utf8_lossy(&output.stdout);
            if usb_output.contains("STMicroelectronics") || 
               usb_output.contains("FTDI") {
                return RobotType::XLE;
            }
        }
        
        RobotType::Unknown
    }
}

fn detect_pi_version() -> String {
    if let Ok(model) = fs::read_to_string("/proc/device-tree/model") {
        if model.contains("Pi 5") {
            return "Raspberry Pi 5".to_string();
        } else if model.contains("Pi 4") {
            return "Raspberry Pi 4".to_string();
        }
    }
    "Unknown Pi".to_string()
}

fn get_boot_id() -> String {
    fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .unwrap_or_else(|_| Uuid::new_v4().to_string())
        .trim()
        .to_string()
}

fn get_temperature() -> Option<f32> {
    fs::read_to_string("/sys/class/thermal/thermal_zone0/temp")
        .ok()
        .and_then(|s| s.trim().parse::<f32>().ok())
        .map(|t| t / 1000.0)
}

fn check_video_active() -> bool {
    // Check if camera service or streaming process is running
    std::process::Command::new("pgrep")
        .args(&["-f", "camera|stream|gstreamer|v4l2"])
        .output()
        .map(|o| !o.stdout.is_empty())
        .unwrap_or(false)
}

fn check_teleop_active() -> bool {
    // Check if ROS2 nodes or teleop processes are running
    std::process::Command::new("pgrep")
        .args(&["-f", "ros2|teleop|joy_node"])
        .output()
        .map(|o| !o.stdout.is_empty())
        .unwrap_or(false)
}

fn get_servo_positions(robot_type: &RobotType) -> Option<Vec<i32>> {
    match robot_type {
        RobotType::Lekiwi => {
            // Read servo positions via I2C
            // This is a placeholder - actual implementation would use rppal or i2c-dev
            Some(vec![0; SERVO_COUNT_LEKIWI])
        }
        _ => None,
    }
}

async fn collect_system_info(robot_id: String) -> SystemInfo {
    let mut sys = System::new_all();
    sys.refresh_all();
    
    let robot_type = RobotType::detect();
    let hostname = sys.host_name().unwrap_or_else(|| "unknown".to_string());
    let kernel_version = sys.kernel_version().unwrap_or_else(|| "unknown".to_string());
    
    let cpu_model = sys.cpus().first()
        .map(|cpu| cpu.brand().to_string())
        .unwrap_or_else(|| "unknown".to_string());
    
    let cpu_cores = sys.cpus().len();
    let total_memory_mb = sys.total_memory() / 1024 / 1024;
    
    let total_disk_gb = sys.disks().iter()
        .map(|disk| disk.total_space() / 1024 / 1024 / 1024)
        .sum();
    
    let mac_addresses: Vec<String> = sys.networks().iter()
        .filter(|(name, _)| !name.starts_with("lo"))
        .map(|(_, data)| {
            format!("{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
                data.mac_address()[0], data.mac_address()[1],
                data.mac_address()[2], data.mac_address()[3],
                data.mac_address()[4], data.mac_address()[5])
        })
        .collect();
    
    SystemInfo {
        robot_id,
        robot_type,
        hostname,
        kernel_version,
        cpu_model,
        cpu_cores,
        total_memory_mb,
        total_disk_gb,
        mac_addresses,
        pi_version: detect_pi_version(),
        agent_version: AGENT_VERSION.to_string(),
    }
}

async fn collect_dynamic_info(robot_type: &RobotType) -> DynamicInfo {
    let mut sys = System::new_all();
    sys.refresh_all();
    
    let cpu_usage_percent = sys.cpus().iter()
        .map(|cpu| cpu.cpu_usage())
        .sum::<f32>() / sys.cpus().len() as f32;
    
    let memory_used_mb = sys.used_memory() / 1024 / 1024;
    let memory_free_mb = sys.available_memory() / 1024 / 1024;
    
    let (disk_used_gb, disk_free_gb) = sys.disks().iter()
        .fold((0.0, 0.0), |(used, free), disk| {
            let used_gb = (disk.total_space() - disk.available_space()) as f64 / 1024.0 / 1024.0 / 1024.0;
            let free_gb = disk.available_space() as f64 / 1024.0 / 1024.0 / 1024.0;
            (used + used_gb, free + free_gb)
        });
    
    let (network_rx_bytes, network_tx_bytes) = sys.networks().iter()
        .filter(|(name, _)| !name.starts_with("lo"))
        .fold((0u64, 0u64), |(rx, tx), (_, data)| {
            (rx + data.total_received(), tx + data.total_transmitted())
        });
    
    DynamicInfo {
        timestamp: Utc::now(),
        uptime_seconds: sys.uptime(),
        cpu_usage_percent,
        memory_used_mb,
        memory_free_mb,
        disk_used_gb,
        disk_free_gb,
        temperature_celsius: get_temperature(),
        network_rx_bytes,
        network_tx_bytes,
        video_active: check_video_active(),
        teleop_active: check_teleop_active(),
        servo_positions: get_servo_positions(robot_type),
        realsense_connected: if matches!(robot_type, RobotType::XLE) {
            Some(Path::new("/dev/realsense2").exists())
        } else {
            None
        },
        process_count: sys.processes().len(),
        boot_id: get_boot_id(),
    }
}

async fn load_or_create_state(robot_id: String) -> RobotState {
    let system_info = collect_system_info(robot_id).await;
    let dynamic_info = collect_dynamic_info(&system_info.robot_type).await;
    
    if let Ok(contents) = fs::read_to_string(STATE_FILE) {
        if let Ok(mut state) = serde_json::from_str::<RobotState>(&contents) {
            // Check if this is a new boot
            if state.dynamic_info.boot_id != dynamic_info.boot_id {
                state.last_boot = Utc::now();
                state.boot_count += 1;
            }
            state.system_info = system_info;
            state.dynamic_info = dynamic_info;
            return state;
        }
    }
    
    // Create new state
    RobotState {
        system_info,
        dynamic_info,
        first_seen: Utc::now(),
        last_boot: Utc::now(),
        boot_count: 1,
    }
}

async fn save_state(state: &RobotState) -> Result<(), Box<dyn std::error::Error>> {
    let dir = Path::new(STATE_FILE).parent().unwrap();
    fs::create_dir_all(dir)?;
    let json = serde_json::to_string_pretty(state)?;
    fs::write(STATE_FILE, json)?;
    Ok(())
}

async fn send_heartbeat(state: &RobotState, server: &str) -> Result<(), Box<dyn std::error::Error>> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()?;
    
    let _response = client
        .post(format!("{}/heartbeat", server))
        .json(state)
        .send()
        .await?;
    
    Ok(())
}

async fn monitoring_loop(agent_state: AgentState) {
    let mut interval = time::interval(Duration::from_millis(POLL_INTERVAL_MS));
    
    loop {
        interval.tick().await;
        
        // Update dynamic info
        let mut state = agent_state.robot_state.write().await;
        let new_dynamic = collect_dynamic_info(&state.system_info.robot_type).await;
        
        // Check for reboot
        if state.dynamic_info.boot_id != new_dynamic.boot_id {
            state.last_boot = Utc::now();
            state.boot_count += 1;
            info!("Detected reboot, updating boot count to {}", state.boot_count);
        }
        
        state.dynamic_info = new_dynamic;
        
        // Save state to disk
        if let Err(e) = save_state(&state).await {
            warn!("Failed to save state: {}", e);
        }
        
        // Send heartbeat to server
        if let Err(e) = send_heartbeat(&state, &agent_state.args.server).await {
            warn!("Failed to send heartbeat: {}", e);
        }
        
        drop(state); // Release write lock
        
        // Check memory usage and adjust if needed
        let current_mem = std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|s| {
                s.lines()
                    .find(|line| line.starts_with("VmRSS:"))
                    .and_then(|line| {
                        line.split_whitespace()
                            .nth(1)
                            .and_then(|s| s.parse::<usize>().ok())
                    })
            })
            .unwrap_or(0) / 1024; // Convert to MB
        
        if current_mem > MAX_MEMORY_MB {
            warn!("Memory usage {}MB exceeds limit {}MB", current_mem, MAX_MEMORY_MB);
        }
    }
}

// API handlers
async fn get_status(State(agent_state): State<AgentState>) -> Json<RobotState> {
    let state = agent_state.robot_state.read().await;
    Json(state.clone())
}

async fn get_health() -> &'static str {
    "OK"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();
    
    let args = Args::parse();
    info!("Starting Lekiwi Agent v{}", AGENT_VERSION);
    
    // Generate or use provided robot ID
    let robot_id = args.robot_id.clone().unwrap_or_else(|| {
        let id = Uuid::new_v4().to_string();
        info!("Generated robot ID: {}", id);
        id
    });
    
    // Load or create initial state
    let initial_state = load_or_create_state(robot_id.clone()).await;
    info!("Robot type detected: {:?}", initial_state.system_info.robot_type);
    info!("Robot ID: {}", initial_state.system_info.robot_id);
    
    // Save initial state
    save_state(&initial_state).await?;
    
    let agent_state = AgentState {
        robot_state: Arc::new(RwLock::new(initial_state)),
        args: Arc::new(args.clone()),
    };
    
    // Start monitoring loop
    let monitor_state = agent_state.clone();
    tokio::spawn(async move {
        monitoring_loop(monitor_state).await;
    });
    
    // Start local API server
    let app = Router::new()
        .route("/status", get(get_status))
        .route("/health", get(get_health))
        .with_state(agent_state);
    
    let addr = format!("0.0.0.0:{}", args.port);
    info!("Starting API server on {}", addr);
    
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;
    
    Ok(())
}