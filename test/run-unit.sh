#!/bin/bash
# 离线单元测试 — 不调任何 API，秒完
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$DIR/.." && pwd)"
PASS=0
FAIL=0

run_test() {
  local name="$1"
  local cmd="$2"
  printf "  %-50s" "$name"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "PASS"
    PASS=$((PASS + 1))
  else
    echo "FAIL"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Unit Tests ==="
echo ""

# ------------------------------------------------
# P1 Tests
# ------------------------------------------------
echo "--- P1: Chunking ---"

WORK=$(mktemp -d)
node "$HARNESS/scripts/p1-chunk.js" --script "$HARNESS/example/demo-script.json" --outdir "$WORK" >/dev/null 2>&1

run_test "P1: produces 4 chunks" \
  "node -e \"const c=require('$WORK/chunks.json'); process.exit(c.length===4?0:1)\""

run_test "P1: all chunks have text + text_normalized" \
  "node -e \"const c=require('$WORK/chunks.json'); process.exit(c.every(x=>x.text&&x.text_normalized)?0:1)\""

run_test "P1: reversibility (concat === original)" \
  "node -e \"
    const fs=require('fs');
    const script=JSON.parse(fs.readFileSync('$HARNESS/example/demo-script.json','utf-8'));
    const chunks=require('$WORK/chunks.json');
    const original=script.segments.map(s=>s.text).join('');
    const rebuilt=chunks.map(c=>c.text).join('');
    process.exit(original===rebuilt?0:1);
  \""



run_test "P1: no chunk exceeds 300 chars" \
  "node -e \"const c=require('$WORK/chunks.json'); process.exit(c.every(x=>x.char_count<=300)?0:1)\""

run_test "P1: date format preserved (no 到 in YYYY-MM-DD)" \
  "node -e \"
    const c=require('$WORK/chunks.json');
    process.exit(c.every(x=>!x.text_normalized.includes('到03到'))?0:1);
  \""

# P1: min-chunk merge respects char limit
# Create a script with a 190-char segment followed by a 1-sentence segment
MERGE_WORK=$(mktemp -d)
cat > "$MERGE_WORK/script.json" << 'EOF'
{"segments":[{"id":1,"text":"这是一段非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的文本，超过一百五十个字的段落。这里还有更多内容来确保这个片段已经接近两百字的上限了。这段话的存在就是为了测试合并保护机制是否正常工作。第三句话。第四句话。第五句话。最后一句。"}]}
EOF
node "$HARNESS/scripts/p1-chunk.js" --script "$MERGE_WORK/script.json" --outdir "$MERGE_WORK" >/dev/null 2>&1

run_test "P1: merged chunk ≤ 300 chars" \
  "node -e \"const c=require('$MERGE_WORK/chunks.json'); process.exit(c.every(x=>x.char_count<=300)?0:1)\""

rm -rf "$WORK" "$MERGE_WORK"

# ------------------------------------------------
# P5 Tests
# ------------------------------------------------
echo ""
echo "--- P5: Subtitles ---"

WORK=$(mktemp -d)
mkdir -p "$WORK/transcripts"

cat > "$WORK/chunks.json" << 'CHUNKS_EOF'
[
  {"id":"shot01_chunk01","shot_id":"shot01","text":"3月7号Karpathy发了630行代码，autoResearch，23天60000 stars。Fortune杂志叫它The Karpathy Loop。","text_normalized":"...","status":"validated","char_count":78,"duration_s":8.5},
  {"id":"shot02_chunk01","shot_id":"shot02","text":"yoyo-evolve，一个Rust写的agent，每8小时自动改一轮自己的源码。它的操作对象是自身代码，评估函数是cargo test加mutation testing。约束系统是一个IDENTITY.md，8条不可变规则。Skill Creator 2.0也一样——操作对象是skill描述文本，四要素齐全，连评估函数都用了验证集六四分割。","text_normalized":"...","status":"validated","char_count":172,"duration_s":20.5}
]
CHUNKS_EOF

cp "$DIR/fixtures/mock-transcript-shot01.json" "$WORK/transcripts/shot01_chunk01.json"
cp "$DIR/fixtures/mock-transcript-shot02.json" "$WORK/transcripts/shot02_chunk01.json"

node "$HARNESS/scripts/p5-subtitles.js" --chunks "$WORK/chunks.json" --transcripts "$WORK/transcripts" --outdir "$WORK" >/dev/null 2>&1

run_test "P5: produces subtitles.json" \
  "test -f '$WORK/subtitles.json'"

run_test "P5: has both shots" \
  "node -e \"const s=require('$WORK/subtitles.json'); process.exit(s.shot01&&s.shot02?0:1)\""

run_test "P5: shot01 has subtitle lines" \
  "node -e \"const s=require('$WORK/subtitles.json'); process.exit(s.shot01.chunks.length>0?0:1)\""

run_test "P5: no NaN or Infinity in timestamps" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      for(const ch of shot.chunks){
        for(const sub of ch.subtitles){
          if(!isFinite(sub.start)||!isFinite(sub.end)) process.exit(1);
        }
      }
    }
    process.exit(0);
  \""

