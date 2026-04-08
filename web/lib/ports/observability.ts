/**
 * Observability ports — 进度查询 + 日志 tail
 *
 * MVP 实现:
 *   StdoutProgressSource — 解析 .work/<ep>/run.log 末尾找 "=== P3: 12/18 ===" 这种
 *   FileLogTailer        — 读 .work/<ep>/run.log 末尾 N 行
 *
 * 未来扩展:
 *   EventsJsonlProgressSource — 读 .work/<ep>/events.jsonl 结构化事件
 */

import type { EpisodeId } from "../types";

export interface ProgressSource {
  /**
   * 当前 stage 的描述。
   * MVP 阶段是个 opaque 字符串(如 "P3 12/18"),前端只显示不解析。
   */
  getCurrentStage(epId: EpisodeId): Promise<string | null>;

  /** 是否有 job 在跑这个 episode */
  isRunning(epId: EpisodeId): Promise<boolean>;
}

export interface LogTailer {
  /** 读最后 N 行 */
  tail(epId: EpisodeId, lines: number): Promise<string[]>;

  /** 清空(MVP 不用,留扩展) */
  clear(epId: EpisodeId): Promise<void>;
}
