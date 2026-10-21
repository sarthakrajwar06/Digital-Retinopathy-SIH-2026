'use strict';

const crypto = require('node:crypto');
const { hashPin } = require('./auth');

const ROLES = ['Batter', 'Bowler', 'All-rounder', 'Wicketkeeper'];
const ROLE_KEYS = ['batter', 'bowler', 'all-rounder', 'wicketkeeper'];
const PLAYER_STATUSES = ['available', 'current', 'sold', 'unsold'];
const AUCTION_STATUSES = ['not-started', 'live', 'paused', 'completed'];
const RESULT_STATES = ['waiting', 'live', 'sold', 'unsold'];
const MAX_HISTORY = 10000;
const ID_PATTERN = /^[a-z0-9][a-z0-9_-]{1,47}$/i;
const PHOTO_PATTERN = /^\/uploads\/[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/;

class AuctionError extends Error {
  constructor(message, statusCode = 400, code = 'INVALID_ACTION') {
    super(message);
    this.name = 'AuctionError';
    this.statusCode = statusCode;
    this.code = code;
  }
}

function fail(message, statusCode = 400, code = 'INVALID_ACTION') {
  throw new AuctionError(message, statusCode, code);
}

function assert(condition, message) {
  if (!condition) throw new Error(`Invalid auction state: ${message}`);
}

function clone(value) {
  return structuredClone(value);
}

function cleanText(value, label, max = 120, required = false) {
  const text = String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim();
  if (required && !text) fail(`${label} is required.`);
  if (text.length > max) fail(`${label} must be ${max} characters or fewer.`);
  return text;
}

function asInteger(value, label, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  const number = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  if (!Number.isSafeInteger(number) || number < min || number > max) {
    fail(`${label} must be a whole number between ${min.toLocaleString('en-IN')} and ${max.toLocaleString('en-IN')}.`);
  }
  return number;
}

function safePhoto(value) {
  const photo = cleanText(value, 'Image path', 180, false);
  if (!photo) return '';
  if (!PHOTO_PATTERN.test(photo)) fail('Images must be uploaded locally using the image upload control.');
  return photo;
}

function makeId(prefix = 'item') {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

function emptyRoleRequirements() {
  return Object.fromEntries(ROLE_KEYS.map((key) => [key, { min: 0, max: null }]));
}

function createInitialState(adminPinHash) {
  return {
    schemaVersion: 1,
    version: 0,
    updatedAt: new Date().toISOString(),
    security: { adminPinHash },
    auction: {
      name: 'Auction Premier League',
      status: 'not-started',
      result: 'waiting',
      currency: 'INR',
      currencySymbol: '₹',
      startingPurse: 10000000,
      defaultBidIncrement: 100000,
      bidIncrements: [],
      minSquadSize: 0,
      maxSquadSize: null,
      roleRequirements: emptyRoleRequirements(),
      showOtherPurses: true,
      revealNextPlayer: false,
      allowUnsoldReintroduction: false,
      allowOverride: true,
      requireTeamPin: false,
      currentPlayerId: null,
      highestBid: null,
      highestBidTeamId: null,
      sequence: 0
    },
    teams: [],
    players: [],
    transactions: [],
    audit: []
  };
}

function normalizedRole(value) {
  const role = String(value ?? '').trim().toLowerCase();
  const map = {
    batter: 'Batter', batsman: 'Batter', batswoman: 'Batter',
    bowler: 'Bowler',
    'all-rounder': 'All-rounder', allrounder: 'All-rounder', 'all rounder': 'All-rounder',
    wicketkeeper: 'Wicketkeeper', 'wicket keeper': 'Wicketkeeper', keeper: 'Wicketkeeper'
  };
  return map[role] || null;
}

function validateSettingsShape(auction) {
  assert(auction && typeof auction === 'object', 'auction settings must be an object');
  assert(typeof auction.name === 'string' && auction.name.trim().length > 0, 'auction name is required');
  assert(AUCTION_STATUSES.includes(auction.status), 'auction status is invalid');
  assert(RESULT_STATES.includes(auction.result), 'auction result is invalid');
  assert(Number.isSafeInteger(auction.startingPurse) && auction.startingPurse > 0, 'starting purse must be a positive integer');
  assert(Number.isSafeInteger(auction.defaultBidIncrement) && auction.defaultBidIncrement > 0, 'bid increment must be a positive integer');
  assert(auction.maxSquadSize === null || (Number.isSafeInteger(auction.maxSquadSize) && auction.maxSquadSize > 0), 'maximum squad size is invalid');
  assert(Number.isSafeInteger(auction.minSquadSize) && auction.minSquadSize >= 0, 'minimum squad size is invalid');
  assert(auction.maxSquadSize === null || auction.minSquadSize <= auction.maxSquadSize, 'minimum squad size exceeds maximum');
  assert(typeof auction.currencySymbol === 'string' && auction.currencySymbol.length > 0 && auction.currencySymbol.length <= 6, 'currency symbol is invalid');
  assert(Array.isArray(auction.bidIncrements), 'bid increment tiers must be an array');
  let previousLimit = -1;
  for (const tier of auction.bidIncrements) {
    assert(tier && (tier.upTo === null || (Number.isSafeInteger(tier.upTo) && tier.upTo > previousLimit)), 'bid tier upper limits must be increasing');
    assert(Number.isSafeInteger(tier.increment) && tier.increment > 0, 'bid tier increment must be positive');
    if (tier.upTo !== null) previousLimit = tier.upTo;
  }
  const requirements = auction.roleRequirements;
  assert(requirements && typeof requirements === 'object', 'role requirements are missing');
  for (const role of ROLE_KEYS) {
    const rule = requirements[role];
    assert(rule && Number.isSafeInteger(rule.min) && rule.min >= 0, `minimum ${role} requirement is invalid`);
    assert(rule.max === null || (Number.isSafeInteger(rule.max) && rule.max >= rule.min), `maximum ${role} requirement is invalid`);
  }
  for (const key of ['showOtherPurses', 'revealNextPlayer', 'allowUnsoldReintroduction', 'allowOverride', 'requireTeamPin']) {
    assert(typeof auction[key] === 'boolean', `${key} must be a boolean`);
  }
  assert(auction.currentPlayerId === null || typeof auction.currentPlayerId === 'string', 'current player id is invalid');
  assert(auction.highestBid === null || (Number.isSafeInteger(auction.highestBid) && auction.highestBid > 0), 'highest bid is invalid');
  assert(auction.highestBidTeamId === null || typeof auction.highestBidTeamId === 'string', 'highest bid team is invalid');
  assert(Number.isSafeInteger(auction.sequence) && auction.sequence >= 0, 'auction sequence is invalid');
}

function validateState(state) {
  assert(state && typeof state === 'object', 'root must be an object');
  assert(state.schemaVersion === 1, 'unsupported schema version');
  assert(Number.isSafeInteger(state.version) && state.version >= 0, 'version is invalid');
  assert(typeof state.updatedAt === 'string' && !Number.isNaN(Date.parse(state.updatedAt)), 'updatedAt is invalid');
  assert(state.security && typeof state.security.adminPinHash === 'string' && state.security.adminPinHash.startsWith('scrypt$'), 'admin PIN hash is missing');
  validateSettingsShape(state.auction);
  assert(Array.isArray(state.teams) && Array.isArray(state.players), 'teams and players must be arrays');
  assert(Array.isArray(state.transactions) && Array.isArray(state.audit), 'history must be arrays');
  assert(state.transactions.length <= MAX_HISTORY, 'transaction history is too large');
  const teamIds = new Set();
  const teamNames = new Set();
  for (const team of state.teams) {
    assert(team && typeof team.id === 'string' && ID_PATTERN.test(team.id), 'team id is invalid');
    assert(!teamIds.has(team.id), 'duplicate team id');
    teamIds.add(team.id);
    assert(typeof team.name === 'string' && team.name.trim().length > 0, 'team name is required');
    const key = team.name.trim().toLocaleLowerCase();
    assert(!teamNames.has(key), 'duplicate team name');
    teamNames.add(key);
    assert(Number.isSafeInteger(team.initialPurse) && team.initialPurse > 0, 'team purse is invalid');
    assert(typeof team.active === 'boolean', 'team active flag is invalid');
    assert(team.pinHash === null || (typeof team.pinHash === 'string' && team.pinHash.startsWith('scrypt$')), 'team PIN hash is invalid');
    assert(typeof team.logo === 'string' && (!team.logo || PHOTO_PATTERN.test(team.logo)), 'team logo path is invalid');
  }
  const playerIds = new Set();
  const playerNames = new Set();
  for (const player of state.players) {
    assert(player && typeof player.id === 'string' && ID_PATTERN.test(player.id), 'player id is invalid');
    assert(!playerIds.has(player.id), 'duplicate player id');
    playerIds.add(player.id);
    assert(typeof player.name === 'string' && player.name.trim().length > 0, 'player name is required');
    const nameKey = `${player.name.trim().toLocaleLowerCase()}|${player.id}`;
    assert(!playerNames.has(nameKey), 'duplicate player record');
    playerNames.add(nameKey);
    assert(ROLES.includes(player.role), 'player role is invalid');
    assert(Number.isSafeInteger(player.basePrice) && player.basePrice > 0, 'player base price is invalid');
    assert(PLAYER_STATUSES.includes(player.status), 'player status is invalid');
    assert(typeof player.photo === 'string' && (!player.photo || PHOTO_PATTERN.test(player.photo)), 'player image path is invalid');
    assert(player.teamId === null || teamIds.has(player.teamId), 'player references an unknown team');
    if (player.status === 'sold') {
      assert(player.teamId && Number.isSafeInteger(player.salePrice) && player.salePrice > 0, 'sold player details are incomplete');
      assert(Number.isSafeInteger(player.sequence) && player.sequence > 0, 'sold player sequence is invalid');
    } else {
      assert(player.teamId === null && player.salePrice === null, 'unsold player cannot have an owner or price');
    }
  }
  if (state.auction.currentPlayerId !== null) assert(playerIds.has(state.auction.currentPlayerId), 'current player does not exist');
  if (state.auction.highestBidTeamId !== null) assert(teamIds.has(state.auction.highestBidTeamId), 'highest bid references an unknown team');
  if (state.auction.highestBid === null) assert(state.auction.highestBidTeamId === null, 'bid team exists without a bid');
  if (state.auction.result === 'live') {
    assert(state.auction.currentPlayerId !== null, 'live result requires a current player');
    const current = state.players.find((p) => p.id === state.auction.currentPlayerId);
    assert(current && current.status === 'current', 'live result player is not current');
  }
  if (state.auction.result === 'sold') {
    const current = state.players.find((p) => p.id === state.auction.currentPlayerId);
    assert(current && current.status === 'sold', 'sold result is inconsistent');
  }
  if (state.auction.result === 'unsold') {
    const current = state.players.find((p) => p.id === state.auction.currentPlayerId);
    assert(current && current.status === 'unsold', 'unsold result is inconsistent');
  }
  const transactionIds = new Set();
  const sequenceIds = new Set();
  for (const tx of state.transactions) {
    assert(tx && typeof tx.id === 'string' && !transactionIds.has(tx.id), 'transaction id is missing or duplicated');
    transactionIds.add(tx.id);
    assert(['sale', 'unsold', 'undo'].includes(tx.type), 'transaction type is invalid');
    assert(Number.isSafeInteger(tx.sequence) && tx.sequence > 0, 'transaction sequence is invalid');
    assert(!sequenceIds.has(tx.sequence), 'transaction sequence is duplicated');
    sequenceIds.add(tx.sequence);
    assert(typeof tx.timestamp === 'string' && !Number.isNaN(Date.parse(tx.timestamp)), 'transaction timestamp is invalid');
    assert(playerIds.has(tx.playerId), 'transaction references an unknown player');
    if (tx.type === 'sale') {
      assert(teamIds.has(tx.teamId) && Number.isSafeInteger(tx.price) && tx.price > 0, 'sale transaction is invalid');
      assert(typeof tx.reversed === 'boolean', 'sale reversal marker is invalid');
    } else if (tx.type === 'unsold') {
      assert(tx.teamId === null, 'unsold transaction must not have a team');
    } else {
      assert(typeof tx.referenceId === 'string' && transactionIds.has(tx.referenceId), 'undo transaction reference is invalid');
    }
  }
  const activeSales = state.transactions.filter((tx) => tx.type === 'sale' && !tx.reversed);
  const activeSaleByPlayer = new Map();
  for (const tx of activeSales) {
    assert(!activeSaleByPlayer.has(tx.playerId), 'player has more than one active sale');
    activeSaleByPlayer.set(tx.playerId, tx);
  }
  for (const player of state.players) {
    if (player.status === 'sold') {
      const sale = activeSaleByPlayer.get(player.id);
      assert(sale && sale.teamId === player.teamId && sale.price === player.salePrice && sale.sequence === player.sequence, 'sold player and sale history disagree');
    } else {
      assert(!activeSaleByPlayer.has(player.id), 'active sale exists for a player who is not sold');
    }
  }
  assert(state.auction.sequence >= Math.max(0, ...state.transactions.map((tx) => tx.sequence)), 'auction sequence is behind history');
  for (const team of state.teams) {
    const finance = calculateTeamFinance(state, team.id);
    assert(finance.remaining >= 0, `team ${team.id} overspent its purse`);
  }
  return true;
}

function calculateTeamFinance(state, teamId) {
  const team = state.teams.find((item) => item.id === teamId);
  if (!team) return null;
  const squad = state.players.filter((player) => player.status === 'sold' && player.teamId === teamId);
  const spent = squad.reduce((sum, player) => sum + player.salePrice, 0);
  return {
    initialPurse: team.initialPurse,
    spent,
    remaining: team.initialPurse - spent,
    purchased: squad.length,
    squad
  };
}

function getRoleCounts(state, teamId) {
  const counts = Object.fromEntries(ROLES.map((role) => [role, 0]));
  for (const player of state.players) {
    if (player.status === 'sold' && player.teamId === teamId) counts[player.role] += 1;
  }
  return counts;
}

function incrementFor(auction, price) {
  for (const tier of auction.bidIncrements || []) {
    if (tier.upTo === null || price <= tier.upTo) return tier.increment;
  }
  return auction.defaultBidIncrement;
}

function canTeamAddPlayer(state, teamId, player, bidAmount = null) {
  const team = state.teams.find((item) => item.id === teamId && item.active);
  if (!team) fail('Choose an active, registered team.');
  const finance = calculateTeamFinance(state, teamId);
  if (bidAmount !== null && bidAmount > finance.remaining) fail(`${team.name} has only ${finance.remaining.toLocaleString('en-IN')} left in its purse.`);
  const roster = finance.squad.length;
  if (state.auction.maxSquadSize !== null && roster >= state.auction.maxSquadSize) {
    fail(`${team.name} has reached the maximum squad size.`);
  }
  const key = player.role.toLowerCase();
  const rule = state.auction.roleRequirements[key];
  const roleCount = getRoleCounts(state, teamId)[player.role];
  if (rule.max !== null && roleCount >= rule.max) fail(`${team.name} has reached its maximum ${player.role.toLowerCase()} count.`);
  return { team, finance };
}

function sanitizeTeamInput(state, input, existing = null) {
  const id = cleanText(input.id ?? existing?.id, 'Team ID', 48, true).toLowerCase();
  if (!ID_PATTERN.test(id)) fail('Team ID may use letters, numbers, hyphens, and underscores (2–48 characters).');
  const name = cleanText(input.name ?? existing?.name, 'Team name', 80, true);
  const initialPurse = asInteger(input.initialPurse ?? existing?.initialPurse ?? state.auction.startingPurse, 'Initial purse', { min: 1 });
  const owner = cleanText(input.owner ?? existing?.owner ?? '', 'Owner or captain', 80);
  const logo = safePhoto(input.logo ?? existing?.logo ?? '');
  const active = input.active === undefined ? (existing?.active ?? true) : input.active === true;
  let pinHash = existing?.pinHash ?? null;
  const pin = String(input.pin ?? '').trim();
  if (pin) {
    if (pin.length < 4 || pin.length > 12 || !/^\d+$/.test(pin)) fail('Team PIN must be 4–12 digits.');
    pinHash = hashPin(pin);
  } else if (input.clearPin === true) {
    pinHash = null;
  }
  return { id, name, owner, logo, initialPurse, active, pinHash };
}

function sanitizePlayerInput(input, existing = null) {
  const id = cleanText(input.id ?? existing?.id ?? makeId('player'), 'Player ID', 48, true).toLowerCase();
  if (!ID_PATTERN.test(id)) fail('Player ID may use letters, numbers, hyphens, and underscores (2–48 characters).');
  const name = cleanText(input.name ?? existing?.name, 'Player name', 100, true);
  const role = normalizedRole(input.role ?? existing?.role);
  if (!role) fail(`Player role must be one of: ${ROLES.join(', ')}.`);
  const basePrice = asInteger(input.basePrice ?? existing?.basePrice, 'Base price', { min: 1 });
  const secondaryRole = cleanText(input.secondaryRole ?? existing?.secondaryRole ?? '', 'Secondary role', 40);
  const stats = cleanText(input.stats ?? existing?.stats ?? '', 'Player stats', 180);
  const category = cleanText(input.category ?? existing?.category ?? '', 'Category', 60);
  const photo = safePhoto(input.photo ?? existing?.photo ?? '');
  return {
    id, name, role, secondaryRole, stats, category, photo,
    basePrice,
    status: existing?.status ?? 'available',
    teamId: existing?.teamId ?? null,
    salePrice: existing?.salePrice ?? null,
    sequence: existing?.sequence ?? null
  };
}

function cleanRoleRequirements(input, previous) {
  const result = {};
  for (const key of ROLE_KEYS) {
    const proposed = input?.[key] ?? previous[key];
    const min = asInteger(proposed.min ?? 0, `${key} minimum`, { min: 0, max: 1000 });
    const max = proposed.max === null || proposed.max === '' || proposed.max === undefined
      ? null
      : asInteger(proposed.max, `${key} maximum`, { min: 0, max: 1000 });
    if (max !== null && max < min) fail(`${key} maximum cannot be lower than its minimum.`);
    result[key] = { min, max };
  }
  return result;
}

function sanitizeSettings(input, current) {
  const next = clone(current);
  if (input.name !== undefined) next.name = cleanText(input.name, 'Auction name', 100, true);
  if (input.currencySymbol !== undefined) next.currencySymbol = cleanText(input.currencySymbol, 'Currency symbol', 6, true);
  if (input.currency !== undefined) next.currency = cleanText(input.currency, 'Currency code', 8, true).toUpperCase();
  if (input.startingPurse !== undefined) next.startingPurse = asInteger(input.startingPurse, 'Default starting purse', { min: 1 });
  if (input.defaultBidIncrement !== undefined) next.defaultBidIncrement = asInteger(input.defaultBidIncrement, 'Default bid increment', { min: 1 });
  if (input.minSquadSize !== undefined) next.minSquadSize = asInteger(input.minSquadSize, 'Minimum squad size', { min: 0, max: 1000 });
  if (input.maxSquadSize !== undefined) {
    next.maxSquadSize = input.maxSquadSize === null || input.maxSquadSize === '' ? null : asInteger(input.maxSquadSize, 'Maximum squad size', { min: 1, max: 1000 });
  }
  if (input.roleRequirements !== undefined) next.roleRequirements = cleanRoleRequirements(input.roleRequirements, current.roleRequirements);
  for (const key of ['showOtherPurses', 'revealNextPlayer', 'allowUnsoldReintroduction', 'allowOverride', 'requireTeamPin']) {
    if (input[key] !== undefined) next[key] = input[key] === true;
  }
  if (input.bidIncrements !== undefined) {
    if (!Array.isArray(input.bidIncrements)) fail('Bid tiers must be provided as a list.');
    next.bidIncrements = input.bidIncrements.map((tier, index) => ({
      upTo: tier.upTo === null || tier.upTo === '' ? null : asInteger(tier.upTo, `Tier ${index + 1} price ceiling`, { min: 1 }),
      increment: asInteger(tier.increment, `Tier ${index + 1} increment`, { min: 1 })
    }));
    if (next.bidIncrements.some((tier, index) => tier.upTo === null && index !== next.bidIncrements.length - 1)) {
      fail('The open-ended bid tier must be the last tier.');
    }
    for (let i = 1; i < next.bidIncrements.length; i += 1) {
      if (next.bidIncrements[i - 1].upTo === null || next.bidIncrements[i].upTo === null || next.bidIncrements[i].upTo <= next.bidIncrements[i - 1].upTo) {
        fail('Bid tier ceilings must be strictly increasing.');
      }
    }
  }
  if (next.maxSquadSize !== null && next.minSquadSize > next.maxSquadSize) fail('Minimum squad size cannot exceed maximum squad size.');
  if (next.requireTeamPin && current.status !== 'not-started') fail('Team PIN requirements cannot be changed after the auction starts.');
  return next;
}

function playerEligibility(state, player) {
  if (!player) return false;
  return player.status === 'available' || (player.status === 'unsold' && state.auction.allowUnsoldReintroduction);
}

function nextSequence(state) {
  state.auction.sequence += 1;
  return state.auction.sequence;
}

function appendAudit(state, action, details = {}) {
  state.audit.push({
    id: makeId('audit'),
    timestamp: new Date().toISOString(),
    action,
    actor: 'admin',
    details
  });
  if (state.audit.length > MAX_HISTORY) state.audit.splice(0, state.audit.length - MAX_HISTORY);
}

function makeTransaction(state, type, details) {
  const tx = {
    id: makeId('tx'),
    sequence: nextSequence(state),
    type,
    timestamp: new Date().toISOString(),
    ...details
  };
  state.transactions.push(tx);
  if (state.transactions.length > MAX_HISTORY) state.transactions.splice(0, state.transactions.length - MAX_HISTORY);
  return tx;
}

class AuctionEngine {
  constructor(initialState, options = {}) {
    validateState(initialState);
    this.state = clone(initialState);
    this.persist = options.persist || (async () => {});
    this.onCommit = options.onCommit || (() => {});
    this.queue = Promise.resolve();
  }

  snapshot() {
    return clone(this.state);
  }

  _mutate(action, details, work) {
    const operation = this.queue.then(async () => {
      const draft = clone(this.state);
      const result = work(draft);
      appendAudit(draft, action, details || {});
      draft.version = this.state.version + 1;
      draft.updatedAt = new Date().toISOString();
      validateState(draft);
      await this.persist(draft);
      this.state = draft;
      try { this.onCommit(this.snapshot()); } catch { /* a UI broadcast failure must not roll back disk state */ }
      return { result, state: this.snapshot() };
    });
    this.queue = operation.catch(() => {});
    return operation;
  }

  addTeam(input) {
    return this._mutate('team.add', { name: input.name }, (state) => {
      if (state.auction.status !== 'not-started') fail('Teams can only be added before the auction starts.');
      const team = sanitizeTeamInput(state, input);
      if ((state.auction.requireTeamPin || !state.auction.showOtherPurses) && team.active && !team.pinHash) fail('Set a PIN before adding an active team while team dashboard PINs are required.');
      if (state.teams.some((item) => item.id === team.id)) fail('That team ID is already in use.');
      if (state.teams.some((item) => item.name.toLowerCase() === team.name.toLowerCase())) fail('That team name is already in use.');
      state.teams.push(team);
      return team.id;
    });
  }

  updateTeam(id, input) {
    return this._mutate('team.update', { id }, (state) => {
      if (state.auction.status !== 'not-started') fail('Team details and purse values are locked after the auction starts.');
      const index = state.teams.findIndex((item) => item.id === id);
      if (index < 0) fail('Team not found.', 404, 'NOT_FOUND');
      const updated = sanitizeTeamInput(state, input, state.teams[index]);
      if ((state.auction.requireTeamPin || !state.auction.showOtherPurses) && updated.active && !updated.pinHash) fail('An active team must keep a PIN while team dashboard PINs are required.');
      if (updated.id !== id && state.teams.some((item) => item.id === updated.id)) fail('That team ID is already in use.');
      if (state.teams.some((item) => item.id !== id && item.name.toLowerCase() === updated.name.toLowerCase())) fail('That team name is already in use.');
      state.teams[index] = updated;
      return updated.id;
    });
  }

  removeTeam(id) {
    return this._mutate('team.remove', { id }, (state) => {
      if (state.auction.status !== 'not-started') fail('Teams can only be removed before the auction starts.');
      const team = state.teams.find((item) => item.id === id);
      if (!team) fail('Team not found.', 404, 'NOT_FOUND');
      if (state.players.some((player) => player.status === 'sold' && player.teamId === id)) fail('This team has completed purchases. Reset or resolve those transactions before removing it.');
      state.teams = state.teams.filter((item) => item.id !== id);
      return true;
    });
  }

  addPlayer(input) {
    return this._mutate('player.add', { name: input.name }, (state) => {
      if (state.auction.status !== 'not-started') fail('Players can only be added before the auction starts.');
      const player = sanitizePlayerInput(input);
      if (state.players.some((item) => item.id === player.id)) fail('That player ID is already in use.');
      state.players.push(player);
      return player.id;
    });
  }

  updatePlayer(id, input) {
    return this._mutate('player.update', { id }, (state) => {
      if (state.auction.status !== 'not-started') fail('Player details are locked after the auction starts.');
      const index = state.players.findIndex((item) => item.id === id);
      if (index < 0) fail('Player not found.', 404, 'NOT_FOUND');
      const updated = sanitizePlayerInput(input, state.players[index]);
      if (updated.id !== id && state.players.some((item) => item.id === updated.id)) fail('That player ID is already in use.');
      state.players[index] = updated;
      return updated.id;
    });
  }

  removePlayer(id) {
    return this._mutate('player.remove', { id }, (state) => {
      if (state.auction.status !== 'not-started') fail('Players can only be removed before the auction starts.');
      const player = state.players.find((item) => item.id === id);
      if (!player) fail('Player not found.', 404, 'NOT_FOUND');
      if (state.transactions.some((tx) => tx.playerId === id)) fail('This player has transaction history and cannot be removed.');
      state.players = state.players.filter((item) => item.id !== id);
      return true;
    });
  }

  importPlayers(rows) {
    return this._mutate('player.import', { count: rows.length }, (state) => {
      if (state.auction.status !== 'not-started') fail('Players can only be imported before the auction starts.');
      if (!Array.isArray(rows) || rows.length === 0) fail('There are no valid player rows to import.');
      const ids = new Set(state.players.map((player) => player.id));
      for (const row of rows) {
        const player = sanitizePlayerInput(row);
        if (ids.has(player.id)) fail(`Duplicate player ID: ${player.id}. Nothing was imported.`);
        ids.add(player.id);
        state.players.push(player);
      }
      return rows.length;
    });
  }

  importTeams(rows) {
    return this._mutate('team.import', { count: rows.length }, (state) => {
      if (state.auction.status !== 'not-started') fail('Teams can only be imported before the auction starts.');
      if (!Array.isArray(rows) || rows.length === 0) fail('There are no valid team rows to import.');
      const ids = new Set(state.teams.map((team) => team.id));
      const names = new Set(state.teams.map((team) => team.name.toLowerCase()));
      for (const row of rows) {
        const team = sanitizeTeamInput(state, row);
        if ((state.auction.requireTeamPin || !state.auction.showOtherPurses) && team.active && !team.pinHash) fail(`Team ${team.name} needs a PIN. Nothing was imported.`);
        if (ids.has(team.id)) fail(`Duplicate team ID: ${team.id}. Nothing was imported.`)
        if (names.has(team.name.toLowerCase())) fail(`Duplicate team name: ${team.name}. Nothing was imported.`);
        ids.add(team.id);
        names.add(team.name.toLowerCase());
        state.teams.push(team);
      }
      return rows.length;
    });
  }

  updateSettings(input) {
    return this._mutate('settings.update', {}, (state) => {
      if (state.auction.status !== 'not-started') fail('Auction rules are locked after the auction starts.');
      state.auction = { ...state.auction, ...sanitizeSettings(input, state.auction) };
      if ((state.auction.requireTeamPin || !state.auction.showOtherPurses) && state.teams.some((team) => team.active && !team.pinHash)) {
        fail('Set a PIN for every active team before hiding purses or requiring team PINs.');
      }
      return true;
    });
  }

  start() {
    return this._mutate('auction.start', {}, (state) => {
      if (state.auction.status !== 'not-started') fail('The auction has already started.');
      if (!state.teams.some((team) => team.active)) fail('Add at least one active team before starting.');
      if (!state.players.length) fail('Add or import players before starting.');
      if ((state.auction.requireTeamPin || !state.auction.showOtherPurses) && state.teams.some((team) => team.active && !team.pinHash)) fail('Every active team needs a PIN before the auction can start.');
      state.auction.status = 'live';
      state.auction.result = 'waiting';
      return true;
    });
  }

  pause() {
    return this._mutate('auction.pause', {}, (state) => {
      if (state.auction.status !== 'live') fail('Only a live auction can be paused.');
      state.auction.status = 'paused';
      return true;
    });
  }

  resume() {
    return this._mutate('auction.resume', {}, (state) => {
      if (state.auction.status !== 'paused') fail('Only a paused auction can be resumed.');
      state.auction.status = 'live';
      return true;
    });
  }

  end() {
    return this._mutate('auction.end', {}, (state) => {
      if (!['live', 'paused'].includes(state.auction.status)) fail('The auction is not running.');
      if (state.auction.result === 'live') fail('Resolve the current player as SOLD or UNSOLD before ending the auction.');
      state.auction.status = 'completed';
      return true;
    });
  }

  selectPlayer(playerId) {
    return this._mutate('player.select', { playerId }, (state) => {
      if (state.auction.status !== 'live') fail('Resume or start the auction before selecting a player.');
      if (state.auction.result === 'live') fail('Finish the current player before selecting the next one.');
      const player = state.players.find((item) => item.id === playerId);
      if (!player || !playerEligibility(state, player)) fail('This player is not eligible for auction.');
      player.status = 'current';
      player.teamId = null;
      player.salePrice = null;
      player.sequence = null;
      state.auction.currentPlayerId = player.id;
      state.auction.result = 'live';
      state.auction.highestBid = null;
      state.auction.highestBidTeamId = null;
      return player.id;
    });
  }

  placeBid(input) {
    return this._mutate('bid.accepted', { teamId: input.teamId, amount: input.amount }, (state) => {
      if (state.auction.status !== 'live') fail('Bids are only accepted while the auction is live.');
      if (state.auction.result !== 'live' || !state.auction.currentPlayerId) fail('Select a player before accepting a bid.');
      const player = state.players.find((item) => item.id === state.auction.currentPlayerId);
      if (!player || player.status !== 'current') fail('The current player is no longer available.');
      const teamId = cleanText(input.teamId, 'Bidding team', 48, true);
      const amount = asInteger(input.amount, 'Bid amount', { min: 1 });
      const override = input.override === true;
      if (override && !state.auction.allowOverride) fail('Bid overrides are disabled in auction settings.');
      const minimum = state.auction.highestBid === null
        ? player.basePrice
        : state.auction.highestBid + incrementFor(state.auction, state.auction.highestBid);
      const increment = incrementFor(state.auction, state.auction.highestBid ?? player.basePrice);
      if (!override && (amount < minimum || (amount - minimum) % increment !== 0)) {
        fail(`Next valid bid is ${minimum.toLocaleString('en-IN')} or a higher amount in increments of ${increment.toLocaleString('en-IN')}.`);
      }
      if (state.auction.highestBid !== null && amount <= state.auction.highestBid) fail('A new bid must be higher than the current highest bid.');
      canTeamAddPlayer(state, teamId, player, amount);
      state.auction.highestBid = amount;
      state.auction.highestBidTeamId = teamId;
      return { amount, teamId };
    });
  }

  sell(input = {}) {
    return this._mutate('player.sold', { teamId: input.teamId || null, price: input.price ?? null }, (state) => {
      if (state.auction.status !== 'live') fail('A sale can only be confirmed while the auction is live.');
      if (state.auction.result !== 'live' || !state.auction.currentPlayerId) fail('There is no active player to sell.');
      const player = state.players.find((item) => item.id === state.auction.currentPlayerId);
      if (!player || player.status !== 'current') fail('The current player has already been finalized.');
      if (state.auction.highestBid === null || !state.auction.highestBidTeamId) fail('Accept a valid bid before confirming a sale.');
      const teamId = cleanText(input.teamId ?? state.auction.highestBidTeamId, 'Winning team', 48, true);
      const price = asInteger(input.price ?? state.auction.highestBid, 'Sale price', { min: player.basePrice });
      if (input.override === true && !state.auction.allowOverride) fail('Sale overrides are disabled in auction settings.');
      const changed = teamId !== state.auction.highestBidTeamId || price !== state.auction.highestBid;
      if (changed && !(input.override === true && state.auction.allowOverride)) {
        fail('The sale must match the accepted highest bid. Enable and confirm an override to change it.');
      }
      const { team } = canTeamAddPlayer(state, teamId, player, price);
      const previousBid = state.auction.highestBid;
      const previousBidTeamId = state.auction.highestBidTeamId;
      const sequence = nextSequence(state);
      player.status = 'sold';
      player.teamId = teamId;
      player.salePrice = price;
      player.sequence = sequence;
      state.auction.result = 'sold';
      state.transactions.push({
        id: makeId('tx'), sequence, type: 'sale', timestamp: new Date().toISOString(),
        playerId: player.id, playerName: player.name, teamId, teamName: team.name,
        price, basePrice: player.basePrice, reversed: false,
        previousStatus: 'current', previousBid, previousBidTeamId
      });
      return { playerId: player.id, teamId, price, sequence };
    });
  }

  markUnsold(input = {}) {
    return this._mutate('player.unsold', { playerId: this.state.auction.currentPlayerId }, (state) => {
      if (state.auction.status !== 'live') fail('A player can only be marked UNSOLD while the auction is live.');
      if (state.auction.result !== 'live' || !state.auction.currentPlayerId) fail('There is no active player to mark UNSOLD.');
      const player = state.players.find((item) => item.id === state.auction.currentPlayerId);
      if (!player || player.status !== 'current') fail('The current player has already been finalized.');
      if (state.auction.highestBid !== null && !(input.override === true && state.auction.allowOverride)) {
        fail('There is an accepted bid. Use the explicitly confirmed override to mark this player UNSOLD.');
      }
      const priorBid = state.auction.highestBid;
      const priorBidTeamId = state.auction.highestBidTeamId;
      const sequence = nextSequence(state);
      player.status = 'unsold';
      player.teamId = null;
      player.salePrice = null;
      player.sequence = sequence;
      state.auction.result = 'unsold';
      state.auction.highestBid = null;
      state.auction.highestBidTeamId = null;
      state.transactions.push({
        id: makeId('tx'), sequence, type: 'unsold', timestamp: new Date().toISOString(),
        playerId: player.id, playerName: player.name, teamId: null, teamName: null,
        price: null, basePrice: player.basePrice, priorBid, priorBidTeamId
      });
      return { playerId: player.id, sequence };
    });
  }

  undoLastSale() {
    return this._mutate('sale.undo', {}, (state) => {
      const last = state.transactions.at(-1);
      if (!last || last.type !== 'sale' || last.reversed) fail('Only the most recent completed sale can be undone. Later transaction history must be resolved first.');
      const otherCurrent = state.players.find((item) => item.status === 'current' && item.id !== last.playerId);
      if (otherCurrent) {
        if (state.auction.highestBid !== null) fail('A different player already has an accepted bid. Finish that player before undoing this sale.');
        const priorResult = state.transactions.slice().reverse().find((tx) => tx.playerId === otherCurrent.id);
        otherCurrent.status = priorResult?.type === 'unsold' ? 'unsold' : 'available';
        otherCurrent.teamId = null;
        otherCurrent.salePrice = null;
        otherCurrent.sequence = null;
      }
      const player = state.players.find((item) => item.id === last.playerId);
      if (!player || player.status !== 'sold' || player.teamId !== last.teamId) fail('The sale no longer matches the current squad records.');
      last.reversed = true;
      player.status = last.previousStatus || 'current';
      player.teamId = null;
      player.salePrice = null;
      player.sequence = null;
      state.auction.currentPlayerId = player.id;
      state.auction.result = 'live';
      state.auction.highestBid = last.previousBid ?? last.price;
      state.auction.highestBidTeamId = last.previousBidTeamId ?? last.teamId;
      const undo = makeTransaction(state, 'undo', {
        playerId: player.id,
        playerName: player.name,
        teamId: last.teamId,
        teamName: last.teamName,
        price: last.price,
        referenceId: last.id
      });
      return { transactionId: undo.id, playerId: player.id };
    });
  }

  changeAdminPin(newPin) {
    return this._mutate('security.admin-pin-changed', {}, (state) => {
      const pin = String(newPin ?? '').trim();
      if (!/^\d{4,12}$/.test(pin)) fail('Administrator PIN must be 4–12 digits.');
      state.security.adminPinHash = hashPin(pin);
      return true;
    });
  }

  resetAuction() {
    return this._mutate('auction.reset', { discardedTransactions: this.state.transactions.length }, (state) => {
      state.auction.status = 'not-started';
      state.auction.result = 'waiting';
      state.auction.currentPlayerId = null;
      state.auction.highestBid = null;
      state.auction.highestBidTeamId = null;
      state.auction.sequence = 0;
      for (const player of state.players) {
        player.status = 'available';
        player.teamId = null;
        player.salePrice = null;
        player.sequence = null;
      }
      state.transactions = [];
      return true;
    });
  }

  async restore(candidate) {
    const operation = this.queue.then(async () => {
      const previous = this.state;
      const draft = clone(candidate);
      if (!draft || typeof draft !== 'object' || !Array.isArray(draft.teams)) fail('Backup JSON is missing the auction team list.', 422, 'INVALID_BACKUP');
      draft.security ||= { adminPinHash: previous.security.adminPinHash };
      draft.security.adminPinHash = previous.security.adminPinHash;
      for (const team of draft.teams) {
        if (!team || typeof team !== 'object') fail('Backup JSON contains an invalid team record.', 422, 'INVALID_BACKUP');
        const old = previous.teams.find((item) => item.id === team.id);
        if (old) team.pinHash = old.pinHash;
        else if (team.pinHash === undefined) team.pinHash = null;
      }
      try { validateState(draft); }
      catch (error) { fail(`Backup data is invalid: ${error.message}`, 422, 'INVALID_BACKUP'); }
      if ((draft.auction.requireTeamPin || !draft.auction.showOtherPurses) && draft.teams.some((team) => team.active && !team.pinHash)) {
        fail('Backup cannot be restored: active teams need PINs while private purse access is enabled.', 422, 'INVALID_BACKUP');
      }
      draft.version = previous.version + 1;
      draft.updatedAt = new Date().toISOString();
      appendAudit(draft, 'data.restore', { replacedVersion: previous.version, restoredVersion: candidate.version });
      validateState(draft);
      await this.persist(draft);
      this.state = draft;
      try { this.onCommit(this.snapshot()); } catch { /* persisted state remains authoritative */ }
      return { result: true, state: this.snapshot() };
    });
    this.queue = operation.catch(() => {});
    return operation;
  }
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  const source = String(text ?? '').replace(/^\uFEFF/, '');
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') { field += '"'; i += 1; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"' && field.length === 0) {
      quoted = true;
    } else if (char === ',') {
      row.push(field); field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[i + 1] === '\n') i += 1;
      row.push(field); field = '';
      if (row.some((cell) => cell.trim() !== '')) rows.push(row);
      row = [];
    } else {
      field += char;
    }
  }
  row.push(field);
  if (row.some((cell) => cell.trim() !== '')) rows.push(row);
  if (quoted) fail('CSV contains an unclosed quoted field.');
  if (!rows.length) fail('CSV file is empty.');
  const headers = rows.shift().map((header) => header.trim().replace(/^\uFEFF/, '').toLowerCase());
  return { headers, rows };
}