run_test "P5: timestamps are non-negative" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      for(const ch of shot.chunks){
        for(const sub of ch.subtitles){
          if(sub.start<0||sub.end<0) process.exit(1);
        }
      }
    }
    process.exit(0);
  \""

run_test "P5: timestamps are monotonically non-decreasing" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      for(const ch of shot.chunks){
        let prev=-1;
        for(const sub of ch.subtitles){
          if(sub.start<prev-0.001) process.exit(1);
          prev=sub.end;
        }
      }
    }
    process.exit(0);
  \""

run_test "P5: no empty text in subtitles" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      for(const ch of shot.chunks){
        for(const sub of ch.subtitles){
          if(!sub.text||sub.text.trim().length===0) process.exit(1);
        }
      }
    }
    process.exit(0);
  \""

run_test "P5: subtitle lines ≤ 25 chars" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      for(const ch of shot.chunks){
        for(const sub of ch.subtitles){
          if(sub.text.length>25) process.exit(1);
        }
      }
    }
    process.exit(0);
  \""

run_test "P5: no English words split mid-word" \
  "node -e \"
    const s=require('$WORK/subtitles.json');
    for(const shot of Object.values(s)){
      const subs = shot.chunks.flatMap(ch=>ch.subtitles);
      for(let i=1;i<subs.length;i++){
        const prev=subs[i-1].text;
        const cur=subs[i].text;
        // Mid-word split: prev ends letter (no trailing space/punct), cur starts letter
        if(/[a-zA-Z]$/.test(prev) && !/[\s，。、；,]$/.test(prev) && /^[a-zA-Z]/.test(cur)) process.exit(1);
      }
    }
    process.exit(0);
  \""

# P5: word 少于 line 数时不丢字幕
FEW_WORDS=$(mktemp -d)
mkdir -p "$FEW_WORDS/transcripts"
cat > "$FEW_WORDS/chunks.json" << 'EOF'
[{"id":"c1","shot_id":"s1","text":"第一句话。第二句话。第三句话。第四句话。第五句话。","text_normalized":"...","status":"validated","char_count":25,"duration_s":5.0}]
EOF
# Only 3 words for 5 subtitle lines
cat > "$FEW_WORDS/transcripts/c1.json" << 'EOF'
{"chunk_id":"c1","shot_id":"s1","original_text":"...","original_normalized":"...","segments":[{"text":"第一句话第二句话第三句话第四句话第五句话","start":0.0,"end":5.0,"words":[{"word":"第","start":0.0,"end":1.0},{"word":"一","start":1.0,"end":2.5},{"word":"句","start":2.5,"end":5.0}]}],"full_transcribed_text":"第一句话第二句话第三句话第四句话第五句话"}
EOF
node "$HARNESS/scripts/p5-subtitles.js" --chunks "$FEW_WORDS/chunks.json" --transcripts "$FEW_WORDS/transcripts" --outdir "$FEW_WORDS" >/dev/null 2>&1

run_test "P5: few words → still produces subtitles" \
  "node -e \"
    const s=require('$FEW_WORDS/subtitles.json');
    const subs=s.s1.chunks[0].subtitles;
    // splitSubtitleLines merges short sentences → 2 lines; 3 words split across 2 lines
    process.exit(subs.length>=2?0:1);
  \""

