// Test the actual native WebSocket client against a local VLC protocol fixture.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseStreamStatus, describeStreamStatus, parseRelaySource, describeQuality } from './stream-status.mjs';

const run = promisify(execFile);
const folder = await mkdtemp(join(tmpdir(), 'tv-playback-'));
const commands = [];
let current = null;
let available = true;
let malformed = false;
let ignoreStop = false;
// Real VLC on tvOS never answers a WebSocket close frame.
let ignoreClose = false;
// How VLC treats the relay after openURL: 'keep' stays connected, 'drop' leaves after
// its probe, 'never' does not connect. The relay fixture reports the viewer count.
let viewer = 'keep';
const relayState = { ok: true, channel: 'star', quality: '1080p60', pending: null, viewers: 0, connections: 0, path: '/sess1' };
let relayUp = true;
const relayURL = 'http://127.0.0.1:8765/sess1';
const preparations = [];
const requests = [];
const server = createServer((req, res) => {
  requests.push([req.url, req.headers.host]);
  if (req.url.startsWith('/fixture-prepare')) {
    if (!available && req.url.includes('auto=false')) {
      res.writeHead(503).end('Open VLC en zet Afspelen op afstand aan.');
      return;
    }
    const woke = !available;
    if (woke) preparations.push('prepare');
    available = true;
    res.end(JSON.stringify({ host: '127.0.0.1', woke }));
    return;
  }
  if (!available) { res.writeHead(503).end(); return; }
  if (preparations.length && !req.headers.host.startsWith('127.0.0.1:')) {
    res.writeHead(503).end(); return;
  }
  if (req.url === '/web_resources.js') res.end('var LOCALES = {PLAYER_CONTROL: {}};');
  else if (req.url === '/playing' && malformed) res.end('{}');
  else if (req.url === '/playing' && current) res.end(JSON.stringify({ media: { id: current } }));
  else res.writeHead(404).end();
});
const upgraded = new Set();
server.on('upgrade', (req, socket) => {
  upgraded.add(socket);
  const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  let pending = Buffer.alloc(0);
  socket.on('data', data => {
    pending = Buffer.concat([pending, data]);
    while (pending.length >= 2) {
      const opcode = pending[0] & 15;
      const length = pending[1] & 127;
      assert(length < 126, 'Fixture commands must be short');
      assert(pending[1] & 128, 'Client frames must be masked');
      if (pending.length < 6 + length) return;
      const mask = pending.subarray(2, 6);
      const content = Buffer.from(pending.subarray(6, 6 + length));
      pending = pending.subarray(6 + length);
      for (let i = 0; i < content.length; i++) content[i] ^= mask[i % 4];
      if (opcode === 8) { if (!ignoreClose) socket.end(Buffer.from([0x88, 0])); return; }
      assert.equal(opcode, 1);
      const command = JSON.parse(content.toString());
      commands.push(command);
      if (command.type === 'ended' && !ignoreStop) current = null;
      if (command.type === 'openURL') {
        current = command.url;
        relayState.viewers = viewer === 'never' ? 0 : 1;
        if (viewer !== 'never') relayState.connections += 1;
        if (viewer === 'drop') setTimeout(() => { relayState.viewers = 0; }, 50);
      }
    }
  });
  socket.on('error', () => {});
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const relaySocket = join(folder, 'relay.sock');
const relay = net.createServer(socket => socket.once('data', () => socket.end(relayUp ? JSON.stringify(relayState) + '\n' : '')));
await new Promise(resolve => relay.listen(relaySocket, resolve));
const configPath = join(folder, 'apple-tv.json');
const logPath = join(folder, 'stream.log');
const testConfig = { host: '127.0.0.1', port: server.address().port, name: 'Test TV', streamPort: 8765 };
const helper = join(folder, 'remote-fixture');
await writeFile(helper, `#!${process.execPath}
if (process.env.TV_FIXTURE_PAIR_MISSING) {
  console.error("Voer eenmalig 'sofastream@dev pair' uit (pincode op tv).");
  process.exit(1);
}
if (process.argv.at(-1) !== 'prepare') process.exit(2);
const config = JSON.parse(require('node:fs').readFileSync(process.env.TV_APPLE_TV_CONFIG, 'utf8'));
fetch('http://127.0.0.1:${server.address().port}/fixture-prepare?auto=' + (config.autoStart !== false))
  .then(async response => {
    const body = await response.text();
    if (!response.ok) { console.error(body); process.exit(1); }
    console.log(body); process.exit(0);
  });
`, { mode: 0o700 });
await writeFile(configPath, JSON.stringify(testConfig));
await writeFile(logPath, '[relay][info] Bron: star · 1080p60\n');
const invoke = (command, extraEnv = {}) => run(process.execPath, [fileURLToPath(new URL('./playback.mjs', import.meta.url)), command, 'star'], {
  env: { ...process.env, TV_APPLE_TV_CONFIG: configPath, TV_ACTIVE_TV_CONFIG: '', TV_STREAM_LOG: logPath,
    TV_REMOTE_PYTHON: helper, TV_RELAY_SOCKET: relaySocket, TV_STREAM_HOLD_MS: '200', TV_STREAM_CONNECT_MS: '600',
    TV_RELAY_READY_MS: '1500', TV_VLC_IDLE_MS: '1500', TV_VLC_SETTLE_MS: '0', ...extraEnv }, timeout: 10000,
});
try {
  const running = parseStreamStatus('state = running\npid = 123\nhttps://www.twitch.tv/star\nlast exit code = 1\n');
  assert.deepEqual(running, { state: 'running', pid: 123, channel: 'star' });
  assert.match(describeStreamStatus(running), /actief · star · PID 123/);
  const exited = parseStreamStatus('state = waiting\nlast exit code = 1\n');
  assert.match(describeStreamStatus(exited), /niet actief · foutcode 1/);
  assert.match(describeStreamStatus(parseStreamStatus('')), /niet beschikbaar/);
  // Channel and quality follow the relay's last "Bron:" line: the channel changes while it runs.
  assert.deepEqual(parseRelaySource('[relay][info] Bron: ohnepixel · 1440p60\n[cli][info] Opening stream: 1080p60 (hls)\n[relay][info] Bron: kaicenat · 1080p60\n'),
    { channel: 'kaicenat', quality: '1080p60' });
  assert.deepEqual(parseRelaySource('[relay][info] Bron: ohnepixel · 1440p60'), { channel: 'ohnepixel', quality: '1440p60 · 2K' });
  assert.equal(describeQuality('2160p60'), '2160p60 · 4K');
  assert.equal(parseRelaySource('[relay][info] Wissel naar kaicenat\n[cli][info] Opening stream: 1080p60 (hls)'), null, 'No source before it plays');
  assert.equal(parseRelaySource('[relay][info] Bron: \x1b[2J · x'), null, 'Log text never reaches the label unchecked');
  assert.match(describeStreamStatus({ ...running, quality: '1440p60 · 2K' }), /actief · star · 1440p60 · 2K · PID 123/);
  console.log('PASS: stream quality in the status');
  assert.equal((await invoke('check')).stdout, '');
  assert.equal((await invoke('prepare')).stdout, '', 'Ready VLC reports no wake');
  console.log('PASS: prepare with VLC ready');
  assert.equal(preparations.length, 0, 'An already available VLC needs no wake command');
  available = false;
  await writeFile(configPath, JSON.stringify({ ...testConfig, autoStart: false }));
  await assert.rejects(invoke('prepare'), error => /Afspelen op afstand/.test(error.stderr));
  assert.equal(preparations.length, 0, 'Respect disabled automatic start');
  console.log('PASS: disabled auto-start');
  await writeFile(configPath, JSON.stringify(testConfig));
  await assert.rejects(invoke('prepare', { TV_FIXTURE_PAIR_MISSING: '1' }), error => /sofastream@dev pair/.test(error.stderr));
  assert.equal(preparations.length, 0, 'Missing pairing never sends a wake command');
  console.log('PASS: missing pairing');
  await writeFile(configPath, JSON.stringify({ ...testConfig, host: 'localhost' }));
  try { assert.equal((await invoke('prepare')).stdout, 'woke\n', 'A wake is reported for the profile retry'); } catch (error) {
    console.error({ preparations, requests });
    throw error;
  }
  console.log('PASS: wake and changed address');
  assert.deepEqual(preparations, ['prepare'], 'One helper owns discovery, wake and readiness');
  assert.equal(commands.length, 0, 'Prepare must not replace or queue playback');
  await writeFile(configPath, JSON.stringify(testConfig));
  const waitIdleSoon = (ms = 300) => setTimeout(() => { current = null; }, ms);

  // Other media plays: stop it, then open the relay once.
  current = 'http://example.invalid/old';
  assert.match((await invoke('play')).stdout, /Afspelen gestart: star in VLC op Test TV/);
  assert.deepEqual(commands, [{ type: 'ended' }, { type: 'openURL', url: relayURL }]);
  const activeStatus = (await invoke('status')).stdout;
  assert.match(activeStatus, /^Streamlink:/);
  assert.match(activeStatus, /Apple TV: speelt .* in VLC/);
  console.log('PASS: other media stopped, relay opened');

  // VLC already shows this relay: nothing is sent.
  commands.length = 0;
  assert.match((await invoke('play')).stdout, /star speelt in VLC op Test TV/);
  assert.equal(commands.length, 0, 'a watched relay needs no VLC command');
  console.log('PASS: a watched relay gets no command');

  // tv stop unloads the relay first; VLC then ends the item itself: no 'ended' (VLC 3.0.24 hangs on it).
  waitIdleSoon();
  assert.match((await invoke('stop')).stdout, /tv-stream gestopt/);
  assert.equal(commands.length, 0, 'stop never sends ended to a SofaStream stream');
  current = relayURL;
  assert.match((await invoke('stop', { TV_VLC_IDLE_MS: '300' })).stdout, /laatste seconden buffer/);
  current = 'http://example.invalid/unrelated';
  assert.match((await invoke('stop')).stdout, /andere media blijven spelen/);
  assert.equal(current, 'http://example.invalid/unrelated', 'Stop must leave unrelated media alone');
  console.log('PASS: stop without ended');

  // An ended earlier relay (own address, older path): wait until VLC finishes it, never 'ended'.
  current = 'http://127.0.0.1:8765/older';
  relayState.viewers = 0;
  waitIdleSoon();
  assert.match((await invoke('play')).stdout, /Afspelen gestart/);
  assert.deepEqual(commands, [{ type: 'openURL', url: relayURL }]);
  commands.length = 0;
  current = 'http://127.0.0.1:8765/older';
  relayState.viewers = 0;
  await assert.rejects(invoke('play', { TV_VLC_IDLE_MS: '300' }), error => /speelt de vorige stream nog af/.test(error.stderr));
  assert.equal(commands.length, 0);
  console.log('PASS: an ended relay item is never stopped with ended');

  // Without a close reply the command must still return promptly (the TUI waits for it).
  current = null;
  relayState.viewers = 0;
  ignoreClose = true;
  let started = Date.now();
  assert.match((await invoke('play')).stdout, /Afspelen gestart/);
  assert.ok(Date.now() - started < 4000, `play hung ${Date.now() - started} ms after VLC ignored close`);
  ignoreClose = false;
  console.log('PASS: play returns although VLC ignores close');

  // VLC confirms the URL but drops (exit 3) or never opens the stream: report it.
  for (const [mode, code, text] of [['drop', 3, /verbrak de stream direct/], ['never', 1, /haalt de stream niet op/]]) {
    current = null;
    relayState.viewers = 0;
    viewer = mode;
    await assert.rejects(invoke('play'), error => error.code === code && text.test(error.stderr));
  }
  viewer = 'keep';
  console.log('PASS: a dropped or unopened stream is not reported as playing');

  assert.match((await invoke('status')).stdout, /speelt|geen actieve/);
  malformed = true;
  assert.match((await invoke('status')).stdout, /afspelen onbekend/);
  malformed = false;
  ignoreStop = true;
  current = 'http://example.invalid/unrelated';
  const previousOpens = commands.filter(command => command.type === 'openURL').length;
  await assert.rejects(invoke('play'), error => /stopt de vorige video niet/.test(error.stderr));
  assert.equal(commands.filter(command => command.type === 'openURL').length, previousOpens, 'Do not silently queue when stopping failed');
  ignoreStop = false;
  current = null;

  // The relay has no video yet: Streamlink's own error appears at once, not after the wait.
  relayState.channel = null;
  await writeFile(logPath, '[cli][info] Found matching plugin twitch for URL https://www.twitch.tv/star\nerror: No playable streams found on this URL: https://www.twitch.tv/star\n');
  const beforeFailure = commands.length;
  await assert.rejects(invoke('play'), error => /^Streamlink: No playable streams/.test(error.stderr));
  assert.equal(commands.length, beforeFailure);
  await writeFile(logPath, 'error: Failed to create HTTP server: [Errno 48] Address already in use\n');
  let failedAt = Date.now();
  await assert.rejects(invoke('play'), error => /Address already in use/.test(error.stderr) && /Poort 8765 is nog bezet/.test(error.stderr));
  assert.ok(Date.now() - failedAt < 2000, `a Streamlink error took ${Date.now() - failedAt} ms to surface`);
  relayUp = false;
  await writeFile(logPath, '[relay][info] Stream ended (star)\n');
  await assert.rejects(invoke('play'), error => /stopte voordat er beeld was/.test(error.stderr));
  relayUp = true;
  relayState.channel = 'star';
  assert.equal(commands.length, beforeFailure);
  console.log('PASS: Streamlink errors surface at once');
  available = false;
  await assert.rejects(invoke('check'), error => /Afspelen op afstand/.test(error.stderr));
  const unavailableStatus = (await invoke('status')).stdout;
  assert.match(unavailableStatus, /^Streamlink:/);
  assert.match(unavailableStatus, /Apple TV: afspelen onbekend/);
  assert.doesNotMatch(unavailableStatus, /geen actieve weergave/);
  console.log('PASS: automatic wake/ready flow, pairing errors, changed IP, opt-out, local stream status, VLC playback, scoped stop and Streamlink failure.');
} finally {
  relay.close();
  server.closeAllConnections();
  for (const socket of upgraded) socket.destroy();
  await new Promise(resolve => server.close(resolve));
  await rm(folder, { recursive: true, force: true });
}
