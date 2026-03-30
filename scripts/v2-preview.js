#!/usr/bin/env node
/**
 * V2 验收 — 生成 HTML 预览页
 *
 * 模拟 Remotion 的渐进字幕渲染：
 * - 当前行逐字显示，已显示的字白色，未显示的暗灰
 * - 语音播放位置用光标标记
 * - 语音比字幕快时视觉上一目了然
 *
 * Usage:
 *   node scripts/v2-preview.js --audiodir <dir> --subtitles <subtitles.json> --output <preview.html>
 */

const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
let audiodir = "";
let subtitlesPath = "";
let outputPath = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--audiodir" && args[i + 1]) audiodir = args[++i];
  else if (args[i] === "--subtitles" && args[i + 1]) subtitlesPath = args[++i];
  else if (args[i] === "--output" && args[i + 1]) outputPath = args[++i];
}

if (!audiodir || !subtitlesPath || !outputPath) {
  console.error(
    "Usage: node v2-preview.js --audiodir <dir> --subtitles <subtitles.json> --output <preview.html>"
  );
  process.exit(1);
}

const subtitles = JSON.parse(fs.readFileSync(subtitlesPath, "utf-8"));

function relativeAudioPath(audiodir, wavFileName, outputHtmlPath) {
  const absWav = path.resolve(path.join(audiodir, wavFileName));
  const absHtmlDir = path.resolve(path.dirname(outputHtmlPath));
  return path.relative(absHtmlDir, absWav);
}

