import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const run = promisify(execFile);

export function parseStreamStatus(output) {
  const state = output.match(/^\s*state = (.+)$/m)?.[1]?.trim();
  const pid = Number(output.match(/^\s*pid = (\d+)\s*$/m)?.[1]) || null;
  const channel = output.match(/https:\/\/www\.twitch\.tv\/([a-zA-Z0-9_]+)/)?.[1] || null;
  const exitCode = output.match(/^\s*last exit code = (\d+)\s*$/m)?.[1];
  if (state === 'running' && pid) return { state: 'running', pid, channel };
  if (state) return { state: 'stopped', channel, exitCode };
  return { state: 'unknown' };
}

// The relay logs "[relay][info] Bron: <channel> · <quality>" whenever a source starts
// playing, so the last such line is what the TV gets now (the channel changes while the
// relay runs). The log belongs to the current session: tv.zsh removes it on every start.
export function parseRelaySource(log) {
  const match = [...String(log).matchAll(/^\[relay\]\[info\] Bron: ([a-z0-9_]{1,25})(?: · ([\w.+-]{1,32}))?$/gm)].at(-1);
  if (!match) return null;
  return { channel: match[1], quality: describeQuality(match[2]) };
}

export function describeQuality(name) {
  if (!name) return null;
  const height = Number(name.match(/^(\d+)p/)?.[1]);
  return height >= 2160 ? `${name} · 4K` : height >= 1440 ? `${name} · 2K` : name;
}

async function relaySource() {
  const path = process.env.TV_STREAM_LOG || join(process.env.TV_CACHE_DIR || join(homedir(), '.cache/tv'), 'stream.log');
  return parseRelaySource(await readFile(path, 'utf8').catch(() => ''));
}

export async function getStreamStatus() {
  try {
    const { stdout } = await run('/bin/launchctl', ['print', `gui/${process.getuid()}/${process.env.TV_LAUNCH_LABEL || "nl.tristan.streamlink-tv"}`], {
      timeout: 1500, maxBuffer: 65536,
    });
    const stream = parseStreamStatus(stdout);
    if (stream.state === 'running') {
      const source = await relaySource();
      if (source) Object.assign(stream, source);
    }
    return stream;
  } catch (error) {
    if (/Could not find service|service not found/i.test(error.stderr || '')) return { state: 'stopped' };
    return { state: 'unknown' };
  }
}

export function describeStreamStatus(stream) {
  if (stream.state === 'running') {
    return `Streamlink: actief${stream.channel ? ` · ${stream.channel}` : ''}${stream.quality ? ` · ${stream.quality}` : ''} · PID ${stream.pid}.`;
  }
  if (stream.state === 'stopped') {
    return `Streamlink: niet actief${stream.exitCode && stream.exitCode !== '0' ? ` · foutcode ${stream.exitCode}` : ''}.`;
  }
  return 'Streamlink: status niet beschikbaar.';
}

// The stream row of the menu (DESIGN.md, Stream row). 256-colour codes only.
const paint = (text, code) => (process.env.NO_COLOR ? text : `\x1b[${code}m${text}\x1b[0m`);
const ON_AIR = /NAAR TV\s+([a-z0-9_]{1,25})/;

export function streamLabel(stream, columns = 80, tick = 0) {
  const width = Math.max(20, columns - 2);
  if (stream.state === 'running') {
    const glyph = tick % 2 ? '▷' : '▶';
    const channel = stream.channel || 'stream';
    // Too wide: drop " · 2K"/" · 4K", then the quality. Never cut the channel name.
    let quality = stream.quality || '';
    const fits = () => `${glyph} NAAR TV  ${channel}${quality ? ` · ${quality}` : ''} `.length <= width;
    if (!fits()) quality = quality.replace(/ · [24]K$/, '');
    if (!fits()) quality = '';
    return paint(`${glyph} NAAR TV  `, '38;5;46') + paint(channel, '1;38;5;231')
      + (quality ? paint(` · ${quality}`, '38;5;51') : '') + ' ';
  }
  if (stream.state === 'stopped') return `${paint('■ GEEN STREAM', '38;5;30')} `;
  return `${paint('? STREAMSTATUS ONBEKEND', '38;5;226')} `;
}

export function onAirChannel(label) {
  return String(label || '').replace(/\x1b\[[0-9;]*m/g, '').match(ON_AIR)?.[1] || '';
}

// fzf action: new stream row, plus a cached reload of the list when the channel that
// goes to the TV changed, so the ▶ in the list never disagrees with the stream row.
// Channel and quality are limited to [a-z0-9_] and [\w.+-]: the label holds no ')'.
export function tuiAction(stream, env = process.env, tick = 0) {
  const label = streamLabel(stream, Number(env.FZF_COLUMNS) || 80, tick);
  const changed = onAirChannel(label) !== onAirChannel(env.FZF_INPUT_LABEL);
  return `change-input-label(${label})${changed && env.TV_TUI_RELOAD ? `+reload(${env.TV_TUI_RELOAD})` : ''}`;
}

// fzf owns this short-lived process; it never contacts the Apple TV.
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  process.stdout.on('error', () => process.exit(0));
  do {
    const stream = await getStreamStatus();
    if (process.argv[2] === '--tui') {
      // The glyph alternates every 2 s (0.25 Hz); TV_TUI_MOTION=0 keeps it still.
      const tick = process.env.TV_TUI_MOTION === '0' ? 0 : Math.floor(Date.now() / 2000);
      process.stdout.write(tuiAction(stream, process.env, tick));
    } else {
      process.stdout.write(`\x1b[2J${describeStreamStatus(stream)}\n`);
    }
    if (process.argv[2] !== '--watch') break;
    await delay(2000);
  } while (true);
}