run_test "P5: few words → no NaN/Infinity" \
  "node -e \"
    const s=require('$FEW_WORDS/subtitles.json');
    const subs=s.s1.chunks[0].subtitles;
    process.exit(subs.every(x=>isFinite(x.start)&&isFinite(x.end))?0:1);
  \""

rm -rf "$FEW_WORDS"

# P5: fallback branch (0 words)
NO_WORDS=$(mktemp -d)
mkdir -p "$NO_WORDS/transcripts"
cat > "$NO_WORDS/chunks.json" << 'EOF'
[{"id":"c1","shot_id":"s1","text":"测试无词级数据的场景。第二句。","text_normalized":"...","status":"validated","char_count":15,"duration_s":3.0}]
EOF
cat > "$NO_WORDS/transcripts/c1.json" << 'EOF'
{"chunk_id":"c1","shot_id":"s1","original_text":"...","original_normalized":"...","segments":[{"text":"测试无词级数据的场景第二句","start":0.0,"end":3.0,"words":[]}],"full_transcribed_text":"测试无词级数据的场景第二句"}
EOF
node "$HARNESS/scripts/p5-subtitles.js" --chunks "$NO_WORDS/chunks.json" --transcripts "$NO_WORDS/transcripts" --outdir "$NO_WORDS" >/dev/null 2>&1

run_test "P5: fallback (0 words) produces subtitles" \
  "node -e \"
    const s=require('$NO_WORDS/subtitles.json');
    process.exit(s.s1.chunks[0].subtitles.length>0?0:1);
  \""

run_test "P5: fallback timestamps are finite" \
  "node -e \"
    const s=require('$NO_WORDS/subtitles.json');
    const subs=s.s1.chunks[0].subtitles;
    process.exit(subs.every(x=>isFinite(x.start)&&isFinite(x.end)&&x.end>x.start)?0:1);
  \""

rm -rf "$NO_WORDS" "$WORK"

# ------------------------------------------------
# P6 Tests
# ------------------------------------------------
echo ""
echo "--- P6: Concat ---"

WORK=$(mktemp -d)
mkdir -p "$WORK/audio" "$WORK/output"

ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 1.0 "$WORK/audio/shot01_chunk01.wav" 2>/dev/null
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 2.0 "$WORK/audio/shot01_chunk02.wav" 2>/dev/null
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 1.5 "$WORK/audio/shot02_chunk01.wav" 2>/dev/null

cat > "$WORK/chunks.json" << 'EOF'
[
  {"id":"shot01_chunk01","shot_id":"shot01","text":"第一句","text_normalized":"第一句","status":"validated","duration_s":1.0,"file":"shot01_chunk01.wav"},
  {"id":"shot01_chunk02","shot_id":"shot01","text":"第二句话更长","text_normalized":"第二句话更长","status":"validated","duration_s":2.0,"file":"shot01_chunk02.wav"},
  {"id":"shot02_chunk01","shot_id":"shot02","text":"另一个段落","text_normalized":"另一个段落","status":"validated","duration_s":1.5,"file":"shot02_chunk01.wav"}
]
EOF

cat > "$WORK/subtitles.json" << 'EOF'
{
  "shot01": {
    "chunks": [
      {"chunk_id":"shot01_chunk01","subtitles":[{"id":"sub_001","text":"第一句","start":0,"end":1.0}]},
      {"chunk_id":"shot01_chunk02","subtitles":[{"id":"sub_002","text":"第二句话更长","start":0,"end":2.0}]}
    ]
  },
  "shot02": {
    "chunks": [
      {"chunk_id":"shot02_chunk01","subtitles":[{"id":"sub_003","text":"另一个段落","start":0,"end":1.5}]}
    ]
  }
}
EOF

node "$HARNESS/scripts/p6-concat.js" --chunks "$WORK/chunks.json" --audiodir "$WORK/audio" --subtitles "$WORK/subtitles.json" --outdir "$WORK/output" >/dev/null 2>&1

run_test "P6: produces shot WAV files" \
  "test -f '$WORK/output/shot01.wav' && test -f '$WORK/output/shot02.wav'"

run_test "P6: produces durations.json" \
  "test -f '$WORK/output/durations.json'"

