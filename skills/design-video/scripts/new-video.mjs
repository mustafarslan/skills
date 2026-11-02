#!/usr/bin/env node
// Start a new composition in the user's project from the reference template.
//
//   node new-video.mjs <folder>
//
// Writes a self-contained folder — index.html, motion.js, tokens.css side by side — so the
// composition opens, previews and renders from any project without the skill folder next to it,
// and the delivered source still works after the skill moves or updates. Refuses to overwrite.

import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const target = process.argv[2];
if (!target) { console.error('usage: node new-video.mjs <folder>'); process.exit(1); }
const skill = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(target);
if (existsSync(join(out, 'index.html'))) { console.error('already exists, not overwriting:', join(out, 'index.html')); process.exit(1); }

let html = readFileSync(join(skill, 'assets', 'template', 'index.html'), 'utf8');
const links = [['href="../../references/tokens.css"', 'href="tokens.css"'], ['src="../lib/motion.js"', 'src="motion.js"']];
for (const [from, to] of links) {
  if (!html.includes(from)) { console.error('template link not found (template changed?):', from); process.exit(1); }
  html = html.replace(from, to);
}
mkdirSync(out, { recursive: true });
writeFileSync(join(out, 'index.html'), html);
copyFileSync(join(skill, 'assets', 'lib', 'motion.js'), join(out, 'motion.js'));
copyFileSync(join(skill, 'references', 'tokens.css'), join(out, 'tokens.css'));
console.log('✓ new composition:', out);
console.log('  index.html  edit this (timeline, COPY, CAPTIONS, visuals)');
console.log('  motion.js, tokens.css  copies from the skill; do not edit tokens here');
