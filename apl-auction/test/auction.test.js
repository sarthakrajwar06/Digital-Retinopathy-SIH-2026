'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { hashPin } = require('../lib/auth');
const {
  AuctionEngine,
  createInitialState,
  calculateTeamFinance,
  previewPlayerCsv,
  previewTeamCsv,
  publicState,
  validateState,
  buildReport
} = require('../lib/auction');

function newEngine(options = {}) {
  const state = createInitialState(hashPin('2468'));
  return new AuctionEngine(state, options);
}

async function configure(engine, { purseA = 1000000, purseB = 1000000, base = 100000, settings = {} } = {}) {
  await engine.updateSettings({ defaultBidIncrement: 50000, ...settings });
  await engine.addTeam({ id: 'north-stars', name: 'North Stars', initialPurse: purseA });
  await engine.addTeam({ id: 'city-strikers', name: 'City Strikers', initialPurse: purseB });
  await engine.addPlayer({ id: 'arjun-mehta', name: 'Arjun Mehta', role: 'Batter', basePrice: base });
}

test('authoritative sale updates squad and purse exactly once', async () => {
  const engine = newEngine();
  await configure(engine);
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  assert.equal(calculateTeamFinance(engine.snapshot(), 'north-stars').remaining, 1000000, 'a provisional bid reserves no money');
  await engine.placeBid({ teamId: 'city-strikers', amount: 150000 });
  await engine.sell({ teamId: 'city-strikers', price: 150000 });
  const state = engine.snapshot();
  assert.equal(state.players[0].status, 'sold');
  assert.equal(state.players[0].teamId, 'city-strikers');
  assert.equal(state.players[0].salePrice, 150000);
  assert.equal(calculateTeamFinance(state, 'city-strikers').spent, 150000);
  assert.equal(calculateTeamFinance(state, 'city-strikers').remaining, 850000);
  assert.equal(calculateTeamFinance(state, 'north-stars').spent, 0);
  assert.equal(state.transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).length, 1);
  assert.equal(validateState(state), true);
});

test('invalid bid, insufficient purse and duplicate sale do not mutate committed state', async () => {
  const engine = newEngine();
  await configure(engine, { purseA: 120000, purseB: 1000000, base: 100000 });
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  const version = engine.snapshot().version;
  await assert.rejects(engine.placeBid({ teamId: 'north-stars', amount: 150000 }), /only .* left|higher amount/i);
  assert.equal(engine.snapshot().version, version);
  await engine.placeBid({ teamId: 'city-strikers', amount: 100000 });
  await engine.sell({ teamId: 'city-strikers', price: 100000 });
  const committedVersion = engine.snapshot().version;
  await assert.rejects(engine.sell({ teamId: 'city-strikers', price: 100000 }), /no active player|finalized/i);
  assert.equal(engine.snapshot().version, committedVersion);
  assert.equal(calculateTeamFinance(engine.snapshot(), 'city-strikers').spent, 100000);
});

test('normal bid increments and explicit authorized overrides are enforced', async () => {
  const engine = newEngine();
  await configure(engine, { settings: { allowOverride: true } });
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  await assert.rejects(engine.placeBid({ teamId: 'city-strikers', amount: 125000 }), /Next valid bid is/);
  await engine.placeBid({ teamId: 'city-strikers', amount: 125000, override: true });
  assert.equal(engine.snapshot().auction.highestBid, 125000);
});

test('sale override requires the auction rule and a valid affordable team', async () => {
  const engine = newEngine();
  await configure(engine, { settings: { allowOverride: false } });
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  await assert.rejects(engine.sell({ teamId: 'city-strikers', price: 100000, override: true }), /overrides are disabled/i);
  await engine.sell({ teamId: 'north-stars', price: 100000 });
  assert.equal(engine.snapshot().players[0].teamId, 'north-stars');
});

test('undoing the latest sale restores the player and exact purse with audit reversal', async () => {
  const engine = newEngine();
  await configure(engine);
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  await engine.sell({ teamId: 'north-stars', price: 100000 });
  await engine.undoLastSale();
  const state = engine.snapshot();
  assert.equal(state.players[0].status, 'current');
  assert.equal(state.players[0].teamId, null);
  assert.equal(state.auction.result, 'live');
  assert.equal(state.auction.highestBid, 100000);
  assert.equal(calculateTeamFinance(state, 'north-stars').remaining, 1000000);
  assert.equal(state.transactions.find((tx) => tx.type === 'sale').reversed, true);
  assert.equal(state.transactions.at(-1).type, 'undo');
  assert.equal(state.audit.at(-1).action, 'sale.undo');
  assert.equal(validateState(state), true);
});

test('undo can safely cancel a later unbid player selection and restore that player to the queue', async () => {
  const engine = newEngine();
  await configure(engine);
  await engine.addPlayer({ id: 'second-player', name: 'Second Player', role: 'Bowler', basePrice: 100000 });
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  await engine.sell({ teamId: 'north-stars', price: 100000 });
  await engine.selectPlayer('second-player');
  await engine.undoLastSale();
  const state = engine.snapshot();
  assert.equal(state.players.find((player) => player.id === 'second-player').status, 'available');
  assert.equal(state.auction.currentPlayerId, 'arjun-mehta');
  assert.equal(state.players.find((player) => player.id === 'arjun-mehta').status, 'current');
});

