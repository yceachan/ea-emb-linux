#!/usr/bin/env python3
"""Native Tauri/WebKit, real file chooser and shared RPC; never opens a USB device.
Run within dbus-run-session + xvfb-run. The only formal transport is a protocol emulator.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

if os.environ.get("UUF_TEST_ISOLATED") != "1":
    raise RuntimeError("Run only in an isolated dbus-run-session + xvfb-run session")
p = argparse.ArgumentParser(description=__doc__)
for key in (
    "binary",
    "native-driver",
    "archive",
    "bundle",
    "firmware",
    "rootfs",
    "uuu",
    "output",
):
    p.add_argument("--" + key, type=Path, required=True)
a = p.parse_args()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=False)
selected_archive = a.output / "system.tar.gz"
selected_archive.symlink_to(a.archive.resolve())
os.environ.update(
    XDG_CONFIG_HOME=str(a.output / "config"), XDG_DATA_HOME=str(a.output / "data")
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from uuflib import package

bundle = package.load_bundle(a.bundle)
offline = a.output / "uuu-offline-only"
offline.write_text(
    "#!/usr/bin/env python3\nimport os, sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != '-dry':\n"
    "    raise SystemExit('Error: native test only permits real UUU -dry')\n"
    + f"os.execv({str(a.uuu)!r}, [{str(a.uuu)!r}, *sys.argv[1:]])\n"
)
offline.chmod(0o755)

control = a.output / "transport-mode"
control.write_text("normal")
state = a.output / "board-state.json"
sim = a.output / "uuu-emulated"
sim.write_text(
    "#!/usr/bin/env python3\n"
    + f"""
import json, sys, subprocess, time
from pathlib import Path
sys.path[:0] = {[str(ROOT),str(ROOT/'tests')]!r}
from test_host import Board
from uuflib import package
control=Path({str(control)!r})
if control.read_text() == 'delay':
    child=subprocess.Popen(['sleep','300'])
    Path({str(a.output/'child.pid')!r}).write_text(str(child.pid))
    print('emulated transport waiting',flush=True)
    time.sleep(300)
if '-lsusb' in sys.argv:
    print('1:2 MX6ULL SDP: 0x15a2 0x0080'); sys.exit(0)
script=Path(sys.argv[-1]).resolve()
board=Board(package.load_bundle({str(a.bundle)!r}))
state=Path({str(state)!r})
if state.exists():
    saved=json.loads(state.read_text()); board.mbr=bytes.fromhex(saved['mbr']); board.partconf=saved['partconf']; board.export=bytes.fromhex(saved['export'])
if control.read_text() == 'blank': board.mbr=bytes(512)
if control.read_text() == 'fail': board.fail='uuf info'
try:
    text=board.run('emulated',sys.argv[1:],script.parent,Path({str(a.output/'emulator.log')!r}),60,lambda *x:None,script=script,dry='-dry' in sys.argv)
except RuntimeError as e:
    print('Error: '+str(e)); sys.exit(1)
