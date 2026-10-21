'use strict';

const fs = require('node:fs');
const fsp = fs.promises;
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const http = require('node:http');
const express = require('express');
const { Server } = require('socket.io');
const { hashPin, verifyPin } = require('./lib/auth');
const {
  AuctionEngine,
  AuctionError,
  createInitialState,
  validateState,
  calculateTeamFinance,
  getRoleCounts,
  previewPlayerCsv,
  previewTeamCsv,
  publicState,
  buildReport
} = require('./lib/auction');

const APP_DIR = __dirname;
const PUBLIC_DIR = path.join(APP_DIR, 'public');
const DATA_DIR = path.resolve(process.env.APL_DATA_DIR || path.join(APP_DIR, 'data'));
const BACKUP_DIR = path.join(DATA_DIR, 'backups');
const STATE_FILE = path.join(DATA_DIR, 'auction.json');
const UPLOAD_DIR = path.join(PUBLIC_DIR, 'uploads');
const SESSION_COOKIE = 'apl_session';
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
const MAX_BACKUPS = 40;
const PORT = Number(process.env.PORT || process.env.APL_PORT || 3000);

if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
  console.error('PORT / APL_PORT must be a valid TCP port between 1 and 65535.');
  process.exit(1);
}

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  serveClient: true,
  maxHttpBufferSize: 1024 * 1024,
  transports: ['websocket', 'polling']
});
const sessions = new Map();
const loginAttempts = new Map();
const connectedDevices = new Map();
let engine;
let shuttingDown = false;

app.disable('x-powered-by');
app.set('trust proxy', false);
app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'same-origin');
  // No X-Frame-Options restriction: Arena's live preview embeds this local UI.
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  res.setHeader('Cache-Control', 'no-store');
  next();
});

function parseCookies(header = '') {
  const result = {};
  for (const part of header.split(';')) {
    const index = part.indexOf('=');
    if (index < 0) continue;
    const key = part.slice(0, index).trim();
    const rawValue = part.slice(index + 1).trim();
    if (key) {
      try { result[key] = decodeURIComponent(rawValue); }
      catch { result[key] = ''; }
    }
  }
  return result;
}

function getSessionFromToken(token) {
  if (!token) return null;
  const session = sessions.get(token);
  if (!session) return null;
  if (Date.now() >= session.expiresAt) {
    sessions.delete(token);
    return null;
  }
  if (session.user.role === 'team') {
    const team = engine?.snapshot().teams.find((item) => item.id === session.user.teamId && item.active);
    if (!team) {
      sessions.delete(token);
      return null;
    }
  }
  return session;
}

function requestSession(req) {
  const token = parseCookies(req.headers.cookie || '')[SESSION_COOKIE];
  const session = getSessionFromToken(token);
  return session ? { ...session, token } : null;
}

function isHttpsRequest(req) {
  const forwarded = String(req.headers['x-forwarded-proto'] || '').split(',')[0].trim().toLowerCase();
  let secureOrigin = false;
  try { secureOrigin = new URL(req.headers.origin).protocol === 'https:'; } catch { /* no browser origin */ }
  return req.secure === true || forwarded === 'https' || secureOrigin;
}

