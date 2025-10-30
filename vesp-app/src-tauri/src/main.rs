#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Stdio};
use std::io::{Write, BufRead, BufReader};
use std::sync::{Arc, Mutex};
use std::path::{Path, PathBuf};
use anyhow::Result;
use serde_json::Value;

struct PyBridge {
    _child: std::process::Child,
    stdin: Arc<Mutex<std::process::ChildStdin>>,
    stdout: Arc<Mutex<BufReader<std::process::ChildStdout>>>,
}

impl PyBridge {
    fn start() -> Result<Self> {
        use std::env;

        let cwd = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let mut repo_hints: Vec<PathBuf> = vec![];

        // Highest priority: explicit override
        if let Ok(r) = env::var("VESP_REPO") {
            repo_hints.push(PathBuf::from(r));
        }

        // Autodetect upwards until we find vesp/vesp_srv.py
        let mut p = cwd.as_path();
        for _ in 0..6 {
            if p.join("vesp/vesp_srv.py").exists() {
                repo_hints.push(p.to_path_buf());
                break;
            }
            if let Some(up) = p.parent() { p = up; } else { break; }
        }

        // Common dev layouts (vesp-app/, vesp-app/src-tauri/, repo root)
        repo_hints.push(cwd.join(".."));
        repo_hints.push(cwd.join("../.."));
        repo_hints.push(cwd.clone());

        // Build (python, repo_root) attempts
        let mut attempts: Vec<(PathBuf, PathBuf)> = vec![];
        for repo in repo_hints {
            if repo.join("vesp/vesp_srv.py").exists() {
                attempts.push((repo.join(".venv/bin/python"), repo.clone()));
            }
        }
        // Final fallback: try system python if cwd (or parent) has the module
        attempts.push((PathBuf::from("/usr/bin/python3"), cwd.clone()));

        // DEBUG: print what we will try
        eprintln!("[bridge] cwd = {:?}", cwd);
        for (py, repo) in &attempts {
            eprintln!("[bridge] try python={:?} repo_root={:?}", py, repo);
        }

        let mut last_err: Option<anyhow::Error> = None;
        for (py, repo_root) in attempts {
            if py.to_string_lossy() != "/usr/bin/python3" && !py.exists() {
                continue;
            }
            if !repo_root.join("vesp/vesp_srv.py").exists() {
                continue;
            }

            let mut cmd = Command::new(&py);
            cmd.args(["-m", "vesp.vesp_srv"])
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .current_dir(&repo_root)
                .env("PYTHONPATH", &repo_root);

            match cmd.spawn() {
                Ok(mut child) => {
                    let stdin = Arc::new(Mutex::new(child.stdin.take().unwrap()));
                    let stdout = Arc::new(Mutex::new(BufReader::new(child.stdout.take().unwrap())));
                    eprintln!("[bridge] spawned OK with python={:?} repo_root={:?}", py, repo_root);
                    return Ok(Self { _child: child, stdin, stdout });
                }
                Err(e) => {
                    eprintln!("[bridge] spawn failed for python={:?} repo_root={:?}: {}", py, repo_root, e);
                    last_err = Some(anyhow::anyhow!("spawn failed for {:?} with repo_root {:?}: {}", py, repo_root, e));
                }
            }
        }

        Err(last_err.unwrap_or_else(|| anyhow::anyhow!("no usable Python found")))
    }

    fn call(&self, method: &str, params: Value) -> Result<Value> {
        let req = serde_json::json!({ "method": method, "params": params });
        {
            let mut w = self.stdin.lock().unwrap();
            writeln!(w, "{}", req.to_string())?;
        }
        let mut line = String::new();
        {
            let mut r = self.stdout.lock().unwrap();
            line.clear();
            r.read_line(&mut line)?;
        }
        Ok(serde_json::from_str::<Value>(&line)?)
    }
}

#[tauri::command]
fn doctor() -> Result<String, String> {
    Ok("doctor-ok".into())
}

#[tauri::command]
fn mesh_action(state: tauri::State<'_, AppState>, method: String, params: Value)
    -> Result<Value, String>
{
    state.py.call(&method, params).map_err(|e| e.to_string())
}

struct AppState {
    py: PyBridge,
}

fn main() {
    tauri::Builder::default()
        .manage(AppState {
            py: PyBridge::start().expect("failed to spawn Python bridge"),
        })
        .invoke_handler(tauri::generate_handler![doctor, mesh_action])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

