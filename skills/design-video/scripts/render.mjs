#!/usr/bin/env node
// Frame-exact renderer for design-video compositions.
//
//   node render.mjs <composition.html> [--out video.mp4] [--mode dark|light|both] [--fps 30]
//                   [--scale 1|2] [--from 0] [--to <s>] [--still <s>] [--audio file]
//                   [--chrome <path>] [--work <dir>]
//
// The composition is an HTML page that sets  window.__video = { width, height, duration }  and
// window.__frame(t, mode), which draws the frame at time t (seconds). The renderer opens it in
// headless Chrome, asks for each frame in turn, screenshots it as PNG, and pipes the frames to ffmpeg.
// Everything it needs (playwright-core, a static ffmpeg, pinned) is installed once into a per-user
// cache folder (see `work` below; override with --work or DESIGN_VIDEO_CACHE), never into the project and never into the skill folder, which
// may be read-only when the skill comes from a plugin.

import { spawn, execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve, join, basename, extname } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

// Accept both `--still 2` and `--still=2`.
const args = process.argv.slice(2).flatMap((a) => (a.startsWith('--') && a.includes('=') ? [a.slice(0, a.indexOf('=')), a.slice(a.indexOf('=') + 1)] : [a]));
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const input = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!input) {
  console.error('usage: node render.mjs <composition.html> [--out video.mp4] [--mode dark|light|both] [--fps 30] [--scale 1|2] [--from s] [--to s] [--still s] [--audio file]');
  process.exit(1);
}

const src = resolve(input);
if (!existsSync(src)) { console.error('composition not found:', src); process.exit(1); }
// Pinned render dependencies. Changing a version changes the folder name, so an old install is never reused.
const DEPS = ['playwright-core@1.52.0', '@ffmpeg-installer/ffmpeg@1.1.0'];
const cacheRoot = process.env.DESIGN_VIDEO_CACHE
  || (process.platform === 'win32' && process.env.LOCALAPPDATA ? join(process.env.LOCALAPPDATA, 'design-video')
  : join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'design-video'));
const work = resolve(opt('work', join(cacheRoot, 'render-deps-' + DEPS.join('_').replace(/[^A-Za-z0-9.]+/g, '-'))));
const fps = Number(opt('fps', 30));
const scale = Number(opt('scale', 1));
const modeArg = opt('mode', 'dark');
const modes = modeArg === 'both' ? ['dark', 'light'] : [modeArg];
const stillAt = opt('still', null);
const audio = opt('audio', null);
const ext = stillAt != null ? '.png' : '.mp4';
let outBase = resolve(opt('out', join(dirname(src), basename(src, extname(src)) + ext)));
if (!extname(outBase)) outBase += ext;   // so --mode both can suffix -dark / -light
mkdirSync(dirname(outBase), { recursive: true });

// 1. Private work folder with pinned dependencies.
mkdirSync(work, { recursive: true });
if (!existsSync(join(work, 'node_modules', 'playwright-core')) || !existsSync(join(work, 'node_modules', '@ffmpeg-installer'))) {
  console.log('» installing render dependencies into', work);
  writeFileSync(join(work, 'package.json'), JSON.stringify({ name: 'video-render-work', private: true }, null, 2));
  execFileSync('npm', ['install', '--no-audit', '--no-fund', '--loglevel=error', '--save-exact', ...DEPS],
    { cwd: work, stdio: 'inherit', shell: process.platform === 'win32' });   // npm is npm.cmd on Windows
}
const req = createRequire(join(work, 'package.json'));
const { chromium } = req('playwright-core');
const ffmpegPath = req('@ffmpeg-installer/ffmpeg').path;

// 2. Browser: the system Chrome (or --chrome / CHROME_PATH).
const candidates = [opt('chrome'), process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe')].filter(Boolean);
const chrome = candidates.find((p) => existsSync(p));
if (!chrome) { console.error('Chrome or Chromium not found. Install Google Chrome, pass --chrome <path>, or set CHROME_PATH.'); process.exit(1); }

const browser = await chromium.launch({ executablePath: chrome });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: scale });  // resized to the composition below
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(pathToFileURL(src).href);
try { await page.waitForFunction(() => window.__video && window.__frame, null, { timeout: 15000 }); }
catch { console.error('composition did not define window.__video and window.__frame:', errors[0] || 'no error reported'); await browser.close(); process.exit(1); }
await page.evaluate(() => document.fonts.ready);
const meta = await page.evaluate(() => window.__video);
const duration = Number(meta.duration);
// The frame size comes from the composition, so a vertical (1080x1920) video renders as one.
const W = Number(meta.width) || 1920, H = Number(meta.height) || 1080;
if (!(duration > 0)) { console.error('window.__video.duration must be a positive number of seconds'); await browser.close(); process.exit(1); }
await page.setViewportSize({ width: W, height: H });
const from = Number(opt('from', 0)), to = Number(opt('to', duration));
const clip = { x: 0, y: 0, width: W, height: H };

const draw = async (t, mode) => {
  await page.evaluate(([tt, m]) => window.__frame(tt, m), [t, mode]);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  if (errors.length) throw new Error('composition threw: ' + errors[0]);
};

try {
  for (const mode of modes) {
    const out = modes.length > 1 ? outBase.replace(/(\.\w+)$/, `-${mode}$1`) : outBase;
    if (stillAt != null) {
      await draw(Number(stillAt), mode);
      await page.screenshot({ path: out, type: 'png', clip });
      console.log(`✓ still ${out} (t=${stillAt}s, ${mode})`);
      continue;
    }
    const frames = Math.round((to - from) * fps);
    const ffArgs = ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-'];
    // Audio starts where the section starts (--from), and is padded with silence so a voice-over
    // that ends before the end card never cuts the video short.
    if (audio) ffArgs.push('-ss', String(from), '-i', resolve(audio), '-map', '0:v', '-map', '1:a');
    ffArgs.push('-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p', '-c:v', 'libx264', '-profile:v', 'high', '-crf', '18', '-r', String(fps),
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709');
    if (audio) ffArgs.push('-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-af', 'loudnorm=I=-14:TP=-1:LRA=11,apad', '-t', String(to - from));
    ffArgs.push('-movflags', '+faststart', out);
    const ff = spawn(ffmpegPath, ffArgs, { stdio: ['pipe', 'inherit', 'inherit'] });
    const done = new Promise((res, rej) => ff.on('close', (c) => (c === 0 ? res() : rej(new Error('ffmpeg exited ' + c)))));
    const started = Date.now();
    for (let i = 0; i < frames; i++) {
      await draw(from + i / fps, mode);
      const buf = await page.screenshot({ type: 'png', clip });
      if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
      if (i % (fps * 5) === 0) process.stdout.write(`  ${mode}: ${(i / fps).toFixed(0)}s / ${(to - from).toFixed(0)}s\r`);
    }
    ff.stdin.end();
    await done;
    console.log(`✓ ${out} — ${(to - from).toFixed(1)}s @ ${fps}fps, ${W * scale}x${H * scale}, ${mode} (${((Date.now() - started) / 1000).toFixed(0)}s)`);
  }
} catch (e) {
  console.error('✗', e.message);
  await browser.close();
  process.exit(1);
}
await browser.close();