function previewPlayerCsv(text, existingPlayers = []) {
  const parsed = parseCsv(text);
  const required = ['id', 'name', 'role', 'baseprice'];
  const missing = required.filter((key) => !parsed.headers.includes(key));
  if (missing.length) fail(`CSV is missing required columns: ${missing.join(', ')}.`);
  const existingIds = new Set(existingPlayers.map((player) => player.id.toLowerCase()));
  const seen = new Set();
  const rows = [];
  const errors = [];
  parsed.rows.forEach((cells, index) => {
    const line = index + 2;
    const record = Object.fromEntries(parsed.headers.map((header, i) => [header, cells[i] ?? '']));
    try {
      const player = sanitizePlayerInput({
        id: record.id,
        name: record.name,
        role: record.role,
        basePrice: record.baseprice,
        photo: record.photo,
        secondaryRole: record.secondaryrole,
        stats: record.stats,
        category: record.category
      });
      if (existingIds.has(player.id.toLowerCase()) || seen.has(player.id.toLowerCase())) fail(`Duplicate player ID “${player.id}”.`);
      seen.add(player.id.toLowerCase());
      rows.push(player);
    } catch (error) {
      errors.push({ line, message: error.message });
    }
  });
  return { rows, errors, totalRows: parsed.rows.length };
}