run_test "P6: shot01 duration ≈ 3.45s (±0.2)" \
  "node -e \"
    const {execSync}=require('child_process');
    const dur=parseFloat(execSync('ffprobe -v quiet -show_entries format=duration -of csv=p=0 $WORK/output/shot01.wav',{encoding:'utf-8'}));
    process.exit(Math.abs(dur-3.45)<0.2?0:1);
  \""

run_test "P6: shot02 duration ≈ 1.9s (±0.2)" \
  "node -e \"
    const {execSync}=require('child_process');
    const dur=parseFloat(execSync('ffprobe -v quiet -show_entries format=duration -of csv=p=0 $WORK/output/shot02.wav',{encoding:'utf-8'}));
    process.exit(Math.abs(dur-1.9)<0.2?0:1);
  \""

run_test "P6: subtitles flattened to arrays" \
  "node -e \"const s=require('$WORK/subtitles.json'); process.exit(Array.isArray(s.shot01)?0:1)\""

run_test "P6: sub_001 start ≈ 0.2 (padding)" \
  "node -e \"const s=require('$WORK/subtitles.json'); process.exit(Math.abs(s.shot01[0].start-0.2)<0.05?0:1)\""

run_test "P6: sub_002 start ≈ 1.25 (pad+chunk1+gap)" \
  "node -e \"const s=require('$WORK/subtitles.json'); process.exit(Math.abs(s.shot01[1].start-1.25)<0.1?0:1)\""

# P6: 0-chunk shot doesn't crash
EMPTY_WORK=$(mktemp -d)
mkdir -p "$EMPTY_WORK/audio" "$EMPTY_WORK/output"
cat > "$EMPTY_WORK/chunks.json" << 'EOF'
[{"id":"empty_chunk","shot_id":"empty_shot","text":"","text_normalized":"","status":"validated","duration_s":0,"file":null}]
EOF
cat > "$EMPTY_WORK/subtitles.json" << 'EOF'
{}
EOF

run_test "P6: 0-chunk shot doesn't crash" \
  "node '$HARNESS/scripts/p6-concat.js' --chunks '$EMPTY_WORK/chunks.json' --audiodir '$EMPTY_WORK/audio' --subtitles '$EMPTY_WORK/subtitles.json' --outdir '$EMPTY_WORK/output' >/dev/null 2>&1"

rm -rf "$WORK" "$EMPTY_WORK"

# ------------------------------------------------
# Precheck Tests
# ------------------------------------------------
echo ""
echo "--- Precheck ---"

WORK=$(mktemp -d)
mkdir -p "$WORK/audio"

ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -ar 44100 -ac 1 "$WORK/audio/good.wav" 2>/dev/null
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -ar 44100 -ac 2 "$WORK/audio/bad_stereo.wav" 2>/dev/null

cat > "$WORK/chunks_good.json" << 'EOF'
[{"id":"good","shot_id":"s1","text":"测试正常音频文件","text_normalized":"测试正常音频文件","status":"synth_done","char_count":8,"duration_s":3.0,"file":"good.wav"}]
EOF

cat > "$WORK/chunks_stereo.json" << 'EOF'
[{"id":"bad_stereo","shot_id":"s2","text":"测试立体声音频","text_normalized":"测试立体声音频","status":"synth_done","char_count":7,"duration_s":3.0,"file":"bad_stereo.wav"}]
EOF

run_test "Precheck P2: passes mono 44100Hz" \
  "node '$HARNESS/scripts/precheck.js' --stage p2 --chunks '$WORK/chunks_good.json' --audiodir '$WORK/audio' 2>/dev/null"

run_test "Precheck P2: rejects stereo (exit 1)" \
  "! node '$HARNESS/scripts/precheck.js' --stage p2 --chunks '$WORK/chunks_stereo.json' --audiodir '$WORK/audio' 2>/dev/null"

# Post-P3 tests
mkdir -p "$WORK/transcripts"

cat > "$WORK/chunks_p3.json" << 'EOF'
[{"id":"t1","shot_id":"s1","text":"测试文本内容","text_normalized":"测试文本内容","status":"transcribed","char_count":6}]
EOF
cat > "$WORK/transcripts/t1.json" << 'EOF'
{"chunk_id":"t1","segments":[{"text":"测试文本内容","start":0.0,"end":1.5,"words":[]}],"full_transcribed_text":"测试文本内容"}
EOF

