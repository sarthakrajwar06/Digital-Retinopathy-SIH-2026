'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs/promises');
const { io } = require('socket.io-client');

const projectDir = path.resolve(__dirname, '..');

async function freePort() {
  const probe = net.createServer();
  await new Promise((resolve, reject) => probe.listen(0, '127.0.0.1', resolve).once('error', reject));
  const port = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));
  return port;
}

function spawnServer(port, dataDir) {
  const child = spawn(process.execPath, ['server.js'], {
    cwd: projectDir,
    env: { ...process.env, PORT: String(port), APL_DATA_DIR: dataDir, APL_ADMIN_PIN: '3579' },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  let output = '';
  child.stdout.on('data', (chunk) => { output += chunk.toString(); });
  child.stderr.on('data', (chunk) => { output += chunk.toString(); });
  return { child, get output() { return output; } };
}

async function waitForServer(instance, port) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (instance.child.exitCode !== null) throw new Error(`Server exited early:\n${instance.output}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/network`);
      if (response.ok) return;
    } catch { /* wait for listening socket */ }
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
  throw new Error(`Server did not start:\n${instance.output}`);
}

async function stopServer(instance) {
  if (!instance?.child || instance.child.exitCode !== null) return;
  instance.child.kill('SIGTERM');
  await Promise.race([once(instance.child, 'exit'), new Promise((resolve) => setTimeout(resolve, 6000))]);
  if (instance.child.exitCode === null) instance.child.kill('SIGKILL');
}

async function connectReadOnlyClient(port) {
  const socket = io(`http://127.0.0.1:${port}`, { autoConnect: false, reconnection: false, transports: ['websocket'] });
  const states = [];
  socket.on('state:update', (state) => states.push(state));
  const connected = new Promise((resolve, reject) => {
    socket.once('connect', resolve);
    socket.once('connect_error', reject);
  });
  socket.connect();
  await connected;
  return {
    socket,
    states,
    async waitFor(predicate) {
      const existing = states.find(predicate);
      if (existing) return existing;
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => { cleanup(); reject(new Error('Timed out waiting for a real-time state update.')); }, 5000);
        const check = (state) => { if (predicate(state)) { cleanup(); resolve(state); } };
        const cleanup = () => { clearTimeout(timeout); socket.off('state:update', check); };
        socket.on('state:update', check);
      });
    }
  };
}

async function api(port, pathName, { method = 'GET', body, cookie } = {}) {
  const headers = {};
  if (body !== undefined) headers['content-type'] = 'application/json';
  if (cookie) headers.cookie = cookie;
  const response = await fetch(`http://127.0.0.1:${port}${pathName}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const payload = await response.json();
  return { response, payload };
}

test('LAN clients receive serialized live updates and the server recovers the committed sale after restart', { timeout: 30000 }, async (t) => {
  const port = await freePort();
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'apl-auction-realtime-'));
  let instance = spawnServer(port, dataDir);
  const clients = [];
  t.after(async () => {
    for (const client of clients) client.socket.disconnect();
    await stopServer(instance);
    await fs.rm(dataDir, { recursive: true, force: true });
  });
  await waitForServer(instance, port);

  const unauth = await api(port, '/api/admin/teams', { method: 'POST', body: { id: 'hidden-team', name: 'Hidden Team', initialPurse: 1000000 } });
  assert.equal(unauth.response.status, 401, 'admin writes are protected server-side');
  const crossOrigin = await fetch(`http://127.0.0.1:${port}/api/admin/teams`, {
    method: 'POST', headers: { 'content-type': 'application/json', origin: 'http://attacker.example' },
    body: JSON.stringify({ id: 'cross-site', name: 'Cross Site', initialPurse: 1000000 })
  });
  assert.equal(crossOrigin.status, 403, 'cross-origin mutations are rejected');

  const first = await connectReadOnlyClient(port); clients.push(first);
  const second = await connectReadOnlyClient(port); clients.push(second);
  await first.waitFor((state) => state.version === 0);
  await second.waitFor((state) => state.version === 0);

  const login = await api(port, '/api/auth/admin/login', { method: 'POST', body: { pin: '3579' } });
  assert.equal(login.response.status, 200);
  const cookie = login.response.headers.get('set-cookie').split(';')[0];
  const admin = (pathName, body = {}) => api(port, pathName, { method: 'POST', body, cookie });

  assert.equal((await admin('/api/admin/teams', { id: 'north-stars', name: 'North Stars', initialPurse: 500000 })).response.status, 201);
  await admin('/api/admin/players', { id: 'arjun-mehta', name: 'Arjun Mehta', role: 'Batter', basePrice: 100000 });
  await admin('/api/admin/start');
  await admin('/api/admin/select-player', { playerId: 'arjun-mehta' });
  await admin('/api/admin/bid', { teamId: 'north-stars', amount: 100000 });

  const bidOnFirst = await first.waitFor((state) => state.auction.highestBid === 100000);
  const bidOnSecond = await second.waitFor((state) => state.auction.highestBid === 100000);
  assert.equal(bidOnFirst.version, bidOnSecond.version);

  await admin('/api/admin/sell', { teamId: 'north-stars', price: 100000 });
  const saleFirst = await first.waitFor((state) => state.auction.result === 'sold');
  const saleSecond = await second.waitFor((state) => state.auction.result === 'sold');
  assert.equal(saleFirst.players[0].status, 'sold');
  assert.equal(saleSecond.teams[0].remaining, 400000);
  assert.equal(saleFirst.version, saleSecond.version);

  const reconnecting = await connectReadOnlyClient(port); clients.push(reconnecting);
  const recovered = await reconnecting.waitFor((state) => state.players[0]?.status === 'sold');
  assert.equal(recovered.teams[0].remaining, 400000);
  assert.equal(recovered.transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).length, 1);

  for (const client of clients) client.socket.disconnect();
  clients.length = 0;
  await stopServer(instance);
  instance = spawnServer(port, dataDir);
  await waitForServer(instance, port);
  const afterRestart = await api(port, '/api/state');
  assert.equal(afterRestart.response.status, 200);
  assert.equal(afterRestart.payload.players[0].status, 'sold');
  assert.equal(afterRestart.payload.teams[0].remaining, 400000);
  assert.equal(afterRestart.payload.version, recovered.version);
});