state.write_text(json.dumps({{'mbr':board.mbr.hex(),'partconf':board.partconf,'export':board.export.hex()}}))
print(text,flush=True)
"""
)
sim.chmod(0o755)
log = (a.output / "native-driver.log").open("w")
# Start accessibility services directly: Fedora's isolated dbus activation can be denied.
a11y = subprocess.Popen(
    ["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"], stdout=log, stderr=log
)
for _ in range(30):
    probe = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.a11y.Bus",
            "--object-path",
            "/org/a11y/bus",
            "--method",
            "org.a11y.Bus.GetAddress",
        ],
        capture_output=True,
    )
    if probe.returncode == 0:
        break
    if a11y.poll() is not None:
        raise RuntimeError("Isolated accessibility service failed; see driver log")
    time.sleep(0.1)
else:
    raise RuntimeError("Isolated accessibility bus did not become ready")
registry = subprocess.Popen(["/usr/libexec/at-spi2-registryd"], stdout=log, stderr=log)
env = dict(
    os.environ,
    NO_AT_BRIDGE="0",
    GTK_A11Y="always",
    GDK_BACKEND="x11",
    GTK_USE_PORTAL="0",
    UUF_LOG_ROOT=str(a.output / "jobs"),
)
driver = subprocess.Popen(
    ["tauri-driver", "--native-driver", str(a.native_driver)],
    stdout=log,
    stderr=log,
    env=env,
    cwd=a.output,
)
sid = None


def request(method, path, data=None):
    req = urllib.request.Request(
        "http://127.0.0.1:4444" + path,
        method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=40))["value"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()) from e


def call(method, path, data=None):
    return request(method, "/session/" + sid + path, data)


def js(script, *args):
    return call("POST", "/execute/sync", {"script": script, "args": list(args)})


def wait(fn, label, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timeout: " + label)


def button(text):
    el = js(
        'return Array.from(document.querySelectorAll("button")).find(b=>b.textContent===arguments[0])',
        text,
    )
    assert el, text
    call("POST", "/element/" + el["element-6066-11e4-a52e-4f735466cecf"] + "/click", {})


def fill(label, value):
    el = js(
        'return document.querySelector("[aria-label="+JSON.stringify(arguments[0])+"]")',
        label,
    )
    assert el, label
    key = el["element-6066-11e4-a52e-4f735466cecf"]
    call("POST", "/element/" + key + "/clear", {})
    call("POST", "/element/" + key + "/value", {"text": str(value)})


def status():
    return js('return document.querySelector("[role=status]").textContent')


def finish(expected="完成"):
    wait(lambda: status() == expected, expected)
    assert js('return !document.querySelector("fieldset").disabled')


def capture(name):
    (a.output / (name + ".png")).write_bytes(
        base64.b64decode(call("GET", "/screenshot"))
    )


def find_accessible(node, role, name=None):
    if (
        node.get_role_name() == role
        and (name is None or node.get_name() == name)
        and (
            role == "application"
            or node.get_state_set().contains(Atspi.StateType.SHOWING)
        )
    ):
        return node
    for i in range(node.get_child_count()):
        found = find_accessible(node.get_child_at_index(i), role, name)
        if found:
            return found
    return None


try:
    for _ in range(100):
        try:
            request("GET", "/status")
            break
        except (OSError, RuntimeError):
            time.sleep(0.1)
    created = request(
        "POST",
        "/session",
        {
            "capabilities": {
                "alwaysMatch": {"tauri:options": {"application": str(a.binary)}}
            }
        },
    )
    sid = created["sessionId"]
    wait(
        lambda: js(
            'return !!document.querySelector("fieldset") && !document.querySelector("fieldset").disabled'
        ),
        "event subscription",
    )
    rect = call("GET", "/window/rect")
    assert rect == {"x": 480, "y": 270, "width": 960, "height": 540}, rect
    capture("01-flash")
    js('document.querySelector("[aria-label=选择完整系统归档]").click()')
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    app = wait(
        lambda: find_accessible(desktop, "application", "uuf-gui"), "accessible app"
    )
    dialog = wait(
        lambda: find_accessible(app, "file chooser", "Open File"), "native file chooser"
    )
    # Navigate through the native chooser's current-directory row and activate a real archive.
    label = wait(
        lambda: find_accessible(dialog, "label", a.output.name),
        "current directory bookmark",
    )
    row = label
    while row.get_role_name() != "list item":
        row = row.get_parent()
    import ctypes

    x = ctypes.CDLL("libX11.so.6")
    xt = ctypes.CDLL("libXtst.so.6")
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xt.XTestFakeMotionEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    xt.XTestFakeButtonEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_ulong,
    ]

    def native_click(node, twice=False):
        rect = Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN)
        assert rect.width > 0 and rect.height > 0, (node.get_name(), rect)
        display = x.XOpenDisplay(os.environ["DISPLAY"].encode())
        assert display
        try:
            assert xt.XTestFakeMotionEvent(
                display, -1, rect.x + rect.width // 2, rect.y + rect.height // 2, 0
            )
            for _ in range(2 if twice else 1):
                xt.XTestFakeButtonEvent(display, 1, 1, 0)
                xt.XTestFakeButtonEvent(display, 1, 0, 0)
                x.XFlush(display)
                time.sleep(0.05)
        finally:
            x.XCloseDisplay(display)

    native_click(row)
    cell = wait(
        lambda: find_accessible(dialog, "table cell", "system.tar.gz"),
        "archive file row",
    )
    native_click(cell)
    time.sleep(0.15)
    native_click(find_accessible(dialog, "button", "Open"))
    wait(
        lambda: js('return document.querySelector("[aria-label=完整系统归档]").value')
        == str(selected_archive),
        "native file selection",
    )
    js('document.querySelector("[aria-label=选择完整系统归档]").click()')
    dialog = wait(
        lambda: find_accessible(app, "file chooser", "Open File"), "second chooser"
    )
    find_accessible(dialog, "button", "Cancel").get_action_iface().do_action(0)
    assert js(
        'return document.querySelector("[aria-label=完整系统归档]").value'
    ) == str(selected_archive)
    js('document.querySelector(".connection").open=true')
    fill("UUU 工具（可选）", offline)
    print("native picker selection + cancellation passed", flush=True)
    button("仅主机预检")
    finish("预检通过 · 未访问硬件")
    plan = json.load(open(next((a.output / "jobs").glob("*/plan.json"))))
    (a.output / "native-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2)
    )
    capture("02-dry-plan")
    # Use only the local protocol emulator from here onward.
    fill("UUU 工具（可选）", sim)
    button("审阅并烧录")
    wait(
        lambda: js('return !!document.querySelector("[role=dialog]")'),
        "host confirmation",
    )
    capture("03-host-confirmation")
    button("继续连接设备")
    wait(
        lambda: js('return document.querySelector("#confirm-title")?.textContent')
        == "确认真实设备写入",
        "target confirmation",
    )
    assert js(
        'return Array.from(document.querySelectorAll("button")).find(b=>b.textContent==="确认写入").disabled'
    )
    fill("确认 CID", "89abcdef")
    capture("04-target-confirmation")
    button("确认写入")
    finish()
    # A disconnected transport must never reach target confirmation.
    control.write_text("fail")
    button("审阅并烧录")
    wait(
        lambda: js('return !!document.querySelector("[role=dialog]")'),
        "failure host confirmation",
    )
    button("继续连接设备")
    finish("失败")
    assert not js('return !!document.querySelector("[role=dialog]")')
    # Cancel while UUU has a live child, then verify no descendant survives.
    control.write_text("delay")
    button("仅主机预检")
    wait(lambda: (a.output / "child.pid").exists(), "UUU descendant")
    button("取消任务")
    finish("已取消 · 子进程清理完成")
    pid = int((a.output / "child.pid").read_text())
    proc = Path("/proc") / str(pid)
    assert not proc.exists() or proc.joinpath("stat").read_text().split()[2] == "Z"
    control.write_text("normal")
    button("设备信息")
    fill("固件发布目录", a.firmware)
    button("探测设备")
    wait(
        lambda: js('return !!document.querySelector("[role=dialog]")'),
        "probe confirmation",
    )
    button("继续连接设备")
    finish()
    assert js(
        'return document.body.textContent.includes("0123456789abcdef0123456789abcdef")'
    )
    button("校验并读取镜像信息")
    finish()
    capture("05-device-and-archive")
    control.write_text("blank")
    button("探测设备")
    wait(
        lambda: js('return !!document.querySelector("[role=dialog]")'),
        "blank disk confirmation",
    )
    button("继续连接设备")
    finish()
    assert js('return document.body.textContent.includes("未发现有效 MBR")')
    capture("05b-blank-device")
    control.write_text("normal")
    button("镜像准备")
    fill("kernel 原始文件", bundle["paths"]["kernel"])
    fill("DTB 原始文件", bundle["paths"]["dtb"])
    fill("rootfs 输入", a.rootfs)
    fill("kernel 目标路径", bundle["manifest"]["targets"]["kernel"]["path"])
    fill("DTB 目标路径", bundle["manifest"]["targets"]["dtb"]["path"])
    fill("布局新目录", a.output / "layout")
    button("按载荷生成布局")
    finish()
    button("读取分区表")
    finish()
    # Resize rtfs alone; packing must still create two new filesystems.
    from uuflib import model

    original_mbr = (a.output / "layout/mbr.bin").read_bytes()
    entry = model.parse_mbr(original_mbr)["entries"][1]
    fill("分区 2 sectors", entry["sectors"] + 16384)
    fill("MBR 另存路径", a.output / "edited-mbr.bin")
    button("检查并另存 MBR")
    finish()
    capture("06-layout-editor")
    fill("制像新目录", a.output / "new-bundle")
    fill("归档输出", a.output / "new-system.tar.gz")
    button("重建两个 ext4 并打包")
    finish()
    prepared = package.load_bundle(a.output / "new-bundle")
    assert prepared["mbr"] == (a.output / "edited-mbr.bin").read_bytes()
    assert all(
        prepared["images"][name]["fs"]["uuid"] != bundle["images"][name]["fs"]["uuid"]
        for name in ("kernel", "rtfs")
    )
    fill("解包新目录", a.output / "unpacked")
    button("校验并解包")
    finish()
    assert package.load_bundle(a.output / "unpacked")["sums"] == prepared["sums"]
    result = {
        "hardware_access": False,
        "native_window": rect,
        "native_file_selection": "passed",
        "native_picker_cancel": "passed",
        "native_uuu_dry_run": "passed",
        "two_confirmations_with_emulated_transport": "passed",
        "disconnect_stops_before_write": "passed",
        "cancel_descendant_cleanup": "passed",
        "archive_and_actual_partition_display": "passed",
        "mbr_edit_and_save": "passed",
        "blank_disk_display": "passed",
        "layout_pack_and_unpack_with_real_payloads": "passed",
    }
    (a.output / "collection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))
except Exception:
    if sid:
        try:
            if "app" in locals():
                opened = find_accessible(app, "file chooser", "Open File")
                if opened:
                    find_accessible(
                        opened, "button", "Cancel"
                    ).get_action_iface().do_action(0)
        except Exception:
            pass
        try:
            capture("failure")
            (a.output / "failure.txt").write_text(js("return document.body.innerText"))
        except Exception:
            pass
    raise
finally:
    if sid:
        try:
            call("DELETE", "")
        except Exception:
            pass
    driver.terminate()
    try:
        driver.wait(timeout=5)
    except subprocess.TimeoutExpired:
        driver.kill()
        driver.wait()
    registry.terminate()
    a11y.terminate()
    registry.wait(timeout=5)
    a11y.wait(timeout=5)
    log.close()
