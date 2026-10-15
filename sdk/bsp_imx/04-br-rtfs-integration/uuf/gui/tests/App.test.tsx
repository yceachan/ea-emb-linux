// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { App } from "../src/App";
const mock = vi.hoisted(() => ({
  receive: null as any,
  start: vi.fn(),
  cancel: vi.fn(),
  confirm: vi.fn(),
  pick: vi.fn(),
}));
vi.mock("../src/api", () => ({
  api: {
    ...mock,
    subscribe: async (fn: any) => {
      mock.receive = fn;
      return () => {};
    },
    closeBlocked: async () => () => {},
  },
}));
const change = (name: string, value: string) =>
  fireEvent.change(screen.getByLabelText(name), { target: { value } });
const click = (name: string) =>
  fireEvent.click(screen.getByRole("button", { name, exact: true }));
const last = () => mock.start.mock.calls.at(-1)!;
const event = (event: string, data: any) =>
  act(() => mock.receive({ id: last()[0], event, data }));
const draft = {
  operation: "update",
  writes: [
    {
      kind: "dtb",
      hw: 0,
      partition: 1,
      target_path: "/actual/name.dtb",
      source_bytes: 12345,
      write_bytes: 12345,
    },
  ],
  actual: null,
  pending_device_checks: ["复核设备"],
  logs: "/logs",
  inputs: {},
  targets: {},
  firmware_target: {},
};
beforeEach(async () => {
  vi.clearAllMocks();
  render(<App />);
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "仅主机预检" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
});
afterEach(cleanup);
describe("GUI operation boundary", () => {
  it("uses native picker and preserves value on dismissal", async () => {
    mock.pick
      .mockResolvedValueOnce("/archive with spaces.tar.gz")
      .mockResolvedValueOnce(null);
    click("选择完整系统归档");
    await waitFor(() =>
      expect(
        (screen.getByLabelText("完整系统归档") as HTMLInputElement).value,
      ).toBe("/archive with spaces.tar.gz"),
    );
    click("选择完整系统归档");
    await waitFor(() => expect(mock.pick).toHaveBeenCalledTimes(2));
    expect(
      (screen.getByLabelText("完整系统归档") as HTMLInputElement).value,
    ).toBe("/archive with spaces.tar.gz");
  });
  it("sends only selected components to the same RPC with dry_run", async () => {
    click("组件更新");
    fireEvent.click(screen.getByLabelText("kernel"));
    change("kernel 更新文件", "/old-kernel");
    fireEvent.click(screen.getByLabelText("kernel"));
    fireEvent.click(screen.getByLabelText("DTB"));
    change("dtb 更新文件", "/source.dtb");
    change("组件目标描述", "/mapping.json");
    click("仅主机预检");
    expect(last()[1]).toMatchObject({
      operation: "update",
      dtb: "/source.dtb",
      targets: "/mapping.json",
      dry_run: true,
    });
    expect(last()[1]).not.toHaveProperty("kernel");
    expect(last()[1]).not.toHaveProperty("uboot");
  });
  it("shows backend target and requires fresh CID confirmation", async () => {
    change("完整系统归档", "/archive");
    click("审阅并烧录");
    event("confirmation", { phase: "host-plan", token: "first", plan: draft });
    expect(screen.getByRole("dialog").textContent).toContain(
      "/actual/name.dtb",
    );
    click("继续连接设备");
    await waitFor(() =>
      expect(mock.confirm).toHaveBeenCalledWith(last()[0], "first"),
    );
    const plan = {
      ...draft,
      actual: { cid: "0123456789abcdef", user: 100000 },
    };
    event("confirmation", { phase: "target-write", token: "second", plan });
    expect(
      (screen.getByRole("button", { name: "确认写入" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    change("确认 CID", "89abcdef");
    click("确认写入");
    await waitFor(() =>
      expect(mock.confirm).toHaveBeenCalledWith(last()[0], "second"),
    );
  });
  it("keeps inputs locked through error and repeated cancel until child completion", async () => {
    change("完整系统归档", "/archive");
    click("仅主机预检");
    event("error", { message: "断连" });
    click("取消任务");
    click("取消任务");
    expect(screen.getByRole("status").textContent).toContain("等待子进程清理");
    expect(
      (screen.getByLabelText("完整系统归档") as HTMLInputElement).matches(
        ":disabled",
      ),
    ).toBe(true);
    event("result", { state: "written-and-verified" }); // result is not process completion
    expect(screen.getByRole("button", { name: "取消任务" })).toBeTruthy();
    event("finished", { code: 130, cancelled: true });
    expect(screen.getByRole("status").textContent).toContain("清理完成");
    expect(
      (screen.getByLabelText("完整系统归档") as HTMLInputElement).matches(
        ":disabled",
      ),
    ).toBe(false);
  });
  it("rejects result without successful exit and ignores stale job events", async () => {
    change("完整系统归档", "/archive");
    click("仅主机预检");
    const oldId = last()[0];
    event("result", { state: "dry-run-passed" });
    event("finished", { code: 1 });
    expect(screen.getByRole("status").textContent).toBe("失败");
    click("仅主机预检");
    act(() =>
      mock.receive({ id: oldId, event: "finished", data: { code: 0 } }),
    );
    expect(screen.getByRole("button", { name: "取消任务" })).toBeTruthy();
  });
  it("loads and edits MBR through RPC and blocks packing unsaved geometry", async () => {
    click("镜像准备");
    change("MBR 文件", "/original.bin");
    change("组件目标描述", "/targets.json");
    click("读取分区表");
    event("result", {
      mbr: "/original.bin",
      signature: "12345678",
      entries: [
        { number: 1, start: 2048, sectors: 65536, type: 131, boot_flag: 128 },
        { number: 2, start: 67584, sectors: 131072, type: 131, boot_flag: 0 },
      ],
    });
    event("finished", { code: 0 });
    change("分区 2 sectors", "262144");
    click("重建两个 ext4 并打包");
    expect(mock.start).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toContain("另存 MBR");
    change("MBR 另存路径", "/edited.bin");
    click("检查并另存 MBR");
    expect(JSON.parse(last()[1].entries)[1].sectors).toBe(262144);
    expect(last()[1].output).toBe("/edited.bin");
  });
});
