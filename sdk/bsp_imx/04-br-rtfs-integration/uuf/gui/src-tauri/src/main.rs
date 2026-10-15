#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod runner;
use runner::Runner;
use serde_json::{json, Value};
use std::path::PathBuf;
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;

fn backend_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = if tauri::is_dev() {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
    } else {
        app.path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("backend")
    };
    let path = root.join("uuf");
    if !path.is_file() {
        return Err(format!("缺少随程序发布的后端：{}", path.display()));
    }
    Ok(path)
}
#[tauri::command]
fn start(
    app: tauri::AppHandle,
    id: String,
    request: Value,
    runner: tauri::State<'_, Runner>,
) -> Result<(), String> {
    let path = backend_path(&app)?;
    runner.start(&path, id.clone(), request, move |event| {
        if app.emit("uuf-event", event).is_err() {
            let _ = app.state::<Runner>().cancel(&id);
        }
    })
}
#[tauri::command]
fn confirm(id: String, token: String, runner: tauri::State<'_, Runner>) -> Result<(), String> {
    runner.confirm(&id, &token)
}
#[tauri::command]
fn cancel(id: String, runner: tauri::State<'_, Runner>) -> Result<(), String> {
    runner.cancel(&id)
}
#[tauri::command]
async fn pick_path(app: tauri::AppHandle, kind: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let dialog = app.dialog().file();
        let path = match kind.as_str() {
            "directory" => dialog.blocking_pick_folder(),
            "save" => dialog.blocking_save_file(),
            "file" => dialog.blocking_pick_file(),
            _ => return Err("未知文件选择方式".into()),
        };
        path.map(|p| {
            p.into_path()
                .map(|p| p.to_string_lossy().into_owned())
                .map_err(|e| e.to_string())
        })
        .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}
fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Runner::default())
        .invoke_handler(tauri::generate_handler![start, confirm, cancel, pick_path])
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
            let monitor = window.current_monitor()?.ok_or("显示器信息不可用")?;
            let size = monitor.size().to_logical::<f64>(monitor.scale_factor());
            window.set_size(tauri::LogicalSize::new(size.width / 2.0, size.height / 2.0))?;
            let origin = monitor.position().to_logical::<f64>(monitor.scale_factor());
            // set_size is asynchronous on GTK; center() could still use the old size.
            window.set_position(tauri::LogicalPosition::new(
                origin.x + size.width / 4.0,
                origin.y + size.height / 4.0,
            ))?;
            window.show()?;
            let handle = app.handle().clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    if handle.state::<Runner>().busy() {
                        api.prevent_close();
                        let _ = handle.emit(
                            "uuf-close-blocked",
                            json!("请先取消任务，等待子进程清理完成后关闭窗口。"),
                        );
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("uuf GUI 启动失败");
}
