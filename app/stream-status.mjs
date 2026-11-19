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

// fzf owns this short-lived preview process; it never contacts the Apple TV.
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  process.stdout.on('error', () => process.exit(0));
  do {
    const stream = await getStreamStatus();
    if (process.argv[2] === '--label') {
      const label = stream.state === 'running' ? `ACTIEF · ${stream.channel || 'stream'}${stream.quality ? ` · ${stream.quality}` : ''}`
        : stream.state === 'stopped' ? 'GESTOPT' : 'STATUS ONBEKEND';
      process.stdout.write(` SOFASTREAM${process.env.TV_DEV_MODE ? ' @DEV' : ''} · ${label} \n`);
    } else {
      process.stdout.write(`\x1b[2J${describeStreamStatus(stream)}\n`);
    }
    if (process.argv[2] !== '--watch') break;
    await delay(2000);
  } while (true);
}
