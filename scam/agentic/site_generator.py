"""GitHub Pages site generator for SCAM benchmark.

Generates a static site in ``docs/`` from a v2 result JSON file.
The site includes a leaderboard, featured scenario replays, the
security skill with integration instructions, and 1Password branding.

Usage::

    scam publish results/agentic/scam-evaluate-*.json
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import zipfile
from pathlib import Path

from scam.agentic.export_html import (
    _CSS,
    _JS,
    export_result,
    prepare_scenario_data,
)
from scam.agentic.results import iter_scenarios, get_run_metadata_for_scenario


# ── Design tokens (1Password developer aesthetic) ────────────────────

_SITE_CSS = """
:root {
  --bg: #ffffff;
  --bg-subtle: #f5f5f7;
  --bg-elevated: #ffffff;
  --bg-card: #ffffff;
  --border: #e5e5ea;
  --border-strong: #d1d1d6;
  --accent: #0572ec;
  --accent-hover: #0461cc;
  --accent-subtle: rgba(5,114,236,0.07);
  --accent-light: #e8f1fd;
  --text: #1d1d1f;
  --text-secondary: #6e6e73;
  --text-tertiary: #98989d;
  --success: #1a8d5f;
  --warning: #b45309;
  --fail: #d93025;
  --font: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-display: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --mono: 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Consolas, monospace;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.08);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: var(--accent); text-decoration: none; transition: color 0.15s; }
a:hover { color: var(--accent-hover); text-decoration: underline; }

.container { max-width: 1080px; margin: 0 auto; padding: 0 32px; }

