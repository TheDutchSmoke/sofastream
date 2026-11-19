#!/usr/bin/env node
// VLC tvOS Remote Playback: the same WebSocket API used by VLC's web interface.
// https://github.com/videolan/vlc-ios/blob/master/Sources/WiFi%20Sharing/VLCPlayerControlWebSocket.m
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import net from 'node:net';
import { networkInterfaces } from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { getStreamStatus, describeStreamStatus } from './stream-status.mjs';

const selectedPath = process.env.TV_APPLE_TV_CONFIG || join(process.env.TV_CONFIG_DIR || join(homedir(), '.config/tv'), 'apple-tv.json');
const activePath = ['address', 'release', 'play', 'stop', 'status'].includes(process.argv[2]) && process.env.TV_ACTIVE_TV_CONFIG;
const selectedConfig = () => readFile(selectedPath, 'utf8').catch(error => { if (error.code === 'ENOENT') return '{}'; throw error; });
const config = JSON.parse(activePath ? await readFile(activePath, 'utf8').catch(selectedConfig) : await selectedConfig());
config.streamPort = Number(process.env.TV_STREAM_PORT || config.streamPort || 8765);
config.port ||= 80;
config.name ||= 'Apple TV';
let base = config.host ? new URL(`http://${config.host}:${config.port}/`) : null;
const unavailable = base ? `Open VLC op ${config.name} en zet Afspelen op afstand aan.` : 'Kies eerst een Apple TV via Instellingen → Apple TV kiezen.';
const runFile = promisify(execFile);

async function request(path) {
  if (!base) throw new Error(unavailable);
  return fetch(new URL(path, base), { signal: AbortSignal.timeout(2500), redirect: 'error' });
}

async function check() {
  let response;
  try {
    response = await request('/web_resources.js');
    const body = await response.text();
    if (!response.ok || !body.includes('PLAYER_CONTROL')) throw new Error('not VLC');
  } catch {
    throw new Error(unavailable);
  }
}

async function prepare() {
  // Only playback calls prepare. Status, stop and menu rendering stay passive.
  const python = process.env.TV_REMOTE_PYTHON || fileURLToPath(new URL('../remote-venv/bin/python', import.meta.url));
  const helper = fileURLToPath(new URL('./remote.py', import.meta.url));
  try {
    const result = await runFile(python, [helper, 'prepare'], { timeout: 90000, maxBuffer: 8192 });
    const prepared = JSON.parse(result.stdout);
    config.host = prepared.host;
    base = new URL(`http://${config.host}:${config.port}/`);
    // tv.zsh uses this to retry once when a wake-time profile choice closes VLC.
    if (prepared.woke === true) console.log('woke');
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('Automatische Apple TV-bediening ontbreekt. Installeer SofaStream opnieuw.');
    const message = String(error.stderr || '').trim().replace(/[\x00-\x1f\x7f-\x9f]/g, ' ');
    throw new Error(message || 'Apple TV wakker maken of VLC openen niet bevestigd. Probeer later opnieuw.');
  }
}

async function localAddress() {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: config.host, port: config.port, family: 4 });
    socket.setTimeout(2500);
    socket.once('connect', () => {
      const address = socket.localAddress;
      socket.destroy();
      resolve(address);
    });
    socket.once('timeout', () => {
      socket.destroy();
      reject(new Error(unavailable));
    });
    socket.once('error', () => reject(new Error(unavailable)));
  });
}

async function streamReady(timeout = 10000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    const log = await streamLog();
    const error = log.split('\n').find(line => /\[error\]|No playable streams/i.test(line));
    if (error) throw new Error(`Streamlink: ${error.replace(/^.*?\[error\]\s*/, '')}`);
    if (log.includes('Starting server')) return;
    await delay(200);
  }
  throw new Error('Streamlink is nog niet gereed. Bekijk Beheer → Streamlog.');
}

async function connect() {
  return new Promise((resolve, reject) => {
    const url = new URL('/socket', base);
    url.protocol = 'ws:';
    const socket = new WebSocket(url);
    const timeout = setTimeout(() => {
      socket.close();
      reject(new Error('VLC reageert niet op de afspeelopdracht.'));
    }, 3000);
    socket.addEventListener('open', () => {
      clearTimeout(timeout);
      resolve(socket);
    }, { once: true });
    socket.addEventListener('error', () => {
      clearTimeout(timeout);
      reject(new Error(unavailable));
    }, { once: true });
  });
}

// VLC on tvOS never answers the close frame; without a bound, node stays alive
// until VLC drops the connection (the end of the video) and the TUI waits on it.
async function closeSocket(socket) {
  if (socket.readyState === WebSocket.CLOSED) return;
  const closed = new Promise(resolve => socket.addEventListener('close', resolve, { once: true }));
  socket.close();
  await Promise.race([closed, delay(1000)]);
}

async function playing() {
  const response = await request('/playing');
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('VLC kan de afspeelstatus niet ophalen.');
  const state = await response.json();
  if (!state?.media || typeof state.media.id !== 'string' || !state.media.id) {
    throw new Error('VLC geeft een onbekende afspeelstatus terug.');
  }
  return state;
}

async function waitIdle() {
  for (let attempt = 0; attempt < 10; attempt++) {
    if (!await playing()) return true;
    await delay(100);
  }
  return false;
}

// A SofaStream URL on this Mac and port, whichever channel or session it was.
async function ownStream(state) {
  let url;
  try { url = new URL(state.media.id); } catch { return false; /* An unrelated local file. */ }
  return url.port === String(config.streamPort) && url.hostname === await localAddress();
}

// Thrown when VLC accepted the URL but dropped the connection; tv.zsh reads exit code 3.
class DroppedStream extends Error {
  exitCode = 3;
}