run_test "Precheck P3: passes valid transcript" \
  "node '$HARNESS/scripts/precheck.js' --stage p3 --chunks '$WORK/chunks_p3.json' --transcripts '$WORK/transcripts' 2>/dev/null"

# Non-monotonic timestamps
cat > "$WORK/transcripts/t1.json" << 'EOF'
{"chunk_id":"t1","segments":[{"text":"a","start":2.0,"end":1.0,"words":[]}],"full_transcribed_text":"测试"}
EOF

run_test "Precheck P3: rejects non-monotonic (exit 1)" \
  "! node '$HARNESS/scripts/precheck.js' --stage p3 --chunks '$WORK/chunks_p3.json' --transcripts '$WORK/transcripts' 2>/dev/null"

# Char ratio boundary: 0.7 should pass, 0.69 should fail
cat > "$WORK/chunks_p3_ratio.json" << 'EOF'
[{"id":"t1","shot_id":"s1","text":"一二三四五六七八九十","text_normalized":"一二三四五六七八九十","status":"transcribed","char_count":10}]
EOF
cat > "$WORK/transcripts/t1.json" << 'EOF'
{"chunk_id":"t1","segments":[{"text":"一二三四五六七","start":0.0,"end":1.5,"words":[]}],"full_transcribed_text":"一二三四五六七"}
EOF

run_test "Precheck P3: char ratio 0.7 passes" \
  "node '$HARNESS/scripts/precheck.js' --stage p3 --chunks '$WORK/chunks_p3_ratio.json' --transcripts '$WORK/transcripts' 2>/dev/null"

cat > "$WORK/transcripts/t1.json" << 'EOF'
{"chunk_id":"t1","segments":[{"text":"一二三","start":0.0,"end":1.5,"words":[]}],"full_transcribed_text":"一二三"}
EOF

run_test "Precheck P3: char ratio 0.3 fails (exit 1)" \
  "! node '$HARNESS/scripts/precheck.js' --stage p3 --chunks '$WORK/chunks_p3_ratio.json' --transcripts '$WORK/transcripts' 2>/dev/null"

rm -rf "$WORK"

# ------------------------------------------------
# trace.js Tests
# ------------------------------------------------
echo ""
echo "--- P1: Merge with existing chunks ---"

# Test: P1 re-run preserves duration_s and file from existing chunks.json
MERGE_WORK=$(mktemp -d)
# First run: create chunks
node "$HARNESS/scripts/p1-chunk.js" --script "$HARNESS/example/demo-script.json" --outdir "$MERGE_WORK" >/dev/null 2>&1

# Simulate P2 having set runtime fields
node -e "
  const fs=require('fs');
  const c=require('$MERGE_WORK/chunks.json');
  c[0].duration_s=9.5;
  c[0].file='shot01_chunk01.wav';
  c[0].status='validated';
  c[1].duration_s=15.2;
  c[1].file='shot02_chunk01.wav';
  c[1].status='transcribed';
  fs.writeFileSync('$MERGE_WORK/chunks.json',JSON.stringify(c,null,2));
"

# Re-run P1 (same script, no text changes)
node "$HARNESS/scripts/p1-chunk.js" --script "$HARNESS/example/demo-script.json" --outdir "$MERGE_WORK" >/dev/null 2>&1

run_test "P1 merge: preserves duration_s after re-run" \
  "node -e \"const c=require('$MERGE_WORK/chunks.json'); process.exit(c[0].duration_s===9.5?0:1)\""

run_test "P1 merge: preserves file after re-run" \
  "node -e \"const c=require('$MERGE_WORK/chunks.json'); process.exit(c[0].file==='shot01_chunk01.wav'?0:1)\""

run_test "P1 merge: preserves status when text unchanged" \
  "node -e \"const c=require('$MERGE_WORK/chunks.json'); process.exit(c[0].status==='validated'?0:1)\""

rm -rf "$MERGE_WORK"

echo ""
echo "--- Trace ---"

WORK=$(mktemp -d)
TRACE_FILE="$WORK/trace.jsonl"