test('conflicting concurrent sale requests are serialized', async () => {
  const engine = newEngine();
  await configure(engine);
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  const results = await Promise.allSettled([
    engine.sell({ teamId: 'north-stars', price: 100000 }),
    engine.sell({ teamId: 'north-stars', price: 100000 })
  ]);
  assert.equal(results.filter((item) => item.status === 'fulfilled').length, 1);
  assert.equal(results.filter((item) => item.status === 'rejected').length, 1);
  assert.equal(calculateTeamFinance(engine.snapshot(), 'north-stars').spent, 100000);
  assert.equal(engine.snapshot().transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).length, 1);
});

test('unsold players have no team assignment and only return when configured', async () => {
  const engine = newEngine();
  await configure(engine, { settings: { allowUnsoldReintroduction: true } });
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.markUnsold();
  assert.equal(engine.snapshot().players[0].status, 'unsold');
  assert.equal(engine.snapshot().players[0].teamId, null);
  assert.equal(engine.snapshot().transactions.at(-1).type, 'unsold');
  await engine.selectPlayer('arjun-mehta');
  assert.equal(engine.snapshot().auction.result, 'live');
});

test('CSV previews report errors and do not partially import invalid rows', async () => {
  const engine = newEngine();
  const playersCsv = 'id,name,role,basePrice\nplayer-a,"A, Player",Batter,50000\nplayer-b,B Player,Coach,70000';
  const preview = previewPlayerCsv(playersCsv, []);
  assert.equal(preview.totalRows, 2);
  assert.equal(preview.rows.length, 1);
  assert.equal(preview.errors.length, 1);
  await assert.rejects(engine.importPlayers(preview.rows.concat([{ id: 'player-a', name: 'Duplicate', role: 'Bowler', basePrice: 1000 }])), /Duplicate player ID/i);
  assert.equal(engine.snapshot().players.length, 0);
});

test('team CSV preview validates unique identifiers and hashed PINs are only committed server-side', async () => {
  const engine = newEngine();
  const csv = 'id,name,initialPurse,active,pin\nnorth-stars,North Stars,1000000,true,1234\n';
  const preview = previewTeamCsv(csv, [], engine.snapshot());
  assert.equal(preview.errors.length, 0);
  assert.equal(preview.rows[0].pin, '1234');
  await engine.importTeams(preview.rows);
  const saved = engine.snapshot().teams[0];
  assert.equal(saved.pinHash.startsWith('scrypt$'), true);
  assert.equal(Object.hasOwn(saved, 'pin'), false);
});

test('private team budgets require PINs and public state reveals only the signed-in team purse', async () => {
  const engine = newEngine();
  await engine.updateSettings({ showOtherPurses: false });
  await assert.rejects(engine.addTeam({ id: 'north-stars', name: 'North Stars', initialPurse: 1000000 }), /Set a PIN/i);
  await engine.addTeam({ id: 'north-stars', name: 'North Stars', initialPurse: 1000000, pin: '1234' });
  await engine.addTeam({ id: 'city-strikers', name: 'City Strikers', initialPurse: 900000, pin: '4321' });
  const publicView = publicState(engine.snapshot(), { role: 'public' });
  assert.equal(publicView.teams[0].remaining, undefined);
  const teamView = publicState(engine.snapshot(), { role: 'team', teamId: 'north-stars' });
  assert.equal(teamView.teams[0].remaining, 1000000);
  assert.equal(teamView.teams[1].remaining, undefined);
  assert.equal(Object.hasOwn(teamView.teams[0], 'pinHash'), false);
});

test('invalid restore data is rejected without replacing committed state', async () => {
  const engine = newEngine();
  await engine.addTeam({ id: 'north-stars', name: 'North Stars', initialPurse: 1000000 });
  const before = engine.snapshot();
  await assert.rejects(engine.restore({ schemaVersion: 1, version: 0, teams: {} }), /team list/i);
  assert.equal(engine.snapshot().version, before.version);
  assert.equal(engine.snapshot().teams.length, 1);
});

test('persistence failure leaves the previously committed state unchanged', async () => {
  let shouldFail = false;
  const engine = newEngine({ persist: async () => { if (shouldFail) throw new Error('disk unavailable'); } });
  await engine.addTeam({ id: 'north-stars', name: 'North Stars', initialPurse: 1000000 });
  const before = engine.snapshot();
  shouldFail = true;
  await assert.rejects(engine.addPlayer({ id: 'arjun-mehta', name: 'Arjun Mehta', role: 'Batter', basePrice: 100000 }), /disk unavailable/);
  assert.equal(engine.snapshot().version, before.version);
  assert.equal(engine.snapshot().players.length, 0);
});

test('report totals are computed from committed sale history and squads', async () => {
  const engine = newEngine();
  await configure(engine);
  await engine.start();
  await engine.selectPlayer('arjun-mehta');
  await engine.placeBid({ teamId: 'north-stars', amount: 100000 });
  await engine.sell({ teamId: 'north-stars', price: 100000 });
  const report = buildReport(engine.snapshot());
  assert.equal(report.summary.sold, 1);
  assert.equal(report.summary.totalExpenditure, 100000);
  assert.equal(report.teams.find((team) => team.id === 'north-stars').remaining, 900000);
});