const shots = [];
for (const [shotId, subs] of Object.entries(subtitles)) {
  const wavFile = `${shotId}.wav`;
  const wavPath = path.join(audiodir, wavFile);
  if (!fs.existsSync(wavPath)) continue;
  const relPath = relativeAudioPath(audiodir, wavFile, outputPath);
  shots.push({ id: shotId, audioSrc: relPath, subtitles: subs });
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const html = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>TTS 字幕验收预览</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'PingFang SC', 'Noto Sans SC', sans-serif; background: #0a0a0a; color: #eee; padding: 40px; }
  h1 { font-size: 24px; margin-bottom: 8px; color: #a855f7; }
  .hint { font-size: 13px; color: #666; margin-bottom: 30px; }

  .shot { margin-bottom: 40px; border: 1px solid #222; border-radius: 12px; padding: 24px; background: #111; }
  .shot-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .shot-header h2 { font-size: 16px; color: #999; font-weight: 500; }
  .shot-header .badge { font-size: 11px; background: #1a1a2e; color: #a855f7; padding: 2px 8px; border-radius: 4px; }
  .shot audio { width: 100%; margin-bottom: 20px; }

  /* 字幕模拟区 — 模拟 1080×1920 底部字幕栏 */
  .subtitle-stage {
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    padding: 32px 40px;
    min-height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;
    position: relative;
  }
  .subtitle-stage .current-text {
    font-size: 28px;
    font-weight: 600;
    letter-spacing: 1px;
    text-align: center;
    line-height: 1.5;
  }
  .subtitle-stage .current-text .revealed { color: #fff; }
  .subtitle-stage .current-text .unrevealed { color: #333; }
  .subtitle-stage .current-text .cursor {
    display: inline-block;
    width: 2px;
    height: 1.1em;
    background: #a855f7;
    vertical-align: middle;
    margin: 0 1px;
    animation: blink 0.6s step-end infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }

  .subtitle-stage .no-sub { color: #333; font-size: 16px; font-style: italic; }
  .subtitle-stage .time-badge {
    position: absolute;
    top: 8px;
    right: 12px;
    font-size: 11px;
    font-family: monospace;
    color: #555;
  }

  /* 时间轴列表 */
  .timeline { margin-top: 8px; }
  .timeline .sub-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 4px 8px;
    margin: 1px 0;
    border-radius: 4px;
    font-size: 14px;
    line-height: 1.5;
    cursor: pointer;
    transition: background 0.1s;
  }
  .timeline .sub-row:hover { background: #1a1a1a; }
  .timeline .sub-row.past { color: #555; }
  .timeline .sub-row.active { background: rgba(168, 85, 247, 0.15); color: #fff; }
  .timeline .sub-row.future { color: #666; }
  .timeline .sub-row .t { font-family: monospace; font-size: 12px; color: #444; min-width: 90px; flex-shrink: 0; padding-top: 2px; }
  .timeline .sub-row.active .t { color: #a855f7; }
  .timeline .sub-row .txt { flex: 1; }

  /* 进度条 */
  .progress-bar {
    width: 100%;
    height: 3px;
    background: #1a1a1a;
    border-radius: 2px;
    margin-bottom: 16px;
    position: relative;
  }
  .progress-bar .fill {
    height: 100%;
    background: #a855f7;
    border-radius: 2px;
    transition: width 0.05s linear;
  }
</style>
</head>
<body>
<h1>TTS 字幕验收预览</h1>
<p class="hint">点击字幕行跳转 | 紫色光标 = 语音位置 | 白字 = 已读出 | 暗字 = 未读出 | 语音快于字幕时光标会跑到暗字区</p>

${shots
  .map(
    (shot, idx) => `
<div class="shot" id="shot-${idx}">
  <div class="shot-header">
    <h2>${shot.id}</h2>
    <span class="badge">${shot.subtitles.length} lines</span>
  </div>
  <audio controls src="${shot.audioSrc}" data-shot-idx="${idx}"></audio>
  <div class="progress-bar"><div class="fill" id="prog-${idx}"></div></div>
  <div class="subtitle-stage" id="stage-${idx}">
    <div class="no-sub">--</div>
  </div>
  <div class="timeline" id="tl-${idx}">
    ${shot.subtitles
      .map(
        (s, si) =>
          '<div class="sub-row future" data-start="' + s.start + '" data-end="' + s.end + '" data-idx="' + si + '" data-shot="' + idx + '">' +
          '<span class="t">' + s.start.toFixed(2) + 's - ' + s.end.toFixed(2) + 's</span>' +
          '<span class="txt">' + esc(s.text) + '</span>' +
          '</div>'
      )
      .join("\n    ")}
  </div>
</div>`
  )
  .join("\n")}

<script>
const shotsData = ${JSON.stringify(shots.map(s => s.subtitles))};

document.querySelectorAll('audio').forEach(audio => {
  const idx = parseInt(audio.dataset.shotIdx);
  const subs = shotsData[idx];
  const stage = document.getElementById('stage-' + idx);
  const rows = document.querySelectorAll('#tl-' + idx + ' .sub-row');
  const progFill = document.getElementById('prog-' + idx);

  audio.addEventListener('timeupdate', () => {
    const t = audio.currentTime;
    const duration = audio.duration || 1;
    progFill.style.width = ((t / duration) * 100) + '%';

    // Find active subtitle
    let activeIdx = -1;
    for (let i = 0; i < subs.length; i++) {
      if (t >= subs[i].start && t < subs[i].end) { activeIdx = i; break; }
    }

    // Update timeline rows
    rows.forEach((row, ri) => {
      row.className = 'sub-row ' + (ri < activeIdx ? 'past' : ri === activeIdx ? 'active' : 'future');
    });

    // Update stage with progressive text
    if (activeIdx === -1) {
      stage.innerHTML = '<div class="no-sub">--</div>';
    } else {
      const sub = subs[activeIdx];
      const text = sub.text;
      const progress = (t - sub.start) / (sub.end - sub.start);
      const revealCount = Math.floor(progress * text.length);

      const revealed = text.slice(0, revealCount);
      const unrevealed = text.slice(revealCount);

      stage.innerHTML =
        '<div class="time-badge">' + t.toFixed(2) + 's / ' + sub.start.toFixed(2) + '-' + sub.end.toFixed(2) + '</div>' +
        '<div class="current-text">' +
          '<span class="revealed">' + escHtml(revealed) + '</span>' +
          '<span class="cursor"></span>' +
          '<span class="unrevealed">' + escHtml(unrevealed) + '</span>' +
        '</div>';
    }
  });

  // Click row to seek
  rows.forEach(row => {
    row.addEventListener('click', () => {
      audio.currentTime = parseFloat(row.dataset.start);
      audio.play();
    });
  });
});

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
</body>
</html>`;

fs.writeFileSync(outputPath, html);
console.log(`=== Preview: ${outputPath} ===`);
console.log(`  ${shots.length} shots, open in browser to review`);