function setSessionCookie(req, res, token) {
  const secure = isHttpsRequest(req);
  const sameSite = secure ? 'None' : 'Strict';
  res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; SameSite=${sameSite}${secure ? '; Secure' : ''}; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`);
}

function clearSessionCookie(req, res) {
  const secure = isHttpsRequest(req);
  const sameSite = secure ? 'None' : 'Strict';
  res.setHeader('Set-Cookie', `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=${sameSite}${secure ? '; Secure' : ''}; Max-Age=0`);
}

function sessionMiddleware(req, res, next) {
  req.session = requestSession(req);
  next();
}

function requireAdmin(req, res, next) {
  if (req.headers.origin) {
    try {
      if (new URL(req.headers.origin).host !== req.headers.host) return res.status(403).json({ error: 'Cross-origin auction requests are not allowed.', code: 'ORIGIN_REJECTED' });
    } catch {
      return res.status(403).json({ error: 'Invalid request origin.', code: 'ORIGIN_REJECTED' });
    }
  }
  req.session = requestSession(req);
  if (!req.session || req.session.user.role !== 'admin') {
    return res.status(401).json({ error: 'Administrator sign-in is required.', code: 'AUTH_REQUIRED' });
  }
  req.user = req.session.user;
  next();
}

function ipFor(req) {
  return req.socket.remoteAddress || 'unknown';
}

function checkLoginRateLimit(key) {
  const record = loginAttempts.get(key);
  if (record && record.blockedUntil > Date.now()) {
    const seconds = Math.ceil((record.blockedUntil - Date.now()) / 1000);
    throw new AuctionError(`Too many sign-in attempts. Try again in ${seconds} seconds.`, 429, 'RATE_LIMITED');
  }
}

function recordLoginFailure(key) {
  const record = loginAttempts.get(key) || { count: 0, blockedUntil: 0, start: Date.now() };
  if (Date.now() - record.start > 5 * 60 * 1000) {
    record.count = 0;
    record.start = Date.now();
  }
  record.count += 1;
  if (record.count >= 5) record.blockedUntil = Date.now() + 60 * 1000;
  loginAttempts.set(key, record);
}

function issueSession(req, res, user) {
  const token = crypto.randomBytes(32).toString('hex');
  sessions.set(token, { user, createdAt: Date.now(), expiresAt: Date.now() + SESSION_TTL_MS });
  setSessionCookie(req, res, token);
}

function currentSnapshot() {
  return engine.snapshot();
}

function connectionSummaries() {
  const state = currentSnapshot();
  return [...connectedDevices.entries()].map(([id, device]) => {
    const team = device.teamId ? state.teams.find((item) => item.id === device.teamId) : null;
    return {
      id,
      role: device.role,
      teamId: device.teamId || null,
      label: device.role === 'admin' ? 'Administrator' : device.role === 'team' ? (team?.name || 'Team dashboard') : 'Public display',
      address: device.address,
      userAgent: device.userAgent,
      connectedAt: device.connectedAt
    };
  });
}

function sendConnectionsToAdmins() {
  const devices = connectionSummaries();
  for (const socket of io.sockets.sockets.values()) {
    if (socket.data.user?.role === 'admin') socket.emit('connections:update', devices);
  }
}

function broadcastState(state = currentSnapshot()) {
  for (const socket of io.sockets.sockets.values()) {
    if (socket.data.sessionToken && !getSessionFromToken(socket.data.sessionToken)) {
      socket.disconnect(true);
      continue;
    }
    const user = socket.data.user || null;
    socket.emit('state:update', publicState(state, user));
  }
}

function csvCell(value) {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function csvResponse(res, filename, rows) {
  const content = rows.map((row) => row.map(csvCell).join(',')).join('\r\n');
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
  res.send(`\uFEFF${content}`);
}

function exportableState(state) {
  const copy = structuredClone(state);
  delete copy.security;
  for (const team of copy.teams) delete team.pinHash;
  return copy;
}

async function ensureDirectories() {
  await Promise.all([
    fsp.mkdir(DATA_DIR, { recursive: true }),
    fsp.mkdir(BACKUP_DIR, { recursive: true }),
    fsp.mkdir(UPLOAD_DIR, { recursive: true })
  ]);
}

async function listBackupFiles() {
  let names = [];
  try { names = await fsp.readdir(BACKUP_DIR); } catch { return []; }
  const files = [];
  for (const name of names) {
    if (!/^backup-[0-9TZ-]+-v\d+\.json$/.test(name)) continue;
    const fullPath = path.join(BACKUP_DIR, name);
    try {
      const stat = await fsp.stat(fullPath);
      if (stat.isFile()) files.push({ name, fullPath, mtimeMs: stat.mtimeMs, size: stat.size });
    } catch { /* file disappeared during listing */ }
  }
  return files.sort((a, b) => b.mtimeMs - a.mtimeMs);
}

async function backupCurrentState() {
  let raw;
  try { raw = await fsp.readFile(STATE_FILE); } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  let version = 0;
  try { version = JSON.parse(raw.toString('utf8')).version || 0; } catch { version = 0; }
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const name = `backup-${stamp}-v${version}.json`;
  await fsp.writeFile(path.join(BACKUP_DIR, name), raw, { flag: 'wx', mode: 0o600 });
  await pruneBackups();
  return name;
}

async function pruneBackups() {
  const files = await listBackupFiles();
  for (const file of files.slice(MAX_BACKUPS)) {
    try { await fsp.unlink(file.fullPath); } catch { /* best effort rotation */ }
  }
}

async function persistState(state, { backup = true } = {}) {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  if (backup) await backupCurrentState();
  const temporary = `${STATE_FILE}.${process.pid}.${crypto.randomUUID()}.tmp`;
  const handle = await fsp.open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(state, null, 2)}\n`, 'utf8');
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await fsp.rename(temporary, STATE_FILE);
  } catch (error) {
    // Windows cannot always replace an existing file with rename. Keep a
    // recovery copy while swapping; backups are already on disk.
    let movedOld = false;
    const rescue = `${STATE_FILE}.recover`;
    try {
      await fsp.rename(STATE_FILE, rescue);
      movedOld = true;
    } catch (moveError) {
      if (moveError.code !== 'ENOENT') throw error;
    }
    try {
      await fsp.rename(temporary, STATE_FILE);
      if (movedOld) await fsp.unlink(rescue).catch(() => {});
    } catch (replaceError) {
      if (movedOld) await fsp.rename(rescue, STATE_FILE).catch(() => {});
      await fsp.unlink(temporary).catch(() => {});
      throw replaceError;
    }
  }
}

