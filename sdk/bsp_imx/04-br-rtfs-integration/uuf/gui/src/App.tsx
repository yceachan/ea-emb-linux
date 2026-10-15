import { useEffect, useRef, useState } from "react";
import { api, Entry, Event, Plan, Request, Target } from "./api";

type Job = {
  id: string;
  operation: string;
  result?: any;
  error?: string;
  done?: (result: any) => void;
  cancelling?: boolean;
};
type Mbr = { mbr: string; signature: string; entries: Entry[] };
const bytes = (n?: number) =>
  n === undefined
    ? "待设备复核"
    : `${n.toLocaleString()} B · ${(n / 1048576).toFixed(2)} MiB`;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
function Json({ title, value }: { title: string; value: unknown }) {
  return (
    <details>
      <summary>{title}</summary>
      <pre>{pretty(value)}</pre>
    </details>
  );
}
export function Partitions({
  title,
  entries,
  valid = true,
}: {
  title: string;
  entries: Entry[];
  valid?: boolean;
}) {
  return (
    <section>
      <h3>{title}</h3>
      {!valid && <p className="notice">未发现有效 MBR；保留原始分区状态。</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>分区</th>
              <th>起点 / 扇区</th>
              <th>长度 / 扇区</th>
              <th>容量</th>
              <th>类型 / 活动</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((p) => (
              <tr key={p.number}>
                <td>#{p.number}</td>
                <td>{p.start}</td>
                <td>{p.sectors}</td>
                <td>{bytes(p.sectors * 512)}</td>
                <td>
                  {p.type?.toString(16)} / {p.boot_flag === 128 ? "是" : "否"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!entries.length && <p className="muted">没有分区表项。</p>}
    </section>
  );
}
export function PlanView({ plan }: { plan: Plan }) {
  return (
    <section className="plan">
      <h3>操作计划 · {plan.operation}</h3>
      {plan.actual && (
        <p className="identity">
          CID {plan.actual.cid} · user area {bytes(plan.actual.user * 512)}
        </p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>组件 / 区域</th>
              <th>目标</th>
              <th>源文件</th>
              <th>分区容量</th>
              <th>有效写入</th>
            </tr>
          </thead>
          <tbody>
            {plan.writes.map((w, i) => (
              <tr key={i}>
                <td>
                  {w.kind}
                  <small>{w.hw === 1 ? "boot0" : "user area"}</small>
                </td>
                <td>
                  {w.partition ? `#${w.partition} ` : ""}
                  {w.target_path ||
                    (w.start_sector === undefined
                      ? "待设备定位"
                      : `LBA ${w.start_sector}`)}
                  {w.conditional && <small>{w.conditional}</small>}
                </td>
                <td>
                  {w.source_bytes === undefined ? "—" : bytes(w.source_bytes)}
                </td>
                <td>
                  {w.partition_bytes === undefined
                    ? "—"
                    : bytes(w.partition_bytes)}
                </td>
                <td>{bytes(w.write_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!plan.writes.length && <p>只读取设备信息，不写入持久存储。</p>}
      {plan.pending_device_checks.map((p, i) => (
        <p className="notice" key={i}>
          {p}
        </p>
      ))}
      <Json
        title="组件映射、固件范围与输入校验"
        value={{
          targets: plan.targets,
          firmware_target: plan.firmware_target,
          inputs: plan.inputs,
        }}
      />
    </section>
  );
}
export function App() {
  const [page, setPage] = useState("烧录");
  const [mode, setMode] = useState("deploy");
  const [f, setF] = useState<Record<string, string>>({
    kernelPath: "",
    dtbPath: "",
    kernelPart: "1",
    rtfsPart: "2",
    kernelReserve: "32",
    rtfsReserve: "64",
    label: "imx",
    append: "console=ttymxc0,1500000",
    region: "firmware",
    timeout: "3600",
  });
  const [selected, setSelected] = useState<string[]>([]);
  const [withBoot, setWithBoot] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const [error, setError] = useState("");
  const [logs, setLogs] = useState("");
  const [logDir, setLogDir] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [image, setImage] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [mbr, setMbr] = useState<Mbr | null>(null);
  const [mbrDirty, setMbrDirty] = useState(false);
  const [confirmation, setConfirmation] = useState<{
    phase: string;
    token: string;
    plan: Plan;
  } | null>(null);
  const [typedCid, setTypedCid] = useState("");
  const job = useRef<Job | null>(null);
  const logBox = useRef<HTMLPreElement>(null);
  const execution = useRef<HTMLElement>(null);
  const blocked = !ready || busy;
  const put = (key: string, value: string) => {
    setF((old) => ({ ...old, [key]: value }));
    if (key === "mbr" || key === "targets") {
      setMbr(null);
      setMbrDirty(false);
    }
  };
  useEffect(() => {
    let disposed = false;
    const subscriptions = Promise.all([
      api.subscribe(receive),
      api.closeBlocked(setError),
    ]);
    subscriptions
      .then((unlisten) => {
        if (disposed) unlisten.forEach((fn) => fn());
        else setReady(true);
      })
      .catch((e) => setError(String(e)));
    return () => {
      disposed = true;
      subscriptions.then((list) => list.forEach((fn) => fn())).catch(() => {});
    };
  }, []);
  useEffect(() => {
    if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight;
  }, [logs]);
  useEffect(() => {
    if (busy || error) execution.current?.scrollIntoView?.({ block: "start" });
  }, [busy, error]);
  function receive(e: Event) {
    const current = job.current;
    if (!current || e.id !== current.id) return;
    const d = e.data;
    switch (e.event) {
      case "workspace":
        setLogDir(d.path);
        break;
      case "log":
        setLogs((old) => (old + d.text).slice(-200000));
        break;
      case "stage":
        if (!current.cancelling) setStatus(d.name);
        break;
      case "plan":
        setPlan(d);
        break;
      case "target":
        setTarget(d);
        break;
      case "confirmation":
        if (!current.cancelling) {
          setPlan(d.plan);
          setTypedCid("");
          setConfirmation(d);
          setStatus(
            d.phase === "host-plan"
              ? "等待主机计划确认"
              : "等待真实设备写入确认",
          );
        }
        break;
      case "error":
        current.error = d.message;
        setError(d.message);
        break;
      case "result":
        current.result = d;
        break;
      case "finished":
        setConfirmation(null);
        setBusy(false);
        job.current = null;
        if (current.cancelling || d.cancelled) {
          setStatus("已取消 · 子进程清理完成");
        } else if (d.code !== 0 || current.error || !current.result) {
          setStatus("失败");
          setError(
            current.error || d.wait_error || `后端异常退出（${d.code}）`,
          );
        } else {
          setStatus(
            current.result.state === "dry-run-passed"
              ? "预检通过 · 未访问硬件"
              : "完成",
          );
          setResult(current.result);
          current.done?.(current.result);
        }
        break;
    }
  }
  async function run(
    operation: string,
    build: () => Omit<Request, "operation">,
    done?: (r: any) => void,
  ) {
    if (job.current) return;
    setError("");
    try {
      const request = { ...build(), operation } as Request;
      const id = crypto.randomUUID();
      job.current = { id, operation, done };
      setBusy(true);
      setConfirmation(null);
      setPlan(null);
      setResult(null);
      setLogs("");
      setLogDir("");
      setStatus("准备输入");
      try {
        await api.start(id, request);
      } catch (e) {
        job.current = null;
        setBusy(false);
        setStatus("失败");
        throw e;
      }
    } catch (e) {
      setError(String(e));
    }
  }
  const required = (key: string, label: string) => {
    const value = f[key]?.trim();
    if (!value) throw new Error(`请填写${label}`);
    return value;
  };
  const number = (key: string, label: string) => {
    const text = required(key, label);
    const n = Number(text);
    if (!Number.isSafeInteger(n) || n < 0)
      throw new Error(`${label}须为非负整数`);
    return n;
  };
  const optional = (keys: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(keys)
        .filter(([k]) => f[k]?.trim())
        .map(([k, v]) => [v, f[k].trim()]),
    );
  function connection() {
    return {
      ...optional({
        firmware: "firmware",
        firmwareTarget: "firmware_target",
        uuu: "uuu",
        usbPath: "usb_path",
        logDir: "log_dir",
      }),
      timeout: number("timeout", "任务时限"),
    };
  }
  async function cancel() {
    const current = job.current;
    if (!current) return;
    current.cancelling = true;
    setConfirmation(null);
    setStatus("正在取消 · 等待子进程清理");
    try {
      await api.cancel(current.id);
    } catch (e) {
      setError(String(e));
    }
  }
  async function confirm() {
    const c = confirmation,
      current = job.current;
    if (!c || !current) return;
    setConfirmation(null);
    setStatus("执行中");
    try {
      await api.confirm(current.id, c.token);
    } catch (e) {
      setError(String(e));
      await cancel();
    }
  }
  function path(key: string, label: string, kind = "file", hint?: string) {
    async function pick(which: string) {
      try {
        const value = await api.pick(which);
        if (value !== null) put(key, value);
      } catch (e) {
        setError(String(e));
      }
    }
    return (
      <label className="field" key={key}>
        <span>{label}</span>
        <div className="path">
          <input
            aria-label={label}
            value={f[key] || ""}
            placeholder={hint}
            onChange={(e) => put(key, e.target.value)}
          />
          <button
            type="button"
            aria-label={`选择${label}`}
            onClick={() => pick(kind === "rootfs" ? "file" : kind)}
          >
            选择
          </button>
          {kind === "rootfs" && (
            <button
              type="button"
              aria-label="选择 rootfs 目录"
              onClick={() => pick("directory")}
            >
              目录
            </button>
          )}
        </div>
      </label>
    );
  }
  function text(key: string, label: string, hint?: string) {
    return (
      <label className="field" key={key}>
        <span>{label}</span>
        <input
          aria-label={label}
          value={f[key] || ""}
          placeholder={hint}
          onChange={(e) => put(key, e.target.value)}
        />
      </label>
    );
  }
  function flash(dry: boolean) {
    run(mode, () => {
      const base = { ...connection(), dry_run: dry };
      if (mode === "deploy")
        return { ...base, archive: required("archive", "完整系统归档") };
      if (mode === "erase")
        return {
          ...base,
          region: f.region,
          ...optional({
            targets: "targets",
            expectedMbr: "expected_mbr",
            bootLabel: "label",
            actualKernelPart: "kernel_part",
          }),
          ...(f.region === "firmware"
            ? {
                offset: number("eraseOffset", "擦除起始字节"),
                bytes: number("eraseBytes", "擦除长度"),
              }
            : { targets: required("targets", "组件目标描述") }),
        };
      if (!selected.length) throw new Error("至少选择一个更新组件");
      return {
        ...base,
        ...optional({
          targets: "targets",
          expectedMbr: "expected_mbr",
          bootLabel: "label",
          actualKernelPart: "kernel_part",
        }),
        ...Object.fromEntries(
          selected.map((k) => [
            k,
            k === "uboot" ? true : required("update" + k, k),
          ]),
        ),
      };
    });
  }
  function layout() {
    run(
      "layout",
      () => ({
        ...optional({ signature: "signature", diskSectors: "disk_sectors" }),
        kernel: required("kernel", "kernel 原始文件"),
        dtb: required("dtb", "DTB 原始文件"),
        rootfs: required("rootfs", "rootfs 输入"),
        kernel_path: required("kernelPath", "kernel 目标路径"),
        dtb_path: required("dtbPath", "DTB 目标路径"),
        kernel_part: number("kernelPart", "kernel 分区号"),
        rtfs_part: number("rtfsPart", "rtfs 分区号"),
        kernel_reserve: number("kernelReserve", "kernel 预留量") * 1048576,
        rtfs_reserve: number("rtfsReserve", "rtfs 预留量") * 1048576,
        label: required("label", "启动 LABEL"),
        append: f.append,
        output: required("layoutOutput", "布局新目录"),
      }),
      (r) => {
        setF((old) => ({
          ...old,
          mbr: r.mbr,
          targets: r.targets,
          boot: r.boot,
        }));
        setMbr(null);
      },
    );
  }
  function loadMbr() {
    run(
      "mbr",
      () => ({
        input: required("mbr", "MBR 文件"),
        targets: required("targets", "组件目标描述"),
      }),
      (r) => {
        setMbr(r);
        setMbrDirty(false);
      },
    );
  }
  function saveMbr() {
    if (!mbr) return;
    run(
      "mbr",
      () => ({
        input: mbr.mbr,
        targets: required("targets", "组件目标描述"),
        output: required("mbrOutput", "MBR 另存路径"),
        signature: mbr.signature,
        entries: JSON.stringify(
          mbr.entries.map((p) => ({
            number: p.number,
            start: p.start,
            sectors: p.sectors,
          })),
        ),
      }),
      (r) => {
        setMbr(r);
        setMbrDirty(false);
        setF((old) => ({ ...old, mbr: r.mbr }));
      },
    );
  }
  function pack() {
    if (mbrDirty) {
      setError("请先检查并另存 MBR，使制像使用编辑后的布局");
      return;
    }
    run(
      "pack",
      () => ({
        firmware: required("firmware", "固件发布目录"),
        kernel: required("kernel", "kernel 原始文件"),
        dtb: required("dtb", "DTB 原始文件"),
        rootfs: required("rootfs", "rootfs 输入"),
        mbr: required("mbr", "MBR 文件"),
        targets: required("targets", "组件目标描述"),
        boot: required("boot", "启动描述"),
        output: required("packOutput", "制像新目录"),
        archive: required("packArchive", "归档输出"),
        kernel_reserve: number("kernelReserve", "kernel 预留量") * 1048576,
        rtfs_reserve: number("rtfsReserve", "rtfs 预留量") * 1048576,
        ...optional({
          linuxBootDevice: "linux_boot_device",
          firmwareTarget: "firmware_target",
        }),
      }),
      () => setF((old) => ({ ...old, archive: old.packArchive })),
    );
  }
  const actualWrite = confirmation?.phase === "target-write";
  const cid = confirmation?.plan.actual?.cid.slice(-8);
  return (
    <div className="app">
      <header>
        <div className="brand">
          uuf<span>i.MX6ULL Pro</span>
        </div>
        <span className="badge">USB · eMMC</span>
      </header>
      <nav aria-label="功能页面">
        {["烧录", "镜像准备", "设备信息"].map((p) => (
          <button
            key={p}
            aria-current={page === p ? "page" : undefined}
            onClick={() => setPage(p)}
          >
            {p}
          </button>
        ))}
      </nav>
      <main>
        <fieldset disabled={blocked} className="inputs">
          {page === "烧录" && (
            <>
              <div className="section-head">
                <h1>部署到板卡</h1>
                <span>先检查，再确认</span>
              </div>
              <div className="segments">
                {[
                  ["deploy", "完整系统"],
                  ["update", "组件更新"],
                  ["erase", "擦除"],
                ].map(([v, l]) => (
                  <button
                    key={v}
                    aria-pressed={mode === v}
                    onClick={() => setMode(v)}
                  >
                    {l}
                  </button>
                ))}
              </div>
              {mode === "deploy" ? (
                <>
                  {path("archive", "完整系统归档")}
                  <p className="muted">
                    归档包含固件、最终 MBR
                    与两张分区镜像。布局更新须使用重建后的两个 ext4。
                  </p>
                </>
              ) : (
                <>
                  {mode === "update" ? (
                    <>
                      <div className="checks">
                        {[
                          ["uboot", "U-Boot"],
                          ["kernel", "kernel"],
                          ["dtb", "DTB"],
                          ["rtfs", "rtfs Sparse"],
                        ].map(([key, label]) => (
                          <label key={key}>
                            <input
                              type="checkbox"
                              checked={selected.includes(key)}
                              onChange={(e) =>
                                setSelected((s) =>
                                  e.target.checked
                                    ? [...s, key]
                                    : s.filter((k) => k !== key),
                                )
                              }
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                      {selected
                        .filter((k) => k !== "uboot")
                        .map((k) =>
                          path(
                            "update" + k,
                            k === "rtfs" ? "rtfs Sparse 文件" : `${k} 更新文件`,
                          ),
                        )}
                    </>
                  ) : (
                    <>
                      <label className="field">
                        <span>擦除区域</span>
                        <select
                          aria-label="擦除区域"
                          value={f.region}
                          onChange={(e) => put("region", e.target.value)}
                        >
                          <option value="firmware">boot0 明确范围</option>
                          <option value="kernel">完整 kernel 分区</option>
                          <option value="rtfs">完整 rtfs 分区</option>
                        </select>
                      </label>
                      {f.region === "firmware" && (
                        <div className="grid">
                          {text("eraseOffset", "擦除起始字节", "512 字节对齐")}
                          {text("eraseBytes", "擦除长度", "512 字节对齐")}
                        </div>
                      )}
                    </>
                  )}
                  {path("targets", "组件目标描述")}
                  {path("expectedMbr", "预期 MBR 快照（可选）")}
                  <div className="grid">
                    {text(
                      "actualKernelPart",
                      "实际 kernel 分区号（可选）",
                      "多个候选时明确选择 1–4",
                    )}
                    {text("bootLabel", "实际启动 LABEL（可选）")}
                  </div>
                </>
              )}
              <div className="actions">
                <button onClick={() => flash(true)}>仅主机预检</button>
                <button className="primary" onClick={() => flash(false)}>
                  审阅并{mode === "erase" ? "擦除" : "烧录"}
                </button>
              </div>
            </>
          )}
          {page === "镜像准备" && (
            <>
              <div className="section-head">
                <h1>准备系统镜像</h1>
                <span>MBR 决定分区几何</span>
              </div>
              <h2>载荷与默认布局</h2>
              {path("kernel", "kernel 原始文件")}
              {path("dtb", "DTB 原始文件")}
              {path("rootfs", "rootfs 输入", "rootfs", "目录或 tar 归档")}
              <div className="grid">
                {text("kernelPath", "kernel 目标路径", "分区内绝对路径")}
                {text("dtbPath", "DTB 目标路径", "分区内绝对路径")}
                {text("kernelPart", "kernel 分区号")}
                {text("rtfsPart", "rtfs 分区号")}
                {text("kernelReserve", "kernel 预留量 / MiB")}
                {text("rtfsReserve", "rtfs 预留量 / MiB")}
                {text(
                  "signature",
                  "磁盘 signature（可选）",
                  "8 位小写十六进制",
                )}
                {text("diskSectors", "设备容量 / 扇区（可选）")}
              </div>
              <div className="grid">
                {text("label", "启动 LABEL")}
                {text("append", "内核启动参数")}
              </div>
              {path("layoutOutput", "布局新目录", "save")}
              <button onClick={layout}>按载荷生成布局</button>
              <h2>分区表编辑</h2>
              {path("mbr", "MBR 文件")}
              {path("targets", "组件目标描述")}
              <button onClick={loadMbr}>读取分区表</button>
              {mbr && (
                <div className="editor">
                  <label className="field">
                    <span>MBR signature</span>
                    <input
                      aria-label="MBR signature"
                      value={mbr.signature}
                      onChange={(e) => {
                        setMbrDirty(true);
                        setMbr({ ...mbr, signature: e.target.value });
                      }}
                    />
                  </label>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>分区</th>
                          <th>起点 / 扇区</th>
                          <th>长度 / 扇区</th>
                          <th>类型 / 活动</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mbr.entries.map((p, i) => (
                          <tr key={p.number}>
                            <td>#{p.number}</td>
                            {(["start", "sectors"] as const).map((k) => (
                              <td key={k}>
                                <input
                                  type="number"
                                  min="0"
                                  step="8"
                                  aria-label={`分区 ${p.number} ${k}`}
                                  value={Number.isNaN(p[k]) ? "" : p[k]}
                                  onChange={(e) => {
                                    setMbrDirty(true);
                                    setMbr({
                                      ...mbr,
                                      entries: mbr.entries.map((v, n) =>
                                        n === i
                                          ? {
                                              ...v,
                                              [k]:
                                                e.target.value === ""
                                                  ? NaN
                                                  : Number(e.target.value),
                                            }
                                          : v,
                                      ),
                                    });
                                  }}
                                />
                              </td>
                            ))}
                            <td>0x83 / {p.boot_flag === 128 ? "是" : "否"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {path("mbrOutput", "MBR 另存路径", "save")}
                  <button onClick={saveMbr}>检查并另存 MBR</button>
                  <p className="muted">
                    另存成功后用于制像。分区角色由组件描述指定，kernel
                    为活动分区。
                  </p>
                </div>
              )}
              <h2>制像与归档</h2>
              {path("boot", "启动描述")}
              {path("packOutput", "制像新目录", "save")}
              {path("packArchive", "归档输出", "save")}
              {text(
                "linuxBootDevice",
                "Linux /boot 设备（可选）",
                "填写实测设备路径",
              )}
              <button className="primary" onClick={pack}>
                重建两个 ext4 并打包
              </button>
              <h2>解包</h2>
              {path("archive", "完整系统归档")}
              {path("unpackOutput", "解包新目录", "save")}
              <button
                onClick={() =>
                  run("unpack", () => ({
                    archive: required("archive", "完整系统归档"),
                    output: required("unpackOutput", "解包新目录"),
                  }))
                }
              >
                校验并解包
              </button>
            </>
          )}
          {page === "设备信息" && (
            <>
              <div className="section-head">
                <h1>设备与镜像</h1>
                <span>实际状态与目标布局</span>
              </div>
              <p className="muted">
                探测先审阅主机计划，再下载 RAM loader。空盘使用基础探测。
              </p>
              <label className="check">
                <input
                  type="checkbox"
                  checked={withBoot}
                  onChange={(e) => setWithBoot(e.target.checked)}
                />
                同时读取 extlinux 与组件角色
              </label>
              <div className="grid">
                {text("actualKernelPart", "实际 kernel 分区号（可选）")}
                {text("bootLabel", "实际启动 LABEL（可选）")}
              </div>
              <button
                onClick={() =>
                  run("inspect", () => ({
                    ...connection(),
                    with_boot: withBoot,
                    ...optional({
                      actualKernelPart: "kernel_part",
                      bootLabel: "label",
                    }),
                  }))
                }
              >
                探测设备
              </button>
              {path("archive", "完整系统归档")}
              <button
                onClick={() =>
                  run(
                    "describe",
                    () => ({ archive: required("archive", "完整系统归档") }),
                    setImage,
                  )
                }
              >
                校验并读取镜像信息
              </button>
            </>
          )}
          <details className="connection" open={page === "设备信息"}>
            <summary>工具与连接设置</summary>
            {path(
              "firmware",
              "固件发布目录",
              "directory",
              "可使用 UUF_FIRMWARE",
            )}
            {path("firmwareTarget", "固件部署描述（可选）")}
            {path("uuu", "UUU 工具（可选）", "file", "使用 UUF_UUU 或 PATH")}
            <div className="grid">
              {text("usbPath", "ROM USB 路径（可选）", "多设备时必须明确选择")}
              {text("timeout", "任务时限 / 秒")}
            </div>
            {path(
              "logDir",
              "任务日志新目录（可选）",
              "save",
              "默认 ~/uuf-logs/…",
            )}
          </details>
        </fieldset>
        {page === "设备信息" && (
          <>
            {target && (
              <>
                <h2>实际设备</h2>
                <p className="identity">CID {target.cid}</p>
                <p>
                  user area {bytes(target.user * 512)} · boot0{" "}
                  {bytes(target.boot_sectors * 512)} · PARTITION_CONFIG 0x
                  {target.partconf.toString(16)}
                </p>
                <Partitions
                  title="实际分区"
                  entries={target.mbr_entries}
                  valid={target.mbr_valid}
                />
                <Json title="实际设备完整信息" value={target} />
              </>
            )}
            {image && (
              <>
                <p className="muted">归档：{image.archive}</p>
                <Partitions title="归档目标分区" entries={image.mbr.entries} />
                <Json
                  title="组件映射与镜像大小"
                  value={{
                    targets: image.targets,
                    images: image.images,
                    files: image.manifest.files,
                  }}
                />
              </>
            )}
            {mbr && (
              <>
                <p className="muted">
                  编辑器中的布局：{mbr.mbr}。部署以实际选择的归档为准。
                </p>
                <Partitions title="准备中的分区" entries={mbr.entries} />
              </>
            )}
          </>
        )}
        <section className="execution" aria-label="执行区" ref={execution}>
          <div className="execution-head">
            <h2>执行区</h2>
            <span role="status">{status}</span>
            {busy && (
              <button className="danger" onClick={cancel}>
                取消任务
              </button>
            )}
          </div>
          {busy && <progress aria-label="任务进行中" />}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {logDir && <p className="muted">日志：{logDir}</p>}
          {plan && !confirmation && <PlanView plan={plan} />}
          {result && <Json title="操作结果" value={result} />}
          <details open={!!logs}>
            <summary>执行日志 · 界面保留最近 200,000 字符</summary>
            <pre className="logs" ref={logBox}>
              {logs || "等待操作。"}
            </pre>
          </details>
        </section>
      </main>
      {confirmation && (
        <div className="modal-shade">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="modal"
          >
            <h2 id="confirm-title">
              {actualWrite ? "确认真实设备写入" : "确认主机计划"}
            </h2>
            <p>
              {actualWrite
                ? "以下范围将写入持久存储。请核对 CID、分区与组件。"
                : "主机预检已通过。继续后将连接 USB 设备并下载 RAM loader。"}
            </p>
            <PlanView plan={confirmation.plan} />
            {actualWrite && (
              <label className="field">
                <span>输入 CID 后 8 位：{cid}</span>
                <input
                  autoFocus
                  aria-label="确认 CID"
                  value={typedCid}
                  onChange={(e) => setTypedCid(e.target.value)}
                />
              </label>
            )}
            <div className="actions">
              <button onClick={cancel}>取消并清理</button>
              <button
                className="primary"
                disabled={actualWrite && typedCid !== cid}
                onClick={confirm}
              >
                {actualWrite ? "确认写入" : "继续连接设备"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
