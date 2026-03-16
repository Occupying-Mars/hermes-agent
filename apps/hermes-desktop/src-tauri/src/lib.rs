use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::State;

const SERVICE_PORT: u16 = 8765;

struct ServiceManager {
    child: Option<Child>,
    client: Client,
    repo_root: PathBuf,
}

impl ServiceManager {
    fn new() -> Result<Self, String> {
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .map_err(|err| format!("failed to resolve repo root: {err}"))?;
        let client = Client::builder()
            .timeout(Duration::from_secs(180))
            .build()
            .map_err(|err| format!("failed to build http client: {err}"))?;
        Ok(Self {
            child: None,
            client,
            repo_root,
        })
    }

    fn service_url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{SERVICE_PORT}{path}")
    }

    fn python_path(&self) -> Result<PathBuf, String> {
        let unix = self.repo_root.join(".venv/bin/python");
        if unix.exists() {
            return Ok(unix);
        }
        let windows = self.repo_root.join(".venv/Scripts/python.exe");
        if windows.exists() {
            return Ok(windows);
        }
        Err(format!(
            "missing project virtualenv python at {}",
            self.repo_root.join(".venv").display()
        ))
    }

    fn child_running(child: &mut Child) -> bool {
        match child.try_wait() {
            Ok(Some(_)) => false,
            Ok(None) => true,
            Err(_) => false,
        }
    }

    fn ensure_running(&mut self) -> Result<(), String> {
        let mut reuse_existing = false;
        if let Some(child) = self.child.as_mut() {
            reuse_existing = Self::child_running(child);
        }
        if reuse_existing && self.health_ok() {
            return Ok(());
        }

        self.child = None;

        let python = self.python_path()?;
        let mut command = Command::new(python);
        command
            .arg("hermes_desktop_service.py")
            .current_dir(&self.repo_root)
            .env("HERMES_DESKTOP_PORT", SERVICE_PORT.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        let child = command
            .spawn()
            .map_err(|err| format!("failed to start hermes desktop service: {err}"))?;
        self.child = Some(child);

        for _ in 0..40 {
            std::thread::sleep(Duration::from_millis(250));
            if self.health_ok() {
                return Ok(());
            }
        }

        Err("desktop service did not become healthy in time".to_string())
    }

    fn health_ok(&self) -> bool {
        match self.client.get(self.service_url("/api/health")).send() {
            Ok(resp) => resp.status().is_success(),
            Err(_) => false,
        }
    }

    fn get_json(&mut self, path: &str) -> Result<Value, String> {
        self.ensure_running()?;
        self.client
            .get(self.service_url(path))
            .send()
            .and_then(|resp| resp.error_for_status())
            .map_err(|err| format!("request failed: {err}"))?
            .json::<Value>()
            .map_err(|err| format!("invalid service response: {err}"))
    }

    fn post_json<T: Serialize>(&mut self, path: &str, payload: &T) -> Result<Value, String> {
        self.ensure_running()?;
        self.client
            .post(self.service_url(path))
            .json(payload)
            .send()
            .and_then(|resp| resp.error_for_status())
            .map_err(|err| format!("request failed: {err}"))?
            .json::<Value>()
            .map_err(|err| format!("invalid service response: {err}"))
    }

    fn delete_json(&mut self, path: &str) -> Result<Value, String> {
        self.ensure_running()?;
        self.client
            .delete(self.service_url(path))
            .send()
            .and_then(|resp| resp.error_for_status())
            .map_err(|err| format!("request failed: {err}"))?
            .json::<Value>()
            .map_err(|err| format!("invalid service response: {err}"))
    }
}

struct AppState {
    service: Mutex<ServiceManager>,
}

#[derive(Deserialize, Serialize)]
struct CreateSessionPayload {
    title: Option<String>,
    cwd: Option<String>,
    model: Option<String>,
    toolsets: Option<Vec<String>>,
    max_turns: Option<u32>,
}

#[derive(Deserialize, Serialize)]
struct ChatPayload {
    session_id: String,
    message: String,
    cwd: Option<String>,
    model: Option<String>,
    toolsets: Option<Vec<String>>,
    max_turns: Option<u32>,
    context_snapshot: Option<DesktopContextPayload>,
}

#[derive(Deserialize, Serialize)]
struct RenamePayload {
    session_id: String,
    title: String,
}

#[derive(Deserialize, Serialize)]
struct SaveConfigPayload {
    config_text: String,
}