async function readValidState(file) {
  const parsed = JSON.parse(await fsp.readFile(file, 'utf8'));
  validateState(parsed);
  return parsed;
}

async function loadOrCreateState() {
  try {
    return await readValidState(STATE_FILE);
  } catch (error) {
    if (error.code === 'ENOENT') {
      const firstPin = process.env.APL_ADMIN_PIN || '2468';
      if (!/^\d{4,12}$/.test(firstPin)) throw new Error('APL_ADMIN_PIN must be 4–12 digits on the first startup.');
      const initial = createInitialState(hashPin(firstPin));
      validateState(initial);
      await persistState(initial, { backup: false });
      console.log(`Created a fresh local auction. Initial administrator PIN: ${process.env.APL_ADMIN_PIN ? 'set from APL_ADMIN_PIN' : '2468 (change it in Admin → Security)'}`);
      return initial;
    }
    console.error(`Auction data could not be read: ${error.message}`);
    const backups = await listBackupFiles();
    for (const backup of backups) {
      try {
        const recovered = await readValidState(backup.fullPath);
        await persistState(recovered, { backup: false });
        console.warn(`Recovered auction state from ${backup.name}.`);
        return recovered;
      } catch (backupError) {
        console.warn(`Skipped invalid backup ${backup.name}: ${backupError.message}`);
      }
    }
    throw new Error('No valid auction data or backup was found. The server stopped without resetting your data. Preserve the data folder and restore a valid backup.');
  }
}

function localAddresses() {
  const addresses = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const entry of list || []) {
      if (entry.family === 'IPv4' && !entry.internal) addresses.push(entry.address);
    }
  }
  return [...new Set(addresses)];
}

function asyncRoute(handler) {
  return (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);
}

function notFound(message = 'The requested record was not found.') {
  return new AuctionError(message, 404, 'NOT_FOUND');
}

