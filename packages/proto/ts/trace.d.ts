/**
 * 轨迹格式 v1 的 TS 类型——M07 §4 冻结编码（docs/03-模块设计/M07-BlockSDK与测试框架.md §4）。
 * 表达细节裁定 C1-C7：docs/09-MS1B执行计划.md §3。
 * 与 packages/proto/schema/*.json、forge_proto（Python）保持同源；
 * 变更一律走 minor 并触发四方（M02/M06/M08/M09）适配评审。
 */

export declare const CURRENT_MAJOR: "1";

/** "主" 或 "主.次"（主段不同 = 不兼容，Recorder/Replayer 拒绝） */
export type FormatVersion = string;

export type TraceAction = "click" | "input" | "scroll" | "wait" | "nav";

export interface TimeSensitiveStep {
  seq: number;
  tolerance_ms: number | null;
}

export interface Manifest {
  format_version: FormatVersion;
  site: string;
  login_steps?: readonly number[];
  time_sensitive_steps?: readonly TimeSensitiveStep[];
}

export interface Step {
  /** 从 1 连续递增 */
  seq: number;
  action: TraceAction;
  target_selector: string | null;
  dom_anchor: string | null;
  /** M07 §4 `value?`：可缺省（input 步携带） */
  value?: string | null;
  wait_condition: string | null;
  /** 毫秒；非递减 */
  ts_offset: number;
}

export interface NetworkEntry {
  url: string;
  /** 全大写（GET/POST/…） */
  method: string;
  status: number;
  mime_type: string | null;
  /** 值→占位符（占位符格式归 M09 细化） */
  request_body: string | null;
  response_body: string | null;
}

export interface NetworkLog {
  /** ISO8601 */
  captured_at: string;
  entries: readonly NetworkEntry[];
}

export interface RunMeta {
  environment_fingerprint: string;
  /** ISO8601 */
  captured_at: string;
  source_cert_run_id: string | null;
}

/** trace/ 目录四件套的整体视图（快照命名 `${seq}` 6 位零填充 + `.html`，与 steps 一一对应） */
export interface TraceDir {
  manifest: Manifest;
  steps: readonly Step[];
  snapshotFiles: readonly string[];
  network: NetworkLog;
}

/** golden/ 三件套（不随积木包分发，M07 §1 不变量 1） */
export interface GoldenDir {
  runMeta: RunMeta;
  expectedSteps: readonly Step[];
  networkStubs: NetworkLog;
}
