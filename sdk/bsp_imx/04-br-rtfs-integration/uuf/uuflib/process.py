"""External commands own a process group; cancellation waits for cleanup."""
import os
import signal
import subprocess


def stop(process, group=True):
    if not group and process.poll() is not None:
        return
    def send(sig):
        if group:
            os.killpg(process.pid, sig)
        else:
            os.kill(process.pid, sig)
    try:
        send(signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            send(signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def command(argv, *, cwd=None, timeout=120, new_session=True):
    process = subprocess.Popen([str(x) for x in argv], cwd=cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=new_session, env=dict(os.environ, LC_ALL='C'))
    try:
        out, err = process.communicate(timeout=timeout)
        if process.returncode:
            raise ValueError(f'命令失败：{argv}\n{out.decode(errors="replace")}\n{err.decode(errors="replace")}')
        return out.decode(errors='replace')
    finally:
        stop(process, group=new_session)