async function createApplication() {
  await ensureDirectories();
  const initialState = await loadOrCreateState();
  engine = new AuctionEngine(initialState, {
    persist: (state) => persistState(state, { backup: true }),
    onCommit: (state) => broadcastState(state)
  });

  io.use((socket, next) => {
    try {
      const cookies = parseCookies(socket.handshake.headers.cookie || '');
      const session = getSessionFromToken(cookies[SESSION_COOKIE]);
      // Anonymous display clients are read-only; every mutation endpoint still
      // requires an administrator session on the server.
      socket.data.user = session?.user || { role: 'public' };
      socket.data.sessionToken = session ? cookies[SESSION_COOKIE] : null;
      next();
    } catch (error) {
      next(error);
    }
  });

  io.on('connection', (socket) => {
    const user = socket.data.user;
    connectedDevices.set(socket.id, {
      role: user.role,
      teamId: user.teamId || null,
      address: socket.handshake.address || '',
      userAgent: String(socket.handshake.headers['user-agent'] || '').slice(0, 160),
      connectedAt: new Date().toISOString()
    });
    socket.emit('state:update', publicState(currentSnapshot(), user));
    sendConnectionsToAdmins();
    socket.on('disconnect', () => {
      connectedDevices.delete(socket.id);
      sendConnectionsToAdmins();
    });
    // Mutations deliberately use authenticated HTTP endpoints only. No client
    // event is permitted to write authoritative auction state.
  });

  // Image uploads are local, size-limited, renamed by the server, and never
  // allow clients to choose a filesystem path.
  app.post('/api/admin/assets', requireAdmin, express.raw({ type: ['image/jpeg', 'image/png', 'image/webp'], limit: '5mb' }), asyncRoute(async (req, res) => {
    const contentType = req.headers['content-type'];
    const buffer = req.body;
    if (!Buffer.isBuffer(buffer) || buffer.length === 0) throw new AuctionError('Choose a non-empty JPG, PNG, or WebP image.');
    const signatures = {
      'image/jpeg': buffer[0] === 0xff && buffer[1] === 0xd8,
      'image/png': buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
      'image/webp': buffer.length >= 12 && buffer.toString('ascii', 0, 4) === 'RIFF' && buffer.toString('ascii', 8, 12) === 'WEBP'
    };
    if (!signatures[contentType]) throw new AuctionError('Image content did not match its file type.');
    const extension = contentType === 'image/jpeg' ? 'jpg' : contentType === 'image/png' ? 'png' : 'webp';
    const filename = `${crypto.randomUUID()}.${extension}`;
    await fsp.writeFile(path.join(UPLOAD_DIR, filename), buffer, { flag: 'wx', mode: 0o644 });
    res.status(201).json({ path: `/uploads/${filename}` });
  }));

  app.use('/api', express.json({ limit: '12mb', strict: true }));
  app.use('/api', (req, res, next) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method) && req.headers.origin) {
      try {
        if (new URL(req.headers.origin).host !== req.headers.host) {
          return res.status(403).json({ error: 'Cross-origin auction requests are not allowed.', code: 'ORIGIN_REJECTED' });
        }
      } catch {
        return res.status(403).json({ error: 'Invalid request origin.', code: 'ORIGIN_REJECTED' });
      }
    }
    next();
  });
  app.use(sessionMiddleware);

  app.get('/api/network', (req, res) => {
    const addresses = localAddresses();
    res.json({
      hostname: os.hostname(),
      port: PORT,
      localUrl: `http://localhost:${PORT}`,
      lanUrls: addresses.map((address) => `http://${address}:${PORT}`),
      addresses
    });
  });

  app.post('/api/auth/admin/login', asyncRoute(async (req, res) => {
    const key = `admin:${ipFor(req)}`;
    checkLoginRateLimit(key);
    const pin = String(req.body?.pin ?? '');
    const state = currentSnapshot();
    if (!verifyPin(pin, state.security.adminPinHash)) {
      recordLoginFailure(key);
      throw new AuctionError('Incorrect administrator PIN.', 401, 'INVALID_CREDENTIALS');
    }
    loginAttempts.delete(key);
    issueSession(req, res, { role: 'admin' });
    res.json({ ok: true, user: { role: 'admin' } });
  }));

  app.post('/api/auth/team/login', asyncRoute(async (req, res) => {
    const teamId = String(req.body?.teamId ?? '');
    const key = `team:${ipFor(req)}`;
    checkLoginRateLimit(key);
    const state = currentSnapshot();
    const team = state.teams.find((item) => item.id === teamId && item.active);
    if (!team) {
      recordLoginFailure(key);
      throw new AuctionError('This team is not registered or active.', 404, 'INVALID_TEAM');
    }
    const pin = String(req.body?.pin ?? '');
    const needsPin = state.auction.requireTeamPin || !state.auction.showOtherPurses || Boolean(team.pinHash);
    if (needsPin && !team.pinHash) throw new AuctionError('The organizer must set a PIN for this team before dashboard access.', 403, 'TEAM_PIN_UNSET');
    if (needsPin && !verifyPin(pin, team.pinHash)) {
      recordLoginFailure(key);
      throw new AuctionError('Incorrect team PIN.', 401, 'INVALID_CREDENTIALS');
    }
    loginAttempts.delete(key);
    issueSession(req, res, { role: 'team', teamId: team.id });
    res.json({ ok: true, user: { role: 'team', teamId: team.id, teamName: team.name } });
  }));

  app.post('/api/auth/logout', (req, res) => {
    const token = req.session?.token;
    if (token) {
      sessions.delete(token);
      for (const socket of io.sockets.sockets.values()) {
        if (socket.data.sessionToken === token) socket.disconnect(true);
      }
    }
    clearSessionCookie(req, res);
    res.json({ ok: true });
  });

  app.get('/api/session', (req, res) => {
    if (!req.session) return res.json({ authenticated: false });
    const user = req.session.user;
    if (user.role === 'team') {
      const team = currentSnapshot().teams.find((item) => item.id === user.teamId);
      return res.json({ authenticated: true, user: { ...user, teamName: team?.name || '' } });
    }
    res.json({ authenticated: true, user });
  });

  app.get('/api/state', (req, res) => res.json(publicState(currentSnapshot(), req.session?.user || null)));

  app.get('/api/admin/connections', requireAdmin, (req, res) => res.json({ devices: connectionSummaries() }));
  app.get('/api/admin/audit', requireAdmin, (req, res) => res.json({ audit: currentSnapshot().audit.slice().reverse() }));

  app.post('/api/admin/password', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.changeAdminPin(req.body?.pin);
    res.json({ ok: true, result, version: state.version });
  }));

  app.post('/api/admin/teams', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.addTeam(req.body || {});
    res.status(201).json({ ok: true, result, version: state.version });
  }));
  app.put('/api/admin/teams/:id', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.updateTeam(req.params.id, req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.delete('/api/admin/teams/:id', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.removeTeam(req.params.id);
    res.json({ ok: true, result, version: state.version });
  }));

  app.post('/api/admin/teams/import/preview', requireAdmin, asyncRoute(async (req, res) => {
    const state = currentSnapshot();
    const preview = previewTeamCsv(req.body?.csv, state.teams, state);
    res.json({ ...preview, rows: preview.rows.map(({ pin, ...row }) => row) });
  }));
  app.post('/api/admin/teams/import/commit', requireAdmin, asyncRoute(async (req, res) => {
    const state = currentSnapshot();
    const preview = previewTeamCsv(req.body?.csv, state.teams, state);
    if (preview.errors.length) throw new AuctionError('Fix the CSV validation errors before importing.', 422, 'CSV_VALIDATION');
    const { result, state: updated } = await engine.importTeams(preview.rows);
    res.json({ ok: true, imported: result, version: updated.version });
  }));

  app.post('/api/admin/players', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.addPlayer(req.body || {});
    res.status(201).json({ ok: true, result, version: state.version });
  }));
  app.put('/api/admin/players/:id', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.updatePlayer(req.params.id, req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.delete('/api/admin/players/:id', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.removePlayer(req.params.id);
    res.json({ ok: true, result, version: state.version });
  }));

  app.post('/api/admin/players/import/preview', requireAdmin, asyncRoute(async (req, res) => {
    const preview = previewPlayerCsv(req.body?.csv, currentSnapshot().players);
    res.json(preview);
  }));
  app.post('/api/admin/players/import/commit', requireAdmin, asyncRoute(async (req, res) => {
    const preview = previewPlayerCsv(req.body?.csv, currentSnapshot().players);
    if (preview.errors.length) throw new AuctionError('Fix the CSV validation errors before importing.', 422, 'CSV_VALIDATION');
    const { result, state } = await engine.importPlayers(preview.rows);
    res.json({ ok: true, imported: result, version: state.version });
  }));

  app.post('/api/admin/settings', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.updateSettings(req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/start', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.start();
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/pause', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.pause();
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/resume', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.resume();
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/end', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.end();
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/reset', requireAdmin, asyncRoute(async (req, res) => {
    if (req.body?.confirm !== true) throw new AuctionError('Explicit reset confirmation is required.');
    const { result, state } = await engine.resetAuction();
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/select-player', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.selectPlayer(req.body?.playerId);
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/bid', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.placeBid(req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/sell', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.sell(req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/unsold', requireAdmin, asyncRoute(async (req, res) => {
    const { result, state } = await engine.markUnsold(req.body || {});
    res.json({ ok: true, result, version: state.version });
  }));
  app.post('/api/admin/undo', requireAdmin, asyncRoute(async (req, res) => {
    if (req.body?.confirm !== true) throw new AuctionError('Explicit undo confirmation is required.');
    const { result, state } = await engine.undoLastSale();
    res.json({ ok: true, result, version: state.version });
  }));

  app.get('/api/admin/backups', requireAdmin, asyncRoute(async (req, res) => {
    const backups = await listBackupFiles();
    res.json({ backups: backups.map(({ name, mtimeMs, size }) => ({ name, createdAt: new Date(mtimeMs).toISOString(), size })) });
  }));
  app.get('/api/admin/backups/:name', requireAdmin, asyncRoute(async (req, res) => {
    const name = String(req.params.name || '');
    if (!/^backup-[0-9TZ-]+-v\d+\.json$/.test(name)) throw new AuctionError('Backup filename is invalid.');
    let candidate;
    try { candidate = await readValidState(path.join(BACKUP_DIR, name)); }
    catch (error) { throw new AuctionError(`Backup is invalid or unavailable: ${error.message}`, 422, 'INVALID_BACKUP'); }
    res.json({
      name, auctionName: candidate.auction.name, status: candidate.auction.status,
      teams: candidate.teams.length, players: candidate.players.length,
      sales: candidate.transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).length,
      createdAt: candidate.updatedAt
    });
  }));
  app.post('/api/admin/restore-backup', requireAdmin, asyncRoute(async (req, res) => {
    const name = String(req.body?.name ?? '');
    if (!/^backup-[0-9TZ-]+-v\d+\.json$/.test(name)) throw new AuctionError('Backup filename is invalid.');
    const file = path.join(BACKUP_DIR, name);
    let candidate;
    try { candidate = JSON.parse(await fsp.readFile(file, 'utf8')); }
    catch (error) { throw new AuctionError(`Backup could not be read: ${error.message}`, 422, 'INVALID_BACKUP'); }
    const { state } = await engine.restore(candidate);
    res.json({ ok: true, version: state.version });
  }));
  app.post('/api/admin/restore', requireAdmin, asyncRoute(async (req, res) => {
    if (!req.body?.state || typeof req.body.state !== 'object') throw new AuctionError('Choose a JSON auction backup to restore.');
    const { state } = await engine.restore(req.body.state);
    res.json({ ok: true, version: state.version });
  }));

  app.get('/api/report', requireAdmin, (req, res) => res.json(buildReport(currentSnapshot())));

  app.get('/api/admin/export/:kind', requireAdmin, asyncRoute(async (req, res) => {
    const state = currentSnapshot();
    const kind = req.params.kind.toLowerCase();
    if (kind === 'json') {
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Content-Disposition', 'attachment; filename="apl-auction-backup.json"');
      return res.send(`${JSON.stringify(exportableState(state), null, 2)}\n`);
    }
    if (kind === 'players.csv') {
      const rows = [['id', 'name', 'role', 'basePrice', 'photo', 'secondaryRole', 'stats', 'category', 'status', 'teamId', 'salePrice', 'sequence']];
      for (const player of state.players) rows.push([player.id, player.name, player.role, player.basePrice, player.photo, player.secondaryRole, player.stats, player.category, player.status, player.teamId, player.salePrice, player.sequence]);
      return csvResponse(res, 'apl-players.csv', rows);
    }
    if (kind === 'teams.csv') {
      const rows = [['id', 'name', 'owner', 'initialPurse', 'active', 'logo', 'spent', 'remaining', 'playersPurchased']];
      for (const team of state.teams) {
        const finance = calculateTeamFinance(state, team.id);
        rows.push([team.id, team.name, team.owner, team.initialPurse, team.active, team.logo, finance.spent, finance.remaining, finance.purchased]);
      }
      return csvResponse(res, 'apl-teams.csv', rows);
    }
    if (kind === 'transactions.csv') {
      const rows = [['sequence', 'type', 'playerId', 'playerName', 'teamId', 'teamName', 'price', 'basePrice', 'reversed', 'referenceId', 'timestamp']];
      for (const tx of state.transactions) rows.push([tx.sequence, tx.type, tx.playerId, tx.playerName, tx.teamId, tx.teamName, tx.price, tx.basePrice, tx.reversed, tx.referenceId, tx.timestamp]);
      return csvResponse(res, 'apl-transactions.csv', rows);
    }
    if (kind === 'report.json') {
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Content-Disposition', 'attachment; filename="apl-final-report.json"');
      return res.send(`${JSON.stringify(buildReport(state), null, 2)}\n`);
    }
    if (kind === 'report.csv') {
      const rows = [['teamId', 'teamName', 'playerName', 'role', 'status', 'price', 'sequence', 'initialPurse', 'spent', 'remaining']];
      for (const team of state.teams) {
        const finance = calculateTeamFinance(state, team.id);
        for (const player of finance.squad) rows.push([team.id, team.name, player.name, player.role, 'SOLD', player.salePrice, player.sequence, finance.initialPurse, finance.spent, finance.remaining]);
      }
      for (const player of state.players.filter((item) => item.status === 'unsold')) rows.push(['', '', player.name, player.role, 'UNSOLD', '', player.sequence, '', '', '']);
      return csvResponse(res, 'apl-final-report.csv', rows);
    }
    throw notFound('Unknown export format.');
  }));

  app.use('/api', (req, res) => res.status(404).json({ error: 'Unknown API route.', code: 'NOT_FOUND' }));

  // Public files are static only. The data directory is never mounted here.
  app.use(express.static(PUBLIC_DIR, { extensions: ['html'], index: 'index.html', maxAge: '1h' }));
  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api/') || req.path === '/api') return next();
    res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
  });

  app.use((error, req, res, next) => {
    if (res.headersSent) return next(error);
    const status = error instanceof AuctionError ? error.statusCode : (error.status || 500);
    const message = status >= 500 ? 'The server could not complete that request. Your last committed auction state is unchanged.' : error.message;
    if (status >= 500) console.error(error.stack || error);
    res.status(status).json({ error: message, code: error.code || (status === 400 ? 'BAD_REQUEST' : 'SERVER_ERROR') });
  });

  return { app, server, io };
}

