//! Own one RPC child until its pipes close and Python's cleanup completes.
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    path::Path,
    process::{ChildStdin, Command, Stdio},
    sync::{Arc, Mutex},
};

struct Running {
    id: String,
    pid: u32,
    input: ChildStdin,
    token: Option<String>,
    cancelling: bool,
}
#[derive(Clone, Default)]
pub struct Runner(Arc<Mutex<Option<Running>>>);

fn signal(pid: u32) -> Result<(), String> {
    if unsafe { libc::kill(pid as i32, libc::SIGINT) } != 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    Ok(())
}
impl Runner {
    pub fn busy(&self) -> bool {
        self.0.lock().expect("runner lock").is_some()
    }
    pub fn start(
        &self,
        backend: &Path,
        id: String,
        request: Value,
        emit: impl Fn(Value) + Send + Sync + 'static,
    ) -> Result<(), String> {
        let mut lock = self.0.lock().map_err(|e| e.to_string())?;
        if lock.is_some() {
            return Err("已有任务正在运行或清理".into());
        }
        let mut child = Command::new("python3")
            .arg("-u")
            .arg(backend)
            .arg("rpc")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("无法启动 Python 后端：{e}"))?;
        let mut input = child.stdin.take().expect("piped stdin");
        if let Err(e) = writeln!(input, "{request}") {
            let _ = child.kill();
            let _ = child.wait();
            return Err(e.to_string());
        }
        let stdout = child.stdout.take().expect("piped stdout");
        let stderr = child.stderr.take().expect("piped stderr");
        *lock = Some(Running {
            id: id.clone(),
            pid: child.id(),
            input,
            token: None,
            cancelling: false,
        });
        drop(lock);
        let runner = self.clone();
        let emit = Arc::new(emit);
        std::thread::spawn(move || {
            let err_emit = emit.clone();
            let err_id = id.clone();
            let err_thread = std::thread::spawn(move || {
                for line in BufReader::new(stderr).lines() {
                    match line {
                        Ok(text) => {
                            err_emit(json!({"id":err_id,"event":"log","data":{"text":text + "\n"}}))
                        }
                        Err(e) => {
                            err_emit(
                                json!({"id":err_id,"event":"error","data":{"message":e.to_string()}}),
                            );
                            break;
                        }
                    }
                }
            });
            for line in BufReader::new(stdout).lines() {
                let parsed = line
                    .map_err(|e| e.to_string())
                    .and_then(|s| serde_json::from_str::<Value>(&s).map_err(|e| e.to_string()));
                match parsed {
                    Ok(mut event) if event["event"].is_string() && event["data"].is_object() => {
                        if event["event"] == "confirmation" {
                            let mut lock = runner.0.lock().expect("runner lock");
                            if let Some(running) = lock.as_mut() {
                                if !running.cancelling {
                                    running.token =
                                        event["data"]["token"].as_str().map(str::to_owned);
                                }
                            }
                        }
                        event["id"] = json!(id);
                        emit(event);
                    }
                    other => {
                        emit(
                            json!({"id":id,"event":"error","data":{"message":format!("后端事件协议错误：{other:?}")}}),
                        );
                        let _ = runner.cancel(&id);
                    }
                }
            }
            let status = child.wait();
            err_thread.join().expect("stderr reader");
            let mut lock = runner.0.lock().expect("runner lock");
            let cancelled = lock.take().expect("running child").cancelling;
            drop(lock);
            // Clearing the slot and emitting completion happen after wait, never at cancel request.
            emit(
                json!({"id":id,"event":"finished","data":{"code":status.as_ref().ok().and_then(|s| s.code()),"cancelled":cancelled,
                "wait_error":status.err().map(|e| e.to_string())}}),
            );
        });
        Ok(())
    }
    pub fn confirm(&self, id: &str, token: &str) -> Result<(), String> {
        let mut lock = self.0.lock().map_err(|e| e.to_string())?;
        let running = lock.as_mut().filter(|r| r.id == id).ok_or("任务已结束")?;
        if running.cancelling || running.token.as_deref() != Some(token) {
            return Err("确认已失效".into());
        }
        writeln!(running.input, "{}", json!({"confirm":token})).map_err(|e| e.to_string())?;
        running.token = None;
        Ok(())
    }
    pub fn cancel(&self, id: &str) -> Result<(), String> {
        let mut lock = self.0.lock().map_err(|e| e.to_string())?;
        let running = lock.as_mut().filter(|r| r.id == id).ok_or("任务已结束")?;
        if !running.cancelling {
            signal(running.pid)?;
            running.cancelling = true;
            running.token = None;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::mpsc::{channel, Receiver},
        time::Duration,
    };
    fn next(rx: &Receiver<Value>, kind: &str) -> Value {
        loop {
            let value = rx
                .recv_timeout(Duration::from_secs(40))
                .expect("RPC event timeout");
            if value["event"] == kind {
                return value["data"].clone();
            }
        }
    }
    #[test]
    fn rejects_concurrent_start_and_waits_for_python_descendant_cleanup() {
        let folder = std::env::temp_dir().join(format!("uuf-runner-{}", std::process::id()));
        std::fs::create_dir(&folder).unwrap();
        let script = folder.join("backend.py");
        std::fs::write(
            &script,
            r#"
import json, subprocess, signal, sys, time, os
signal.signal(signal.SIGINT, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()))
sys.stdin.readline()
child = subprocess.Popen(['sleep', '300'], start_new_session=True)
print(json.dumps({'event':'child','data':{'pid':child.pid}}), flush=True)
try:
    print(json.dumps({'event':'confirmation','data':{'token':'fresh'}}), flush=True)
    assert json.loads(sys.stdin.readline()) == {'confirm':'fresh'}
    print(json.dumps({'event':'accepted','data':{}}), flush=True)
    time.sleep(300)
except KeyboardInterrupt:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    os.killpg(child.pid, signal.SIGTERM)
    time.sleep(.2)
    child.wait()
    sys.exit(130)
"#,
        )
        .unwrap();
        let runner = Runner::default();
        let (tx, rx) = channel();
        runner
            .start(&script, "test".into(), json!({}), move |v| {
                tx.send(v).unwrap()
            })
            .unwrap();
        let pid = next(&rx, "child")["pid"].as_i64().unwrap() as i32;
        next(&rx, "confirmation");
        assert!(runner
            .start(&script, "other".into(), json!({}), |_| {})
            .is_err());
        assert!(runner.confirm("test", "stale").is_err());
        runner.confirm("test", "fresh").unwrap();
        assert!(runner.confirm("test", "fresh").is_err());
        next(&rx, "accepted");
        runner.cancel("test").unwrap();
        runner.cancel("test").unwrap();
        assert!(runner.busy());
        assert_eq!(next(&rx, "finished")["code"], 130);
        assert!(!runner.busy());
        assert_eq!(unsafe { libc::kill(pid, 0) }, -1);
        std::fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    #[ignore = "requires UUF_TEST_ARCHIVE and native UUU; no board access"]
    fn real_rpc_dry_run_matches_cli_target_and_ranges() {
        let backend = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../uuf");
        let request = json!({"operation":"deploy","archive":std::env::var("UUF_TEST_ARCHIVE").unwrap(),"dry_run":true,
            "uuu":std::env::var("UUF_TEST_UUU").unwrap_or_else(|_|"uuu".into())});
        let (tx, rx) = channel();
        let runner = Runner::default();
        runner
            .start(&backend, "actual".into(), request.clone(), move |v| {
                tx.send(v).unwrap()
            })
            .unwrap();
        let gui = next(&rx, "plan");
        assert_eq!(next(&rx, "result")["state"], "dry-run-passed");
        assert_eq!(next(&rx, "finished")["code"], 0);
        let mut cli = Command::new("python3")
            .arg(backend)
            .arg("rpc")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        writeln!(cli.stdin.take().unwrap(), "{request}").unwrap();
        let out = cli.wait_with_output().unwrap();
        assert!(out.status.success());
        let plan = String::from_utf8(out.stdout)
            .unwrap()
            .lines()
            .map(|s| serde_json::from_str::<Value>(s).unwrap())
            .find(|v| v["event"] == "plan")
            .unwrap()["data"]
            .clone();
        assert_eq!(gui["writes"], plan["writes"]);
        assert_eq!(gui["targets"], plan["targets"]);
        assert_eq!(gui["firmware_target"], plan["firmware_target"]);
    }
}
