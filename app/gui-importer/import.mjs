import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { ClassicLevel } from 'classic-level';

export const defaultProfile = path.join(os.homedir(), 'Library/Application Support/streamlink-twitch-gui/Default/Local Storage/leveldb');
export const defaultFavorites = path.join(process.env.TV_CONFIG_DIR || path.join(os.homedir(), '.config/tv'), 'favorites');
const loginPattern = /^[a-z0-9_]{1,25}$/;
const databaseFile = /^(CURRENT|MANIFEST-\d+|\d+\.(ldb|sst|log))$/;

export class ImportError extends Error {}

async function inventory(directory) {
  const files = [];
  for (const name of (await fs.readdir(directory)).filter(name => databaseFile.test(name)).sort()) {
    const stat = await fs.lstat(path.join(directory, name), { bigint: true });
    if (!stat.isFile()) throw new ImportError('Onverwacht bestand in de GUI-opslag; import afgebroken.');
    files.push({ name, size: String(stat.size), modified: String(stat.mtimeNs), inode: String(stat.ino) });
  }
  if (!files.some(file => file.name === 'CURRENT')) {
    throw new ImportError('GUI-opslag niet gevonden. Open Streamlink Twitch GUI en log daar in.');
  }
  return files;
}

export function decodeStorageString(buffer) {
  if (!buffer.length || ![0, 1].includes(buffer[0]) || (buffer[0] === 0 && buffer.length % 2 !== 1)) {
    throw new ImportError('Onbekend Chromium-opslagformaat; je favorieten blijven ongewijzigd.');
  }
  return buffer.subarray(1).toString(buffer[0] === 0 ? 'utf16le' : 'latin1');
}

export function decodeAuth(buffer) {
  let document;
  try { document = JSON.parse(decodeStorageString(buffer)); } catch {
    throw new ImportError('De GUI-login heeft een onbekend formaat; import afgebroken.');
  }
  const records = document?.auth?.records;
  if (!records || typeof records !== 'object' || Array.isArray(records) || Object.keys(records).length !== 1) {
    throw new ImportError('Geen eenduidige GUI-login gevonden; import afgebroken.');
  }
  const record = Object.values(records)[0];
  if (!record || typeof record.access_token !== 'string' || !/^[a-zA-Z0-9]{30,256}$/.test(record.access_token)) {
    throw new ImportError('Geen bruikbare GUI-login. Log eerst in bij Streamlink Twitch GUI.');
  }
  return record.access_token;
}

export async function readGuiToken(profile = defaultProfile) {
  // Never let LevelDB open the live profile: opening a database can recover logs
  // and take a lock. All such activity is confined to a private temporary copy.
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'tv-gui-import-'));
  await fs.chmod(temporary, 0o700);
  let db;
  try {
    const snapshot = path.join(temporary, 'leveldb');
    await fs.mkdir(snapshot, { mode: 0o700 });
    const before = await inventory(profile);
    for (const file of before) await fs.copyFile(path.join(profile, file.name), path.join(snapshot, file.name));
    const after = await inventory(profile);
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      throw new ImportError('De GUI-opslag veranderde tijdens het lezen. Probeer opnieuw of sluit de GUI eerst.');
    }
    db = new ClassicLevel(snapshot, { keyEncoding: 'buffer', valueEncoding: 'buffer', createIfMissing: false });
    await db.open();
    const tokens = [];
    for await (const key of db.keys()) {
      const separator = key.indexOf(0);
      if (separator < 0 || !key.subarray(0, separator).toString('ascii').startsWith('_chrome-extension://')) continue;
      if (decodeStorageString(key.subarray(separator + 1)) !== 'auth') continue;
      tokens.push(decodeAuth(await db.get(key)));
    }
    if (tokens.length !== 1) throw new ImportError('Geen eenduidige GUI-login gevonden. Open de GUI en controleer je login.');
    return tokens[0];
  } catch (error) {
    if (error instanceof ImportError) throw error;
    throw new ImportError('GUI-opslag kon niet betrouwbaar worden gelezen. Je favorieten blijven ongewijzigd.');
  } finally {
    try { if (db) await db.close(); }
    finally { await fs.rm(temporary, { recursive: true, force: true }); }
  }
}

async function getJson(url, headers, fetcher) {
  let response;
  try {
    response = await fetcher(url, { headers, redirect: 'error', signal: AbortSignal.timeout(8000) });
  } catch {
    throw new ImportError('Twitch is niet bereikbaar. Je favorieten blijven ongewijzigd.');
  }
  if ([401, 403].includes(response.status)) {
    throw new ImportError('De GUI-login is verlopen of mist toestemming. Log opnieuw in bij Streamlink Twitch GUI en probeer de import nogmaals.');
  }
  if (!response.ok) throw new ImportError(`Twitch gaf HTTP ${response.status}; import afgebroken zonder wijzigingen.`);
  try { return await response.json(); }
  catch { throw new ImportError('Onleesbaar Twitch-antwoord; import afgebroken zonder wijzigingen.'); }
}