run_test "trace: writes valid JSONL" \
  "node -e \"
    const {trace}=require('$HARNESS/scripts/trace.js');
    trace('$TRACE_FILE',{chunk:'c1',phase:'p2',event:'start'});
    trace('$TRACE_FILE',{chunk:'c1',phase:'p2',event:'done',duration_ms:1234});
    const lines=require('fs').readFileSync('$TRACE_FILE','utf-8').trim().split('\n');
    process.exit(lines.length===2 && lines.every(l=>JSON.parse(l).ts)?0:1);
  \""

run_test "trace: summary doesn't crash" \
  "node -e \"require('$HARNESS/scripts/trace.js').summary('$TRACE_FILE')\" 2>/dev/null"

rm -rf "$WORK"

# ------------------------------------------------
# Text Diff Tests
# ------------------------------------------------
echo ""
echo "--- Text Diff ---"

DIFF_WORK=$(mktemp -d)
mkdir -p "$DIFF_WORK/transcripts"

# Chunk with minor difference (should auto-pass)
cat > "$DIFF_WORK/chunks.json" << 'EOF'
[
  {"id":"c1","shot_id":"s1","text":"测试文本","text_normalized":"测试的文本内容","status":"transcribed","char_count":7},
  {"id":"c2","shot_id":"s1","text":"差异大的","text_normalized":"这是完全不同的内容啊","status":"transcribed","char_count":10}
]
EOF
# c1: similar transcription (homophone 的→地)
cat > "$DIFF_WORK/transcripts/c1.json" << 'EOF'
{"chunk_id":"c1","full_transcribed_text":"测试地文本内容","segments":[{"text":"测试地文本内容","start":0,"end":1,"words":[]}]}
EOF
# c2: very different transcription
cat > "$DIFF_WORK/transcripts/c2.json" << 'EOF'
{"chunk_id":"c2","full_transcribed_text":"完全无关的其他东西","segments":[{"text":"完全无关的其他东西","start":0,"end":1,"words":[]}]}
EOF

node "$HARNESS/scripts/text-diff.js" --chunks "$DIFF_WORK/chunks.json" --transcripts "$DIFF_WORK/transcripts" >/dev/null 2>&1

run_test "TextDiff: similar text auto-validated" \
  "node -e \"const c=require('$DIFF_WORK/chunks.json'); process.exit(c.find(x=>x.id==='c1').status==='validated'?0:1)\""

run_test "TextDiff: different text stays transcribed" \
  "node -e \"const c=require('$DIFF_WORK/chunks.json'); process.exit(c.find(x=>x.id==='c2').status==='transcribed'?0:1)\""

rm -rf "$DIFF_WORK"

# ------------------------------------------------
# Post-P6 Validation Tests
# ------------------------------------------------
echo ""
echo "--- Post-P6 Validation ---"

P6V_WORK=$(mktemp -d)

# Good subtitles + durations
cat > "$P6V_WORK/subtitles.json" << 'EOF'
{
  "shot01": [
    {"id":"s1","text":"第一句","start":0.2,"end":2.0},
    {"id":"s2","text":"第二句","start":2.0,"end":4.5},
    {"id":"s3","text":"第三句","start":4.5,"end":5.8}
  ]
}
EOF
cat > "$P6V_WORK/durations.json" << 'EOF'
[{"id":"shot01","duration_s":6.0,"file":"shot01.wav"}]
EOF

run_test "PostP6: valid subtitles pass" \
  "node '$HARNESS/scripts/postcheck-p6.js' --subtitles '$P6V_WORK/subtitles.json' --durations '$P6V_WORK/durations.json' 2>/dev/null"

# Overlapping subtitles (should fail)
cat > "$P6V_WORK/subtitles_overlap.json" << 'EOF'
{
  "shot01": [
    {"id":"s1","text":"第一句","start":0.2,"end":3.0},
    {"id":"s2","text":"第二句","start":2.0,"end":4.5}
  ]
}
EOF

run_test "PostP6: overlapping subtitles detected" \
  "! node '$HARNESS/scripts/postcheck-p6.js' --subtitles '$P6V_WORK/subtitles_overlap.json' --durations '$P6V_WORK/durations.json' 2>/dev/null"