async function main() {
  await createApplication();
  server.listen(PORT, '0.0.0.0', () => {
    const addresses = localAddresses();
    console.log('\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓');
    console.log('┃       APL · LIVE AUCTION MANAGEMENT          ┃');
    console.log('┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛');
    console.log(`Local:  http://localhost:${PORT}`);
    if (addresses.length) {
      console.log('LAN:');
      for (const address of addresses) console.log(`  http://${address}:${PORT}`);
    } else {
      console.log('LAN: no active IPv4 address found yet; connect to Wi-Fi and restart.');
    }
    console.log('Public display: /display  ·  Team dashboards: /teams');
    console.log('Keep this window open during the auction. Press Ctrl+C to stop safely.\n');
  });

  const pidPath = path.join(DATA_DIR, 'server.pid');
  await fsp.writeFile(pidPath, String(process.pid), 'utf8').catch(() => {});
  const shutdown = async (signal) => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n${signal} received — closing the local auction server...`);
    try { await engine.queue; } catch { /* previous committed state is already durable */ }
    io.close(async () => {
      await fsp.unlink(pidPath).catch(() => {});
      console.log('Server stopped. The latest committed auction state is saved locally.');
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 5000).unref();
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

main().catch((error) => {
  console.error(`APL server did not start: ${error.message}`);
  process.exit(1);
});