function previewTeamCsv(text, existingTeams = [], state = createInitialState('scrypt$invalid$invalid')) {
  const parsed = parseCsv(text);
  const purseHeader = parsed.headers.includes('initialpurse') ? 'initialpurse' : 'purse';
  const required = ['id', 'name', purseHeader];
  const missing = required.filter((key) => !parsed.headers.includes(key));
  if (missing.length) fail(`CSV is missing required columns: ${missing.join(', ')}.`);
  const existingIds = new Set(existingTeams.map((team) => team.id.toLowerCase()));
  const existingNames = new Set(existingTeams.map((team) => team.name.toLowerCase()));
  const seenIds = new Set();
  const seenNames = new Set();
  const rows = [];
  const errors = [];
  parsed.rows.forEach((cells, index) => {
    const line = index + 2;
    const record = Object.fromEntries(parsed.headers.map((header, i) => [header, cells[i] ?? '']));
    try {
      let active = true;
      if (String(record.active ?? '').trim()) {
        const activeValue = String(record.active).trim().toLowerCase();
        if (!['true', 'false', 'yes', 'no', '1', '0'].includes(activeValue)) fail('Active must be true or false.');
        active = ['true', 'yes', '1'].includes(activeValue);
      }
      const raw = {
        id: record.id,
        name: record.name,
        owner: record.owner,
        initialPurse: record[purseHeader],
        logo: record.logo,
        pin: record.pin,
        active
      };
      const normalized = sanitizeTeamInput(state, raw);
      const idKey = normalized.id.toLowerCase();
      const nameKey = normalized.name.toLowerCase();
      if (existingIds.has(idKey) || seenIds.has(idKey)) fail(`Duplicate team ID “${normalized.id}”.`);
      if (existingNames.has(nameKey) || seenNames.has(nameKey)) fail(`Duplicate team name “${normalized.name}”.`);
      seenIds.add(idKey);
      seenNames.add(nameKey);
      // The raw PIN remains server-side only and is removed from the preview response.
      rows.push({
        id: normalized.id, name: normalized.name, owner: normalized.owner,
        initialPurse: normalized.initialPurse, logo: normalized.logo,
        active: normalized.active, pin: raw.pin || ''
      });
    } catch (error) {
      errors.push({ line, message: error.message });
    }
  });
  return { rows, errors, totalRows: parsed.rows.length };
}