export async function fetchFollows(token, fetcher = fetch) {
  // Get client/user identity from Twitch itself rather than parsing GUI config.
  // The token is only held in memory and sent to these two fixed Twitch hosts.
  const session = await getJson('https://id.twitch.tv/oauth2/validate', { Authorization: `OAuth ${token}` }, fetcher);
  if (!session || !/^[a-zA-Z0-9]+$/.test(session.client_id ?? '') || !/^\d+$/.test(session.user_id ?? '') ||
      !loginPattern.test(session.login ?? '') || !Array.isArray(session.scopes) || !session.scopes.includes('user:read:follows')) {
    throw new ImportError('De GUI-login heeft geen geldige Twitch-identiteit of toestemming om follows te lezen.');
  }
  const headers = { Authorization: `Bearer ${token}`, 'Client-ID': session.client_id };
  const channels = new Map();
  const cursors = new Set();
  let cursor = '', expectedTotal;
  for (let page = 0; page < 100; page++) {
    const url = new URL('https://api.twitch.tv/helix/channels/followed');
    url.searchParams.set('user_id', session.user_id);
    url.searchParams.set('first', '100');
    if (cursor) url.searchParams.set('after', cursor);
    const data = await getJson(url, headers, fetcher);
    if (!data || !Array.isArray(data.data) || !Number.isSafeInteger(data.total) || data.total < 0 ||
        !data.pagination || typeof data.pagination !== 'object') {
      throw new ImportError('Onverwacht Twitch-antwoord; geen kanalen geïmporteerd.');
    }
    expectedTotal ??= data.total;
    if (data.total !== expectedTotal) throw new ImportError('Je volglijst veranderde tijdens het ophalen. Probeer de import opnieuw.');
    for (const item of data.data) {
      if (!item || !/^\d+$/.test(item.broadcaster_id ?? '') || !loginPattern.test(item.broadcaster_login ?? '')) {
        throw new ImportError('Ongeldige kanaalgegevens; geen kanalen geïmporteerd.');
      }
      channels.set(item.broadcaster_id, item.broadcaster_login);
    }
    cursor = data.pagination.cursor;
    if (cursor === undefined || cursor === '') {
      const logins = [...new Set(channels.values())].sort();
      if (logins.length !== expectedTotal || channels.size !== expectedTotal) {
        throw new ImportError('De Twitch-volglijst is onvolledig; je favorieten blijven ongewijzigd.');
      }
      return { account: session.login, channels: logins };
    }
    if (typeof cursor !== 'string' || cursors.has(cursor) || !data.data.length) {
      throw new ImportError('Ongeldige Twitch-paginering; import afgebroken.');
    }
    cursors.add(cursor);
  }
  throw new ImportError('Te veel Twitch-pagina’s; import afgebroken zonder wijzigingen.');
}

export async function mergeFavorites(channels, favorites = defaultFavorites, dryRun = false) {
  if (!Array.isArray(channels) || channels.some(login => typeof login !== 'string' || !loginPattern.test(login))) {
    throw new ImportError('Ongeldige importlijst; je favorieten blijven ongewijzigd.');
  }
  let original = '';
  try {
    if (!(await fs.lstat(favorites)).isFile()) throw new ImportError('Favorietenbestand is geen gewoon bestand; import afgebroken.');
    original = await fs.readFile(favorites, 'utf8');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const existing = original.split(/\r?\n/).map(line => line.trim().toLowerCase()).filter(Boolean);
  if (existing.some(login => !loginPattern.test(login))) throw new ImportError('Het favorietenbestand bevat onverwachte regels; import afgebroken.');
  const merged = [...new Set([...existing, ...channels])].sort();
  const added = merged.length - new Set(existing).size;
  if (dryRun || added === 0) return { added, total: merged.length, backup: null };
  await fs.mkdir(path.dirname(favorites), { recursive: true });
  const suffix = `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`;
  const backup = `${favorites}.before-import-${suffix}`;
  const temporary = `${favorites}.import-${randomUUID()}`;
  try {
    await fs.writeFile(temporary, merged.join('\n') + '\n', { mode: 0o600, flag: 'wx' });
    const current = await fs.readFile(favorites, 'utf8').catch(error => { if (error.code === 'ENOENT') return ''; throw error; });
    if (current !== original) throw new ImportError('Je favorieten veranderden tijdens de import. Probeer opnieuw.');
    await fs.writeFile(backup, original, { mode: 0o600, flag: 'wx' });
    await fs.rename(temporary, favorites);
  } finally { await fs.rm(temporary, { force: true }); }
  return { added, total: merged.length, backup };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 1 || !['--check', '--import'].includes(args[0])) {
    throw new ImportError('Gebruik: tv fav import (of node import.mjs --check voor een voorvertoning).');
  }
  const token = await readGuiToken();
  const followed = await fetchFollows(token);
  const result = await mergeFavorites(followed.channels, defaultFavorites, args[0] === '--check');
  console.log(`Twitch-account: ${followed.account} · ${followed.channels.length} gevolgde kanalen.`);
  if (args[0] === '--check') console.log(`Voorvertoning: ${result.added} nieuwe kanalen; niets gewijzigd.`);
  else console.log(`✓ ${result.added} kanalen toegevoegd; ${result.total} totaal. Je sterren blijven ongewijzigd.`);
  if (result.backup) console.log(`Back-up: ${result.backup}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    console.error(error instanceof ImportError ? error.message : 'Import mislukt. Je bestaande favorieten zijn niet vervangen.');
    process.exitCode = 1;
  });
}
