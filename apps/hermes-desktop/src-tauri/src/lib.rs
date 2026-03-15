use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
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
fn reveal_repo_root(state: State<AppState>) -> Result<String, String> {
    let guard = state
        .service
        .lock()
        .map_err(|_| "service lock poisoned".to_string())?;
    Ok(guard.repo_root.display().to_string())
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
            reveal_repo_root
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
