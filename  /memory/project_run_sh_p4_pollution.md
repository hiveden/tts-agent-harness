---
name: run.sh --from p3 会跑 P4 并污染状态
description: run.sh 没有跳过 P4 的开关,--from p3 会经过 P4 把 chunks 状态全打成 needs_human;单 chunk 重做要绕开 run.sh
type: project
---

`run.sh` 的步骤序列硬编码为 `p1 → p2 → check2 → p3 → check3 → diff → p4 → p5 → p6 → checkp6 → v2`,**没有 `--no-p4` 之类的开关**。`--from p3` 会经过 P4 校验,P4 失败后会把所有相关 chunks 标成 `needs_human`,污染 chunks.json 状态字段。CLAUDE.md 所谓的"生产流程跳过 P4"实际上只能通过 `--from p5` 实现——必须保证 P5 之前的状态已经手动准备好。

**Why:** 单 chunk 重做时(用户要求重跑某个 shot 的 TTS),如果走 `--from p3` 让 run.sh 接管,会触发 P4 验证 → P4 把状态污染成 needs_human → 后续 P5 因为状态过滤(只接受 `transcribed`/`validated`)直接跳过这些 chunk,生成的产物不完整。我在 ch01 重做 shot03/04 时就是这么踩坑的。

**How to apply:** 单 chunk 重做的正确流程绕开 run.sh 的 P3-P4:
1. `node scripts/p2-synth.js --chunks ... --outdir ... --chunk <id>` 重新合成
2. **直接调** `python3 scripts/p3-transcribe.py --chunks ... --audiodir ... --outdir ... --server-url http://127.0.0.1:5555` 转写 synth_done 状态的 chunks(P3 server 已在跑就复用,否则先启动)
3. 用 node 一次性把所有 chunks 的 status 改回 `transcribed`(P4 留下的 `needs_human` 也要清掉)
4. `bash run.sh ... --from p5` 跑 P5/P6/postcheck/V2

调 P3 时记得先 `unset HTTPS_PROXY` 再调,因为 ClashX 代理会拦 localhost 请求。