rm -rf "$P6V_WORK"

# ------------------------------------------------
# Changelog Tests
# ------------------------------------------------
echo ""
echo "--- Changelog ---"

CL_WORK=$(mktemp -d)
node "$HARNESS/scripts/p1-chunk.js" --script "$HARNESS/example/demo-script.json" --outdir "$CL_WORK" >/dev/null 2>&1

run_test "Changelog: P1 output has normalized_history" \
  "node -e \"const c=require('$CL_WORK/chunks.json'); process.exit(c.every(x=>Array.isArray(x.normalized_history)&&x.normalized_history.length===1)?0:1)\""

run_test "Changelog: history[0] source is p1-normalize" \
  "node -e \"const c=require('$CL_WORK/chunks.json'); process.exit(c.every(x=>x.normalized_history[0].source==='p1-normalize')?0:1)\""

rm -rf "$CL_WORK"

# ------------------------------------------------
# .harness/ Memory Tests
# ------------------------------------------------
echo ""
echo "--- .harness/ Memory ---"

# Test: config.json loads defaults when missing
NOCONFIG_WORK=$(mktemp -d)
cat > "$NOCONFIG_WORK/script.json" << 'EOF'
{"segments":[{"id":1,"text":"无配置文件测试。第二句。"}]}
EOF

run_test ".harness: P1 works without config.json" \
  "node '$HARNESS/scripts/p1-chunk.js' --script '$NOCONFIG_WORK/script.json' --outdir '$NOCONFIG_WORK' --harness-dir '$NOCONFIG_WORK' >/dev/null 2>&1 && test -f '$NOCONFIG_WORK/chunks.json'"

run_test ".harness: P1 works without .harness dir at all" \
  "node '$HARNESS/scripts/p1-chunk.js' --script '$NOCONFIG_WORK/script.json' --outdir '$NOCONFIG_WORK' --harness-dir '/tmp/nonexistent_harness_dir_$$' >/dev/null 2>&1 && test -f '$NOCONFIG_WORK/chunks.json'"

rm -rf "$NOCONFIG_WORK"

# Test: config.json overrides defaults
CONFIG_WORK=$(mktemp -d)
mkdir -p "$CONFIG_WORK/.harness"
cat > "$CONFIG_WORK/.harness/config.json" << 'EOF'
{"p1":{"max_chars_per_chunk":50,"max_sentences_per_chunk":2,"min_sentences_per_chunk":1}}
EOF
cat > "$CONFIG_WORK/script.json" << 'EOF'
{"segments":[{"id":1,"text":"第一句话。第二句话。第三句话。第四句话。第五句话。"}]}
EOF

node "$HARNESS/scripts/p1-chunk.js" --script "$CONFIG_WORK/script.json" --outdir "$CONFIG_WORK" --harness-dir "$CONFIG_WORK" >/dev/null 2>&1

run_test ".harness: config.json max_sentences_per_chunk=2 produces more chunks" \
  "node -e \"const c=require('$CONFIG_WORK/chunks.json'); process.exit(c.length>=2?0:1)\""

rm -rf "$CONFIG_WORK"

# Test: empty patches file doesn't break P1
EMPTY_PATCH_WORK=$(mktemp -d)
mkdir -p "$EMPTY_PATCH_WORK/.harness"
echo '[]' > "$EMPTY_PATCH_WORK/.harness/normalize-patches.json"
cat > "$EMPTY_PATCH_WORK/script.json" << 'EOF'
{"segments":[{"id":1,"text":"空补丁测试。第二句。"}]}
EOF

run_test ".harness: empty patches array is safe" \
  "node '$HARNESS/scripts/p1-chunk.js' --script '$EMPTY_PATCH_WORK/script.json' --outdir '$EMPTY_PATCH_WORK' --harness-dir '$EMPTY_PATCH_WORK' >/dev/null 2>&1 && test -f '$EMPTY_PATCH_WORK/chunks.json'"

rm -rf "$EMPTY_PATCH_WORK"

# ------------------------------------------------
# Summary
# ------------------------------------------------
echo ""
echo "=================================================="
echo " Results: $PASS passed, $FAIL failed"
echo "=================================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
