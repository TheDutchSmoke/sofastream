import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { ClassicLevel } from 'classic-level';
import { readGuiToken, decodeAuth, decodeStorageString, fetchFollows, mergeFavorites } from './import.mjs';

const key = Buffer.from('_chrome-extension://test\0\x01auth');
const auth = token => Buffer.concat([Buffer.from([1]), Buffer.from(JSON.stringify({ auth: { records: { 1: { access_token: token } } } }))]);
const session = { client_id: 'client123', user_id: '123', login: 'tester', scopes: ['user:read:follows'] };
const reply = (data, status = 200) => ({ ok: status === 200, status, json: async () => data });

async function temporary(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'tv-import-test-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  return directory;
}

async function hashes(directory) {
  return Promise.all((await fs.readdir(directory)).sort().map(async name => [name,
    createHash('sha256').update(await fs.readFile(path.join(directory, name))).digest('hex')]));
}

test('snapshot uses current LevelDB state, leaves open source untouched, respects deletion', async t => {
  const directory = await temporary(t);
  const source = path.join(directory, 'source');
  const db = new ClassicLevel(source, { keyEncoding: 'buffer', valueEncoding: 'buffer' });
  try {
    await db.put(key, auth('a'.repeat(30)));
    await db.put(key, auth('b'.repeat(30)));
    const before = await hashes(source);
    assert.equal(await readGuiToken(source), 'b'.repeat(30));
    assert.deepEqual(await hashes(source), before);
    await db.del(key);
    await assert.rejects(readGuiToken(source), /Geen eenduidige GUI-login/);
  } finally { await db.close(); }
});

test('unknown encodings and authentication schemas fail closed', () => {
  assert.throws(() => decodeStorageString(Buffer.from([2, 3])), /Onbekend/);
  assert.throws(() => decodeAuth(Buffer.from([1, 123])), /onbekend formaat/);
  assert.throws(() => decodeAuth(Buffer.concat([Buffer.from([1]), Buffer.from('{}')])), /eenduidige/);
  assert.equal(decodeStorageString(Buffer.concat([Buffer.from([0]), Buffer.from('auth', 'utf16le')])), 'auth');
});

test('all API pages are fetched using validated identity and fixed Twitch hosts', async () => {
  const requests = [];
  const responses = [reply(session),
    reply({ total: 2, data: [{ broadcaster_id: '1', broadcaster_login: 'bravo' }], pagination: { cursor: 'next' } }),
    reply({ total: 2, data: [{ broadcaster_id: '2', broadcaster_login: 'alpha' }], pagination: {} })];
  const result = await fetchFollows('fake', async (url, options) => {
    requests.push({ url: new URL(url), options });
    return responses.shift();
  });
  assert.deepEqual(result, { account: 'tester', channels: ['alpha', 'bravo'] });
  assert.deepEqual(requests.map(r => r.url.hostname), ['id.twitch.tv', 'api.twitch.tv', 'api.twitch.tv']);
  assert.equal(requests[2].url.searchParams.get('after'), 'next');
  assert.equal(requests[1].url.searchParams.get('first'), '100');
  assert.equal(requests[1].url.searchParams.get('user_id'), '123');
  assert.equal(requests[1].options.headers['Client-ID'], 'client123');
  assert.ok(requests.every(r => r.options.redirect === 'error'));
});

test('incomplete, changed and repeating pages are rejected', async () => {
  for (const pages of [
    [{ total: 2, data: [{ broadcaster_id: '1', broadcaster_login: 'alpha' }], pagination: {} }],
    [{ total: 2, data: [{ broadcaster_id: '1', broadcaster_login: 'alpha' }], pagination: { cursor: 'next' } },
     { total: 3, data: [], pagination: {} }],
    [{ total: 2, data: [{ broadcaster_id: '1', broadcaster_login: 'alpha' }], pagination: { cursor: 'next' } },
     { total: 2, data: [{ broadcaster_id: '2', broadcaster_login: 'bravo' }], pagination: { cursor: 'next' } }],
    [{ total: 1, data: [{ broadcaster_id: '1', broadcaster_login: 'bad\nchannel' }], pagination: {} }],
  ]) {
    const responses = [reply(session), ...pages.map(page => reply(page))];
    await assert.rejects(fetchFollows('fake', async () => responses.shift()));
  }
});

test('expired token, missing scope and network errors have safe errors', async () => {
  await assert.rejects(fetchFollows('secret', async () => reply({}, 401)), /Log opnieuw in/);
  await assert.rejects(fetchFollows('secret', async () => reply({ ...session, scopes: [] })), /toestemming/);
  await assert.rejects(fetchFollows('secret', async () => { throw new Error('private internals'); }), /niet bereikbaar/);
});

test('preview, merge, backup and duplicate import preserve existing favorites', async t => {
  const directory = await temporary(t);
  const favorites = path.join(directory, 'favorites');
  await fs.writeFile(favorites, 'manual\nalpha\n');
  const preview = await mergeFavorites(['alpha', 'bravo'], favorites, true);
  assert.equal(preview.added, 1);
  assert.equal(await fs.readFile(favorites, 'utf8'), 'manual\nalpha\n');
  assert.deepEqual(await fs.readdir(directory), ['favorites']);
  const result = await mergeFavorites(['alpha', 'bravo'], favorites);
  assert.equal(result.added, 1);
  assert.equal(await fs.readFile(result.backup, 'utf8'), 'manual\nalpha\n');
  assert.equal(await fs.readFile(favorites, 'utf8'), 'alpha\nbravo\nmanual\n');
  assert.equal((await fs.stat(favorites)).mode & 0o777, 0o600);
  assert.equal((await mergeFavorites(['alpha', 'bravo'], favorites)).added, 0);
  assert.equal((await fs.readdir(directory)).length, 2);
});

test('API failure on later page never produces a partial import', async t => {
  const directory = await temporary(t);
  const favorites = path.join(directory, 'favorites');
  await fs.writeFile(favorites, 'manual\n');
  const responses = [reply(session), reply({ total: 2, data: [{ broadcaster_id: '1', broadcaster_login: 'alpha' }], pagination: { cursor: 'next' } }), reply({}, 503)];
  await assert.rejects(async () => {
    const result = await fetchFollows('fake', async () => responses.shift());
    await mergeFavorites(result.channels, favorites);
  });
  assert.equal(await fs.readFile(favorites, 'utf8'), 'manual\n');
  assert.deepEqual(await fs.readdir(directory), ['favorites']);
});

test('unexpected existing favorite contents are preserved on error', async t => {
  const directory = await temporary(t);
  const favorites = path.join(directory, 'favorites');
  await fs.writeFile(favorites, '# unexpected format\nmanual\n');
  await assert.rejects(mergeFavorites(['alpha'], favorites), /onverwachte regels/);
  assert.equal(await fs.readFile(favorites, 'utf8'), '# unexpected format\nmanual\n');
});