#[derive(Deserialize, Serialize)]
struct SessionSettingsPayload {
    session_id: String,
    model: Option<String>,
    cwd: Option<String>,
    toolsets: Option<Vec<String>>,
    max_turns: Option<u32>,
}

#[derive(Deserialize, Serialize)]
struct ObservationStartPayload {
    goal: String,
}

#[derive(Deserialize, Serialize)]
struct ObservationSettingsPayload {
    guidance: Option<String>,
    target_session_id: Option<String>,
    auto_intervene: Option<bool>,
}

#[derive(Serialize)]
struct EmptyPayload {}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
struct BrowserTabPayload {
    browser: Option<String>,
    title: Option<String>,
    domain: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
struct DesktopContextPayload {
    active_app: Option<String>,
    window_title: Option<String>,
    browser_tab: Option<BrowserTabPayload>,
    draft_text: Option<String>,
    captured_at: Option<u64>,
}

#[derive(Debug, Serialize)]
struct DesktopContextSnapshot {
    platform: String,
    active_app: Option<String>,
    window_title: Option<String>,
    browser_tab: Option<BrowserTabPayload>,
    captured_at: u64,
    error: Option<String>,
}

fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn non_empty(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn escape_applescript(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn extract_domain(url: &str) -> Option<String> {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return None;
    }
    let without_scheme = trimmed
        .split_once("://")
        .map(|(_, rest)| rest)
        .unwrap_or(trimmed);
    let host = without_scheme
        .split('/')
        .next()
        .unwrap_or("")
        .split('@')
        .next_back()
        .unwrap_or("")
        .split(':')
        .next()
        .unwrap_or("");
    non_empty(host)
}

#[cfg(target_os = "macos")]
fn run_osascript(script: &str) -> Result<String, String> {
    let output = Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .map_err(|err| format!("failed to run osascript: {err}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        return Err(if detail.is_empty() {
            "osascript exited with a non-zero status".to_string()
        } else {
            detail.to_string()
        });
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

#[cfg(target_os = "macos")]
fn chrome_tab_script(app_name: &str) -> String {
    let escaped = escape_applescript(app_name);
    format!(
        r#"tell application "{escaped}"
if (count of windows) is 0 then
    return ""
end if
set tabTitle to title of active tab of front window
set tabUrl to URL of active tab of front window
return tabTitle & linefeed & tabUrl
end tell"#
    )
}

#[cfg(target_os = "macos")]
fn safari_tab_script() -> &'static str {
    r#"tell application "Safari"
if (count of windows) is 0 then
    return ""
end if
set currentTab to current tab of front window
set tabTitle to name of currentTab
set tabUrl to URL of currentTab
return tabTitle & linefeed & tabUrl
end tell"#
}

#[cfg(target_os = "macos")]
fn browser_tab_snapshot(app_name: &str) -> Option<BrowserTabPayload> {
    let script = match app_name {
        "Google Chrome" | "Arc" | "Brave Browser" | "Microsoft Edge" | "Opera" | "Vivaldi" => {
            chrome_tab_script(app_name)
        }
        "Safari" => safari_tab_script().to_string(),
        _ => return None,
    };

    let output = run_osascript(&script).ok()?;
    if output.trim().is_empty() {
        return None;
    }

    let mut lines = output.lines();
    let title = lines.next().and_then(non_empty);
    let url = lines.next().and_then(non_empty);
    if title.is_none() && url.is_none() {
        return None;
    }

    Some(BrowserTabPayload {
        browser: Some(app_name.to_string()),
        title,
        domain: url.as_deref().and_then(extract_domain),
    })
}

#[cfg(target_os = "macos")]
fn collect_desktop_context() -> DesktopContextSnapshot {
    let captured_at = now_unix_secs();
    let script = r#"tell application "System Events"
set frontApp to first application process whose frontmost is true
set appName to name of frontApp
set winTitle to ""
try
    if (count of windows of frontApp) > 0 then
        set winTitle to name of front window of frontApp
    end if
end try
return appName & linefeed & winTitle
end tell"#;

    match run_osascript(script) {
        Ok(output) => {
            let mut lines = output.lines();
            let active_app = lines.next().and_then(non_empty);
            let window_title = lines.next().and_then(non_empty);
            let browser_tab = active_app
                .as_deref()
                .and_then(browser_tab_snapshot);
            DesktopContextSnapshot {
                platform: "macos".to_string(),
                active_app,
                window_title,
                browser_tab,
                captured_at,
                error: None,
            }
        }
        Err(error) => DesktopContextSnapshot {
            platform: "macos".to_string(),
            active_app: None,
            window_title: None,
            browser_tab: None,
            captured_at,
            error: Some(error),
        },
    }
}

#[cfg(not(target_os = "macos"))]
fn collect_desktop_context() -> DesktopContextSnapshot {
    DesktopContextSnapshot {
        platform: std::env::consts::OS.to_string(),
        active_app: None,
        window_title: None,
        browser_tab: None,
        captured_at: now_unix_secs(),
        error: Some("desktop context capture is currently implemented for macos only".to_string()),
    }
}

fn with_service<F>(state: &State<AppState>, func: F) -> Result<Value, String>
where
    F: FnOnce(&mut ServiceManager) -> Result<Value, String>,
{
    let mut guard = state
        .service
        .lock()
        .map_err(|_| "service lock poisoned".to_string())?;
    func(&mut guard)
}

#[tauri::command]
fn bootstrap(state: State<AppState>) -> Result<Value, String> {
    with_service(&state, |service| service.get_json("/api/bootstrap"))
}

#[tauri::command]
fn list_sessions(state: State<AppState>) -> Result<Value, String> {
    with_service(&state, |service| service.get_json("/api/sessions"))
}

#[tauri::command]
fn get_session(state: State<AppState>, session_id: String) -> Result<Value, String> {
    let path = format!("/api/sessions/{session_id}");
    with_service(&state, |service| service.get_json(&path))
}

#[tauri::command]
fn create_session(state: State<AppState>, payload: CreateSessionPayload) -> Result<Value, String> {
    with_service(&state, |service| {
        service.post_json("/api/sessions", &payload)
    })
}

#[tauri::command]
fn send_message(state: State<AppState>, payload: ChatPayload) -> Result<Value, String> {
    with_service(&state, |service| service.post_json("/api/chat", &payload))
}

#[tauri::command]
fn rename_session(state: State<AppState>, payload: RenamePayload) -> Result<Value, String> {
    let path = format!("/api/sessions/{}/rename", payload.session_id);
    with_service(&state, |service| service.post_json(&path, &payload))
}

#[tauri::command]
fn delete_session(state: State<AppState>, session_id: String) -> Result<Value, String> {
    let path = format!("/api/sessions/{session_id}");
    with_service(&state, |service| service.delete_json(&path))
}

#[tauri::command]
fn save_config(state: State<AppState>, payload: SaveConfigPayload) -> Result<Value, String> {
    with_service(&state, |service| {
        service.post_json("/api/config/save", &payload)
    })
}

#[tauri::command]
fn update_session_settings(
    state: State<AppState>,
    payload: SessionSettingsPayload,
) -> Result<Value, String> {
    let path = format!("/api/sessions/{}/settings", payload.session_id);
    with_service(&state, |service| service.post_json(&path, &payload))
}

#[tauri::command]
fn get_observation_state(state: State<AppState>) -> Result<Value, String> {
    with_service(&state, |service| service.get_json("/api/observation"))
}

#[tauri::command]
fn start_observation(state: State<AppState>, payload: ObservationStartPayload) -> Result<Value, String> {
    with_service(&state, |service| service.post_json("/api/observation/start", &payload))
}

#[tauri::command]
fn stop_observation(state: State<AppState>) -> Result<Value, String> {
    with_service(&state, |service| service.post_json("/api/observation/stop", &EmptyPayload {}))
}

#[tauri::command]
fn check_observation_now(state: State<AppState>) -> Result<Value, String> {
    with_service(&state, |service| service.post_json("/api/observation/check", &EmptyPayload {}))
}

#[tauri::command]
fn update_observation_settings(
    state: State<AppState>,
    payload: ObservationSettingsPayload,
) -> Result<Value, String> {
    with_service(&state, |service| service.post_json("/api/observation/settings", &payload))
}

#[tauri::command]
fn reveal_repo_root(state: State<AppState>) -> Result<String, String> {
    let guard = state
        .service
        .lock()
        .map_err(|_| "service lock poisoned".to_string())?;
    Ok(guard.repo_root.display().to_string())
}

#[tauri::command]
fn get_desktop_context() -> Result<DesktopContextSnapshot, String> {
    Ok(collect_desktop_context())
}

pub fn run() {
    let app_state = AppState {
        service: Mutex::new(ServiceManager::new().expect("failed to construct service manager")),
    };

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            list_sessions,
            get_session,
            create_session,
            send_message,
            rename_session,
            delete_session,
            save_config,
            update_session_settings,
            get_observation_state,
            start_observation,
            stop_observation,
            check_observation_now,
            update_observation_settings,
            reveal_repo_root,
            get_desktop_context
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
