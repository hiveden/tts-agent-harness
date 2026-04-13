---
name: 长任务后台执行 + 主动监控
description: 长任务必须后台跑,主线程负责轮询监控,绝不在已有后台任务时再前台启动同一命令
type: feedback
---

长任务(TTS 流水线、模型转写、批量合成等耗时 > 30s 的命令)必须用 `run_in_background: true` 启动,主线程通过读取 output 文件轮询进度直到完成。

**Why:** 用户明确指示"长任务后台执行,你来监控"。我之前在 ch01 流水线中先后台启动了 `run.sh --from p3`,接着没等它就前台又跑了一次同样的命令,两个进程同时持有 P3 WhisperX server 单例端口,后启动的把先启动的 P3 server kill 掉,导致后台任务所有 chunks 在 P4 阶段 timeout 报 `needs_human`。表面上前台那次成功了,但浪费了一倍 token 和算力,还污染了 chunks.json 状态。

**How to apply:**
- 估计耗时 > 30s 的 Bash 调用一律 `run_in_background: true`,记下 task id
- 启动后通过 Read 读 output 文件 + 必要时 sleep 短轮询,等待 status=completed
- 一个 episode 的 run.sh 同时只能跑一个实例(P3 WhisperX server 是单例),后台任务未结束前不要再启同一命令的第二次执行
- 如果主线程需要并行做别的事,确认那件事不会和后台任务争抢资源(端口、文件、API 配额)
