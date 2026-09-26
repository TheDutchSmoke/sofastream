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

const configPath = process.env.TV_APPLE_TV_CONFIG || join(process.env.TV_CONFIG_DIR || join(homedir(), '.config/tv'), 'apple-tv.json');
const config = JSON.parse(await readFile(configPath, 'utf8').catch(error => { if (error.code === 'ENOENT') return '{}'; throw error; }));
config.streamPort = Number(process.env.TV_STREAM_PORT || config.streamPort || 8765);
config.port ||= 80;
config.name ||= 'Apple TV';
const base = config.host ? new URL(`http://${config.host}:${config.port}/`) : null;
const unavailable = base ? `Open VLC op ${config.name} en zet Afspelen op afstand aan.` : 'Geen Apple TV gekozen. Gebruik tv configure <host> [naam].';
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
  try { await check(); return; } catch { /* VLC needs to be brought forward. */ }
  if (config.autoStart === false) throw new Error(unavailable);
  const python = process.env.TV_REMOTE_PYTHON || fileURLToPath(new URL('../remote-venv/bin/python', import.meta.url));
  const helper = fileURLToPath(new URL('./remote.py', import.meta.url));
  try {
    await runFile(python, [helper, 'wake-vlc'], { timeout: 60000, maxBuffer: 8192 });
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('Automatische Apple TV-bediening ontbreekt. Installeer SofaStream opnieuw.');
    const message = String(error.stderr || '').trim().replace(/[\x00-\x1f\x7f-\x9f]/g, ' ');
    throw new Error(message || 'Apple TV wakker maken of VLC openen niet bevestigd. Probeer later opnieuw.');
  }
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try { await check(); return; } catch { await delay(500); }
  }
  throw new Error(`VLC-bediening op ${config.name} nog niet bereikbaar. Zet in VLC Afspelen op afstand aan.`);
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
    const log = await readFile(process.env.TV_STREAM_LOG || '/tmp/streamlink-tv.log', 'utf8').catch(() => '');
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

async function openStream(channel) {
  await check();
  await streamReady();
  const address = await localAddress();
  const url = `http://${address}:${config.streamPort}/`;
  const socket = await connect();
  try {
    // VLC's openURL appends to its queue while playing, so stop before opening.
    socket.send(JSON.stringify({ type: 'ended' }));
    let stopped = false;
    for (let attempt = 0; attempt < 10; attempt++) {
      if (!await playing()) { stopped = true; break; }
      await delay(100);
    }
    if (!stopped) throw new Error('VLC stopt de vorige video niet. Probeer de kanaalkeuze opnieuw.');
    socket.send(JSON.stringify({ type: 'openURL', url }));
    for (let attempt = 0; attempt < 25; attempt++) {
      await delay(300);
      const state = await playing();
      if (state?.media?.id === url) {
        console.log(`▶ Afspelen gestart: ${channel} in VLC op ${config.name}.`);
        return;
      }
    }
    throw new Error(`Stream verzonden naar ${config.name}; VLC bevestigt nog geen beeld. Bekijk Streamlog.`);
  } finally {
    socket.close();
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
    let ownStream = false;
    try {
      const url = new URL(state.media?.id);
      const addresses = Object.values(networkInterfaces()).flat().map(item => item.address);
      ownStream = url.port === String(config.streamPort) && addresses.includes(url.hostname);
    } catch { /* Other VLC media can have non-URL identifiers. */ }
    const title = (ownStream && stream.channel) || state.media?.title || (ownStream ? 'tv-stream' : 'media');
    const safeTitle = String(title).replace(/[\x00-\x1f\x7f-\x9f]/g, ' ');
    console.log(`Apple TV: speelt ${safeTitle} in VLC.`);
  }
}

async function stop() {
  await check();
  const state = await playing();
  if (!state) { console.log('VLC: geen actieve tv-stream.'); return; }
  let url;
  try { url = new URL(state.media.id); } catch { /* An unrelated local file. */ }
  if (!url || url.port !== String(config.streamPort) || url.hostname !== await localAddress()) {
    console.log('VLC: andere media blijven spelen.');
    return;
  }
  const socket = await connect();
  socket.send(JSON.stringify({ type: 'ended' }));
  try {
    for (let attempt = 0; attempt < 10; attempt++) {
      await delay(100);
      if (!await playing()) {
        console.log('VLC: tv-stream gestopt.');
        return;
      }
    }
    throw new Error('VLC bevestigt het stoppen nog niet.');
  } finally {
    socket.close();
  }
}

try {
  switch (process.argv[2]) {
    case 'check': await check(); break;
    case 'prepare': await prepare(); break;
    case 'play': await openStream(process.argv[3] || 'Kanaal'); break;
    case 'status': await status(); break;
    case 'stop': await stop(); break;
    default: throw new Error(`Gebruik: node ${fileURLToPath(import.meta.url)} check|prepare|play|status|stop`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
