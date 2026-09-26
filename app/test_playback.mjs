// Test the actual native WebSocket client against a local VLC protocol fixture.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseStreamStatus, describeStreamStatus } from './stream-status.mjs';

const run = promisify(execFile);
const folder = await mkdtemp(join(tmpdir(), 'tv-playback-'));
const commands = [];
let current = null;
let available = true;
let malformed = false;
let ignoreStop = false;
const server = createServer((req, res) => {
  if (!available) { res.writeHead(503).end(); return; }
  if (req.url === '/web_resources.js') res.end('var LOCALES = {PLAYER_CONTROL: {}};');
  else if (req.url === '/playing' && malformed) res.end('{}');
  else if (req.url === '/playing' && current) res.end(JSON.stringify({ media: { id: current } }));
  else res.writeHead(404).end();
});
server.on('upgrade', (req, socket) => {
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
      if (opcode === 8) { socket.end(Buffer.from([0x88, 0])); return; }
      assert.equal(opcode, 1);
      const command = JSON.parse(content.toString());
      commands.push(command);
      if (command.type === 'ended' && !ignoreStop) current = null;
      if (command.type === 'openURL') current = command.url;
    }
  });
  socket.on('error', () => {});
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const configPath = join(folder, 'apple-tv.json');
const logPath = join(folder, 'stream.log');
await writeFile(configPath, JSON.stringify({ host: '127.0.0.1', port: server.address().port, name: 'Test TV', streamPort: 8765 }));
await writeFile(logPath, '[cli][info] Starting server\n');
const invoke = command => run(process.execPath, [fileURLToPath(new URL('./playback.mjs', import.meta.url)), command, 'star'], {
  env: { ...process.env, TV_APPLE_TV_CONFIG: configPath, TV_STREAM_LOG: logPath }, timeout: 10000,
});
try {
  const running = parseStreamStatus('state = running\npid = 123\nhttps://www.twitch.tv/star\nlast exit code = 1\n');
  assert.deepEqual(running, { state: 'running', pid: 123, channel: 'star' });
  assert.match(describeStreamStatus(running), /actief · star · PID 123/);
  const exited = parseStreamStatus('state = waiting\nlast exit code = 1\n');
  assert.match(describeStreamStatus(exited), /niet actief · foutcode 1/);
  assert.match(describeStreamStatus(parseStreamStatus('')), /niet beschikbaar/);
  assert.equal((await invoke('check')).stdout, '');
  current = 'http://example.invalid/old';
  assert.match((await invoke('play')).stdout, /Afspelen gestart: star in VLC op Test TV/);
  assert.deepEqual(commands, [{ type: 'ended' }, { type: 'openURL', url: 'http://127.0.0.1:8765/' }]);
  const activeStatus = (await invoke('status')).stdout;
  assert.match(activeStatus, /^Streamlink:/);
  assert.match(activeStatus, /Apple TV: speelt .* in VLC/);
  await invoke('stop');
  assert.equal(current, null);
  assert.match((await invoke('status')).stdout, /geen actieve weergave/);
  current = 'http://example.invalid/unrelated';
  await invoke('stop');
  assert.equal(current, 'http://example.invalid/unrelated', 'Stop must leave unrelated media alone');
  malformed = true;
  assert.match((await invoke('status')).stdout, /afspelen onbekend/);
  malformed = false;
  ignoreStop = true;
  const previousOpens = commands.filter(command => command.type === 'openURL').length;
  await assert.rejects(invoke('play'), error => /stopt de vorige video niet/.test(error.stderr));
  assert.equal(commands.filter(command => command.type === 'openURL').length, previousOpens, 'Do not silently queue when stopping failed');
  current = 'http://127.0.0.1:8765/';
  await assert.rejects(invoke('stop'), error => /bevestigt het stoppen nog niet/.test(error.stderr));
  ignoreStop = false;
  await writeFile(logPath, '[cli][error] No playable streams found\n');
  const beforeFailure = commands.length;
  await assert.rejects(invoke('play'), error => /No playable streams/.test(error.stderr));
  assert.equal(commands.length, beforeFailure);
  available = false;
  await assert.rejects(invoke('check'), error => /Afspelen op afstand/.test(error.stderr));
  const unavailableStatus = (await invoke('status')).stdout;
  assert.match(unavailableStatus, /^Streamlink:/);
  assert.match(unavailableStatus, /Apple TV: afspelen onbekend/);
  assert.doesNotMatch(unavailableStatus, /geen actieve weergave/);
  console.log('PASS: local stream status, VLC playing/stopped/unknown, stop-before-open, playback, scoped stop, Streamlink failure.');
} finally {
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  await rm(folder, { recursive: true, force: true });
}