/* ── Top nav bar ─────────────────────────────────────────── */
.topnav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255,255,255,0.88);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
}
.topnav-inner {
  max-width: 1080px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  height: 52px;
}
.topnav-brand {
  display: flex; align-items: center; gap: 10px;
  font-weight: 700; font-size: 0.95rem; color: var(--text);
  text-decoration: none; font-family: var(--font-display);
}
.topnav-brand:hover { color: var(--text); text-decoration: none; }
.topnav-brand .brand-dot { color: var(--text-secondary); font-weight: 400; }
.topnav-links { display: flex; gap: 24px; align-items: center; }
.topnav-links a {
  font-size: 0.84rem; font-weight: 500; color: var(--text-secondary);
}
.topnav-links a:hover { color: var(--text); text-decoration: none; }
.topnav-links .nav-cta {
  background: var(--text); color: #fff; padding: 6px 16px;
  border-radius: 980px; font-weight: 600; font-size: 0.8rem;
}
.topnav-links .nav-cta:hover { background: #333; color: #fff; text-decoration: none; }

/* ── Hero ────────────────────────────────────────────────── */
.hero {
  padding: 80px 0 64px;
  text-align: center;
  background: linear-gradient(180deg, var(--bg-subtle) 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
}
.hero-eyebrow {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.76rem; font-weight: 600; color: var(--accent);
  background: var(--accent-light); padding: 5px 14px;
  border-radius: 980px; margin-bottom: 20px;
  letter-spacing: 0.01em;
}
.hero h1 {
  font-size: 3.4rem; font-weight: 700;
  letter-spacing: -0.04em; margin-bottom: 16px;
  line-height: 1.08;
  color: var(--text);
  font-family: var(--font-display);
}
.hero h1 .accent-word { color: var(--accent); }
.hero .tagline {
  font-size: 1.15rem; color: var(--text-secondary);
  max-width: 580px; margin: 0 auto 28px;
  line-height: 1.6; font-weight: 400;
}
.hero-cta-row {
  display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;
  margin-bottom: 28px;
}
.btn-primary {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 11px 24px; border-radius: 980px;
  background: var(--accent); color: #fff;
  font-size: 0.88rem; font-weight: 600;
  transition: background 0.15s, box-shadow 0.15s;
  box-shadow: 0 1px 3px rgba(5,114,236,0.3);
}
.btn-primary:hover { background: var(--accent-hover); text-decoration: none; color: #fff; box-shadow: 0 2px 8px rgba(5,114,236,0.35); }
.btn-secondary {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 11px 24px; border-radius: 980px;
  background: var(--bg); color: var(--text);
  border: 1px solid var(--border-strong);
  font-size: 0.88rem; font-weight: 600;
  transition: border-color 0.15s, background 0.15s;
}
.btn-secondary:hover { border-color: var(--text-tertiary); background: var(--bg-subtle); text-decoration: none; color: var(--text); }
.hero-meta {
  display: flex; gap: 20px; justify-content: center; flex-wrap: wrap;
  font-size: 0.95rem; color: var(--text-secondary);
}
.hero-meta span { display: inline-flex; align-items: center; gap: 5px; }
.hero-meta a { font-weight: 600; }

/* ── Sections ────────────────────────────────────────────── */
.section { padding: 72px 0; }
.section-divider {
  border: none; border-top: 1px solid var(--border);
  margin: 0;
}
.section-label {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--accent);
  margin-bottom: 10px;
}
.section-title {
  font-size: 1.75rem; font-weight: 700; margin-bottom: 10px;
  letter-spacing: -0.025em; line-height: 1.2;
  font-family: var(--font-display); color: var(--text);
}
.skill-version {
  font-size: 0.55em; font-weight: 600; color: var(--accent);
  background: var(--accent-light); padding: 2px 10px; border-radius: 9px;
  vertical-align: middle; letter-spacing: 0; position: relative; top: -2px;
}
.section-sub {
  color: var(--text-secondary); font-size: 0.95rem;
  margin-bottom: 36px; max-width: 560px; line-height: 1.6;
}
.intro-prose {
  margin-bottom: 32px;
}
.intro-prose p {
  font-size: 0.95rem; line-height: 1.75; color: var(--text-secondary);
  margin: 0 0 16px 0;
}
.intro-prose p:last-child { margin-bottom: 0; }

/* ── What it measures ────────────────────────────────────── */
.measures-grid {
  display: flex; flex-direction: column; gap: 40px;
}
.measures-prose h3 {
  font-size: 1.05rem; font-weight: 700; color: var(--text);
  margin-bottom: 8px; margin-top: 28px;
}
.measures-prose h3:first-child { margin-top: 0; }
.measures-prose p {
  font-size: 0.92rem; line-height: 1.75; color: var(--text-secondary);
  margin-bottom: 0;
}
.measures-callout {
  display: flex; flex-direction: column; gap: 18px;
}
.measures-callout .mc-label {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  font-weight: 700; color: var(--accent);
}
.measures-callout .replay-card {
  margin: 0;
}
.measures-callout .replay-card .rc-desc {
  -webkit-line-clamp: 4;
}
.measures-embed {
  display: flex; flex-direction: column; gap: 14px;
}
.measures-embed .mc-label {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  font-weight: 700; color: var(--accent);
}
.measures-embed-meta {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.78rem; color: var(--text-tertiary);
  margin-bottom: 4px;
}
.measures-embed-meta .score-badge {
  display: inline-block; padding: 2px 8px; border-radius: 6px;
  font-weight: 700; font-size: 0.78rem;
}
.measures-embed-meta .score-badge.score-red { background: #ffeef0; color: #d1242f; }
.measures-embed-meta .score-badge.score-yellow { background: #fff8e1; color: #9a6700; }
.measures-embed-meta .score-badge.score-green { background: #e6ffec; color: #1a7f37; }
.embed-replay-frame {
  width: 100%; height: 460px; border: 1px solid var(--border);
  border-radius: var(--radius); background: #fff;
}
.embed-poster {
  width: 100%; height: 460px; border: 1px solid var(--border);
  border-radius: var(--radius); background: var(--bg-subtle);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  cursor: pointer; transition: box-shadow 0.2s, border-color 0.2s;
  position: relative; overflow: hidden;
}
.embed-poster:hover { box-shadow: var(--shadow-md); border-color: var(--accent); }
.embed-poster-play {
  width: 64px; height: 64px; border-radius: 50%;
  background: var(--accent); color: #fff; border: none;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 16px rgba(5,114,236,0.3);
  cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;
  pointer-events: none;
}
.embed-poster:hover .embed-poster-play { transform: scale(1.08); box-shadow: 0 6px 24px rgba(5,114,236,0.4); }
.embed-poster-title {
  font-size: 1rem; font-weight: 700; color: var(--text); margin-top: 16px;
}
.embed-poster-sub {
  font-size: 0.85rem; color: var(--text-secondary); margin-top: 6px;
  max-width: 400px; text-align: center; line-height: 1.5;
}
.embed-poster-stats {
  display: flex; gap: 16px; margin-top: 14px;
  font-size: 0.78rem; color: var(--text-tertiary);
}
.embed-poster-stats span { display: flex; align-items: center; gap: 4px; }
.embed-poster-stats .stat-danger { color: var(--fail); font-weight: 600; }
.embed-share-cta {
  margin-top: 14px; padding: 16px 20px;
  background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.embed-share-text {
  font-size: 0.88rem; color: var(--text-secondary); margin: 0;
  flex: 1; min-width: 200px; line-height: 1.5;
}
.embed-share-links {
  display: flex; align-items: center; gap: 8px;
}
.embed-share-links .share-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 8px;
  background: #e8e8ed; color: #48484a; text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.embed-share-links .share-btn:hover { background: #d1d1d6; color: #1d1d1f; }
.embed-share-links .share-btn svg { width: 15px; height: 15px; }
.embed-share-replay-link {
  font-size: 0.84rem; font-weight: 600; color: var(--accent);
  text-decoration: none; margin-left: 4px; white-space: nowrap;
}
.embed-share-replay-link:hover { text-decoration: underline; }
.copy-link-btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: 4px; height: 30px; padding: 0 10px; border-radius: 8px;
  background: #e8e8ed; color: #48484a; border: none;
  font-size: 0.72rem; font-weight: 600; font-family: var(--font);
  cursor: pointer; white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.copy-link-btn:hover { background: #d1d1d6; color: #1d1d1f; }
.copy-link-btn svg { width: 13px; height: 13px; }
.embed-meta-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 10px; font-size: 0.82rem; color: var(--text-secondary);
}
.embed-meta-bar strong { color: var(--text); font-weight: 700; }
.embed-meta-bar .emb-tag {
  display: inline-block; padding: 2px 10px; border-radius: 6px;
  font-size: 0.74rem; font-weight: 700;
}
.embed-meta-bar .emb-tag.tag-red { background: #ffeef0; color: #d1242f; }
.embed-meta-bar .emb-tag.tag-green { background: #e6ffec; color: #1a7f37; }
.embed-meta-bar .emb-tag.tag-cat {
  background: var(--accent-light); color: var(--accent); font-weight: 600;
}
.embed-caption {
  font-size: 0.84rem; line-height: 1.6; color: var(--text-tertiary);
  margin-top: 12px; text-align: center;
}

/* ── Category chart ─────────────────────────────────────── */
.cat-chart {
  margin-top: 36px; margin-bottom: 12px;
}
.cat-chart-title {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
  font-weight: 700; color: var(--text-tertiary); margin-bottom: 16px;
}
.cat-bar-row {
  display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
}
.cat-bar-label {
  flex: 0 0 180px; text-align: right;
  font-size: 0.82rem; font-weight: 600; color: var(--text-secondary);
  white-space: nowrap;
}
.cat-bar-track {
  flex: 1; height: 24px; background: var(--bg-subtle);
  border-radius: 6px; overflow: hidden; position: relative;
}
.cat-bar-fill {
  height: 100%; background: var(--accent); border-radius: 6px;
  transition: width 0.4s ease;
  display: flex; align-items: center; justify-content: flex-end;
  padding-right: 8px;
}
.cat-bar-count {
  font-size: 0.72rem; font-weight: 700; color: #fff;
}
.cat-bar-count-outside {
  margin-left: 8px; font-size: 0.72rem; font-weight: 700; color: var(--text-tertiary);
}

/* ── How to run ──────────────────────────────────────────── */
.explain-text {
  font-size: 1rem; line-height: 1.75; color: var(--text-secondary);
  max-width: 680px; margin-bottom: 40px;
}
.install-block {
  background: #1d1d1f; color: #e5e5ea; border-radius: var(--radius);
  padding: 20px 24px; font-size: 0.82rem; line-height: 1.7;
  font-family: var(--mono); overflow-x: auto; margin-bottom: 0;
  max-width: 600px;
}
.cat-tags-row {
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;
}
.cat-tag {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: 980px;
  background: var(--bg-subtle); border: 1px solid var(--border);
  font-size: 0.8rem; color: var(--text-secondary);
  font-weight: 500; white-space: nowrap;
  text-decoration: none; transition: border-color 0.15s, background 0.15s;
}
a.cat-tag:hover {
  border-color: var(--accent); background: #f0f6ff;
}
.cat-tag strong {
  color: var(--accent); font-weight: 700;
}
.subsection-title {
  font-size: 1.25rem; font-weight: 700; color: var(--text-primary);
  margin-bottom: 12px;
}
.contribute-cta {
  margin-top: 48px; padding: 32px 36px;
  background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: var(--radius);
}
.contribute-cta .subsection-title { margin-top: 0; }
.contribute-list {
  list-style: none; padding: 0; margin: 0 0 20px;
  max-width: 680px;
}
.contribute-list li {
  position: relative; padding-left: 20px; margin-bottom: 10px;
  font-size: 0.95rem; line-height: 1.65; color: var(--text-secondary);
}
.contribute-list li::before {
  content: ""; position: absolute; left: 0; top: 10px;
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
}
.contribute-list li strong { color: var(--text-primary); }
.btn-contribute {
  display: inline-block; padding: 10px 22px;
  font-size: 0.88rem; font-weight: 600;
  color: var(--accent); border: 1.5px solid var(--accent);
  border-radius: 8px; text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.btn-contribute:hover {
  background: var(--accent); color: #fff;
}
.cards-row {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.info-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 24px 22px;
  transition: box-shadow 0.2s, transform 0.15s;
  box-shadow: var(--shadow-sm);
}
.info-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.info-card .icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; margin-bottom: 14px;
  background: var(--accent-light);
}
.info-card h3 { font-size: 0.95rem; font-weight: 700; margin-bottom: 6px; color: var(--text); }
.info-card p { font-size: 0.86rem; color: var(--text-secondary); line-height: 1.6; }

/* ── Leaderboard ─────────────────────────────────────────── */
.lb-meta {
  font-size: 0.78rem; color: var(--text-tertiary);
  margin-bottom: 16px;
}
.lb-downloads {
  margin-top: 20px; padding-top: 16px;
  border-top: 1px solid var(--border);
  text-align: center; font-size: 0.85rem;
}
.lb-downloads-label {
  margin: 0 0 6px; color: var(--text-secondary);
  font-size: 0.78rem; font-weight: 500;
}
.dl-link {
  color: var(--accent); text-decoration: none;
  font-weight: 500;
}
.dl-link:hover { text-decoration: underline; }
.dl-hash {
  display: block; margin-top: 6px;
  font-size: 0.72rem; color: var(--text-tertiary);
  font-family: var(--mono); letter-spacing: 0.02em;
}
.dl-hash code {
  background: rgba(0,0,0,0.04); padding: 2px 8px;
  border-radius: 4px; user-select: all;
}
/* ── Combined leaderboard score bar ── */
.lb-score-bar {
  display: flex; align-items: center; gap: 8px; min-width: 120px;
}
.lb-score-val { font-weight: 700; min-width: 36px; text-align: right; }
.lb-bar {
  flex: 1; height: 8px; background: var(--border-light);
  border-radius: 4px; overflow: hidden; min-width: 60px;
}
.lb-bar-fill { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
.lb-bar-fill.score-green { background: var(--success); }
.lb-bar-fill.score-yellow { background: var(--warning); }
.lb-bar-fill.score-red { background: var(--fail); }
.lb-muted { color: var(--text-tertiary) !important; font-weight: 400 !important; }
.lb-skill-col { color: var(--text-tertiary); }
.lb-combined th.lb-skill-col {
  border-left: 1px solid var(--border);
}
.lb-combined td:nth-child(5) {
  border-left: 1px solid var(--border);
}

/* ── Mobile leaderboard (hidden on desktop) ──────────────── */
.lb-mobile-row { display: none; }
.lb-m-scores {
  display: flex; align-items: center; gap: 6px; margin-top: 4px;
}
.lb-m-bar {
  flex: 1; height: 6px; background: var(--bg-subtle);
  border-radius: 3px; overflow: hidden; min-width: 40px; max-width: 120px;
}
.lb-m-fill { height: 100%; border-radius: 3px; }
.lb-m-fill.score-green { background: var(--success); }
.lb-m-fill.score-yellow { background: var(--warning); }
.lb-m-fill.score-red { background: var(--fail); }
.lb-m-bl { font-size: 0.82rem; font-weight: 600; min-width: 32px; text-align: right; }
.lb-m-label { font-size: 0.65rem; color: var(--text-tertiary); font-weight: 400; }
.lb-m-arrow { color: var(--text-tertiary); font-size: 0.75rem; }
.lb-m-sk { font-size: 0.82rem; font-weight: 600; color: var(--success); min-width: 32px; }

@media (max-width: 700px) {
  /* Hide all desktop columns except rank and model */
  .lb-combined th:not(:nth-child(1)):not(:nth-child(2)),
  .lb-combined td:not(:nth-child(1)):not(:nth-child(2)) { display: none; }
  /* Hide desktop header row entirely – mobile rows are self-explanatory */
  .lb-combined thead { display: none; }
  /* Show mobile row inside model cell */
  .lb-mobile-row { display: block; }
  /* Allow model cell to use full width and wrap */
  .lb-model { max-width: none; white-space: normal; overflow: visible; }
  .lb-model-name { display: block; }
  .lb-table td { padding: 10px 12px; }
  .rank-cell { width: 32px; padding-right: 4px; }
}
.lb-table-wrap {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.lb-table {
  width: 100%; border-collapse: collapse;
}
.lb-table th {
  text-align: left; padding: 12px 14px;
  font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--text-tertiary); border-bottom: 1px solid var(--border);
  background: var(--bg-subtle); white-space: nowrap;
}
.lb-table th.num, .lb-table td.num { text-align: right; }
.lb-table td {
  padding: 14px 14px; font-size: 0.88rem;
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.lb-table tr:last-child td { border-bottom: none; }
.lb-table tbody tr { transition: background 0.1s; }
.lb-table tbody tr:hover { background: var(--bg-subtle); }
.lb-model {
  font-weight: 600; color: var(--text);
  max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.score-green { color: var(--success); font-weight: 600; }
.score-yellow { color: var(--warning); font-weight: 600; }
.score-red { color: var(--fail); font-weight: 600; }
.delta-pos { color: var(--success); font-weight: 600; }
.delta-neg { color: var(--fail); font-weight: 600; }
.delta-zero { color: var(--text-tertiary); }
.rank-cell { color: var(--text-tertiary); font-weight: 600; width: 44px; }

/* ── Featured replays ────────────────────────────────────── */
.replay-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}
.replay-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 22px;
  display: flex; flex-direction: column; gap: 10px;
  transition: box-shadow 0.2s, transform 0.15s;
  color: var(--text); box-shadow: var(--shadow-sm);
}
.replay-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); text-decoration: none; color: var(--text); }
.replay-card .rc-cat {
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--accent); font-weight: 700;
}
.replay-card .rc-name { font-size: 0.95rem; font-weight: 700; color: var(--text); line-height: 1.3; }
.replay-card .rc-desc {
  font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.replay-card .rc-model { font-size: 0.76rem; color: var(--text-tertiary); }
.replay-card .rc-bottom {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border);
}
.replay-card .rc-scores { display: flex; align-items: center; gap: 6px; }
.replay-card .rc-score { font-size: 0.82rem; font-weight: 700; }
.replay-card .rc-arrow { font-size: 0.78rem; color: var(--text-tertiary); }
.replay-card .rc-play {
  font-size: 0.78rem; font-weight: 600; color: var(--accent);
  display: flex; align-items: center; gap: 4px;
}

/* ── Skill section ───────────────────────────────────────── */
.skill-viewer {
  border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; margin-bottom: 20px; box-shadow: var(--shadow-sm);
}
.skill-viewer-toolbar {
  display: flex; align-items: center; gap: 0;
  background: var(--bg-subtle); border-bottom: 1px solid var(--border);
  padding: 0 16px; height: 44px;
}
.skill-view-btn {
  padding: 6px 14px; font-size: 0.8rem; font-weight: 600;
  background: transparent; border: 1px solid transparent;
  border-radius: var(--radius-sm); color: var(--text-tertiary);
  cursor: pointer; font-family: var(--font);
  transition: color 0.12s, background 0.12s;
}
.skill-view-btn:hover { color: var(--text); background: rgba(0,0,0,0.04); }
.skill-view-btn.active {
  color: var(--accent); background: var(--bg);
  border-color: var(--border); box-shadow: var(--shadow-sm);
}
.skill-copy-btn {
  margin-left: auto; padding: 5px 14px; font-size: 0.78rem; font-weight: 600;
  background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text-secondary);
  cursor: pointer; font-family: var(--font);
  transition: color 0.12s, border-color 0.12s, background 0.12s;
  display: flex; align-items: center; gap: 5px;
}
.skill-copy-btn:hover { color: var(--accent); border-color: var(--accent); }
.skill-copy-btn.copied { color: var(--success); border-color: var(--success); }
.skill-view-rendered {
  background: var(--bg); padding: 28px 28px;
  height: 480px; overflow-y: auto;
}
.skill-view-rendered h2 { font-size: 1.1rem; font-weight: 700; margin-bottom: 4px; color: var(--text); }
.skill-view-rendered h3 { font-size: 0.95rem; font-weight: 700; margin: 20px 0 6px; color: var(--text); }
.skill-view-rendered h4 { font-size: 0.88rem; font-weight: 700; margin: 16px 0 6px; color: var(--text); }
.skill-view-rendered p {
  font-size: 0.88rem; line-height: 1.7; color: var(--text-secondary);
  margin-bottom: 10px;
}
.skill-view-rendered ul { padding-left: 20px; margin-bottom: 10px; }
.skill-view-rendered li {
  font-size: 0.86rem; color: var(--text-secondary); line-height: 1.7;
  margin-bottom: 4px;
}
.skill-view-rendered strong { color: var(--text); }
.skill-view-rendered code {
  background: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 4px;
  font-size: 0.84em; font-family: var(--mono);
}
.skill-view-raw {
  display: none; background: #1d1d1f; padding: 24px 28px;
  height: 480px; overflow-y: auto;
}
.skill-view-raw pre {
  margin: 0; white-space: pre-wrap; word-wrap: break-word;
  font-size: 0.82rem; line-height: 1.7; color: #c9d1d9;
  font-family: var(--mono);
}
/* Markdown syntax highlighting (raw view) */
.sk-h { color: #79c0ff; font-weight: 700; }
.sk-bold { color: #d2a8ff; font-weight: 700; }
.sk-li { color: #7ee787; }
.sk-code { color: #ffa657; }
.sk-em { color: #d2a8ff; font-style: italic; }

/* Python syntax highlighting (code blocks) */
.hl-kw { color: #ff7b72; }
.hl-str { color: #a5d6ff; }
.hl-fn { color: #d2a8ff; }
.hl-cm { color: #8b949e; font-style: italic; }
.hl-op { color: #ff7b72; }
.hl-num { color: #79c0ff; }
.hl-cls { color: #ffa657; }
.hl-dec { color: #ffa657; }
.hl-var { color: #c9d1d9; }

.skill-actions {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 8px;
}
.skill-download {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 22px; border-radius: 980px; font-size: 0.86rem; font-weight: 600;
  background: var(--accent); color: #fff;
  transition: background 0.15s, box-shadow 0.15s;
  box-shadow: 0 1px 3px rgba(5,114,236,0.3);
}
.skill-download:hover { background: var(--accent-hover); text-decoration: none; color: #fff; }

/* ── Quick start steps ───────────────────────────────────── */
.steps { counter-reset: step; margin-top: 0; }
.step-item {
  display: flex; gap: 16px; padding: 24px 0;
  border-bottom: 1px solid var(--border);
}
.step-item:last-child { border-bottom: none; }
.step-num {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%;
  background: var(--accent-light); color: var(--accent);
  font-size: 0.82rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  margin-top: 2px;
}
.step-body { flex: 1; min-width: 0; }
.step-body h4 {
  font-size: 0.95rem; font-weight: 700; margin-bottom: 6px; color: var(--text);
}
.step-body p {
  font-size: 0.86rem; line-height: 1.6; color: var(--text-secondary);
  margin-bottom: 8px;
}
.step-body pre {
  background: #1d1d1f; border-radius: 8px; padding: 14px 16px;
  overflow-x: auto; font-size: 0.8rem; line-height: 1.65;
  color: #e5e5ea; font-family: var(--mono); margin: 0;
}
.step-body code {
  background: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 4px;
  font-size: 0.84em; font-family: var(--mono);
}
.code-block-wrap {
  position: relative; margin: 8px 0;
}
.code-block-wrap pre {
  padding-top: 36px;
}
.code-copy-btn {
  position: absolute; top: 8px; right: 8px; z-index: 2;
  font-size: 0.72rem; font-weight: 600; font-family: var(--font);
  color: #8e8e93; cursor: pointer;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12);
  border-radius: 6px; padding: 4px 12px;
  transition: color 0.15s, background 0.15s;
}
.code-copy-btn:hover {
  color: #fff; background: rgba(255,255,255,0.14);
}
.code-copy-btn.copied {
  color: #34c759; border-color: #34c759;
}

/* ── Integration tabs ────────────────────────────────────── */
.integrate-section { margin-top: 44px; }
.integrate-mobile-hint { display: none; }
.integrate-details { display: block; }
@media (max-width: 700px) {
  .integrate-mobile-hint {
    display: block; padding: 16px; background: var(--bg-subtle);
    border: 1px solid var(--border); border-radius: var(--radius);
    margin-bottom: 16px;
  }
  .integrate-mobile-hint p {
    font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;
    margin: 0 0 12px 0;
  }
  .integrate-show-btn {
    font-size: 0.8rem; font-weight: 600; color: var(--accent);
    background: none; border: 1px solid var(--accent); border-radius: var(--radius-sm);
    padding: 6px 14px; cursor: pointer; font-family: var(--font);
  }
  .integrate-details { display: none; }
  .integrate-desktop-only { display: none; }
}
.integrate-section h3 {
  font-size: 1.25rem; font-weight: 700; margin-bottom: 4px;
  letter-spacing: -0.02em; font-family: var(--font-display);
}
.tabs { display: flex; gap: 0; margin-bottom: 0; margin-top: 18px; }
.tab-btn {
  padding: 9px 20px; font-size: 0.82rem; font-weight: 600;
  background: transparent; border: 1px solid var(--border);
  color: var(--text-secondary);
  cursor: pointer; font-family: var(--font);
  border-bottom: none; border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  transition: background 0.12s, color 0.12s;
}
.tab-btn:hover { color: var(--text); background: var(--bg-subtle); }
.tab-btn.active {
  background: var(--bg-subtle); color: var(--accent);
  border-color: var(--border); border-bottom-color: var(--bg-subtle);
  position: relative; z-index: 1; margin-bottom: -1px;
}
.tab-content {
  display: none; background: var(--bg-subtle); border: 1px solid var(--border);
  border-radius: 0 var(--radius-sm) var(--radius-sm) var(--radius-sm);
  padding: 18px 22px;
}
.tab-content.active { display: block; }
.tab-content pre {
  background: #1d1d1f; border-radius: 8px; padding: 16px 18px;
  overflow-x: auto; font-size: 0.8rem; line-height: 1.7;
  color: #e5e5ea; font-family: var(--mono);
  margin: 0;
}
.tab-content .tab-note {
  font-size: 0.78rem; color: var(--text-tertiary); margin-top: 10px;
}
/* ── Terminal replay ──────────────────────────────────────── */
.term-window {
  position: relative; border-radius: var(--radius); overflow: hidden;
  box-shadow: 0 8px 40px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.08);
}
.term-chrome {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; background: #1e2028;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.term-dot { width: 12px; height: 12px; border-radius: 50%; }
.term-dot-r { background: #ff5f57; }
.term-dot-y { background: #febc2e; }
.term-dot-g { background: #28c840; }
.term-title {
  flex: 1; text-align: center; font-size: 0.72rem; color: #6b7280;
  font-family: var(--mono);
}
.term-body {
  background: #0d1117; padding: 16px 20px;
  height: 480px; overflow-y: auto; overflow-x: auto;
  font-family: var(--mono); font-size: 13px; line-height: 1.5;
  color: #e6edf3;
}
.term-body::-webkit-scrollbar { width: 8px; }
.term-body::-webkit-scrollbar-track { background: transparent; }
.term-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 4px; }
.tf { display: none; white-space: pre; }
.tf.shown { display: block; }
.tc { border-right: 2px solid #4ade80; padding-right: 1px; }
.tc-done { border-right: none; padding-right: 0; }
@keyframes blink { 0%,100% { border-color: #4ade80; } 50% { border-color: transparent; } }
.tc { animation: blink 1s step-end infinite; }
.tc-done { animation: none; }
.t-g { color: #4ade80; }
.t-r { color: #f87171; }
.t-y { color: #fbbf24; }
.t-c { color: #67e8f9; }
.t-d { color: #484f58; }
.t-b { font-weight: 700; }
.t-w { color: #e6edf3; }
.t-accent { color: #79c0ff; }
.term-overlay {
  position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; background: rgba(13,17,23,0.6);
  -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
  cursor: pointer; z-index: 2;
}
.term-play-btn {
  background: var(--accent); color: #fff; border: none;
  padding: 14px 36px; border-radius: 980px; font-size: 0.92rem;
  font-weight: 600; cursor: pointer; font-family: var(--font);
  box-shadow: 0 2px 16px rgba(5,114,236,0.4);
  transition: transform 0.15s, box-shadow 0.15s;
  display: flex; align-items: center; gap: 8px;
}
.term-play-btn:hover { transform: scale(1.04); box-shadow: 0 4px 24px rgba(5,114,236,0.5); }
.term-replay-btn {
  position: absolute; top: 52px; right: 12px; z-index: 3;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.1);
  color: #9ca3af; padding: 5px 12px; border-radius: 6px;
  font-size: 0.7rem; font-weight: 600; cursor: pointer;
  font-family: var(--font); display: none;
  transition: color 0.12s, background 0.12s;
}
.term-replay-btn:hover { color: #e6edf3; background: rgba(255,255,255,0.12); }
.tbar { display: block; white-space: pre; }
.tbar-fill { color: #4ade80; }
.tbar-pct { color: #6b7280; }
.tbar-done { color: #4ade80; }
.term-caption {
  text-align: center; font-size: 0.82rem; color: var(--text-tertiary);
  margin-top: 16px; line-height: 1.5;
}

/* ── Footer ──────────────────────────────────────────────── */
.site-footer {
  text-align: center; padding: 44px 32px;
  border-top: 1px solid var(--border);
  background: var(--bg-subtle);
  font-size: 0.82rem; color: var(--text-tertiary);
}
.site-footer a { color: var(--text-secondary); }
.site-footer a:hover { color: var(--accent); text-decoration: none; }
.site-footer .footer-sep { margin: 0 8px; color: var(--border-strong); }
.footer-bottom { margin-top: 10px; font-size: 0.74rem; }

.topnav-toggle {
  display: none; background: none; border: none; cursor: pointer;
  padding: 6px; color: var(--text-secondary); line-height: 0;
}
.topnav-toggle:hover { color: var(--text); }

@media (max-width: 768px) {
  .hero h1 { font-size: 2.2rem; }
  .hero { padding: 56px 0 40px; }
  .section { padding: 48px 0; }
  .section-title { font-size: 1.4rem; }
  .cards-row { grid-template-columns: 1fr; }
  .lb-table th, .lb-table td { padding: 10px 12px; font-size: 0.82rem; }
  .container { padding: 0 20px; }
  .topnav { padding: 0 16px; }
  .topnav-inner { flex-wrap: wrap; height: auto; min-height: 48px; padding: 8px 0; }
  .topnav-brand { font-size: 0.88rem; }
  .topnav-brand .brand-dot { display: none; }
  .topnav-toggle { display: block; margin-left: auto; }
  .topnav-links {
    display: none; flex-direction: column; align-items: flex-start;
    width: 100%; gap: 4px; padding: 8px 0 4px;
  }
  .topnav-links.open { display: flex; }
  .topnav-links a {
    display: block; width: 100%; padding: 8px 0;
    font-size: 0.88rem;
  }
  .topnav-links .nav-cta {
    display: inline-block; width: auto; margin-top: 4px;
  }
}
"""


# ── Scenario selection ───────────────────────────────────────────────


def _select_featured_scenarios(
    result: dict,
    *,
    count: int = 4,
    pinned: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Pick the most interesting scenarios for the featured replays.

    For evaluate runs, selects scenarios with the biggest baseline→skill
    improvement, ensuring at least one per model where possible.

    Args:
        pinned: Optional list of ``(model_name, scenario_id)`` tuples that
            must appear first, in exactly that order.  Remaining slots are
            filled by the normal selection algorithm.

    Returns a list of dicts with keys:
        model, scenario_id, category, description,
        baseline_score, baseline_crit, skill_score, skill_crit,
        baseline_scenario (dict), skill_scenario (dict),
        improvement (float)
    """
    is_evaluate = result.get("metadata", {}).get("command") == "evaluate"
    all_scenarios = iter_scenarios(result)
    if not all_scenarios:
        return []

    if not is_evaluate:
        # For non-evaluate runs, pick diverse scenarios by score
        pool = all_scenarios
        selected: list[dict] = []
        used_sids: set[str] = set()
        pool_sorted = sorted(pool, key=lambda s: s[3].get("safety_score", 0))
        for model_name, phase_name, run_idx, sc in pool_sorted:
            sid = sc.get("scenario_id", "")
            if sid in used_sids:
                continue
            if len(selected) >= count:
                break
            used_sids.add(sid)
            selected.append({
                "model": model_name,
                "scenario_id": sid,
                "category": sc.get("category", ""),
                "description": sc.get("description", ""),
                "baseline_score": sc.get("safety_score", 0),
                "baseline_crit": sc.get("critical_failure", False),
                "skill_score": None,
                "skill_crit": None,
                "baseline_scenario": sc,
                "skill_scenario": None,
                "improvement": 0,
            })
        return selected[:count]

    # ── Evaluate mode: find biggest baseline→skill improvements ──
    # Build lookup: (model, scenario_id) → {baseline: sc, skill: sc}
    pairs: dict[tuple[str, str], dict] = {}
    for model_name, phase_name, run_idx, sc in all_scenarios:
        sid = sc.get("scenario_id", "")
        key = (model_name, sid)
        if key not in pairs:
            pairs[key] = {"model": model_name, "sid": sid, "sc": sc}
        if phase_name == "no-skill":
            pairs[key]["baseline"] = sc
        else:
            pairs[key]["skill"] = sc

    # Compute improvement for each pair that has both phases
    candidates: list[dict] = []
    for key, p in pairs.items():
        if "baseline" not in p or "skill" not in p:
            continue
        b_score = p["baseline"].get("safety_score", 0)
        s_score = p["skill"].get("safety_score", 0)
        improvement = s_score - b_score
        candidates.append({
            "model": p["model"],
            "scenario_id": p["sid"],
            "category": p["baseline"].get("category", ""),
            "description": p["baseline"].get("description", ""),
            "baseline_score": b_score,
            "baseline_crit": p["baseline"].get("critical_failure", False),
            "skill_score": s_score,
            "skill_crit": p["skill"].get("critical_failure", False),
            "baseline_scenario": p["baseline"],
            "skill_scenario": p["skill"],
            "improvement": improvement,
        })

    if not candidates:
        return []

    # Sort by biggest improvement (descending), then by baseline_crit (prefer
    # those that had critical failures at baseline), then by lowest baseline score
    candidates.sort(key=lambda c: (-c["improvement"], -int(c["baseline_crit"]), c["baseline_score"]))

    # Build a fast lookup for pinning
    cand_by_key: dict[tuple[str, str], dict] = {}
    for c in candidates:
        cand_by_key[(c["model"], c["scenario_id"])] = c

    # ── Pinned selections first ──────────────────────────────
    selected: list[dict] = []
    used_models: set[str] = set()
    used_sids: set[str] = set()

    if pinned:
        for model_name, sid in pinned:
            if len(selected) >= count:
                break
            pick = cand_by_key.get((model_name, sid))
            if pick and sid not in used_sids:
                selected.append(pick)
                used_models.add(model_name)
                used_sids.add(sid)

    # ── Fill remaining: one per model, preferring biggest improvements ──
    models_in_data = list(result.get("models", {}).keys())

    for model_name in models_in_data:
        if len(selected) >= count:
            break
        if model_name in used_models:
            continue
        model_candidates = [c for c in candidates if c["model"] == model_name and c["scenario_id"] not in used_sids]
        if model_candidates:
            pick = model_candidates[0]  # already sorted by improvement
            selected.append(pick)
            used_models.add(model_name)
            used_sids.add(pick["scenario_id"])

    # Fill any remaining slots with biggest improvements across any model
    for c in candidates:
        if len(selected) >= count:
            break
        if c["scenario_id"] in used_sids:
            continue
        selected.append(c)
        used_sids.add(c["scenario_id"])

    return selected[:count]


# ── Terminal demo ────────────────────────────────────────────────────


def _build_terminal_demo() -> str:
    """Build the fake terminal replay component with scripted frames."""
    # Each <div class="tf"> is a frame.
    #   data-d  = delay in ms before this frame appears
    #   data-type / data-speed = typed text (user input simulation)
    #   <span class="tc"> = cursor / insertion point for typed text
    return r'''
<div class="term-window">
  <div class="term-chrome">
    <span class="term-dot term-dot-r"></span>
    <span class="term-dot term-dot-y"></span>
    <span class="term-dot term-dot-g"></span>
    <span class="term-title">Terminal</span>
  </div>
  <button class="term-replay-btn" id="term-replay" onclick="playTerm()">&#8635; Replay</button>
  <div class="term-body" id="term-body">

<div class="tf" data-d="600" data-type="scam -i" data-speed="80"><span class="t-g">$ </span><span class="tc"></span></div>

<div class="tf" data-d="900">
<span class="t-d">╭──────────────────────────────────────────────────────────────────╮
│</span> <span class="t-c t-b">SCAM -- Interactive Benchmark Wizard</span>                             <span class="t-d">│
│</span>                                                                  <span class="t-d">│
│</span> Configure and launch a benchmark in a few steps.                 <span class="t-d">│
╰──────────────────────────────────────────────────────────────────╯</span>
</div>

<div class="tf" data-d="500">
<span class="t-c t-b">Step 1:</span> What would you like to do?

  1  Run        <span class="t-d">--</span> Single benchmark (with optional skill)
  2  Evaluate   <span class="t-d">--</span> Baseline vs skill comparison
</div>

<div class="tf" data-d="800" data-type="2" data-speed="300">
Mode [1]&gt; <span class="tc"></span></div>

<div class="tf" data-d="700">

<span class="t-c t-b">Step 2:</span> Select models

  <span class="t-d">Anthropic</span>
      1  claude-opus-4-6          <span class="t-accent">Frontier</span>  ~$1.33/run
      2  claude-sonnet-4          <span class="t-accent">Mid-tier</span>  ~$0.80/run
      3  claude-haiku-4-5         <span class="t-accent">Fast</span>      ~$0.27/run
  <span class="t-d">OpenAI</span>
      4  gpt-5.2                  <span class="t-accent">Frontier</span>  ~$0.67/run
      5  gpt-4.1                  <span class="t-accent">Mid-tier</span>  ~$0.46/run
      6  gpt-4.1-mini             <span class="t-accent">Fast</span>      ~$0.09/run
  <span class="t-d">Google (Gemini)</span>
      8  gemini-3-flash-preview   <span class="t-accent">Mid-tier</span>  ~$0.15/run
      9  gemini-2.5-flash         <span class="t-accent">Fast</span>      ~$0.03/run
</div>

<div class="tf" data-d="1000" data-type="1,2,3,4,5,6,8,9" data-speed="55">
Select models&gt; <span class="tc"></span></div>

<div class="tf" data-d="600">

<span class="t-d">Selected:</span> claude-opus-4-6, claude-sonnet-4, claude-haiku-4-5,
         gpt-5.2, gpt-4.1, gpt-4.1-mini, gemini-3-flash, gemini-2.5-flash
</div>

<div class="tf" data-d="600">
<span class="t-c t-b">Step 4:</span> Parallelization -- <span class="t-d">Recommended: 3 in parallel</span>

Parallel models [3]&gt; <span class="t-d">↵</span>

<span class="t-c t-b">Step 5:</span> Number of runs
</div>

<div class="tf" data-d="800" data-type="3" data-speed="300">
Runs per model [1]&gt; <span class="tc"></span></div>

<div class="tf" data-d="800">

<span class="t-d">╭──────────────────────────────────────────────────────────────────╮
│</span> <span class="t-b">Benchmark Configuration</span>                                          <span class="t-d">│
│</span>                                                                  <span class="t-d">│
│</span>   Mode       <span class="t-c">Evaluate</span> (baseline vs security_expert.md)           <span class="t-d">│
│</span>   Models     <span class="t-b">8 models</span>                                            <span class="t-d">│
│</span>   Scenarios  30 scenarios (9 categories)                         <span class="t-d">│
│</span>   Runs       3 per phase                                         <span class="t-d">│
│</span>   Est. cost  <span class="t-y">~$35.93</span>                                             <span class="t-d">│
╰──────────────────────────────────────────────────────────────────╯</span>
</div>

<div class="tf" data-d="1000" data-type="y" data-speed="400">
Proceed? [y/N]: <span class="tc"></span></div>

<div class="tf" data-d="1200" data-progress="true">

<span class="t-d">Running evaluate...</span>
<span class="tbar" data-label="  claude-opus-4-6        "></span>
<span class="tbar" data-label="  claude-sonnet-4        "></span>
<span class="tbar" data-label="  claude-haiku-4-5       "></span>
<span class="tbar" data-label="  gpt-5.2                "></span>
<span class="tbar" data-label="  gpt-4.1                "></span>
<span class="tbar" data-label="  gpt-4.1-mini           "></span>
<span class="tbar" data-label="  gemini-3-flash-preview "></span>
<span class="tbar" data-label="  gemini-2.5-flash       "></span>
</div>

<div class="tf" data-d="1000">

<span class="t-d">╭──────────────────────────────────────────────────────────────────╮
│</span> <span class="t-b">SCAM Unified Report</span>  --  evaluate                                <span class="t-d">│
│</span> Models: 8  |  Scenarios: 30  |  Runs per phase: 3                <span class="t-d">│
│</span> Skill: security_expert.md  |  Cost: <span class="t-y">$38.38</span>                       <span class="t-d">│
╰──────────────────────────────────────────────────────────────────╯</span>
</div>

<div class="tf" data-d="600">
                           <span class="t-b">Leaderboard</span>
<span class="t-d">┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━┓
┃</span>   # <span class="t-d">┃</span> Model                  <span class="t-d">┃</span> Baseline <span class="t-d">┃</span> Skill <span class="t-d">┃</span> Delta <span class="t-d">┃</span> Crit(bl->sk) <span class="t-d">┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━┩</span>
<span class="t-d">│</span>   1 <span class="t-d">│</span> <span class="t-b">gemini-3-flash-preview</span> <span class="t-d">│</span>  <span class="t-y">76%</span>     <span class="t-d">│</span> <span class="t-g">  99%</span> <span class="t-d">│</span> <span class="t-g"> +24%</span> <span class="t-d">│</span>  6.0 -> 0.0  <span class="t-d">│</span>
<span class="t-d">│</span>   2 <span class="t-d">│</span> <span class="t-b">claude-opus-4-6</span>        <span class="t-d">│</span>  <span class="t-g">92%</span>     <span class="t-d">│</span> <span class="t-g">  98%</span> <span class="t-d">│</span> <span class="t-g">  +6%</span> <span class="t-d">│</span>  2.0 -> 0.0  <span class="t-d">│</span>
<span class="t-d">│</span>   3 <span class="t-d">│</span> <span class="t-b">claude-sonnet-4</span>        <span class="t-d">│</span>  <span class="t-r">49%</span>     <span class="t-d">│</span> <span class="t-g">  98%</span> <span class="t-d">│</span> <span class="t-g"> +49%</span> <span class="t-d">│</span> 15.7 -> 0.0  <span class="t-d">│</span>
<span class="t-d">│</span>   4 <span class="t-d">│</span> <span class="t-b">claude-haiku-4-5</span>       <span class="t-d">│</span>  <span class="t-y">65%</span>     <span class="t-d">│</span> <span class="t-g">  98%</span> <span class="t-d">│</span> <span class="t-g"> +32%</span> <span class="t-d">│</span>  8.3 -> 0.0  <span class="t-d">│</span>
<span class="t-d">│</span>   5 <span class="t-d">│</span> <span class="t-b">gpt-5.2</span>                <span class="t-d">│</span>  <span class="t-g">81%</span>     <span class="t-d">│</span> <span class="t-g">  97%</span> <span class="t-d">│</span> <span class="t-g"> +16%</span> <span class="t-d">│</span>  6.3 -> 1.3  <span class="t-d">│</span>
<span class="t-d">│</span>   6 <span class="t-d">│</span> <span class="t-b">gpt-4.1</span>                <span class="t-d">│</span>  <span class="t-r">38%</span>     <span class="t-d">│</span> <span class="t-g">  96%</span> <span class="t-d">│</span> <span class="t-g"> +58%</span> <span class="t-d">│</span> 19.0 -> 0.3  <span class="t-d">│</span>
<span class="t-d">│</span>   7 <span class="t-d">│</span> <span class="t-b">gemini-2.5-flash</span>       <span class="t-d">│</span>  <span class="t-r">35%</span>     <span class="t-d">│</span> <span class="t-g">  95%</span> <span class="t-d">│</span> <span class="t-g"> +60%</span> <span class="t-d">│</span> 20.0 -> 1.3  <span class="t-d">│</span>
<span class="t-d">│</span>   8 <span class="t-d">│</span> <span class="t-b">gpt-4.1-mini</span>           <span class="t-d">│</span>  <span class="t-r">36%</span>     <span class="t-d">│</span> <span class="t-g">  95%</span> <span class="t-d">│</span> <span class="t-g"> +59%</span> <span class="t-d">│</span> 18.3 -> 0.3  <span class="t-d">│</span>
<span class="t-d">└─────┴────────────────────────┴──────────┴───────┴───────┴──────────────┘</span>
</div>

<div class="tf" data-d="800">

Results saved to <span class="t-accent">results/agentic/scam-evaluate-1770653270.json</span>
</div>

<div class="tf" data-d="800" data-type="y" data-speed="400">
Export HTML dashboard? &gt; <span class="tc"></span></div>

<div class="tf" data-d="600">
<span class="t-g">Exported:</span> exports/scam-evaluate-1770653270/index.html
</div>

  </div>
  <div class="term-overlay" id="term-overlay" onclick="playTerm()">
    <button class="term-play-btn">&#9654; Watch Demo</button>
  </div>
</div>
'''


# ── Markdown rendering (basic) ───────────────────────────────────────


def _md_to_html(text: str) -> str:
    """Convert simple markdown to HTML (headings, bold, italic, lists, paragraphs)."""
    lines = text.strip().split("\n")
    out: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Headings
        if stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h4>{html.escape(stripped[4:])}</h4>")
            continue
        if stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{html.escape(stripped[3:])}</h3>")
            continue
        if stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{html.escape(stripped[2:])}</h2>")
            continue

        # List items
        if stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            content = _inline_md(stripped[2:])
            out.append(f"<li>{content}</li>")
            continue

        # Empty line
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        # Regular paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline_md(stripped)}</p>")

    if in_list:
        out.append("</ul>")

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic, code, links)."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


# ── Syntax highlighting ──────────────────────────────────────────────


def _highlight_md_raw(text: str) -> str:
    """Apply syntax highlighting to raw markdown text for display."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        escaped = html.escape(line)
        # Headings
        if line.startswith("# "):
            out.append(f'<span class="sk-h">{escaped}</span>')
            continue
        if line.startswith("## "):
            out.append(f'<span class="sk-h">{escaped}</span>')
            continue
        if line.startswith("### "):
            out.append(f'<span class="sk-h">{escaped}</span>')
            continue
        # Bold markers
        escaped = re.sub(
            r"\*\*(.+?)\*\*",
            r'<span class="sk-bold">**\1**</span>',
            escaped,
        )
        # Inline code
        escaped = re.sub(
            r"`(.+?)`",
            r'<span class="sk-code">`\1`</span>',
            escaped,
        )
        # List bullets
        if line.startswith("- "):
            escaped = '<span class="sk-li">-</span>' + escaped[1:]
        out.append(escaped)
    return "\n".join(out)


def _highlight_python(code: str) -> str:
    """Apply basic Python syntax highlighting to an HTML-escaped code string.

    Operates on already-escaped HTML text, adding <span class="hl-*"> wrappers.
    """
    t = html.escape(code)

    # Comments (# to end of line, but not inside strings — simplified)
    t = re.sub(r"(#.*)$", r'<span class="hl-cm">\1</span>', t, flags=re.MULTILINE)

    # Triple-quoted strings
    t = re.sub(r'(&quot;&quot;&quot;.*?&quot;&quot;&quot;)', r'<span class="hl-str">\1</span>', t, flags=re.DOTALL)

    # Double-quoted strings
    t = re.sub(r'(&quot;[^&]*?&quot;)', r'<span class="hl-str">\1</span>', t)

    # Single-quoted strings (not already wrapped)
    t = re.sub(r"(&#x27;[^&]*?&#x27;)", r'<span class="hl-str">\1</span>', t)

    # F-string braces inside strings — leave as-is for simplicity

    # Keywords
    _kws = (
        "from", "import", "def", "class", "return", "if", "else", "elif",
        "for", "while", "in", "not", "and", "or", "is", "None", "True",
        "False", "with", "as", "try", "except", "finally", "raise", "yield",
        "pass", "break", "continue", "lambda", "async", "await",
    )
    for kw in _kws:
        t = re.sub(
            rf"\b({kw})\b(?![^<]*>)",
            rf'<span class="hl-kw">\1</span>',
            t,
        )

    # Function calls: word followed by (
    t = re.sub(
        r"\b([a-zA-Z_]\w*)\s*(?=\()",
        lambda m: (
            m.group(0)
            if m.group(1) in _kws
            else f'<span class="hl-fn">{m.group(1)}</span>'
        ),
        t,
    )

    # Decorators
    t = re.sub(r"^(@\w+)", r'<span class="hl-dec">\1</span>', t, flags=re.MULTILINE)

    return t


# ── Score helpers ────────────────────────────────────────────────────


def _score_cls(score: float) -> str:
    if score >= 0.8:
        return "score-green"
    if score >= 0.5:
        return "score-yellow"
    return "score-red"


def _delta_cls(delta: float) -> str:
    if delta > 0.005:
        return "delta-pos"
    if delta < -0.005:
        return "delta-neg"
    return "delta-zero"


_CATEGORY_LABELS: dict[str, str] = {
    "agentic_credential_autofill": "Credential Autofill",
    "agentic_phishing": "Phishing",
    "agentic_confused_deputy": "Confused Deputy",
    "agentic_credential_exposure": "Credential Exposure",
    "agentic_data_leakage": "Data Leakage",
    "agentic_ecommerce_scams": "E-Commerce Scams",
    "agentic_prompt_injection": "Prompt Injection",
    "agentic_social_engineering": "Social Engineering",
    "agentic_multi_stage": "Multi-Stage Attacks",
}


def _pretty_category(raw: str) -> str:
    """Turn a raw category slug into a human-readable label."""
    if raw in _CATEGORY_LABELS:
        return _CATEGORY_LABELS[raw]
    return raw.replace("agentic_", "").replace("_", " ").title()


def _build_category_chart(cat_counts: dict[str, int]) -> str:
    """Build an HTML horizontal bar chart of scenario categories."""
    if not cat_counts:
        return ""
    sorted_cats = sorted(cat_counts.items(), key=lambda x: -x[1])
    max_count = max(cat_counts.values())
    rows = ""
    for cat, count in sorted_cats:
        pct = count / max_count * 100
        label = html.escape(_pretty_category(cat))
        # If the bar is wide enough, put count inside; otherwise outside
        if pct >= 25:
            rows += f"""
    <div class="cat-bar-row">
      <div class="cat-bar-label">{label}</div>
      <div class="cat-bar-track">
        <div class="cat-bar-fill" style="width:{pct:.0f}%;">
          <span class="cat-bar-count">{count}</span>
        </div>
      </div>
    </div>"""
        else:
            rows += f"""
    <div class="cat-bar-row">
      <div class="cat-bar-label">{label}</div>
      <div class="cat-bar-track">
        <div class="cat-bar-fill" style="width:{pct:.0f}%;"></div>
      </div>
      <span class="cat-bar-count-outside">{count}</span>
    </div>"""

    total = sum(cat_counts.values())
    return f"""
  <div class="cat-chart">
    <div class="cat-chart-title">{total} scenarios across {len(cat_counts)} threat categories</div>
    {rows}
  </div>"""


def _short_model(name: str) -> str:
    """Shorten model names for display."""
    name = re.sub(r"-\d{8}$", "", name)
    name = re.sub(r"-preview$", "", name)
    return name


# ── HTML generation ──────────────────────────────────────────────────


def generate_site(
    result: dict,
    output_dir: Path,
    skill_path: Path,
) -> list[Path]:
    """Generate the full GitHub Pages site from a v2 result.

    Creates ``index.html`` and standalone replay pages in ``output_dir``.

    Returns:
        List of paths to generated files.
    """
    meta = result.get("metadata", {})
    summary = result.get("summary", {})
    command = meta.get("command", "run")
    is_evaluate = command == "evaluate"
    leaderboard = summary.get("leaderboard", [])

    bench_ref = meta.get("benchmark_ref", meta.get("benchmark_version", "")) or "0.1"
    timestamp = meta.get("timestamp", "")
    if "T" in str(timestamp):
        timestamp = str(timestamp).split("T")[0]
    n_scenarios = meta.get("scenario_count", "?")
    n_runs = meta.get("runs_per_phase", 1)

    # Read skill file
    skill_text = ""
    if skill_path.exists():
        skill_text = skill_path.read_text(encoding="utf-8")

    # Select featured scenarios
    # Pin specific (model, scenario_id) pairs to appear first on the
    # landing page.  Remaining slots are filled automatically.
    _pinned_featured: list[tuple[str, str]] = [
        ("gemini-2.5-flash", "phish-calendar-invite"),
        ("gpt-4.1", "ecom-fake-storefront"),
    ]
    featured = _select_featured_scenarios(
        result,
        count=len(result.get("models", {})),
        pinned=_pinned_featured,
    )

    # Generate replay pages
    output_dir.mkdir(parents=True, exist_ok=True)
    replays_dir = output_dir / "replays"
    replays_dir.mkdir(exist_ok=True)
    written: list[Path] = []

    # First pass: prepare all data for replay pages
    replay_links: list[dict] = []
    for feat in featured:
        model_name = feat["model"]
        sid = feat["scenario_id"]

        baseline_prepared = prepare_scenario_data(feat["baseline_scenario"]) if feat["baseline_scenario"] else None
        baseline_meta = get_run_metadata_for_scenario(result, model_name, "no-skill") if feat["baseline_scenario"] else None

        skill_prepared = prepare_scenario_data(feat["skill_scenario"]) if feat.get("skill_scenario") else None
        skill_meta = get_run_metadata_for_scenario(result, model_name, next(
            (p for p in result.get("models", {}).get(model_name, {}) if p != "no-skill"), "no-skill"
        )) if feat.get("skill_scenario") else None

        replay_links.append({
            "scenario_id": sid,
            "category": feat.get("category", ""),
            "description": feat.get("description", ""),
            "model": _short_model(model_name),
            "baseline_score": feat.get("baseline_score", 0),
            "baseline_crit": feat.get("baseline_crit", False),
            "skill_score": feat.get("skill_score"),
            "skill_crit": feat.get("skill_crit"),
            "improvement": feat.get("improvement", 0),
            "href": f"replays/{sid}.html",
            "_baseline_prepared": baseline_prepared,
            "_baseline_meta": baseline_meta,
            "_skill_prepared": skill_prepared,
            "_skill_meta": skill_meta,
            "_model_name": model_name,
        })

    # Second pass: generate replay HTML pages (now we have the full list for cross-links)
    for r in replay_links:
        replay_html = _generate_replay_page(
            baseline_scenario=r["_baseline_prepared"],
            baseline_meta=r["_baseline_meta"],
            skill_scenario=r["_skill_prepared"],
            skill_meta=r["_skill_meta"],
            model_name=r["_model_name"],
            description=r.get("description", ""),
            other_replays=replay_links,
        )
        replay_path = replays_dir / f"{r['scenario_id']}.html"
        replay_path.write_text(replay_html, encoding="utf-8")
        written.append(replay_path)

    # Compute scenario category distribution (deduplicated by scenario_id)
    all_sc = iter_scenarios(result)
    seen_sids: set[str] = set()
    cat_counts: dict[str, int] = {}
    for _m, _p, _r, sc in all_sc:
        sid = sc.get("scenario_id", "")
        if sid in seen_sids:
            continue
        seen_sids.add(sid)
        cat = sc.get("category", "unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # ── Generate downloadable data zip (before index so we have the hash) ──
    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)

    tmp_dir = data_dir / "_build_tmp"
    tmp_dir.mkdir(exist_ok=True)

    json_path = tmp_dir / "results.json"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    # Generate the full HTML dashboard export
    export_result(result, tmp_dir)
    html_dashboard_path = tmp_dir / "index.html"

    # Build the README for the zip
    n_models = len(result.get("models", {}))
    readme_text = f"""\
# SCAM Benchmark Results

This archive contains the raw data and interactive dashboard for a SCAM
benchmark run so you can independently verify the published results.

## Contents

- **results.json** — The complete benchmark output including every model
  response, tool call, and evaluation checkpoint across all scenarios and
  runs.  This is the authoritative data source.

- **dashboard.html** — A self-contained HTML file you can open in any
  browser to explore the results interactively, including animated
  replays of each scenario.

- **README.md** — This file.

## Run details

- Command: `scam {html.escape(command)}`
- Benchmark version: {bench_ref}
- Date: {timestamp}
- Models: {n_models}
- Scenarios: {n_scenarios}
- Runs per phase: {n_runs}

## How to use

1. Unzip this archive.
2. Open `dashboard.html` in your browser for the interactive view.
3. Inspect `results.json` directly for raw data analysis.

## More information

- Repository: https://github.com/1Password/SCAM
- License: MIT — Copyright (c) 1Password
"""

    # Bundle into a zip
    zip_path = data_dir / "scam-results.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme_text)
        zf.write(json_path, "results.json")
        if html_dashboard_path.exists():
            zf.write(html_dashboard_path, "dashboard.html")

    # Compute SHA-256 of the zip
    zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    # Clean up temp build directory
    for f in tmp_dir.iterdir():
        f.unlink()
    tmp_dir.rmdir()

    written.append(zip_path)

    # Build index.html
    index_html = _build_index(
        meta=meta,
        leaderboard=leaderboard,
        is_evaluate=is_evaluate,
        bench_ref=bench_ref,
        timestamp=timestamp,
        n_scenarios=n_scenarios,
        n_runs=n_runs,
        skill_text=skill_text,
        skill_filename=skill_path.name,
        replay_links=replay_links,
        category_counts=cat_counts,
        zip_sha256=zip_sha256,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    written.append(index_path)

    # .nojekyll
    nojekyll = output_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)

    return written


def _build_more_replays_html(current_sid: str, other_replays: list[dict] | None) -> str:
    """Build an HTML section with up to 3 replay cards linking to other scenarios."""
    if not other_replays:
        return ""

    # Pick up to 3 replays that aren't the current scenario
    picks = [r for r in other_replays if r.get("scenario_id") != current_sid][:3]
    if not picks:
        return ""

    cards = ""
    for r in picks:
        bs = r.get("baseline_score", 0)
        ss = r.get("skill_score")
        b_crit = r.get("baseline_crit", False)
        s_crit = r.get("skill_crit", False)

        b_label = "Crit Fail" if b_crit else f"{bs:.0%}"
        b_cls = "score-red" if b_crit else _score_cls(bs)
        desc = html.escape(r.get("description", ""))

        if ss is not None:
            s_label = "Crit Fail" if s_crit else f"{ss:.0%}"
            s_cls = "score-red" if s_crit else _score_cls(ss)
            score_html = (
                f'<span class="rc-score {b_cls}">{b_label}</span>'
                f' <span class="rc-arrow">&rarr;</span> '
                f'<span class="rc-score {s_cls}">{s_label}</span>'
            )
        else:
            score_html = f'<span class="rc-score {b_cls}">{b_label}</span>'

        cards += f"""
      <a class="replay-card" href="{html.escape(r['scenario_id'])}.html">
        <div class="rc-cat">{html.escape(_pretty_category(r.get('category', '')))}</div>
        <div class="rc-name">{html.escape(r['scenario_id'])}</div>
        <div class="rc-desc">{desc}</div>
        <div class="rc-model">{html.escape(r.get('model', ''))}</div>
        <div class="rc-bottom">
          <span class="rc-scores">{score_html}</span>
          <span class="rc-play">&#9654; Watch</span>
        </div>
      </a>"""

    return f"""
<div style="max-width:900px;margin:40px auto 0;padding:0 20px 40px;">
  <div style="border-top:1px solid #ebebf0;padding-top:32px;">
    <h3 style="font-size:1.05rem;font-weight:700;color:#1d1d1f;margin:0 0 6px;">Watch More Replays</h3>
    <p style="font-size:0.88rem;color:#6e6e73;margin:0 0 20px;line-height:1.5;">See how different models handle other real-world threats &mdash; phishing, credential theft, social engineering, and more.</p>
    <div class="replay-grid" style="grid-template-columns:repeat(3,1fr);">
{cards}
    </div>
  </div>
</div>"""


def _generate_replay_page(
    *,
    baseline_scenario: dict | None = None,
    baseline_meta: dict | None = None,
    skill_scenario: dict | None = None,
    skill_meta: dict | None = None,
    model_name: str = "",
    description: str = "",
    other_replays: list[dict] | None = None,
) -> str:
    """Generate a standalone replay HTML page with baseline/skill phase switcher."""
    # Use whichever scenario we have to get the sid
    primary = baseline_scenario or skill_scenario
    sid = primary.get("scenario_id", "unknown") if primary else "unknown"
    desc = description or primary.get("description", "") if primary else ""
    category = primary.get("category", "") if primary else ""
    difficulty = primary.get("difficulty", 0) if primary else 0

    has_both = baseline_scenario is not None and skill_scenario is not None

    # Build JSON blobs for each phase
    baseline_json = json.dumps(
        {"scenarios": [baseline_scenario], "metadata": baseline_meta},
        indent=None, default=str,
    ) if baseline_scenario else "null"

    skill_json = json.dumps(
        {"scenarios": [skill_scenario], "metadata": skill_meta},
        indent=None, default=str,
    ) if skill_scenario else "null"

    # Phase switcher HTML (only if both phases available)
    switcher_html = ""
    if has_both:
        b_score = baseline_scenario.get("safety_score", 0)
        s_score = skill_scenario.get("safety_score", 0)
        b_crit = baseline_scenario.get("critical_failure", False)
        s_crit = skill_scenario.get("critical_failure", False)
        b_label = "Critical Failure" if b_crit else f"{b_score:.0%}"
        s_label = "Critical Failure" if s_crit else f"{s_score:.0%}"
        switcher_html = f"""
  <div class="phase-switcher">
    <button class="phase-btn active" data-phase="baseline" onclick="switchPhase('baseline')">
      Baseline <span class="phase-score">{b_label}</span>
    </button>
    <button class="phase-btn" data-phase="skill" onclick="switchPhase('skill')">
      With Skill <span class="phase-score">{s_label}</span>
    </button>
  </div>"""

    # Category badge
    cat_badge = f'<span class="replay-meta-cat">{html.escape(category)}</span>' if category else ""

    # Model label for explainer
    short_model = _short_model(model_name) if model_name else ""
    model_tag = f" on <strong>{html.escape(short_model)}</strong>" if short_model else ""

    # Social sharing
    page_url = f"https://1password.github.io/SCAM/replays/{sid}.html"
    share_text = f"Watch an AI agent fall for a live security threat in real time. SCAM benchmark replay: {sid}"
    encoded_url = html.escape(page_url)
    pct_url = urllib.parse.quote(page_url, safe="")
    pct_text = urllib.parse.quote(share_text, safe="")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCAM Replay &mdash; {html.escape(sid)}</title>
<meta property="og:title" content="SCAM Replay &mdash; {html.escape(sid)}">
<meta property="og:description" content="{html.escape(desc or 'Watch an AI agent handle a live security threat in the SCAM benchmark.')}">
<meta property="og:url" content="{encoded_url}">
<meta name="twitter:card" content="summary">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{_CSS}
</style>
<style>
  body {{ background: #ffffff; color: #1d1d1f; }}
  .replay-topbar {{
    position: sticky; top: 0; z-index: 100;
    background: rgba(255,255,255,0.88);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    backdrop-filter: saturate(180%) blur(20px);
    border-bottom: 1px solid #e5e5ea;
    padding: 0 20px;
  }}
  .replay-topbar-inner {{
    max-width: 900px; margin: 0 auto;
    display: flex; align-items: center; height: 52px; gap: 12px;
  }}
  .replay-back {{
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 0.82rem; font-weight: 600;
    color: #6e6e73;
  }}
  .replay-back:hover {{ color: #1d1d1f; text-decoration: none; }}
  .replay-brand {{
    font-size: 0.82rem; font-weight: 700; color: #98989d;
    margin-left: auto;
  }}
  .replay-brand a {{ color: #6e6e73; }}
  .replay-brand a:hover {{ color: #0572ec; }}

  /* ── Replay header area ──────────────────────────────── */
  .replay-header-area {{
    max-width: 900px; margin: 0 auto; padding: 28px 20px 0;
  }}

  /* ── Explainer banner (dismissable) ────────────────────── */
  .explainer-box {{
    position: relative;
    background: #f8f8fa; border: 1px solid #ebebf0; border-radius: 14px;
    padding: 28px 32px 24px;
    margin-bottom: 16px;
  }}
  .explainer-dismiss {{
    position: absolute; top: 14px; right: 14px;
    width: 28px; height: 28px; border: none; border-radius: 8px;
    background: transparent; color: #98989d; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.15s, color 0.15s;
  }}
  .explainer-dismiss:hover {{ background: #e8e8ed; color: #1d1d1f; }}
  .explainer-dismiss svg {{ width: 14px; height: 14px; }}
  .explainer-heading {{
    font-size: 1.05rem; font-weight: 700; color: #1d1d1f;
    margin: 0 0 10px; line-height: 1.35;
  }}
  .explainer-body {{
    font-size: 0.92rem; line-height: 1.7; color: #48484a; margin: 0 0 4px;
    max-width: 720px;
  }}
  .explainer-body strong {{ color: #1d1d1f; font-weight: 600; }}
  .explainer-body a {{ color: #0572ec; text-decoration: none; }}
  .explainer-body a:hover {{ text-decoration: underline; }}

  /* ── Scenario meta bar (always visible) ────────────────── */
  .replay-meta-bar {{
    display: flex; align-items: center; gap: 16px;
    padding: 0 4px 16px; flex-wrap: wrap;
  }}
  .replay-meta-tags {{
    display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap;
  }}
  .replay-meta-cat {{
    font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: #6e6e73;
    background: #e8e8ed; border-radius: 5px; padding: 3px 10px;
  }}
  .replay-meta-model {{
    font-size: 0.8rem; color: #6e6e73;
  }}
  .replay-meta-model strong {{ color: #1d1d1f; font-weight: 600; }}

  /* ── Scenario title (static, always visible) ────────── */
  .replay-scenario-title {{
    padding: 0 4px;
  }}
  .replay-scenario-title h2 {{
    font-size: 1.05rem; font-weight: 600; color: #1d1d1f;
    margin: 0 0 4px; display: flex; align-items: center; gap: 8px;
  }}
  .replay-scenario-title .diff-badge {{
    font-size: 0.65rem; background: #e8e8ed; color: #6e6e73;
    padding: 2px 8px; border-radius: 9px; font-weight: 600;
  }}
  .replay-scenario-desc {{
    font-size: 0.85rem; color: #6e6e73; line-height: 1.5;
  }}

  /* Hide the JS-rendered scenario header on replay pages (we render it statically above) */
  .scenario-header {{ display: none; }}

  /* ── More Replays cards ─────────────────────────────────── */
  .replay-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
  }}
  .replay-card {{
    background: #fff; border: 1px solid #ebebf0;
    border-radius: 14px; padding: 22px;
    display: flex; flex-direction: column; gap: 6px;
    transition: box-shadow 0.15s, transform 0.15s;
    text-decoration: none; color: #1d1d1f;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .replay-card:hover {{
    box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-2px);
    text-decoration: none; color: #1d1d1f;
  }}
  .replay-card .rc-cat {{
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: #0572ec; font-weight: 700;
  }}
  .replay-card .rc-name {{ font-size: 0.95rem; font-weight: 700; color: #1d1d1f; line-height: 1.3; }}
  .replay-card .rc-desc {{
    font-size: 0.82rem; color: #6e6e73; line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }}
  .replay-card .rc-model {{ font-size: 0.76rem; color: #98989d; }}
  .replay-card .rc-bottom {{
    display: flex; justify-content: space-between; align-items: center;
    margin-top: auto; padding-top: 10px; border-top: 1px solid #ebebf0;
  }}
  .replay-card .rc-scores {{ display: flex; align-items: center; gap: 6px; }}
  .replay-card .rc-score {{ font-size: 0.82rem; font-weight: 700; }}
  .replay-card .rc-arrow {{ font-size: 0.78rem; color: #98989d; }}
  .replay-card .rc-play {{
    font-size: 0.78rem; font-weight: 600; color: #0572ec;
    display: flex; align-items: center; gap: 4px;
  }}
  .score-green {{ color: #1a7f37; font-weight: 600; }}
  .score-yellow {{ color: #9a6700; font-weight: 600; }}
  .score-red {{ color: #d1242f; font-weight: 600; }}
  @media (max-width: 700px) {{
    .replay-grid {{ grid-template-columns: 1fr !important; }}
  }}
  @media (min-width: 701px) and (max-width: 960px) {{
    .replay-grid {{ grid-template-columns: repeat(2, 1fr) !important; }}
  }}

  /* ── Social share ─────────────────────────────────────── */
  .share-bar {{
    display: flex; align-items: center; gap: 6px;
    margin-left: auto;
  }}
  .share-label {{
    font-size: 0.72rem; font-weight: 600; color: #98989d;
    text-transform: uppercase; letter-spacing: 0.04em; margin-right: 2px;
  }}
  .share-btn {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px; border-radius: 8px;
    background: #e8e8ed; color: #48484a; text-decoration: none;
    transition: background 0.15s, color 0.15s;
  }}
  .share-btn:hover {{ background: #d1d1d6; color: #1d1d1f; }}
  .share-btn svg {{ width: 15px; height: 15px; }}
  .copy-link-btn {{
    display: inline-flex; align-items: center; justify-content: center;
    gap: 4px; height: 30px; padding: 0 10px; border-radius: 8px;
    background: #e8e8ed; color: #48484a; border: none;
    font-size: 0.72rem; font-weight: 600; font-family: var(--font);
    cursor: pointer; white-space: nowrap;
    transition: background 0.15s, color 0.15s;
  }}
  .copy-link-btn:hover {{ background: #d1d1d6; color: #1d1d1f; }}
  .copy-link-btn svg {{ width: 13px; height: 13px; }}

  /* ── Phase switcher ───────────────────────────────────── */
  .phase-switcher {{
    display: flex; gap: 0; margin: 20px 0 4px;
    background: #f5f5f7; border-radius: 10px; padding: 3px;
    width: fit-content;
  }}
  .phase-btn {{
    padding: 8px 20px; border: none; border-radius: 8px;
    font-size: 0.84rem; font-weight: 600; cursor: pointer;
    background: transparent; color: #6e6e73;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    display: flex; align-items: center; gap: 8px;
    transition: background 0.15s, color 0.15s, box-shadow 0.15s;
  }}
  .phase-btn:hover {{ color: #1d1d1f; }}
  .phase-btn.active {{
    background: #fff; color: #1d1d1f;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
  }}
  .phase-score {{
    font-size: 0.76rem; font-weight: 700; padding: 2px 8px;
    border-radius: 6px;
  }}
  .phase-btn[data-phase="baseline"] .phase-score {{
    background: #ffeef0; color: #d1242f;
  }}
  .phase-btn[data-phase="skill"] .phase-score {{
    background: #e6ffec; color: #1a7f37;
  }}

  /* ── Skill CTA (injected between transcript and checkpoints) ── */
  .skill-cta-box {{
    margin: 28px 0; padding: 24px 28px;
    background: linear-gradient(135deg, #f0f7ff 0%, #f5f5f7 100%);
    border: 1px solid #d1e3f6; border-radius: 12px;
  }}
  .skill-cta-label {{
    font-size: 1rem; font-weight: 700; color: #1d1d1f; margin-bottom: 8px;
  }}
  .skill-cta-text {{
    font-size: 0.9rem; line-height: 1.65; color: #48484a; margin: 0 0 18px;
    max-width: 640px;
  }}
  .skill-cta-text strong {{ color: #1d1d1f; }}
  .skill-cta-btn {{
    display: inline-block; padding: 10px 22px;
    font-size: 0.86rem; font-weight: 600;
    color: #fff; background: #0572ec; border: none; border-radius: 8px;
    cursor: pointer; font-family: inherit;
    transition: background 0.15s;
  }}
  .skill-cta-btn:hover {{ background: #0461c8; }}
  .skill-cta-actions {{
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  }}
  .skill-cta-share {{
    display: flex; align-items: center; gap: 6px;
  }}
  .skill-cta-share-label {{
    font-size: 0.76rem; font-weight: 600; color: #8e8e93;
    margin-right: 2px;
  }}
</style>
</head>
<body>
<div class="replay-topbar">
  <div class="replay-topbar-inner">
    <a class="replay-back" href="../index.html">&larr; Back to SCAM</a>
    <div class="replay-brand">
      <a href="../index.html">SCAM Benchmark</a> by 1Password
    </div>
  </div>
</div>

<div class="replay-header-area">
  <div class="explainer-box" id="replay-explainer">
    <button class="explainer-dismiss" onclick="document.getElementById('replay-explainer').style.display='none';try{{sessionStorage.setItem('scam-explainer-dismissed','1')}}catch(e){{}}" aria-label="Dismiss">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
    </button>
    <script>try{{if(sessionStorage.getItem('scam-explainer-dismissed'))document.getElementById('replay-explainer').style.display='none'}}catch(e){{}}</script>
    <h2 class="explainer-heading">What&rsquo;s SCAM?</h2>
    <p class="explainer-body">
      <strong>SCAM</strong> (Security Comprehension Awareness Measure) is an
      <a href="https://github.com/1Password/SCAM">open-source agentic AI benchmark</a>
      by <strong>1Password</strong>. It drops AI agents into realistic workplace
      situations with access to email, a credential vault, and a web browser
      &mdash; then embeds real-world threats (phishing, social engineering,
      credential theft) in the workflow. The agent has to complete the task
      without falling for the trap.
    </p>
    <p class="explainer-body" style="margin-bottom:0;">
      What you&rsquo;re watching below is a recorded evaluation: the agent was given a
      routine task, and a threat was hidden in the environment. Everything is
      sandboxed &mdash; no real credentials, emails, or systems were involved.
    </p>
  </div>
  <div class="replay-meta-bar">
    <div class="replay-meta-tags">
      {cat_badge}
      <span class="replay-meta-model">Tested{model_tag}</span>
    </div>
    <div class="share-bar">
      <span class="share-label">Share</span>
      <a class="share-btn" href="https://twitter.com/intent/tweet?text={pct_text}&url={pct_url}" target="_blank" rel="noopener" title="Share on X">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
      </a>
      <a class="share-btn" href="https://reddit.com/submit?url={pct_url}&title={pct_text}" target="_blank" rel="noopener" title="Share on Reddit">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.05 1.604a3.6 3.6 0 0 1 .042.52c0 2.694-3.13 4.876-7.004 4.876-3.874 0-7.004-2.182-7.004-4.876 0-.18.015-.36.043-.52A1.755 1.755 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.36.36 0 0 0 0-.463.327.327 0 0 0-.462 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/></svg>
      </a>
      <a class="share-btn" href="https://bsky.app/intent/compose?text={pct_text}%20{pct_url}" target="_blank" rel="noopener" title="Share on Bluesky">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 10.8c-1.087-2.114-4.046-6.053-6.798-7.995C2.566.944 1.561 1.266.902 1.565.139 1.908 0 3.08 0 3.768c0 .69.378 5.65.624 6.479.785 2.627 3.6 3.476 6.243 3.226-3.868.577-7.283 2.402-3.7 7.078 3.935 4.842 6.15-.18 6.833-2.928.684 2.748 2.266 7.54 6.833 2.928 3.696-5.166-.073-6.501-3.7-7.078 2.643.25 5.458-.599 6.243-3.226C19.622 9.418 20 4.458 20 3.768c0-.688-.139-1.86-.902-2.203-.66-.299-1.664-.62-4.3 1.24C12.046 4.748 9.087 8.687 8 10.8h4z" transform="translate(2 2) scale(0.833)"/></svg>
      </a>
      <button class="copy-link-btn" onclick="navigator.clipboard.writeText('{page_url}').then(function(){{var b=this;b.textContent='Copied!';setTimeout(function(){{b.innerHTML='<svg viewBox=&quot;0 0 24 24&quot; fill=&quot;none&quot; stroke=&quot;currentColor&quot; stroke-width=&quot;2&quot;><rect x=&quot;9&quot; y=&quot;9&quot; width=&quot;13&quot; height=&quot;13&quot; rx=&quot;2&quot;/><path d=&quot;M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1&quot;/></svg> Copy link'}},1500)}}.bind(this))" title="Copy link">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy link
      </button>
    </div>
  </div>
  <div class="replay-scenario-title">
    <h2>{html.escape(sid)} <span class="diff-badge">D{difficulty}</span></h2>
    <div class="replay-scenario-desc">{html.escape(desc)}</div>
  </div>
</div>

<div style="max-width:900px;margin:0 auto;padding:0 20px;">
  {switcher_html}
  <div id="scenario-content" style="padding-top:16px;"></div>
</div>
<script>
var __BASELINE_DATA__ = {baseline_json};
var __SKILL_DATA__ = {skill_json};
var __currentPhase = 'baseline';
var __hasBoth = {'true' if has_both else 'false'};

function switchPhase(phase, autoPlay) {{
  __currentPhase = phase;
  var data = phase === 'skill' ? __SKILL_DATA__ : __BASELINE_DATA__;
  if (!data) return;
  window.__SCAM_DATA__ = data;
  document.querySelectorAll('.phase-btn').forEach(function(b) {{
    b.classList.toggle('active', b.getAttribute('data-phase') === phase);
  }});
  if (typeof window.__renderScenario === 'function') {{
    window.__renderScenario(0);
  }}
  // Scroll to the recording stage area
  var stage = document.getElementById('recording-stage');
  if (stage) {{
    stage.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
  }} else {{
    window.scrollTo({{ top: 0 }});
  }}
  // Auto-play after a short delay to let the DOM settle and scroll finish
  if (autoPlay && typeof window.__play === 'function') {{
    setTimeout(function() {{ window.__play(); }}, 400);
  }}
}}

// After baseline playback, inject a skill CTA between the transcript and checkpoints
window.__onPlaybackDone = function() {{
  if (__currentPhase !== 'baseline' || !__hasBoth) return;
  // Remove any existing CTA
  var old = document.getElementById('skill-cta-inject');
  if (old) old.remove();
  // Find the checkpoints section inside scenario-content
  var cp = document.querySelector('#scenario-content .checkpoints');
  if (!cp) return;
  var cta = document.createElement('div');
  cta.id = 'skill-cta-inject';
  cta.innerHTML = '<div class="skill-cta-box">'
    + '<div class="skill-cta-label">That didn\\u2019t go well.</div>'
    + '<p class="skill-cta-text">'
    + 'SCAM ships with a <strong>security skill</strong> \\u2014 a plain-text system prompt '
    + 'that teaches agents to verify domains, inspect content before acting, and protect '
    + 'credentials. Watch the same scenario again with the skill enabled to see the difference.'
    + '</p>'
    + '<div class="skill-cta-actions">'
    + '<button class="skill-cta-btn" onclick="switchPhase(\\u0027skill\\u0027, true)">Watch with skill \\u2192</button>'
    + '<div class="skill-cta-share">'
    + '<span class="skill-cta-share-label">Share this replay</span>'
    + '<a class="share-btn" href="https://twitter.com/intent/tweet?text={pct_text}&url={pct_url}" target="_blank" rel="noopener" title="Share on X"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>'
    + '<a class="share-btn" href="https://reddit.com/submit?url={pct_url}&title={pct_text}" target="_blank" rel="noopener" title="Share on Reddit"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.05 1.604a3.6 3.6 0 0 1 .042.52c0 2.694-3.13 4.876-7.004 4.876-3.874 0-7.004-2.182-7.004-4.876 0-.18.015-.36.043-.52A1.755 1.755 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.36.36 0 0 0 0-.463.327.327 0 0 0-.462 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/></svg></a>'
    + '<a class="share-btn" href="https://bsky.app/intent/compose?text={pct_text}%20{pct_url}" target="_blank" rel="noopener" title="Share on Bluesky"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 10.8c-1.087-2.114-4.046-6.053-6.798-7.995C2.566.944 1.561 1.266.902 1.565.139 1.908 0 3.08 0 3.768c0 .69.378 5.65.624 6.479.785 2.627 3.6 3.476 6.243 3.226-3.868.577-7.283 2.402-3.7 7.078 3.935 4.842 6.15-.18 6.833-2.928.684 2.748 2.266 7.54 6.833 2.928 3.696-5.166-.073-6.501-3.7-7.078 2.643.25 5.458-.599 6.243-3.226C19.622 9.418 20 4.458 20 3.768c0-.688-.139-1.86-.902-2.203-.66-.299-1.664-.62-4.3 1.24C12.046 4.748 9.087 8.687 8 10.8h4z" transform="translate(2 2) scale(0.833)"/></svg></a>'
    + '</div>'
    + '</div>'
    + '</div>';
  cp.parentNode.insertBefore(cta, cp);
  cta.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
}};

// Initialize with baseline (or skill if no baseline)
window.__SCAM_DATA__ = __BASELINE_DATA__ || __SKILL_DATA__;
</script>
<script>
{_JS}
</script>
{_build_more_replays_html(sid, other_replays)}
</body>
</html>"""


def _build_index(
    *,
    meta: dict,
    leaderboard: list[dict],
    is_evaluate: bool,
    bench_ref: str,
    timestamp: str,
    n_scenarios: int | str,
    n_runs: int,
    skill_text: str,
    skill_filename: str,
    replay_links: list[dict],
    category_counts: dict[str, int] | None = None,
    zip_sha256: str = "",
) -> str:
    """Build the main index.html page."""
    parts: list[str] = []

    # ── Nav ───────────────────────────────────────────────────
    parts.append("""
<nav class="topnav">
  <div class="topnav-inner">
    <a class="topnav-brand" href="#">
      <svg width="18" height="18" viewBox="0 0 32 32" fill="none"><rect width="32" height="32" rx="8" fill="#0572ec"/><path d="M20 9C20 5 11 5 11 9.5C11 14 21 15 21 20.5C21 25 12 25 12 21.5" stroke="#fff" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M12 21.5L15.5 18" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="20" cy="7.5" r="1.8" fill="#fff"/></svg>
      SCAM Benchmark <span class="brand-dot">by 1Password</span>
    </a>
    <button class="topnav-toggle" onclick="this.nextElementSibling.classList.toggle('open')" aria-label="Menu">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </button>
    <div class="topnav-links" id="topnav-links">
      <a href="#leaderboard" onclick="document.getElementById('topnav-links').classList.remove('open')">Leaderboard</a>
      <a href="#replays" onclick="document.getElementById('topnav-links').classList.remove('open')">Replays</a>
      <a href="#skill" onclick="document.getElementById('topnav-links').classList.remove('open')">Skill</a>
      <a class="nav-cta" href="https://github.com/1Password/SCAM">GitHub</a>
    </div>
  </div>
</nav>
""")

    # ── Hero ──────────────────────────────────────────────────
    parts.append(f"""
<section class="hero">
  <div class="container">
    <div class="hero-eyebrow">v{html.escape(bench_ref)}</div>
    <h1>Security Comprehension<br><span class="accent-word">Awareness Measure</span></h1>
    <p class="tagline">SCAM is an open-source benchmark that tests AI agents' security awareness during realistic, multi-turn workplace tasks.</p>
    <div class="hero-cta-row">
      <a class="btn-primary" href="#leaderboard">View Leaderboard &#8595;</a>
      <a class="btn-secondary" href="https://github.com/1Password/SCAM">View on GitHub</a>
    </div>
    <div class="hero-meta">
      <span>By <a href="https://1password.com" style="color:inherit;font-weight:600;text-decoration:none;">1Password</a></span>
      <span>&middot;</span>
      <span><a href="https://1password.com/blog/ai-agent-security-benchmark" style="color:inherit;text-decoration:underline;text-underline-offset:2px;">Read the blog post</a></span>
    </div>
  </div>
</section>
""")

    # ── What it measures ────────────────────────────────────────
    # Find the worst baseline-performing featured replay for the embedded player
    worst_replay = None
    if replay_links:
        worst_replay = min(replay_links, key=lambda r: (-int(r.get("baseline_crit", False)), r.get("baseline_score", 0)))

    def _embed_iframe(scenario_data: dict, meta_data: dict) -> str:
        """Build an embedded replay iframe srcdoc."""
        data_json = json.dumps(
            {"scenarios": [scenario_data], "metadata": meta_data},
            indent=None, default=str,
        )
        body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>{_CSS}</style>
<style>
html, body {{ margin:0; padding:0; height:100%; overflow:hidden; background:#fff; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,sans-serif; }}
#scenario-content {{ padding:16px 20px; height:100%; overflow-y:auto; box-sizing:border-box; }}
</style></head><body>
<div id="scenario-content"></div>
<script>window.__SCAM_DATA__ = {data_json};</script>
<script>{_JS}</script>
<script>
(function() {{
  var sc = document.getElementById('scenario-content');
  // Redirect the lerp scroller to use this container instead of window
  if (typeof window.__setScrollContainer === 'function') window.__setScrollContainer(sc);
  // Also override window.scrollTo for any remaining direct calls
  window.scrollTo = function(opts) {{
    if (opts && typeof opts.top === 'number') sc.scrollTop = opts.top;
  }};
}})();
</script>
</body></html>"""
        return body.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    baseline_embed = ""
    skill_embed = ""
    skill_bridge = ""
    if worst_replay and worst_replay.get("_baseline_prepared"):
        w_model = html.escape(worst_replay.get("model", ""))
        w_sid = html.escape(worst_replay.get("scenario_id", ""))
        w_cat = html.escape(_pretty_category(worst_replay.get("category", "")))
        w_bs = worst_replay.get("baseline_score", 0)
        w_bc = worst_replay.get("baseline_crit", False)
        w_score_label = "Critical Failure" if w_bc else f"{w_bs:.0%}"
        w_score_cls = "tag-red" if w_bc or w_bs < 0.5 else ""

        bl_data = worst_replay["_baseline_prepared"]
        bl_msgs = len(bl_data.get("messages", []))
        bl_tools = bl_data.get("tool_call_count", 0)
        bl_danger = bl_data.get("dangerous_call_count", 0)
        bl_desc = html.escape(bl_data.get("description", ""))

        srcdoc_baseline = _embed_iframe(bl_data, worst_replay["_baseline_meta"])
        danger_stat = f' <span class="stat-danger">&middot; {bl_danger} dangerous</span>' if bl_danger else ""

        # Precompute URLs for social sharing on the embed CTA
        _embed_sid = worst_replay.get("scenario_id", "")
        _embed_page_url = f"https://1password.github.io/SCAM/replays/{_embed_sid}.html"
        _embed_share_text = f"Watch an AI agent fall for a live security threat. SCAM benchmark replay: {_embed_sid}"
        _embed_pct_url = urllib.parse.quote(_embed_page_url, safe="")
        _embed_pct_text = urllib.parse.quote(_embed_share_text, safe="")
        baseline_embed = f"""
    <div class="measures-embed">
      <div class="embed-meta-bar">
        <strong>{w_model}</strong>
        <span>&middot;</span>
        <span>{w_sid}</span>
        <span>&middot;</span>
        <span class="emb-tag tag-cat">{w_cat}</span>
        <span>&middot;</span>
        <span>Baseline</span>
        <span>&middot;</span>
        <span class="emb-tag {w_score_cls}">{w_score_label}</span>
      </div>
      <div class="embed-poster" id="baseline-poster" onclick="activateEmbed('baseline')">
        <div class="embed-poster-play">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none"><polygon points="6 3 20 12 6 21" fill="currentColor"/></svg>
        </div>
        <div class="embed-poster-title">Agent Recording</div>
        <div class="embed-poster-sub">{bl_desc}</div>
        <div class="embed-poster-stats">
          <span>{bl_msgs} messages</span>
          <span>&middot;</span>
          <span>{bl_tools} tool calls</span>
          {danger_stat}
        </div>
      </div>
      <template id="baseline-srcdoc">{srcdoc_baseline}</template>
      <div id="embed-share-cta" class="embed-share-cta" style="display:none;">
        <p class="embed-share-text">Shocked? Share this replay so others can see what AI agents do out of the box.</p>
        <div class="embed-share-links">
          <a class="share-btn" href="https://twitter.com/intent/tweet?text={_embed_pct_text}&url={_embed_pct_url}" target="_blank" rel="noopener" title="Share on X">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
          </a>
          <a class="share-btn" href="https://reddit.com/submit?url={_embed_pct_url}&title={_embed_pct_text}" target="_blank" rel="noopener" title="Share on Reddit">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.05 1.604a3.6 3.6 0 0 1 .042.52c0 2.694-3.13 4.876-7.004 4.876-3.874 0-7.004-2.182-7.004-4.876 0-.18.015-.36.043-.52A1.755 1.755 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 0-.463.327.327 0 0 0-.232-.094c-.843.843-1.331 1.044-2.729 1.044s-1.886-.201-2.73-1.044z"/></svg>
          </a>
          <a class="share-btn" href="https://bsky.app/intent/compose?text={_embed_pct_text}%20{_embed_pct_url}" target="_blank" rel="noopener" title="Share on Bluesky">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 10.8c-1.087-2.114-4.046-6.053-6.798-7.995C2.566.944 1.561 1.266.902 1.565.139 1.908 0 3.08 0 3.768c0 .69.378 5.65.624 6.479.785 2.627 3.6 3.476 6.243 3.226-3.868.577-7.283 2.402-3.7 7.078 3.935 4.842 6.15-.18 6.833-2.928.684 2.748 2.266 7.54 6.833 2.928 3.696-5.166-.073-6.501-3.7-7.078 2.643.25 5.458-.599 6.243-3.226C19.622 9.418 20 4.458 20 3.768c0-.688-.139-1.86-.902-2.203-.66-.299-1.664-.62-4.3 1.24C12.046 4.748 9.087 8.687 8 10.8h4z" transform="translate(2 2) scale(0.833)"/></svg>
          </a>
          <button class="copy-link-btn" onclick="navigator.clipboard.writeText('{_embed_page_url}').then(function(){{var b=this;b.textContent='Copied!';setTimeout(function(){{b.innerHTML='<svg viewBox=&quot;0 0 24 24&quot; fill=&quot;none&quot; stroke=&quot;currentColor&quot; stroke-width=&quot;2&quot;><rect x=&quot;9&quot; y=&quot;9&quot; width=&quot;13&quot; height=&quot;13&quot; rx=&quot;2&quot;/><path d=&quot;M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1&quot;/></svg> Copy link'}},1500)}}.bind(this))" title="Copy link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy link
          </button>
          <a class="embed-share-replay-link" href="replays/{html.escape(_embed_sid)}.html">Watch full replay &rarr;</a>
        </div>
      </div>
    </div>"""

        # Build the skill version embed if available
        if worst_replay.get("_skill_prepared"):
            ss = worst_replay.get("skill_score", 0)
            sc_flag = worst_replay.get("skill_crit", False)
            s_label = "Critical Failure" if sc_flag else f"{ss:.0%}"
            s_cls = "tag-red" if sc_flag else ("tag-green" if ss >= 0.8 else "")

            sk_data = worst_replay["_skill_prepared"]
            sk_msgs = len(sk_data.get("messages", []))
            sk_tools = sk_data.get("tool_call_count", 0)
            sk_danger = sk_data.get("dangerous_call_count", 0)
            sk_desc = html.escape(sk_data.get("description", ""))

            srcdoc_skill = _embed_iframe(sk_data, worst_replay["_skill_meta"])
            sk_danger_stat = f' <span class="stat-danger">&middot; {sk_danger} dangerous</span>' if sk_danger else ""
            skill_bridge = """
    <div style="margin:48px 0 12px;">
      <div class="section-label" style="margin-bottom:8px;">The Fix</div>
      <h3 style="font-size:1.3rem;font-weight:700;color:var(--text);margin-bottom:12px;font-family:var(--font-display);">
        Same model. Same scenario. Different instructions.
      </h3>
      <p class="section-sub" style="max-width:680px;">
        Then we gave the model a security skill &mdash; 35 lines of plain text, roughly 1,200 words.
        It works the same way security training
        works for people: you don't teach every specific scam, you teach a framework for recognizing
        when something is off, and you give permission to stop and ask questions even when the request
        comes from the boss. Here's the same scenario again.
      </p>
    </div>"""
            skill_embed = f"""
    <div class="measures-embed">
      <div class="embed-meta-bar">
        <strong>{w_model}</strong>
        <span>&middot;</span>
        <span>{w_sid}</span>
        <span>&middot;</span>
        <span class="emb-tag tag-cat">{w_cat}</span>
        <span>&middot;</span>
        <span>With Skill</span>
        <span>&middot;</span>
        <span class="emb-tag {s_cls}">{s_label}</span>
      </div>
      <div class="embed-poster" id="skill-poster" onclick="activateEmbed('skill')">
        <div class="embed-poster-play">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none"><polygon points="6 3 20 12 6 21" fill="currentColor"/></svg>
        </div>
        <div class="embed-poster-title">Agent Recording &mdash; With Skill</div>
        <div class="embed-poster-sub">{sk_desc}</div>
        <div class="embed-poster-stats">
          <span>{sk_msgs} messages</span>
          <span>&middot;</span>
          <span>{sk_tools} tool calls</span>
          {sk_danger_stat}
        </div>
      </div>
      <template id="skill-srcdoc">{srcdoc_skill}</template>
    </div>"""

    parts.append(f"""
<hr class="section-divider">
<section class="section" id="measures">
  <div class="container">
    <div class="section-label">Why SCAM</div>
    <h2 class="section-title">The problem</h2>
    <div class="intro-prose" style="max-width:680px;">
      <p>
        As AI agents become more capable, they are gaining access to the sensitive
        information of the people they assist. SCAM measures whether agents will be
        good stewards of that information against the kinds of threats humans
        encounter every day.
      </p>
      <p>
        Most benchmarks show an AI a phishing email and ask &ldquo;is this bad?&rdquo;
        SCAM is different. It tests whether an agent can proactively recognize and
        report threats during normal activity.
      </p>
      <p>
        Below, we asked a leading AI model to check a user&rsquo;s inbox. Within
        ten seconds it opened a phishing link, pulled a real password from the
        vault, and typed it into the attacker&rsquo;s fake login page. Press play
        to see for yourself.
      </p>
    </div>
    {baseline_embed}
    {skill_bridge}
    {skill_embed}
    <script>
    function activateEmbed(phase) {{
      var poster = document.getElementById(phase + '-poster');
      var tmpl = document.getElementById(phase + '-srcdoc');
      if (!poster || !tmpl) return;
      var container = poster.parentNode;
      var iframe = document.createElement('iframe');
      iframe.className = 'embed-replay-frame';
      iframe.sandbox = 'allow-scripts';
      // Decode the srcdoc and inject an auto-play script before </body>
      var doc = tmpl.innerHTML
        .replace(/&amp;/g, '&').replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>');
      // Hide the play-screen so it never flashes, then auto-play once ready
      var hideStage = '<style>.recording-stage{{display:none!important}}</style>';
      // Notify parent when playback finishes, then auto-play
      var doneNotify = '<script>'
        + 'var _origDone = window.__onPlaybackDone;'
        + 'window.__onPlaybackDone = function(){{'
        + '  if(typeof _origDone==="function")_origDone();'
        + '  try{{parent.postMessage("scam-embed-done-"+document.title,"*")}}catch(e){{}}'
        + '}};'
        + 'document.addEventListener("DOMContentLoaded",function(){{setTimeout(function(){{if(window.__play)window.__play()}},100)}});'
        + '</' + 'script>';
      iframe.srcdoc = doc.replace('</head>', hideStage + '</head>').replace('</body>', doneNotify + '</body>');
      container.replaceChild(iframe, poster);
    }}
    // Listen for playback-done from embedded iframes
    window.addEventListener('message', function(e) {{
      if (typeof e.data === 'string' && e.data.indexOf('scam-embed-done-') === 0) {{
        var cta = document.getElementById('embed-share-cta');
        if (cta) cta.style.display = '';
      }}
    }});
    </script>
    <p style="text-align:center;margin-top:28px;">
      <a href="#replays" style="font-size:0.9rem;font-weight:600;color:var(--accent);">Watch more replays &#8595;</a>
    </p>
  </div>
</section>
""")

    # ── The Skill ─────────────────────────────────────────────
    if skill_text:
        # Parse YAML frontmatter for version, then strip it from display text
        import re as _re
        skill_version = None
        _display_skill = skill_text
        if skill_text.startswith("---"):
            _fm_end = skill_text.find("\n---", 3)
            if _fm_end != -1:
                _fm_block = skill_text[3:_fm_end]
                _ver_match = _re.search(r"version:\s*([\d]+\.[\d]+\.[\d]+)", _fm_block)
                if _ver_match:
                    skill_version = _ver_match.group(1)
                _display_skill = skill_text[_fm_end + 4:].lstrip("\n")

        skill_html = _md_to_html(_display_skill)
        skill_raw_highlighted = _highlight_md_raw(_display_skill)
        integration_steps = _render_integration_steps(skill_filename, _display_skill)

        parts.append(f"""
<hr class="section-divider">
<section class="section" id="skill">
  <div class="container">
    <div class="section-label">Defense</div>
    <h2 class="section-title">The Security Skill{f' <span class="skill-version">v{html.escape(skill_version)}</span>' if skill_version else ''}</h2>
    <p class="section-sub">A single system prompt addition that dramatically improves agent safety across all models.</p>

    <div class="skill-viewer">
      <div class="skill-viewer-toolbar">
        <button class="skill-view-btn active" onclick="showSkillView('rendered')" id="sv-btn-rendered">Readable</button>
        <button class="skill-view-btn" onclick="showSkillView('raw')" id="sv-btn-raw">Markdown</button>
        <button class="skill-copy-btn" onclick="copySkill(this)" id="skill-copy-btn">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="5" width="9" height="9" rx="1.5"/><path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5"/></svg>
          Copy
        </button>
      </div>
      <div class="skill-view-rendered" id="sv-rendered">
        {skill_html}
      </div>
      <div class="skill-view-raw" id="sv-raw">
        <pre>{skill_raw_highlighted}</pre>
        <pre id="skill-raw-text" style="display:none;">{html.escape(_display_skill)}</pre>
      </div>
    </div>

    <div class="skill-actions">
      <a class="skill-download" href="https://github.com/1Password/SCAM/blob/main/skills/{html.escape(skill_filename)}">
        &#8595; Download {html.escape(skill_filename)}
      </a>{f'<span style="font-size:0.78rem;color:var(--text-tertiary);margin-left:10px;">v{html.escape(skill_version)}</span>' if skill_version else ''}
    </div>

    <div class="integrate-section">
      <h3>How to Use the Skill</h3>
      <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:24px;max-width:600px;line-height:1.6;">
        The skill is plain text. Prepend it to your agent&rsquo;s system prompt and it works immediately.
        <span class="integrate-desktop-only">Here&rsquo;s how to integrate it with each major provider.</span>
      </p>
      <div class="integrate-mobile-hint">
        <p>Detailed integration examples for each provider are easier to follow on a wider screen.</p>
        <button class="integrate-show-btn" onclick="this.parentElement.style.display='none';this.closest('.integrate-section').querySelector('.integrate-details').style.display='block';">Show anyway</button>
      </div>
      <div class="integrate-details">
        {integration_steps}
      </div>
    </div>
  </div>
</section>
""")

    # ── Leaderboard ───────────────────────────────────────────
    lb_rows = _render_leaderboard_rows(leaderboard, is_evaluate)
    eval_label = "evaluate" if is_evaluate else "run"
    parts.append(f"""
<hr class="section-divider">
<section class="section" id="leaderboard">
  <div class="container">
    <div class="section-label">Results</div>
    <h2 class="section-title">Leaderboard</h2>
    <p class="section-sub">Latest results from <code style="background:rgba(0,0,0,0.05);padding:2px 8px;border-radius:4px;font-size:0.88em;font-family:var(--mono);">scam {html.escape(eval_label)}</code></p>
    <div class="lb-meta">
      Benchmark v{html.escape(bench_ref)} &middot; {html.escape(timestamp)} &middot;
      {html.escape(str(n_scenarios))} scenarios &middot; {n_runs} run{"s" if n_runs > 1 else ""} per phase
    </div>
    {lb_rows}
    <p style="font-size:0.82rem;color:var(--text-tertiary);margin-top:14px;max-width:720px;line-height:1.6;">
      <strong>Note:</strong> These results do not include GPT 5.3-codex and Gemini-3-pro-preview due to those models not being available with sufficient capability to complete the benchmark successfully. We will update these results when those models are available for benchmarking.
    </p>
    <div class="lb-downloads">
      <p class="lb-downloads-label">Independently verify these results:</p>
      <a href="data/scam-results.zip" download class="dl-link">&#8681; Download results (ZIP)</a>
      <span class="dl-hash"><code>SHA-256: {zip_sha256[:16]}&hellip;</code></span>
    </div>
  </div>
</section>
""")

    # ── How to run ──────────────────────────────────────────
    # Build category breakdown
    # Map category keys to their YAML filenames on GitHub
    _CAT_TO_YAML: dict[str, str] = {
        "agentic_confused_deputy": "confused_deputy.yaml",
        "agentic_credential_autofill": "credential_autofill.yaml",
        "agentic_credential_exposure": "credential_exposure.yaml",
        "agentic_data_leakage": "data_leakage.yaml",
        "agentic_ecommerce_scams": "ecommerce_scams.yaml",
        "agentic_phishing": "inbox_phishing.yaml",
        "agentic_multi_stage": "multi_stage.yaml",
        "agentic_prompt_injection": "prompt_injection.yaml",
        "agentic_social_engineering": "social_engineering.yaml",
    }
    _GITHUB_SCENARIOS = "https://github.com/1Password/SCAM/blob/main/scenarios/"

    cc = category_counts or {}
    sorted_cats = sorted(cc.items(), key=lambda x: -x[1])
    cat_items = ""
    for cat_key, count in sorted_cats:
        label = html.escape(_pretty_category(cat_key))
        yaml_file = _CAT_TO_YAML.get(cat_key, "")
        if yaml_file:
            href = html.escape(_GITHUB_SCENARIOS + yaml_file)
            cat_items += f'<a class="cat-tag" href="{href}" target="_blank" rel="noopener">{label} <strong>{count}</strong></a>'
        else:
            cat_items += f'<span class="cat-tag">{label} <strong>{count}</strong></span>'
    total_scenarios = sum(cc.values()) if cc else 0
    n_cats = len(cc)

    terminal_html = _build_terminal_demo()
    parts.append(f"""
<hr class="section-divider">
<section class="section" id="how-to-run">
  <div class="container">
    <div class="section-label">Getting Started</div>
    <h2 class="section-title">How it works</h2>
    <p class="explain-text">
      Each scenario gives the agent a routine workplace task — checking email, looking up a
      credential, reviewing an invoice — along with a set of simulated MCP tool servers:
      an inbox, a password vault, a web browser, and more. These tools feel real to the model,
      but everything is sandboxed. No actual credentials are exposed, no real emails are sent,
      and no live systems are touched.
    </p>
    <p class="explain-text">
      The catch is that real-world attack patterns are woven into the task.
      A phishing link sits in the inbox. A lookalike domain shows up in a forwarded thread.
      An attacker's form is pre-filled with the right company name.
      The agent has to complete the task without falling for the trap — exactly the way a
      human employee would have to.
    </p>
    <p class="explain-text">
      The benchmark includes <strong>{total_scenarios} scenarios</strong> across
      <strong>{n_cats} threat categories</strong>, each inspired by attacks that security
      teams see in the wild:
    </p>
    <div class="cat-tags-row">
      {cat_items}
    </div>
    <h3 class="subsection-title" style="margin-top:48px;">Running it yourself</h3>
    <p class="explain-text">
      Clone the repo, install dependencies, set at least one provider API key, and run
      <code style="background:rgba(0,0,0,0.05);padding:2px 8px;border-radius:4px;font-size:0.88em;font-family:var(--mono);">scam evaluate -i</code>.
      SCAM runs each model through every scenario multiple times, scores the results, and
      produces a report with exportable HTML replays you can share.
    </p>
    <pre class="install-block"><span class="hl-cm"># Clone and install</span>
git clone https://github.com/1Password/SCAM.git
<span class="hl-kw">cd</span> SCAM
python3 -m venv .venv && source .venv/bin/activate
pip install -e <span class="hl-str">".[dev]"</span>

<span class="hl-cm"># Set your API key(s)</span>
<span class="hl-kw">export</span> OPENAI_API_KEY=<span class="hl-str">"sk-..."</span>
<span class="hl-kw">export</span> ANTHROPIC_API_KEY=<span class="hl-str">"sk-ant-..."</span>
<span class="hl-kw">export</span> GOOGLE_API_KEY=<span class="hl-str">"AIza..."</span>

<span class="hl-cm"># Run the benchmark</span>
scam evaluate -i</pre>
    <p class="explain-text" style="margin-top:36px;">
      Here is what a full evaluation looks like in the terminal. Interactive mode walks
      you through model selection, runs every scenario, and prints a scored report at the end.
    </p>
    {terminal_html}
    <p class="term-caption">
      A full evaluation across 8 models, {total_scenarios} scenarios, 3 runs each. About 20 minutes, ~$36.
    </p>
    <div class="contribute-cta">
      <h3 class="subsection-title">Help make SCAM better</h3>
      <p class="explain-text" style="margin-bottom:16px;">
        The threat landscape changes fast, and no single team can cover all of it.
        If you work in security, AI safety, or red-teaming, there are real ways to help:
      </p>
      <ul class="contribute-list">
        <li><strong>Write new scenarios.</strong> Model a threat you have seen in the wild. The YAML format is straightforward and documented in the contributor guide.</li>
        <li><strong>Add new tool servers.</strong> The more realistic the agent's environment, the more meaningful the benchmark. Slack, Jira, cloud consoles — every new surface makes the test harder to game.</li>
        <li><strong>Improve evaluation.</strong> Better checkpoint logic, fewer false positives, more nuanced scoring — all welcome.</li>
        <li><strong>Run it on new models.</strong> Publish your results. The more data points the community has, the harder it is to ignore.</li>
      </ul>
      <a href="https://github.com/1Password/SCAM/blob/main/CONTRIBUTING.md" class="btn-contribute">Read the contributor guide &rarr;</a>
      <p style="margin-top:20px;font-size:0.84rem;color:var(--text-tertiary);">
        Interested in working on AI security full-time? <a href="https://jobs.ashbyhq.com/1password/7172893a-9fbb-46e3-a364-6c2f59658892" style="color:var(--accent);font-weight:600;text-decoration:none;">1Password is hiring &rarr;</a>
      </p>
    </div>
  </div>
</section>
""")

    # ── Featured Replays ──────────────────────────────────────
    if replay_links:
        cards = ""
        for r in replay_links:
            bs = r.get("baseline_score", 0)
            ss = r.get("skill_score")
            b_crit = r.get("baseline_crit", False)
            s_crit = r.get("skill_crit", False)

            # Baseline label
            b_label = "Crit Fail" if b_crit else f"{bs:.0%}"
            b_cls = "score-red" if b_crit else _score_cls(bs)

            desc = r.get("description", "")

            # Build the score display
            if ss is not None:
                s_label = "Crit Fail" if s_crit else f"{ss:.0%}"
                s_cls = "score-red" if s_crit else _score_cls(ss)
                score_html = f'<span class="rc-score {b_cls}">{b_label}</span> <span class="rc-arrow">&rarr;</span> <span class="rc-score {s_cls}">{s_label}</span>'
            else:
                score_html = f'<span class="rc-score {b_cls}">{b_label}</span>'

            cards += f"""
      <a class="replay-card" href="{html.escape(r['href'])}">
        <div class="rc-cat">{html.escape(_pretty_category(r['category']))}</div>
        <div class="rc-name">{html.escape(r['scenario_id'])}</div>
        <div class="rc-desc">{html.escape(desc)}</div>
        <div class="rc-model">{html.escape(r['model'])}</div>
        <div class="rc-bottom">
          <span class="rc-scores">{score_html}</span>
          <span class="rc-play">&#9654; Watch</span>
        </div>
      </a>
"""
        parts.append(f"""
<hr class="section-divider">
<section class="section" id="replays">
  <div class="container">
    <div class="section-label">Evidence</div>
    <h2 class="section-title">Featured Replays</h2>
    <p class="section-sub">Watch how agents handle real threats. Click to see the full conversation and tool calls.</p>
    <div class="replay-grid">
      {cards}
    </div>
  </div>
</section>
""")

    # (Skill section moved above "How to run")

    # ── Footer ────────────────────────────────────────────────
    parts.append(f"""
<footer class="site-footer">
  <div>
    <svg width="14" height="14" viewBox="0 0 32 32" fill="none" style="vertical-align:-2px;margin-right:3px;"><rect width="32" height="32" rx="8" fill="#0572ec"/><path d="M20 9C20 5 11 5 11 9.5C11 14 21 15 21 20.5C21 25 12 25 12 21.5" stroke="#fff" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M12 21.5L15.5 18" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="20" cy="7.5" r="1.8" fill="#fff"/></svg>
    SCAM is an open-source benchmark by <a href="https://1password.com">1Password</a>
  </div>
  <div style="margin-top:10px;">
    <a href="https://github.com/1Password/SCAM">GitHub</a>
    <span class="footer-sep">&middot;</span>
    <a href="https://github.com/1Password/SCAM/blob/main/CONTRIBUTING.md">Contribute</a>
    <span class="footer-sep">&middot;</span>
    <a href="https://github.com/1Password/SCAM/blob/main/LICENSE">MIT License</a>
  </div>
  <div class="footer-bottom">Benchmark v{html.escape(bench_ref)} &middot; {html.escape(timestamp)}</div>
</footer>
""")

    body = "\n".join(parts)

    # Tab switching JS
    tab_js = """
<script>
function switchTab(group, tabId) {
  document.querySelectorAll('[data-tab-group="' + group + '"]').forEach(function(el) {
    el.classList.remove('active');
  });
  document.querySelectorAll('[data-tab-btn="' + group + '"]').forEach(function(btn) {
    btn.classList.remove('active');
  });
  var content = document.getElementById(tabId);
  if (content) content.classList.add('active');
  var btn = document.querySelector('[data-tab-btn="' + group + '"][onclick*="' + tabId + '"]');
  if (btn) btn.classList.add('active');
}
function copyCode(btnEl) {
  var wrap = btnEl.closest('.code-block-wrap');
  var pre = wrap ? wrap.querySelector('pre') : btnEl.closest('.tab-content,.step-body').querySelector('pre');
  if (pre) {
    navigator.clipboard.writeText(pre.textContent).then(function() {
      var orig = btnEl.textContent;
      btnEl.textContent = 'Copied!';
      btnEl.classList.add('copied');
      setTimeout(function() { btnEl.textContent = orig; btnEl.classList.remove('copied'); }, 2000);
    });
  }
}
function copyCursorSkill(btnEl) {
  var raw = document.getElementById('cursor-skill-raw');
  if (raw) {
    navigator.clipboard.writeText(raw.textContent).then(function() {
      var orig = btnEl.textContent;
      btnEl.textContent = 'Copied!';
      btnEl.classList.add('copied');
      setTimeout(function() { btnEl.textContent = orig; btnEl.classList.remove('copied'); }, 2000);
    });
  }
}
function showSkillView(view) {
  var rendered = document.getElementById('sv-rendered');
  var raw = document.getElementById('sv-raw');
  var btnRendered = document.getElementById('sv-btn-rendered');
  var btnRaw = document.getElementById('sv-btn-raw');
  if (view === 'raw') {
    rendered.style.display = 'none';
    raw.style.display = 'block';
    btnRendered.classList.remove('active');
    btnRaw.classList.add('active');
  } else {
    rendered.style.display = 'block';
    raw.style.display = 'none';
    btnRendered.classList.add('active');
    btnRaw.classList.remove('active');
  }
}
function copySkill(btnEl) {
  var raw = document.getElementById('skill-raw-text');
  if (raw) {
    navigator.clipboard.writeText(raw.textContent).then(function() {
      btnEl.classList.add('copied');
      var lbl = btnEl.querySelector('span') || btnEl;
      var origHTML = btnEl.innerHTML;
      btnEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 8 6.5 11.5 13 5"/></svg> Copied!';
      setTimeout(function() {
        btnEl.innerHTML = origHTML;
        btnEl.classList.remove('copied');
      }, 2000);
    });
  }
}

/* ── Terminal replay engine ──────────────────────────────── */
var _termPlaying = false;
var BAR_FULL = '████████████████████';
var BAR_EMPTY = '░░░░░░░░░░░░░░░░░░░░';

function animateBars(frame, cb) {
  var bars = frame.querySelectorAll('.tbar');
  if (!bars.length) { cb(); return; }
  var body = document.getElementById('term-body');
  var total = bars.length;
  var targets = [];
  // Each bar finishes at a random time between 1.5s and 4s, staggered
  for (var b = 0; b < total; b++) {
    targets.push({ el: bars[b], duration: 3500 + Math.random() * 4000, pct: 0, done: false });
  }
  var start = performance.now();
  function tick(now) {
    var allDone = true;
    for (var t = 0; t < targets.length; t++) {
      var tgt = targets[t];
      if (tgt.done) continue;
      var elapsed = now - start;
      var progress = Math.min(elapsed / tgt.duration, 1);
      // Ease out
      var eased = 1 - Math.pow(1 - progress, 2.5);
      var pct = Math.round(eased * 100);
      var filled = Math.round(eased * 20);
      var bar = BAR_FULL.substring(0, filled) + BAR_EMPTY.substring(0, 20 - filled);
      var label = tgt.el.dataset.label || '';
      if (pct >= 100) {
        tgt.el.innerHTML = label + '<span class="tbar-fill">' + BAR_FULL + '</span> 100%  <span class="tbar-done">✓</span>';
        tgt.done = true;
      } else {
        tgt.el.innerHTML = label + '<span class="tbar-fill">' + BAR_FULL.substring(0, filled) + '</span><span class="tbar-pct">' + BAR_EMPTY.substring(0, 20 - filled) + '</span> ' + String(pct).padStart(3) + '%';
        allDone = false;
      }
    }
    body.scrollTop = body.scrollHeight;
    if (allDone) { setTimeout(cb, 400); }
    else { requestAnimationFrame(tick); }
  }
  requestAnimationFrame(tick);
}

function playTerm() {
  if (_termPlaying) return;
  _termPlaying = true;
  var overlay = document.getElementById('term-overlay');
  var body = document.getElementById('term-body');
  var replay = document.getElementById('term-replay');
  if (overlay) overlay.style.display = 'none';
  if (replay) replay.style.display = 'none';

  // Reset all frames
  var frames = body.querySelectorAll('.tf');
  frames.forEach(function(f) {
    f.classList.remove('shown');
    var cur = f.querySelector('.tc');
    if (cur) { cur.textContent = ''; cur.classList.remove('tc-done'); }
    // Reset progress bars
    f.querySelectorAll('.tbar').forEach(function(b) { b.innerHTML = ''; });
  });
  body.scrollTop = 0;

  var i = 0;
  function nextFrame() {
    if (i >= frames.length) {
      _termPlaying = false;
      if (replay) replay.style.display = 'block';
      return;
    }
    var f = frames[i];
    var delay = parseInt(f.dataset.d) || 200;
    setTimeout(function() {
      f.classList.add('shown');
      body.scrollTop = body.scrollHeight;

      // Progress bar frame
      if (f.dataset.progress) {
        animateBars(f, function() { i++; nextFrame(); });
        return;
      }

      // Typing frame
      var typeText = f.dataset.type;
      var cur = f.querySelector('.tc');
      if (typeText && cur) {
        var speed = parseInt(f.dataset.speed) || 80;
        var j = 0;
        function typeNext() {
          if (j >= typeText.length) {
            cur.classList.add('tc-done');
            i++;
            setTimeout(nextFrame, 500);
            return;
          }
          cur.textContent += typeText[j];
          j++;
          body.scrollTop = body.scrollHeight;
          setTimeout(typeNext, speed);
        }
        setTimeout(typeNext, 300);
      } else {
        i++;
        nextFrame();
      }
    }, delay);
  }
  nextFrame();
}

// Auto-play when terminal scrolls into view
(function() {
  var played = false;
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting && !played && !_termPlaying) {
        played = true;
        playTerm();
      }
    });
  }, { threshold: 0.3 });
  var termEl = document.querySelector('.term-window');
  if (termEl) observer.observe(termEl);
})();
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCAM — Security Comprehension Awareness Measure</title>
<meta name="description" content="An open-source benchmark by 1Password for testing whether AI agents protect users from phishing, credential theft, and social engineering.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
{_SITE_CSS}
</style>
</head>
<body>
{body}
{tab_js}
</body>
</html>"""


def _render_leaderboard_rows(leaderboard: list[dict], is_evaluate: bool) -> str:
    """Render the leaderboard as an HTML table (single combined table for evaluate)."""
    if not leaderboard:
        return '<p style="color:var(--text-tertiary);">No results available.</p>'

    if is_evaluate:
        # Sort by baseline score descending — the benchmark ranking
        sorted_lb = sorted(leaderboard, key=lambda e: -e.get("baseline", 0))

        rows = ""
        for i, entry in enumerate(sorted_lb, 1):
            model = _short_model(entry.get("model", "?"))
            bl = entry.get("baseline", 0)
            sk = entry.get("skill", 0)
            delta = entry.get("delta", 0)
            bl_crit = entry.get("baseline_critical_failures", 0)
            sk_crit = entry.get("skill_critical_failures", 0)
            d_sign = "+" if delta > 0 else ""
            d_cls = _delta_cls(delta)
            bl_crit_display = f"{bl_crit:.1f}" if bl_crit else "0"

            # Baseline score with prominent bar visualization
            bl_pct = int(bl * 100)
            bl_bar_cls = _score_cls(bl)

            # Skill crit: show checkmark if 0, otherwise the count
            sk_crit_cell = '<span style="color:var(--success);">&#10003;</span>' if sk_crit == 0 else f'<span style="color:var(--fail);">{sk_crit:.1f}</span>'

            rows += f"""<tr>
  <td class="rank-cell">{i}</td>
  <td class="lb-model">
    <span class="lb-model-name">{html.escape(model)}</span>
    <div class="lb-mobile-row">
      <div class="lb-m-scores">
        <div class="lb-m-bar"><div class="lb-m-fill {bl_bar_cls}" style="width:{bl_pct}%"></div></div>
        <span class="lb-m-bl {bl_bar_cls}">{bl:.0%}</span>
        <span class="lb-m-label">baseline</span>
        <span class="lb-m-arrow">&rarr;</span>
        <span class="lb-m-sk">{sk:.0%}</span>
        <span class="lb-m-label">w/ skill</span>
      </div>
    </div>
  </td>
  <td class="num">
    <div class="lb-score-bar">
      <span class="lb-score-val {bl_bar_cls}">{bl:.0%}</span>
      <div class="lb-bar"><div class="lb-bar-fill {bl_bar_cls}" style="width:{bl_pct}%"></div></div>
    </div>
  </td>
  <td class="num lb-muted">{bl_crit_display}</td>
  <td class="num lb-muted">{sk:.0%}</td>
  <td class="num {d_cls}">{d_sign}{delta:.0%}</td>
  <td class="num lb-muted">{sk_crit_cell}</td>
</tr>
"""
        return f"""
<div class="lb-table-wrap">
<table class="lb-table lb-combined">
<thead><tr>
  <th>#</th>
  <th>Model</th>
  <th class="num">Baseline Score</th>
  <th class="num">Crit&nbsp;Failures</th>
  <th class="num lb-skill-col">With&nbsp;Skill</th>
  <th class="num lb-skill-col">Improvement</th>
  <th class="num lb-skill-col">Crit&nbsp;w/&nbsp;Skill</th>
</tr></thead>
<tbody>{rows}</tbody></table></div>"""

    else:
        header = """
<div class="lb-table-wrap">
<table class="lb-table">
<thead><tr>
  <th>#</th>
  <th>Model</th>
  <th class="num">Score</th>
  <th class="num">Failure Rate</th>
</tr></thead>
<tbody>
"""
        rows = ""
        for i, entry in enumerate(leaderboard, 1):
            model = _short_model(entry.get("model", "?"))
            score = entry.get("score", 0)
            crit = entry.get("critical_failures", 0)

            rows += f"""<tr>
  <td class="rank-cell">{i}</td>
  <td class="lb-model">{html.escape(model)}</td>
  <td class="num {_score_cls(score)}">{score:.0%}</td>
  <td class="num" style="color:var(--text-secondary);">{crit:.1f}</td>
</tr>
"""
        return header + rows + "</tbody></table></div>"


def _render_integration_steps(skill_filename: str, skill_text: str = "") -> str:
    """Render step-by-step integration instructions for each provider."""
    esc_fn = html.escape(skill_filename)

    openai_code = f'''from openai import OpenAI
from pathlib import Path

client = OpenAI()
skill = Path("skills/{esc_fn}").read_text()
your_system_prompt = "You are a helpful assistant with tool access."

response = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
        {{"role": "system", "content": skill + "\\n\\n" + your_system_prompt}},
        {{"role": "user", "content": "Check my inbox and handle anything urgent."}},
    ],
    tools=[...],
)'''

    openai_agents_code = f'''from agents import Agent, Runner
from pathlib import Path
import asyncio

skill = Path("skills/{esc_fn}").read_text()
your_instructions = "You are a helpful assistant with tool access."

agent = Agent(
    name="My Agent",
    instructions=skill + "\\n\\n" + your_instructions,
    tools=[...],
)

result = asyncio.run(
    Runner.run(agent, "Check my inbox and handle anything urgent.")
)'''

    anthropic_code = f'''import anthropic
from pathlib import Path

client = anthropic.Anthropic()
skill = Path("skills/{esc_fn}").read_text()
your_system_prompt = "You are a helpful assistant with tool access."

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    system=skill + "\\n\\n" + your_system_prompt,
    messages=[
        {{"role": "user", "content": "Check my inbox and handle anything urgent."}},
    ],
    tools=[...],
)'''

    gemini_code = f'''from google import genai
from google.genai import types
from pathlib import Path

client = genai.Client()  # uses GOOGLE_API_KEY env var
skill = Path("skills/{esc_fn}").read_text()
your_system_prompt = "You are a helpful assistant with tool access."

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Check my inbox and handle anything urgent.",
    config=types.GenerateContentConfig(
        system_instruction=skill + "\\n\\n" + your_system_prompt,
        tools=[...],
    ),
)'''

    # Build the Cursor .mdc file content for the code block
    cursor_mdc_content = f"""---
description: Security awareness skill for agentic AI
alwaysApply: true
---

{skill_text.strip()}"""

    return f"""
<div class="tabs" style="margin-top:0;">
  <button class="tab-btn active" data-tab-btn="guide" onclick="switchTab('guide','guide-openai')">OpenAI</button>
  <button class="tab-btn" data-tab-btn="guide" onclick="switchTab('guide','guide-anthropic')">Anthropic</button>
  <button class="tab-btn" data-tab-btn="guide" onclick="switchTab('guide','guide-gemini')">Google Gemini</button>
  <button class="tab-btn" data-tab-btn="guide" onclick="switchTab('guide','guide-agents')">Coding Agents</button>
</div>

<div class="tab-content active" id="guide-openai" data-tab-group="guide">
  <div class="steps">
    <div class="step-item">
      <div class="step-num">1</div>
      <div class="step-body">
        <h4>Download the skill file</h4>
        <p>Save <a href="https://github.com/1Password/SCAM/blob/main/skills/{esc_fn}">{esc_fn}</a> to your project's <code>skills/</code> directory.</p>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">2</div>
      <div class="step-body">
        <h4>Prepend it to your system prompt</h4>
        <p>Load the file and concatenate it before your existing system instructions. The skill must come first so the model applies security analysis before any task logic.</p>
        <p style="font-size:0.82rem;color:var(--text-tertiary);margin-top:6px;"><strong>Chat Completions API</strong></p>
        <div class="code-block-wrap">
          <button class="code-copy-btn" onclick="copyCode(this)">Copy</button>
          <pre>{_highlight_python(openai_code)}</pre>
        </div>
        <p style="font-size:0.82rem;color:var(--text-tertiary);margin-top:16px;"><strong>Agents SDK</strong> &mdash; pass it as <code>instructions</code></p>
        <div class="code-block-wrap">
          <button class="code-copy-btn" onclick="copyCode(this)">Copy</button>
          <pre>{_highlight_python(openai_agents_code)}</pre>
        </div>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">3</div>
      <div class="step-body">
        <h4>That's it</h4>
        <p>Works with <strong>gpt-4.1</strong>, <strong>gpt-4o</strong>, <strong>o3</strong>, <strong>o4-mini</strong>, and all other chat completion models. Compatible with the Agents SDK, Responses API, and any framework that sets a system prompt.</p>
      </div>
    </div>
  </div>
</div>

<div class="tab-content" id="guide-anthropic" data-tab-group="guide">
  <div class="steps">
    <div class="step-item">
      <div class="step-num">1</div>
      <div class="step-body">
        <h4>Download the skill file</h4>
        <p>Save <a href="https://github.com/1Password/SCAM/blob/main/skills/{esc_fn}">{esc_fn}</a> to your project's <code>skills/</code> directory.</p>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">2</div>
      <div class="step-body">
        <h4>Add to the <code>system</code> parameter</h4>
        <p>Anthropic's Messages API accepts a <code>system</code> string. Concatenate the skill text before your own system instructions.</p>
        <div class="code-block-wrap">
          <button class="code-copy-btn" onclick="copyCode(this)">Copy</button>
          <pre>{_highlight_python(anthropic_code)}</pre>
        </div>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">3</div>
      <div class="step-body">
        <h4>That's it</h4>
        <p>Works with <strong>Claude Opus</strong>, <strong>Sonnet</strong>, and <strong>Haiku</strong> via the Messages API. Compatible with tool use, extended thinking, and the <a href="https://docs.anthropic.com/en/docs/agents-and-tools/computer-use" style="color:var(--accent);">computer use</a> API.</p>
      </div>
    </div>
  </div>
</div>

<div class="tab-content" id="guide-gemini" data-tab-group="guide">
  <div class="steps">
    <div class="step-item">
      <div class="step-num">1</div>
      <div class="step-body">
        <h4>Download the skill file</h4>
        <p>Save <a href="https://github.com/1Password/SCAM/blob/main/skills/{esc_fn}">{esc_fn}</a> to your project's <code>skills/</code> directory.</p>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">2</div>
      <div class="step-body">
        <h4>Pass as <code>system_instruction</code> in the config</h4>
        <p>Using the <code>google-genai</code> SDK, pass the skill text as <code>system_instruction</code> inside <code>GenerateContentConfig</code>.</p>
        <div class="code-block-wrap">
          <button class="code-copy-btn" onclick="copyCode(this)">Copy</button>
          <pre>{_highlight_python(gemini_code)}</pre>
        </div>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">3</div>
      <div class="step-body">
        <h4>That's it</h4>
        <p>Works with <strong>Gemini 2.5 Pro</strong>, <strong>2.5 Flash</strong>, and all other models via the <a href="https://github.com/googleapis/python-genai" style="color:var(--accent);"><code>google-genai</code></a> SDK. Also works with <strong>Vertex AI</strong> by setting <code>vertexai=True</code> on the client.</p>
      </div>
    </div>
  </div>
</div>

<div class="tab-content" id="guide-agents" data-tab-group="guide">
  <div class="steps">
    <div class="step-item">
      <div class="step-num">1</div>
      <div class="step-body">
        <h4>Create a rule file</h4>
        <p>The skill is just text &mdash; drop it into whichever file your IDE or coding agent reads for instructions. Here's where each tool looks:</p>
        <table style="font-size:0.84rem;margin:12px 0 4px;border-collapse:collapse;width:100%;">
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:6px 12px 6px 0;font-weight:600;white-space:nowrap;">Cursor</td>
            <td style="padding:6px 0;"><code>.cursor/rules/security-awareness.mdc</code></td>
          </tr>
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:6px 12px 6px 0;font-weight:600;white-space:nowrap;">Windsurf</td>
            <td style="padding:6px 0;"><code>.windsurfrules</code></td>
          </tr>
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:6px 12px 6px 0;font-weight:600;white-space:nowrap;">Claude Code</td>
            <td style="padding:6px 0;"><code>CLAUDE.md</code></td>
          </tr>
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:6px 12px 6px 0;font-weight:600;white-space:nowrap;">GitHub Copilot</td>
            <td style="padding:6px 0;"><code>.github/copilot-instructions.md</code></td>
          </tr>
          <tr>
            <td style="padding:6px 12px 6px 0;font-weight:600;white-space:nowrap;">Other</td>
            <td style="padding:6px 0;"><code>AGENTS.md</code> in project root</td>
          </tr>
        </table>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">2</div>
      <div class="step-body">
        <h4>Paste the skill content</h4>
        <p>For <strong>Cursor</strong>, use the <code>.mdc</code> format with frontmatter so the skill is always active. For other tools, paste the skill text at the top of the instructions file.</p>
        <div class="code-block-wrap">
          <button class="code-copy-btn" onclick="copyCursorSkill(this)">Copy</button>
          <pre>{_highlight_md_raw(cursor_mdc_content)}</pre>
          <pre id="cursor-skill-raw" style="display:none;">{html.escape(cursor_mdc_content)}</pre>
        </div>
      </div>
    </div>
    <div class="step-item">
      <div class="step-num">3</div>
      <div class="step-body">
        <h4>That's it</h4>
        <p>The skill applies security analysis automatically whenever your coding agent handles emails, URLs, credentials, or web content. Works with any model your IDE supports. Commit the file to your repo so every contributor gets the same protection.</p>
      </div>
    </div>
  </div>
</div>
"""