function publicState(state, viewer = null) {
  const isAdmin = viewer?.role === 'admin';
  const ownTeamId = viewer?.role === 'team' ? viewer.teamId : null;
  const showAllPurses = isAdmin || state.auction.showOtherPurses;
  const teams = state.teams.map((team) => {
    const finance = calculateTeamFinance(state, team.id);
    const expose = showAllPurses || team.id === ownTeamId;
    return {
      id: team.id,
      name: team.name,
      owner: team.owner,
      logo: team.logo,
      active: team.active,
      pinRequired: state.auction.requireTeamPin || !state.auction.showOtherPurses || Boolean(team.pinHash),
      roleCounts: getRoleCounts(state, team.id),
      ...(expose ? { initialPurse: finance.initialPurse, spent: finance.spent, remaining: finance.remaining, purchased: finance.purchased } : {})
    };
  });
  return {
    schemaVersion: state.schemaVersion,
    version: state.version,
    updatedAt: state.updatedAt,
    auction: clone(state.auction),
    teams,
    players: clone(state.players),
    transactions: clone(state.transactions)
  };
}

function buildReport(state) {
  const activeSales = state.transactions.filter((tx) => tx.type === 'sale' && !tx.reversed);
  const soldPlayers = state.players.filter((player) => player.status === 'sold');
  const spend = activeSales.reduce((sum, tx) => sum + tx.price, 0);
  const prices = activeSales.map((tx) => tx.price);
  return {
    auction: {
      name: state.auction.name,
      status: state.auction.status,
      currencySymbol: state.auction.currencySymbol,
      version: state.version,
      generatedAt: new Date().toISOString()
    },
    summary: {
      teams: state.teams.filter((team) => team.active).length,
      players: state.players.length,
      sold: soldPlayers.length,
      unsold: state.players.filter((player) => player.status === 'unsold').length,
      totalExpenditure: spend,
      averageSalePrice: prices.length ? Math.round(spend / prices.length) : 0,
      highestPricedPlayer: [...soldPlayers].sort((a, b) => b.salePrice - a.salePrice)[0] || null
    },
    teams: state.teams.map((team) => {
      const finance = calculateTeamFinance(state, team.id);
      const roleCounts = getRoleCounts(state, team.id);
      return {
        id: team.id, name: team.name, owner: team.owner,
        initialPurse: finance.initialPurse, spent: finance.spent,
        remaining: finance.remaining, squadSize: finance.purchased,
        roleCounts,
        squad: finance.squad.map((player) => ({
          id: player.id, name: player.name, role: player.role,
          price: player.salePrice, sequence: player.sequence, photo: player.photo
        }))
      };
    }),
    unsoldPlayers: state.players.filter((player) => player.status === 'unsold').map((player) => ({
      id: player.id, name: player.name, role: player.role, basePrice: player.basePrice, sequence: player.sequence
    })),
    transactions: clone(state.transactions)
  };
}

module.exports = {
  AuctionEngine,
  AuctionError,
  ROLES,
  ROLE_KEYS,
  PLAYER_STATUSES,
  createInitialState,
  validateState,
  calculateTeamFinance,
  getRoleCounts,
  incrementFor,
  normalizedRole,
  previewPlayerCsv,
  previewTeamCsv,
  publicState,
  buildReport,
  makeId,
  fail
};