const streamLog = () => readFile(process.env.TV_STREAM_LOG || '/tmp/streamlink-tv.log', 'utf8').catch(() => '');

// VLC confirms a URL before it has read any video, so its status alone is not
// proof of playback. Streamlink accepts one connection: if VLC drops it right
// away, the Mac stream has already ended and the TV stays black.
async function streamHolds() {
  const until = Date.now() + Number(process.env.TV_STREAM_CONNECT_MS || 5000);
  while (!(await streamLog()).includes('Got HTTP request')) {
    if (Date.now() > until) throw new Error(`VLC op ${config.name} haalt de stream niet op. Sluit VLC op de Apple TV en kies het kanaal opnieuw.`);
    await delay(100);
  }
  await delay(Number(process.env.TV_STREAM_HOLD_MS || 1500));
  if (/HTTP connection closed|Stream ended/.test(await streamLog())) {
    throw new DroppedStream(`VLC op ${config.name} verbrak de stream direct. Sluit VLC op de Apple TV (twee keer op de tv-knop, VLC omhoog vegen) en kies het kanaal opnieuw.`);
  }
}

// Run before the Mac stream restarts. A VLC item that still points at the old
// stream reconnects to the port as soon as the new server listens, takes the
// single connection Streamlink accepts, and is then cut off by the stop sent
// before openURL: the new stream ends before it reaches the TV.
async function release() {
  try { await check(); } catch { return; } // Asleep or VLC closed: nothing holds the port.
  const state = await playing();
  if (!state || !await ownStream(state)) return;
  const socket = await connect();
  try {
    socket.send(JSON.stringify({ type: 'ended' }));
    if (!await waitIdle()) throw new Error('VLC stopt de vorige stream niet; je huidige stream blijft ongewijzigd. Sluit VLC op de Apple TV en probeer opnieuw.');
  } finally {
    await closeSocket(socket);
  }
}

async function openStream(channel) {
  await check();
  await streamReady();
  const address = await localAddress();
  // A fresh path per session: VLC's status then names this session, never an
  // older item that happens to use the same port. Streamlink ignores the path.
  const url = `http://${address}:${config.streamPort}/${encodeURIComponent(channel)}-${Date.now().toString(36)}`;
  const socket = await connect();
  try {
    // VLC's openURL appends to its queue while playing, so stop other media first.
    if (await playing()) {
      socket.send(JSON.stringify({ type: 'ended' }));
      if (!await waitIdle()) throw new Error('VLC stopt de vorige video niet. Probeer de kanaalkeuze opnieuw.');
      // VLC can report idle before its player has fully closed; let that finish
      // so it cannot close the new item.
      await delay(Number(process.env.TV_VLC_SETTLE_MS ?? 500));
    }
    socket.send(JSON.stringify({ type: 'openURL', url }));
    for (let attempt = 0; attempt < 25; attempt++) {
      await delay(300);
      const state = await playing();
      if (state?.media?.id === url) {
        await streamHolds();
        console.log(`▶ Afspelen gestart: ${channel} in VLC op ${config.name}.`);
        return;
      }
    }
    throw new Error(`Stream verzonden naar ${config.name}; VLC bevestigt nog geen beeld. Bekijk Streamlog.`);
  } finally {
    await closeSocket(socket);
  }
}

async function status() {
  const streamPromise = getStreamStatus();
  let state;
  let reachable = false;
  try {
    await check();
    state = await playing();
    reachable = true;
  } catch {
    // A sleeping TV or disabled VLC control must not hide the local stream.
  }
  const stream = await streamPromise;
  console.log(describeStreamStatus(stream));
  if (!reachable) {
    console.log('Apple TV: afspelen onbekend · VLC-bediening niet bereikbaar.');
  } else if (!state) {
    console.log('Apple TV: geen actieve weergave gemeld door VLC.');
  } else {
    let own = false;
    try {
      const url = new URL(state.media?.id);
      const addresses = Object.values(networkInterfaces()).flat().map(item => item.address);
      own = url.port === String(config.streamPort) && addresses.includes(url.hostname);
    } catch { /* Other VLC media can have non-URL identifiers. */ }
    const title = (own && stream.channel) || state.media?.title || (own ? 'tv-stream' : 'media');
    const safeTitle = String(title).replace(/[\x00-\x1f\x7f-\x9f]/g, ' ');
    console.log(`Apple TV: speelt ${safeTitle} in VLC.`);
  }
}

async function stop() {
  await check();
  const state = await playing();
  if (!state) { console.log('VLC: geen actieve tv-stream.'); return; }
  if (!await ownStream(state)) {
    console.log('VLC: andere media blijven spelen.');
    return;
  }
  const socket = await connect();
  socket.send(JSON.stringify({ type: 'ended' }));
  try {
    await delay(100);
    if (!await waitIdle()) throw new Error('VLC bevestigt het stoppen nog niet.');
    console.log('VLC: tv-stream gestopt.');
  } finally {
    await closeSocket(socket);
  }
}

try {
  switch (process.argv[2]) {
    case 'check': await check(); break;
    case 'prepare': await prepare(); break;
    case 'address': console.log(await localAddress()); break;
    case 'release': await release(); break;
    case 'play': await openStream(process.argv[3] || 'Kanaal'); break;
    case 'status': await status(); break;
    case 'stop': await stop(); break;
    default: throw new Error(`Gebruik: node ${fileURLToPath(import.meta.url)} check|prepare|address|release|play|status|stop`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = error.exitCode || 1;
}
// Safety net: only fires if a socket still holds the event loop open.
setTimeout(() => process.exit(), 1000).unref();
