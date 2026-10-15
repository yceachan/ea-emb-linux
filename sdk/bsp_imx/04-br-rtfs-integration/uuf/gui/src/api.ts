import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
export type Request = {
  operation: string;
  [key: string]: string | number | boolean;
};
export type Entry = {
  number: number;
  start: number;
  sectors: number;
  type?: number;
  boot_flag?: number;
};
export type Target = {
  cid: string;
  user: number;
  boot_sectors: number;
  partconf: number;
  mbr_valid: boolean;
  mbr_entries: Entry[];
};
export type Write = {
  kind: string;
  hw: number;
  partition?: number;
  target_path?: string;
  start_sector?: number;
  source_bytes?: number;
  partition_bytes?: number;
  logical_bytes?: number;
  write_bytes: number;
  conditional?: string;
};
export type Plan = {
  operation: string;
  writes: Write[];
  pending_device_checks: string[];
  actual: Target | null;
  logs: string;
  targets: unknown;
  firmware_target: unknown;
  inputs: unknown;
};
export type Event = { id: string; event: string; data: any };
export const api = {
  start: (id: string, request: Request) =>
    invoke<void>("start", { id, request }),
  cancel: (id: string) => invoke<void>("cancel", { id }),
  confirm: (id: string, token: string) =>
    invoke<void>("confirm", { id, token }),
  pick: (kind: string) => invoke<string | null>("pick_path", { kind }),
  subscribe: (fn: (event: Event) => void) =>
    listen<Event>("uuf-event", (e) => fn(e.payload)),
  closeBlocked: (fn: (message: string) => void) =>
    listen<string>("uuf-close-blocked", (e) => fn(e.payload)),
};
