'use strict';

const App = {
  state: null, session: null, network: null, socket: null, connected: false,
  connections: [], audit: [], report: null, playerSearch: '', playerRole: 'all', playerStatus: 'all', playerCategory: 'all',
  queueSearch: '', queueRole: 'all', queueCategory: 'all', teamSearch: '', playerSort: 'name', importKind: '',
  importText: '', importPreview: null, reportLoading: false, renderedPath: null
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const root = $('#app');
const modal = $('#modal');

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}
function appState() {
  return App.state || { version: 0, updatedAt: new Date().toISOString(), auction: { name: 'Auction Premier League', status: 'not-started', result: 'waiting', currencySymbol: '₹', startingPurse: 10000000, defaultBidIncrement: 100000, bidIncrements: [], minSquadSize: 0, maxSquadSize: null, roleRequirements: { batter: { min: 0, max: null }, bowler: { min: 0, max: null }, 'all-rounder': { min: 0, max: null }, wicketkeeper: { min: 0, max: null } }, showOtherPurses: true, revealNextPlayer: false, allowUnsoldReintroduction: false, allowOverride: true, requireTeamPin: false, currentPlayerId: null, highestBid: null, highestBidTeamId: null, sequence: 0 }, teams: [], players: [], transactions: [] };
}
function money(value, auction = appState().auction) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${auction.currencySymbol || '₹'}${Math.round(number).toLocaleString('en-IN')}`;
}
function number(value) { return Number(value || 0).toLocaleString('en-IN'); }
function dateTime(value, includeDate = true) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-IN', includeDate ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}
function timeAgo(value) { return value ? `Updated ${dateTime(value, false)}` : 'Waiting for first update'; }
function teamById(id) { return appState().teams.find((team) => team.id === id) || null; }
function playerById(id) { return appState().players.find((player) => player.id === id) || null; }
function initials(value) {
  const parts = String(value || '').trim().split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts.at(-1)[0] : (parts[0] || 'APL').slice(0, 3)).toUpperCase();
}
function logoMarkup(team, className = 'team-logo') {
  const name = team?.name || 'Team';
  return `<span class="${className}">${team?.logo ? `<img src="${esc(team.logo)}" alt="${esc(name)} logo">` : esc(initials(name))}</span>`;
}
function photoMarkup(player, className = 'player-photo') {
  const name = player?.name || 'Player';
  return `<div class="${className}">${player?.photo ? `<img src="${esc(player.photo)}" alt="${esc(name)}" loading="lazy">` : `<span class="photo-placeholder">${esc(initials(name))}</span>`}</div>`;
}
function statusClass(status) { return String(status || 'not-started').toLowerCase().replace(/[^a-z-]/g, '-'); }
function statusText(status) {
  return ({ 'not-started': 'Not started', live: 'Live', paused: 'Paused', completed: 'Completed', available: 'Available', current: 'On the block', sold: 'Sold', unsold: 'Unsold', waiting: 'Waiting' })[status] || status || 'Unknown';
}
function pill(status, text = statusText(status)) { return `<span class="status-pill ${statusClass(status)}">${esc(text)}</span>`; }
function toast(message, type = 'success') {
  const stack = $('#toast-stack');
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.innerHTML = `<span class="toast-mark">${type === 'error' ? '!' : '✓'}</span><span>${esc(message)}</span>`;
  stack.append(node);
  setTimeout(() => node.remove(), 4300);
}
async function request(url, options = {}) {
  const init = { credentials: 'same-origin', ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== 'string' && !(options.body instanceof Blob)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }
  let response;
  try { response = await fetch(url, init); }
  catch { throw new Error('Could not reach the local auction server. Check the Wi-Fi connection and server window.'); }
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload?.error || `Request failed (${response.status}).`);
  return payload;
}
async function refreshState() {
  const state = await request('/api/state');
  if (!App.state || state.version >= App.state.version) App.state = state;
  render();
  return state;
}
async function refreshSession() {
  const result = await request('/api/session');
  App.session = result.authenticated ? result.user : null;
  return App.session;
}
async function refreshNetwork() { try { App.network = await request('/api/network'); } catch { App.network = null; } }
function startSocket(force = false) {
  if (!window.io || (App.socket && !force)) return;
  if (App.socket) App.socket.disconnect();
  App.socket = window.io({ transports: ['websocket', 'polling'], tryAllTransports: true, reconnection: true, reconnectionDelay: 700, reconnectionDelayMax: 5000, timeout: 7000 });
  App.socket.on('connect', async () => {
    App.connected = true; render();
    try { await refreshState(); } catch { /* connection indicator shows recovery state */ }
    if (App.session?.role === 'admin') refreshConnections();
  });
  App.socket.on('disconnect', () => { App.connected = false; render(); });
  App.socket.on('connect_error', () => { App.connected = false; render(); });
  App.socket.on('state:update', (state) => {
    if (!App.state || state.version >= App.state.version) {
      App.state = state; render();
      if (App.session?.role === 'admin' && location.pathname === '/report') refreshReport();
    }
  });
  App.socket.on('connections:update', (devices) => { App.connections = devices || []; if (App.session?.role === 'admin') render(); });
}
async function refreshConnections() {
  if (App.session?.role !== 'admin') return;
  try { App.connections = (await request('/api/admin/connections')).devices || []; render(); } catch { /* session may have expired */ }
}
function reconnectSocket() { startSocket(true); }
function navigate(path) {
  if (location.pathname !== path) history.pushState({}, '', path);
  render(); window.scrollTo({ top: 0, behavior: 'smooth' });
  if (path === '/history' && App.session?.role === 'admin') refreshAudit();
  if (path === '/report' && App.session?.role === 'admin') refreshReport();
}
async function runAdminAction(url, body, successMessage) {
  try {
    const result = await request(url, { method: 'POST', body: body || {} });
    await refreshState();
    if (location.pathname === '/history') await refreshAudit();
    if (location.pathname === '/report') await refreshReport();
    if (successMessage) toast(successMessage);
    return result;
  } catch (error) { toast(error.message, 'error'); return null; }
}
function confirmDialog(title, copy, confirmText = 'Confirm', danger = false) {
  return new Promise((resolve) => {
    if (modal.open) modal.close();
    modal.className = 'modal';
    modal.innerHTML = `<form method="dialog" class="confirm-form"><div class="modal-head"><div><h2>${esc(title)}</h2><p>APL administrator confirmation</p></div><button class="modal-close" value="cancel" aria-label="Close">×</button></div><div class="modal-body"><p class="confirm-copy">${esc(copy)}</p></div><div class="modal-footer"><button class="btn btn-quiet" value="cancel">Cancel</button><button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" value="confirm">${esc(confirmText)}</button></div></form>`;
    modal.addEventListener('close', () => resolve(modal.returnValue === 'confirm'), { once: true });
    modal.showModal();
  });
}
function openDialog(html, wide = false) {
  modal.className = `modal${wide ? ' modal-wide' : ''}`;
  modal.innerHTML = html;
  if (!modal.open) modal.showModal();
}
function publicHeader(extra = '') {
  return `<header class="app-topbar"><a class="brand-lockup" href="/" data-nav="/" aria-label="APL home"><span class="brand-mark">APL</span><span><strong>Auction Premier League</strong><span>Live auction management</span></span></a><nav class="top-actions"><a class="nav-link" href="/display" data-nav="/display">◉ <span>Live display</span></a><a class="nav-link" href="/teams" data-nav="/teams">▦ <span>Team dashboards</span></a>${extra}</nav></header>`;
}
function renderLanding() {
  const addresses = App.network?.lanUrls || [];
  const lanHtml = addresses.length ? addresses.map((url) => `<span class="url-chip">${esc(url)}</span>`).join('') : `<span class="url-chip">http://&lt;host-laptop-ip&gt;:${esc(App.network?.port || '3000')}</span>`;
  root.innerHTML = `<main class="landing">${publicHeader(`<a class="nav-link" href="/admin" data-nav="/admin">Operator sign in</a>`)}
    <section class="landing-hero"><div class="hero-copy"><span class="hero-tag"><span class="live-dot"></span> Local network · no cloud required</span><h1>The room is live.<br><span>The auction is in sync.</span></h1><p>One operator. One authoritative auction. Every bid, squad and purse updated instantly across the projector and team phones — stored on your laptop, ready for offline play.</p><div class="hero-actions"><a class="btn btn-primary" href="/admin" data-nav="/admin">Open operator console <span>↗</span></a><a class="btn btn-quiet" href="/display" data-nav="/display">View projector display <span>↗</span></a><a class="btn btn-quiet" href="/teams" data-nav="/teams">Team dashboards</a></div><div class="hero-note"><span class="connection-dot" style="background:var(--green)"></span> Data stays on this host laptop. Participants connect over the same Wi-Fi.</div></div>
      <div class="hero-visual" aria-hidden="true"><div class="hero-orbit"></div><div class="hero-stadium"><div class="stadium-top"><span>APL · Player auction</span><span class="status-pill live"><span class="live-dot"></span> Live</span></div><div class="stadium-score"><div><strong>${App.state?.auction?.highestBid ? esc(money(App.state.auction.highestBid)) : '₹—'}</strong><span>Current highest bid</span></div><b>${App.state?.players?.filter((p) => p.status === 'sold').length || 0} sold</b></div><div class="stadium-player"><div class="stadium-avatar">${esc(initials(playerById(appState().auction.currentPlayerId)?.name || 'APL'))}</div><div><strong>${esc(playerById(appState().auction.currentPlayerId)?.name || 'Ready for the first player')}</strong><span>${esc(statusText(appState().auction.status))} · live sync on</span></div></div></div></div>
    </section><section class="landing-lan"><div class="lan-card"><div class="lan-card-main"><div class="lan-icon">⌁</div><div><strong>Connect on your local network</strong><p>Keep the host laptop and all phones on the same Wi-Fi. Use one of these addresses:</p></div></div><div class="lan-addresses">${lanHtml}</div></div></section>
    <section class="home-grid"><article class="home-feature"><b>One source of truth</b><p>Server-validated bids and sales are broadcast instantly to every connected screen.</p></article><article class="home-feature"><b>Runs on your LAN</b><p>No cloud account, internet connection, API key or external database is needed during auction day.</p></article><article class="home-feature"><b>Local recovery</b><p>Committed changes are atomically saved to JSON, with rotating timestamped backups.</p></article></section><footer class="home-footer"><span>Auction Premier League · Live Auction Management System</span><span>APL v1.0 · LAN ready</span></footer></main>`;
}
function renderAdminLogin() {
  const wrongRole = App.session && App.session.role !== 'admin';
  const requestedPath = ['/admin','/players','/team-management','/settings','/history','/report'].includes(location.pathname) ? location.pathname : '/admin';
  root.innerHTML = `<main class="auth-wrap"><section class="auth-card"><a class="brand-mark" href="/" data-nav="/">APL</a><div class="eyebrow">Authorized operator</div><h1>Admin sign in</h1><p>Enter the locally configured administrator PIN to manage teams, players, bidding and auction data.</p>${wrongRole ? `<div class="form-note">You are signed in to a team dashboard. <button class="text-button" data-action="logout">Sign out</button> before opening the operator console.</div>` : ''}<form id="admin-login-form"><input type="hidden" name="next" value="${esc(requestedPath)}"><div class="field"><label for="admin-pin">Administrator PIN</label><input id="admin-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" autocomplete="current-password" required autofocus placeholder="4–12 digits"></div><div class="form-actions"><button class="btn btn-primary btn-block" type="submit">Unlock operator console <span>→</span></button></div></form><div class="auth-foot"><a class="text-button" href="/" data-nav="/">← Back to APL</a><span>Local server only</span></div><div class="form-note">On first start, use the default PIN documented in the local README. Change it from <em>Admin → Settings → Security</em> before the event.</div></section></main>`;
}
function adminNavLink(href, label, icon, active) { return `<a href="${href}" data-nav="${href}" class="${active === href ? 'active' : ''}"><span class="nav-icon">${icon}</span>${label}</a>`; }
function adminShell(content, title, subtitle, active) {
  const auction = appState().auction;
  return `<div class="admin-shell"><aside class="admin-sidebar"><a href="/admin" data-nav="/admin" class="sidebar-brand"><span class="brand-mark">APL</span><span><b>Auction Premier League</b><small>Operator desk</small></span></a><div><div class="sidebar-section-label">Auction</div><nav class="sidebar-nav">${adminNavLink('/admin', 'Live control', '◉', active)}${adminNavLink('/players', 'Player pool', '♙', active)}${adminNavLink('/team-management', 'Teams', '▦', active)}${adminNavLink('/settings', 'Settings', '⚙', active)}${adminNavLink('/history', 'History', '≋', active)}${adminNavLink('/report', 'Final report', '▤', active)}</nav></div><div class="sidebar-spacer"></div><div class="sidebar-local"><strong><span class="connection-dot" style="background:var(--green)"></span> Local network</strong><p>No external services. Auction data is saved on this host laptop.</p></div><div class="sidebar-user"><div><strong>Administrator</strong><span>${App.connections.length} connected device${App.connections.length === 1 ? '' : 's'}</span></div><button class="text-button" data-action="logout">Sign out</button></div></aside>
    <main class="admin-main"><header class="admin-header"><div class="admin-heading"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="admin-header-actions"><span class="connection-pill ${App.connected ? 'online' : 'offline'}"><i class="connection-dot"></i>${App.connected ? 'Live sync' : 'Reconnecting'}</span><span class="status-pill ${statusClass(auction.status)}">${esc(statusText(auction.status))}</span><a class="btn btn-quiet btn-sm" href="/display" data-nav="/display">Open display ↗</a></div></header><section class="admin-content">${content}</section></main></div>`;
}
function countStats() {
  const state = appState();
  return { teams: state.teams.filter((team) => team.active).length, players: state.players.length, sold: state.players.filter((player) => player.status === 'sold').length, unsold: state.players.filter((player) => player.status === 'unsold').length, remaining: state.players.filter((player) => player.status === 'available').length, devices: App.connections.length };
}
function statsBar() {
  const stats = countStats();
  return `<div class="stat-grid"><div class="stat-card"><span>Participating teams</span><b>${number(stats.teams)}</b><small>Active franchises</small></div><div class="stat-card"><span>Player pool</span><b>${number(stats.players)}</b><small>Registered players</small></div><div class="stat-card"><span>Players sold</span><b>${number(stats.sold)}</b><small>Completed purchases</small></div><div class="stat-card"><span>Players unsold</span><b>${number(stats.unsold)}</b><small>Current unsold pool</small></div><div class="stat-card"><span>Players remaining</span><b>${number(stats.remaining)}</b><small>Not yet auctioned</small></div><div class="stat-card"><span>Connected devices</span><b>${number(stats.devices)}</b><small>${App.connected ? 'Server connection healthy' : 'Waiting to reconnect'}</small></div></div>`;
}
function eligiblePlayers() { return appState().players.filter((player) => player.status === 'available' || (player.status === 'unsold' && appState().auction.allowUnsoldReintroduction)); }
function currentPlayer() { return playerById(appState().auction.currentPlayerId); }
function renderPlayerCard(player) {
  if (!player) return `<div class="empty-player"><div><div class="empty-player-mark">♙</div><h3>No player is on the block</h3><p>Start the auction, then select an eligible player from the queue. The projector updates as soon as you select them.</p></div></div>`;
  const auction = appState().auction;
  const leader = teamById(auction.highestBidTeamId);
  return `<div class="current-player-card">${photoMarkup(player)}<div class="player-info"><div class="eyebrow">${auction.result === 'live' ? 'Current player' : `Auction result · ${statusText(auction.result)}`}</div><h2>${esc(player.name)}</h2><div class="player-meta"><span class="pill">${esc(player.role)}</span>${player.category ? `<span class="pill">${esc(player.category)}</span>` : ''}${player.secondaryRole ? `<span class="pill">${esc(player.secondaryRole)}</span>` : ''}</div>${player.stats ? `<p class="player-stats">${esc(player.stats)}</p>` : ''}<div class="price-strip"><div class="price-box"><span>Base price</span><b>${money(player.basePrice)}</b></div><div class="price-box highest"><span>Highest bid</span><b>${auction.highestBid === null ? '—' : money(auction.highestBid)}</b></div></div><div class="leader-line">${leader ? `${logoMarkup(leader)} <span>Leading team <strong>${esc(leader.name)}</strong></span>` : '<span>No bid has been recorded yet</span>'}</div></div></div>`;
}
function bidIncrement(price) {
  const auction = appState().auction;
  for (const tier of auction.bidIncrements || []) if (tier.upTo === null || price <= tier.upTo) return tier.increment;
  return auction.defaultBidIncrement;
}
function renderBidControls(player) {
  const auction = appState().auction;
  const canBid = Boolean(player && auction.status === 'live' && auction.result === 'live');
  const teams = appState().teams.filter((team) => team.active);
  if (!canBid) return `<div class="bid-control"><div class="bid-control-head"><b>Bidding controls</b><span>${esc(statusText(auction.status))}</span></div><p class="control-note">${player ? 'Resume the auction to continue bidding.' : 'Select a player to activate bid entry.'}</p></div>`;
  const defaultTeam = auction.highestBidTeamId || teams[0]?.id || '';
  const defaultAmount = auction.highestBid === null ? player.basePrice : auction.highestBid;
  return `<form id="bid-form" class="bid-control"><div class="bid-control-head"><b>Bidding controls</b><span>Drafts are not committed until confirmed</span></div><div class="control-row"><div class="field"><label for="bid-team">Bidding team</label><select id="bid-team" name="teamId" ${teams.length ? '' : 'disabled'}>${teams.length ? teams.map((team) => `<option value="${esc(team.id)}" ${team.id === defaultTeam ? 'selected' : ''}>${esc(team.name)}</option>`).join('') : '<option>No active teams</option>'}</select></div><div class="field"><label for="bid-amount">Bid amount (${esc(auction.currencySymbol)})</label><input id="bid-amount" class="bid-value" name="amount" type="number" min="${player.basePrice}" step="1" value="${defaultAmount}" inputmode="numeric" required></div><button class="btn btn-quiet" type="button" data-action="increment-bid" title="Increase draft bid by the configured increment">+ Increment</button></div>${auction.allowOverride ? `<label class="checkbox-line" style="margin-top:10px"><input type="checkbox" name="override"><span>Authorized increment override for this bid</span></label>` : ''}<div class="bid-actions"><button class="btn btn-primary" type="submit">Confirm bid</button><button class="btn btn-quiet" type="button" data-action="cancel-bid">Cancel / reset draft</button><span class="control-note">Next valid amount is checked by the server.</span></div><div class="result-actions"><button class="btn btn-sold" type="button" data-action="sell-player" ${auction.highestBid === null ? 'disabled' : ''}>✓ Mark SOLD</button><button class="btn btn-unsold" type="button" data-action="mark-unsold">Mark UNSOLD</button></div><p class="control-note">Money is not deducted for a provisional bid. It is deducted only after a sale is committed.</p></form>`;
}
function recentSaleRows(limit = 6) {
  const transactions = appState().transactions.filter((tx) => tx.type === 'sale').slice().reverse().slice(0, limit);
  if (!transactions.length) return `<div class="empty-state"><b>No completed sales yet</b><p>Confirmed purchases will appear here as the auction progresses.</p></div>`;
  return `<div class="sale-list">${transactions.map((tx) => `<div class="recent-sale-row"><span class="sale-token">${tx.reversed ? '↺' : 'S'}</span><div><strong>${esc(tx.playerName)}</strong><span>${esc(tx.teamName || teamById(tx.teamId)?.name || 'Unknown team')}${tx.reversed ? ' · sale reversed' : ''}</span></div><b class="nowrap">${money(tx.price)}</b></div>`).join('')}</div>`;
}
function renderQueue() {
  const search = App.queueSearch.toLowerCase();
  const queue = eligiblePlayers().filter((player) => {
    const matches = `${player.name} ${player.id} ${player.role} ${player.category || ''}`.toLowerCase().includes(search);
    return matches && (App.queueRole === 'all' || player.role === App.queueRole) && (App.queueCategory === 'all' || player.category === App.queueCategory);
  });
  if (!queue.length) return `<div class="empty-state"><b>${eligiblePlayers().length ? 'No players match these queue filters' : 'Queue is clear'}</b><p>${eligiblePlayers().length ? 'Change the search, role or category filters.' : appState().auction.allowUnsoldReintroduction ? 'All players have been auctioned.' : 'No eligible players remain in the pool.'}</p></div>`;
  return `<div class="queue-list">${queue.map((player, index) => `<div class="queue-row"><span class="queue-number">${String(index + 1).padStart(2, '0')}</span><div class="queue-player"><strong>${esc(player.name)}</strong><span>${esc(player.role)}${player.category ? ` · ${esc(player.category)}` : ''} · Base ${money(player.basePrice)}${player.status === 'unsold' ? ' · Returning unsold' : ''}</span></div><button class="btn btn-quiet btn-sm" data-action="select-player" data-id="${esc(player.id)}" ${appState().auction.status !== 'live' || appState().auction.result === 'live' ? 'disabled' : ''}>Select</button></div>`).join('')}</div>`;
}
function auctionControls() {
  const status = appState().auction.status;
  if (status === 'not-started') return `<button class="btn btn-primary" data-action="start-auction" ${!appState().teams.some((team) => team.active) || !appState().players.length ? 'disabled' : ''}>Start auction</button>`;
  if (status === 'live') return `<button class="btn btn-gold" data-action="pause-auction">Ⅱ Pause</button><button class="btn btn-danger btn-sm" data-action="end-auction">End auction</button>`;
  if (status === 'paused') return `<button class="btn btn-primary" data-action="resume-auction">▶ Resume</button><button class="btn btn-danger btn-sm" data-action="end-auction">End auction</button>`;
  return `<button class="btn btn-quiet btn-sm" data-action="reset-auction">Reset for a new run</button>`;
}
function renderConnections() {
  if (!App.connections.length) return `<div class="empty-state" style="padding:18px 10px"><b>No connected devices yet</b><p>Open /display or a team dashboard on a device connected to this Wi-Fi.</p></div>`;
  return `<div class="queue-list">${App.connections.slice(0, 8).map((device) => `<div class="queue-row"><span class="queue-number">⌁</span><div class="queue-player"><strong>${esc(device.label)}</strong><span>${esc(device.role)} · connected ${dateTime(device.connectedAt, false)}${device.address ? ` · ${esc(device.address)}` : ''}</span></div><span class="status-pill live">Online</span></div>`).join('')}</div>`;
}
function renderOverview() {
  const player = currentPlayer();
  const auction = appState().auction;
  const last = appState().transactions.at(-1);
  const canUndo = last?.type === 'sale' && !last.reversed;
  const content = `${statsBar()}<div class="section-heading"><div><h2>Live auction desk</h2><p>Fast controls for the operator. Every accepted change is validated and saved on this laptop.</p></div><div class="btn-row">${auctionControls()}${canUndo ? `<button class="btn btn-quiet btn-sm" data-action="undo-sale">↶ Undo last sale</button>` : ''}${auction.status !== 'not-started' ? `<button class="btn btn-quiet btn-sm" data-action="reset-auction">Reset auction</button>` : ''}</div></div><div class="admin-grid"><div class="admin-stack"><section class="panel"><div class="panel-head"><div class="panel-title-wrap"><span class="panel-index">01</span><div><h2>Current player</h2><p>Selection, bid entry and final result</p></div></div><span class="status-pill ${statusClass(auction.result)}">${esc(statusText(auction.result))}</span></div><div class="panel-body">${renderPlayerCard(player)}${renderBidControls(player)}</div></section><section class="panel"><div class="panel-head"><div class="panel-title-wrap"><span class="panel-index">02</span><div><h2>Player queue</h2><p>${number(eligiblePlayers().length)} eligible player${eligiblePlayers().length === 1 ? '' : 's'} remaining</p></div></div><a class="text-button" href="/players" data-nav="/players">Manage pool →</a></div><div class="panel-body compact"><form id="queue-search-form" class="filters" style="margin-bottom:10px"><input class="search-input search-field" name="query" value="${esc(App.queueSearch)}" placeholder="Search next player"><select class="select-control" name="role"><option value="all">All roles</option>${['Batter','Bowler','All-rounder','Wicketkeeper'].map((role) => `<option value="${role}" ${App.queueRole === role ? 'selected' : ''}>${role}</option>`).join('')}</select><select class="select-control" name="category"><option value="all">All categories</option>${[...new Set(appState().players.map((player) => player.category).filter(Boolean))].sort().map((category) => `<option value="${esc(category)}" ${App.queueCategory === category ? 'selected' : ''}>${esc(category)}</option>`).join('')}</select><button class="btn btn-quiet btn-sm" type="submit">Filter</button></form>${renderQueue()}</div></section></div><div class="admin-stack"><section class="panel"><div class="panel-head"><div class="panel-title-wrap"><span class="panel-index">03</span><div><h2>Recent results</h2><p>Latest completed transactions</p></div></div><a class="text-button" href="/history" data-nav="/history">Full history →</a></div><div class="panel-body compact">${recentSaleRows(6)}</div></section><section class="panel"><div class="panel-head"><div class="panel-title-wrap"><span class="panel-index">04</span><div><h2>Connected devices</h2><p>${number(App.connections.length)} live connection${App.connections.length === 1 ? '' : 's'}</p></div></div><span class="connection-pill ${App.connected ? 'online' : 'offline'}"><i class="connection-dot"></i>${App.connected ? 'Server online' : 'Reconnecting'}</span></div><div class="panel-body compact">${renderConnections()}</div></section><section class="panel"><div class="panel-head"><div class="panel-title-wrap"><span class="panel-index">05</span><div><h2>Live operation notes</h2><p>Keep the room moving smoothly</p></div></div></div><div class="panel-body"><div class="setting-toggle"><div><strong>Next player</strong><small>Select manually after each SOLD or UNSOLD result. The result stays on the projector until you advance.</small></div></div><div class="setting-toggle"><div><strong>Keyboard friendly</strong><small>Tab between controls. Use the increment button to draft a normal next bid; sales always require confirmation.</small></div></div><div class="setting-toggle"><div><strong>Last saved</strong><small>Version ${number(appState().version)} · ${esc(timeAgo(appState().updatedAt))}</small></div></div></div></section></div></div>`;
  return adminShell(content, 'Live control', 'Auction overview and bid console', '/admin');
}

function playerStatusFilter(player) {
  if (App.playerStatus === 'all') return true;
  if (App.playerStatus === 'available') return player.status === 'available' || (player.status === 'unsold' && appState().auction.allowUnsoldReintroduction);
  return player.status === App.playerStatus;
}
function playerTableRows() {
  const query = App.playerSearch.toLowerCase();
  const filtered = appState().players.filter((player) => {
    const matchQuery = !query || `${player.id} ${player.name} ${player.role} ${player.category}`.toLowerCase().includes(query);
    const matchCategory = App.playerCategory === 'all' || (player.category || '') === App.playerCategory;
    return matchQuery && (App.playerRole === 'all' || player.role === App.playerRole) && matchCategory && playerStatusFilter(player);
  });
  filtered.sort((a, b) => App.playerSort === 'price' ? a.basePrice - b.basePrice : App.playerSort === 'role' ? a.role.localeCompare(b.role) || a.name.localeCompare(b.name) : a.name.localeCompare(b.name));
  if (!filtered.length) return `<tr><td colspan="7"><div class="empty-state"><b>No players match these filters</b><p>Change the search or add a player to the pool.</p></div></td></tr>`;
  return filtered.map((player) => `<tr><td><strong>${esc(player.name)}</strong><small>${esc(player.id)}${player.category ? ` · ${esc(player.category)}` : ''}</small></td><td>${esc(player.role)}</td><td class="num">${money(player.basePrice)}</td><td>${pill(player.status)}</td><td>${player.teamId ? esc(teamById(player.teamId)?.name || 'Team') : '—'}</td><td class="num">${player.salePrice ? money(player.salePrice) : '—'}</td><td><div class="row-actions"><button class="btn btn-quiet btn-sm" data-action="edit-player" data-id="${esc(player.id)}" ${appState().auction.status !== 'not-started' ? 'disabled' : ''}>Edit</button><button class="btn btn-danger btn-sm" data-action="delete-player" data-id="${esc(player.id)}" ${appState().auction.status !== 'not-started' ? 'disabled' : ''}>×</button></div></td></tr>`).join('');
}
function importPanel(kind) {
  const isPlayers = kind === 'players';
  const preview = App.importKind === kind ? App.importPreview : null;
  const fileTextExists = App.importKind === kind && Boolean(App.importText);
  const sampleUrl = isPlayers ? '/samples/players-demo.csv' : '/samples/teams-demo.csv';
  const templateUrl = isPlayers ? '/samples/players-template.csv' : '/samples/teams-template.csv';
  return `<section class="panel" style="margin-top:14px"><div class="panel-head"><div><h2>Import ${isPlayers ? 'players' : 'teams'} from CSV</h2><p>Validation runs before anything is added. Imports are all-or-nothing.</p></div><div class="panel-tools"><a class="text-button" href="${templateUrl}" download>Template</a><a class="text-button" href="${sampleUrl}" download>Sample data</a></div></div><div class="panel-body"><div class="form-grid"><div class="field span-2"><label for="${kind}-csv">Choose CSV file</label><input id="${kind}-csv" type="file" accept=".csv,text/csv" data-import-kind="${kind}"><small class="field-help">${isPlayers ? 'Required: id, name, role, basePrice. Roles: Batter, Bowler, All-rounder, Wicketkeeper.' : 'Required: id, name, initialPurse. Optional: owner, active, logo, pin.'}</small></div></div>${fileTextExists ? `<div class="warning-box" style="margin-top:12px">${esc(preview ? `Checked ${preview.totalRows} CSV rows.` : 'Reading and validating CSV…')}</div>` : ''}${preview?.errors?.length ? `<div class="warning-box"><strong>${preview.errors.length} validation error${preview.errors.length === 1 ? '' : 's'} — no rows will be imported.</strong><ul>${preview.errors.map((item) => `<li>Line ${item.line}: ${esc(item.message)}</li>`).join('')}</ul></div>` : ''}${preview && !preview.errors.length ? `<div class="form-note" style="margin-top:12px">${number(preview.rows.length)} valid ${kind} rows ready. No changes have been committed yet.</div>` : ''}${fileTextExists ? `<div class="form-actions"><button class="btn btn-quiet" data-action="cancel-import">Cancel import</button>${preview && !preview.errors.length && preview.rows.length ? `<button class="btn btn-primary" data-action="commit-import" data-kind="${kind}">Import ${number(preview.rows.length)} ${kind}</button>` : ''}</div>` : ''}</div></section>`;
}
function renderPlayersPage() {
  const locked = appState().auction.status !== 'not-started';
  const content = `<div class="section-heading"><div><h2>Player pool</h2><p>Add, edit, search and validate player records before the auction starts.</p></div><div class="btn-row"><a class="btn btn-quiet btn-sm" href="/api/admin/export/players.csv">Export CSV</a><button class="btn btn-primary" data-action="add-player" ${locked ? 'disabled' : ''}>＋ Add player</button></div></div>${locked ? `<div class="form-note" style="margin:0 0 13px">Player records are locked because the auction has started. Export remains available.</div>` : ''}<section class="panel"><div class="panel-head"><div><h2>Registered players</h2><p>${number(appState().players.length)} players · ${number(eligiblePlayers().length)} eligible for auction</p></div><form id="player-search-form" class="filters"><input class="search-input search-field" name="query" value="${esc(App.playerSearch)}" placeholder="Search name or ID"><select class="select-control" name="role"><option value="all">All roles</option>${['Batter','Bowler','All-rounder','Wicketkeeper'].map((role) => `<option value="${role}" ${App.playerRole === role ? 'selected' : ''}>${role}</option>`).join('')}</select><select class="select-control" name="category"><option value="all">All categories</option>${[...new Set(appState().players.map((player) => player.category).filter(Boolean))].sort().map((category) => `<option value="${esc(category)}" ${App.playerCategory === category ? 'selected' : ''}>${esc(category)}</option>`).join('')}</select><select class="select-control" name="status"><option value="all" ${App.playerStatus === 'all' ? 'selected' : ''}>All statuses</option><option value="available" ${App.playerStatus === 'available' ? 'selected' : ''}>Available</option><option value="sold" ${App.playerStatus === 'sold' ? 'selected' : ''}>Sold</option><option value="unsold" ${App.playerStatus === 'unsold' ? 'selected' : ''}>Unsold</option></select><button class="btn btn-quiet btn-sm" type="submit">Filter</button></form></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Player</th><th>Primary role</th><th class="num">Base price</th><th>Status</th><th>Team</th><th class="num">Sale price</th><th></th></tr></thead><tbody>${playerTableRows()}</tbody></table></div></section>${importPanel('players')}`;
  return adminShell(content, 'Player pool', 'Player database and CSV import', '/players');
}
function teamTableCard(team) {
  const terms = `${team.name} ${team.id} ${team.owner || ''}`.toLowerCase();
  return `<article class="team-card" data-search="${esc(terms)}"><div class="team-card-head"><div class="team-identity">${logoMarkup(team)}<div><strong>${esc(team.name)}</strong><span>${esc(team.owner || 'Owner not set')} · ${team.active ? 'Active' : 'Inactive'}</span></div></div>${pill(team.active ? 'live' : 'paused', team.active ? 'Active' : 'Inactive')}</div><div class="team-finance"><div><span>Initial purse</span><b>${team.initialPurse !== undefined ? money(team.initialPurse) : 'Hidden'}</b></div><div><span>Spent</span><b>${team.spent !== undefined ? money(team.spent) : 'Hidden'}</b></div><div><span>Squad</span><b>${team.purchased ?? 0}</b></div></div><div class="row-actions" style="margin-top:13px"><button class="btn btn-quiet btn-sm" data-action="edit-team" data-id="${esc(team.id)}" ${appState().auction.status !== 'not-started' ? 'disabled' : ''}>Edit</button><button class="btn btn-danger btn-sm" data-action="delete-team" data-id="${esc(team.id)}" ${appState().auction.status !== 'not-started' ? 'disabled' : ''}>Remove</button></div></article>`;
}
function renderTeamsPage() {
  const locked = appState().auction.status !== 'not-started';
  const filtered = appState().teams.filter((team) => `${team.name} ${team.id} ${team.owner}`.toLowerCase().includes(App.teamSearch.toLowerCase()));
  const content = `<div class="section-heading"><div><h2>Team management</h2><p>Configure franchises, local team PINs and purse values. Team count is not fixed.</p></div><div class="btn-row"><a class="btn btn-quiet btn-sm" href="/api/admin/export/teams.csv">Export CSV</a><button class="btn btn-primary" data-action="add-team" ${locked ? 'disabled' : ''}>＋ Add team</button></div></div>${locked ? `<div class="form-note" style="margin:0 0 13px">Team identifiers, purse values and membership are locked after the auction starts.</div>` : ''}<section class="panel" style="margin-bottom:14px"><div class="panel-head"><div><h2>Participating teams</h2><p>${number(appState().teams.length)} registered · ${number(appState().teams.filter((team) => team.active).length)} active</p></div><div class="field" style="min-width:180px"><input class="search-input" id="team-search" value="${esc(App.teamSearch)}" placeholder="Search teams"></div></div><div class="panel-body"><div class="team-grid">${filtered.map(teamTableCard).join('') || `<div class="empty-state" style="grid-column:1/-1"><b>No teams configured</b><p>Add teams or import the included sample CSV to set up a test auction.</p></div>`}</div></div></section>${importPanel('teams')}`;
  return adminShell(content, 'Teams', 'Franchises, purse budgets and access', '/team-management');
}
function toggleLine(name, title, description, checked) {
  return `<div class="setting-toggle"><div><strong>${esc(title)}</strong><small>${esc(description)}</small></div><label class="toggle"><input type="checkbox" name="${esc(name)}" ${checked ? 'checked' : ''}><span></span></label></div>`;
}
function tierValue(tier) { return tier.upTo === null ? `*: ${tier.increment}` : `${tier.upTo}: ${tier.increment}`; }
function renderSettingsPage() {
  const auction = appState().auction;
  const locked = auction.status !== 'not-started';
  const tierText = (auction.bidIncrements || []).map(tierValue).join('\n');
  const requirements = auction.roleRequirements || {};
  const roleFields = [['batter','Batters'],['bowler','Bowlers'],['all-rounder','All-rounders'],['wicketkeeper','Wicketkeepers']].map(([key,label]) => `<label>${label}</label><div class="field"><input name="role-min-${key}" type="number" min="0" value="${requirements[key]?.min || 0}" aria-label="${label} minimum"></div><div class="field"><input name="role-max-${key}" type="number" min="0" value="${requirements[key]?.max ?? ''}" placeholder="No max" aria-label="${label} maximum"></div>`).join('');
  const content = `<div class="section-heading"><div><h2>Auction configuration</h2><p>Choose the rules for your event. Financial values use whole rupees and are validated on the server.</p></div>${pill(auction.status, locked ? 'Rules locked' : 'Editable before start')}</div>${locked ? `<div class="form-note" style="margin:0 0 13px">Auction rules are locked once the first run starts. Reset only after confirming that completed transactions should be cleared.</div>` : ''}<div class="settings-layout"><div class="admin-stack"><section class="panel"><div class="panel-head"><div><h2>Core auction rules</h2><p>Default purse applies to newly created teams only.</p></div></div><div class="panel-body"><form id="settings-form"><div class="settings-grid"><div class="field"><label>Auction name</label><input name="name" value="${esc(auction.name)}" maxlength="100" required></div><div class="field"><label>Currency symbol</label><input name="currencySymbol" value="${esc(auction.currencySymbol)}" maxlength="6" required></div><div class="field"><label>Default starting purse per team (whole rupees)</label><input name="startingPurse" type="number" min="1" value="${auction.startingPurse}" required></div><div class="field"><label>Default bid increment (whole rupees)</label><input name="defaultBidIncrement" type="number" min="1" value="${auction.defaultBidIncrement}" required></div><div class="field"><label>Minimum squad size (optional)</label><input name="minSquadSize" type="number" min="0" value="${auction.minSquadSize}"></div><div class="field"><label>Maximum squad size (optional)</label><input name="maxSquadSize" type="number" min="1" value="${auction.maxSquadSize ?? ''}" placeholder="No maximum"></div><div class="field span-2"><label>Price-based bid increments (optional)</label><textarea name="bidTiers" placeholder="1000000:100000\n*:200000">${esc(tierText)}</textarea><small class="field-help">One tier per line: <code>price ceiling:increment</code>. Use <code>*:increment</code> for the final open-ended tier. Leave blank to use the default.</small></div></div><div style="margin-top:19px"><div class="field-label" style="margin-bottom:10px">Squad role limits per team</div><div class="role-rules"><span class="muted tiny">Role</span><span class="muted tiny">Minimum</span><span class="muted tiny">Maximum</span>${roleFields}</div><small class="field-help" style="display:block;margin-top:9px">Role minimums are reported as requirements; maximums are enforced during bidding and sales.</small></div><div style="margin-top:17px"><div class="field-label" style="margin-bottom:5px">Live-auction options</div>${toggleLine('showOtherPurses','Show other teams’ remaining purses','When disabled, every active team needs a PIN; the projector hides team purse figures.',auction.showOtherPurses)}${toggleLine('revealNextPlayer','Reveal the next player on the display','When enabled, the public screen shows the next eligible player while waiting.',auction.revealNextPlayer)}${toggleLine('allowUnsoldReintroduction','Allow unsold players to be reintroduced','Unsold players become eligible again in the player queue.',auction.allowUnsoldReintroduction)}${toggleLine('allowOverride','Allow authorized bid and sale overrides','An explicit checkbox and server validation are still required for each override.',auction.allowOverride)}${toggleLine('requireTeamPin','Require a PIN for team dashboards','Every active team must have a configured PIN before this can be enabled.',auction.requireTeamPin)}</div><div class="form-actions"><button class="btn btn-primary" type="submit" ${locked ? 'disabled' : ''}>Save auction rules</button></div></form></div></section>
    <section class="panel"><div class="panel-head"><div><h2>Administrator security</h2><p>Change the local operator PIN. No external identity service is used.</p></div></div><div class="panel-body"><form id="pin-form"><div class="form-grid"><div class="field"><label>New administrator PIN</label><input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" required placeholder="4–12 digits"></div><div class="field"><label>Confirm new PIN</label><input name="confirmPin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" required placeholder="Repeat PIN"></div></div><div class="form-actions"><button class="btn btn-primary" type="submit">Update administrator PIN</button></div></form></div></section></div>
    <aside class="admin-stack"><section class="panel"><div class="panel-head"><div><h2>Data & recovery</h2><p>Keep a local copy before event day.</p></div></div><div class="panel-body"><div class="btn-row"><a class="btn btn-quiet btn-sm" href="/api/admin/export/json">Export full auction JSON</a><a class="btn btn-quiet btn-sm" href="/api/admin/export/players.csv">Players CSV</a><a class="btn btn-quiet btn-sm" href="/api/admin/export/teams.csv">Teams CSV</a><a class="btn btn-quiet btn-sm" href="/api/admin/export/transactions.csv">Transactions CSV</a></div><div class="setting-toggle" style="margin-top:11px"><div><strong>Restore from JSON</strong><small>Validate a locally selected backup before replacing the current auction.</small></div><button class="btn btn-quiet btn-sm" data-action="select-restore">Choose file</button><input id="restore-file" type="file" accept="application/json,.json" hidden></div><div class="setting-toggle"><div><strong>Server backups</strong><small>Automatic timestamped snapshots are stored locally (latest 40 retained).</small></div><button class="btn btn-quiet btn-sm" data-action="list-backups">View</button></div><div class="setting-toggle"><div><strong>State version</strong><small>Last committed version ${number(appState().version)} · ${esc(timeAgo(appState().updatedAt))}</small></div></div></div></section><section class="panel"><div class="panel-head"><div><h2>Network details</h2><p>Share a local URL with event devices.</p></div></div><div class="panel-body">${App.network?.lanUrls?.length ? App.network.lanUrls.map((url) => `<div class="url-chip" style="margin:0 0 7px">${esc(url)}</div>`).join('') : `<span class="muted small">LAN address will appear when the host is connected to Wi-Fi.</span>`}<p class="field-help" style="margin-top:7px">Devices must use the same Wi-Fi network. Do not forward this port to the public internet.</p></div></section></aside></div>`;
  return adminShell(content, 'Settings', 'Auction rules, access and data recovery', '/settings');
}
function renderHistoryPage() {
  const transactions = appState().transactions.slice().reverse();
  const txRows = transactions.length ? transactions.map((tx) => {
    const player = playerById(tx.playerId); const team = teamById(tx.teamId);
    const label = tx.type === 'sale' ? (tx.reversed ? 'Reversed' : 'SOLD') : tx.type === 'unsold' ? 'UNSOLD' : 'UNDO';
    const resultClass = tx.type === 'sale' ? (tx.reversed ? 'paused' : 'sold') : tx.type === 'unsold' ? 'unsold' : 'available';
    return `<tr><td class="num">${String(tx.sequence).padStart(3,'0')}</td><td>${pill(resultClass,label)}</td><td><strong>${esc(tx.playerName || player?.name || 'Player')}</strong><small>${tx.type === 'undo' ? `Reversal of ${esc(tx.referenceId || '')}` : `Base ${money(tx.basePrice)}`}</small></td><td>${esc(tx.teamName || team?.name || '—')}</td><td class="num">${tx.price ? money(tx.price) : '—'}</td><td>${dateTime(tx.timestamp)}</td></tr>`;
  }).join('') : `<tr><td colspan="6"><div class="empty-state"><b>No auction history yet</b><p>Completed sales, unsold results and reversals will appear here.</p></div></td></tr>`;
  const audit = App.audit.length ? App.audit.slice(0,80).map((entry) => `<div class="audit-entry"><time>${dateTime(entry.timestamp)}</time><strong>${esc(entry.action.replace(/[._]/g,' '))}</strong><span>${esc(JSON.stringify(entry.details || {}))}</span></div>`).join('') : `<div class="empty-state"><b>Audit activity will appear here</b><p>Server-committed changes are retained in the local audit log.</p></div>`;
  const last = appState().transactions.at(-1);
  const content = `<div class="section-heading"><div><h2>Auction history</h2><p>Sequence-numbered, timestamped results and a durable operator audit trail.</p></div><div class="btn-row"><a class="btn btn-quiet btn-sm" href="/api/admin/export/transactions.csv">Export transactions CSV</a>${last?.type === 'sale' && !last.reversed ? `<button class="btn btn-quiet btn-sm" data-action="undo-sale">↶ Undo last sale</button>` : ''}</div></div><section class="panel"><div class="panel-head"><div><h2>Completed auction transactions</h2><p>${number(appState().transactions.length)} history events · reversed purchases remain visible for audit</p></div><span class="pill">Version ${number(appState().version)}</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th class="num">Sequence</th><th>Result</th><th>Player</th><th>Team</th><th class="num">Price</th><th>Time</th></tr></thead><tbody>${txRows}</tbody></table></div></section><section class="panel" style="margin-top:14px"><div class="panel-head"><div><h2>Operator audit log</h2><p>Latest 80 actions · all state changes are persisted locally.</p></div></div><div class="panel-body">${audit}</div></section>`;
  return adminShell(content, 'Auction history', 'Committed transactions and audit events', '/history');
}
async function refreshAudit() {
  if (App.session?.role !== 'admin') return;
  try { App.audit = (await request('/api/admin/audit')).audit || []; render(); } catch { /* session may have expired */ }
}
async function refreshReport() {
  if (App.session?.role !== 'admin' || App.reportLoading) return;
  App.reportLoading = true;
  try { App.report = await request('/api/report'); } catch (error) { toast(error.message, 'error'); }
  finally { App.reportLoading = false; render(); }
}
function renderReportPage() {
  if (!App.report && !App.reportLoading) refreshReport();
  if (!App.report) return adminShell(`<div class="empty-state"><b>${App.reportLoading ? 'Preparing final report…' : 'Report is unavailable'}</b><p>Report data is calculated by the local server.</p></div>`, 'Final report', 'Live analytics and final squad summaries', '/report');
  const report = App.report; const summary = report.summary; const high = summary.highestPricedPlayer;
  const teamCards = report.teams.map((team) => `<section class="panel report-team"><div class="report-team-head"><div><strong>${esc(team.name)}</strong><div class="report-role-chips">${Object.entries(team.roleCounts).map(([role,count]) => `<span class="pill">${esc(role)} ${number(count)}</span>`).join('')}</div></div><span>${number(team.squadSize)} players · ${money(team.remaining)} remaining</span></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Player</th><th>Role</th><th class="num">Price</th><th class="num">Sequence</th></tr></thead><tbody>${team.squad.length ? team.squad.map((player) => `<tr><td><strong>${esc(player.name)}</strong></td><td>${esc(player.role)}</td><td class="num">${money(player.price)}</td><td class="num">${String(player.sequence).padStart(3,'0')}</td></tr>`).join('') : `<tr><td colspan="4" class="muted">No completed purchases.</td></tr>`}</tbody></table></div><div class="team-finance" style="padding:13px 15px 15px;margin-top:0;border-top:1px solid var(--line-soft)"><div><span>Initial purse</span><b>${money(team.initialPurse)}</b></div><div><span>Total spent</span><b>${money(team.spent)}</b></div><div><span>Remaining</span><b>${money(team.remaining)}</b></div></div></section>`).join('');
  const unsoldRows = report.unsoldPlayers.length ? report.unsoldPlayers.map((player) => `<div class="queue-row"><span class="queue-number">U</span><div class="queue-player"><strong>${esc(player.name)}</strong><span>${esc(player.role)}</span></div><span>${money(player.basePrice)}</span></div>`).join('') : `<div class="empty-state"><b>No unsold players</b></div>`;
  const content = `<div class="section-heading"><div><h2>Final auction report</h2><p>Calculated from committed server state · generated ${dateTime(report.auction.generatedAt)}</p></div><div class="btn-row"><a class="btn btn-quiet btn-sm" href="/api/admin/export/report.json">Export JSON</a><a class="btn btn-quiet btn-sm" href="/api/admin/export/report.csv">Export CSV</a><button class="btn btn-primary btn-sm" data-action="print-report">Print report</button></div></div><div class="analytics-grid"><div class="analytics-tile"><span>Players sold</span><strong>${number(summary.sold)}</strong></div><div class="analytics-tile"><span>Total expenditure</span><strong>${money(summary.totalExpenditure)}</strong></div><div class="analytics-tile"><span>Average sale</span><strong>${money(summary.averageSalePrice)}</strong></div><div class="analytics-tile"><span>Highest sale</span><strong>${high ? money(high.salePrice) : '—'}</strong><small>${high ? esc(high.name) : 'No sales yet'}</small></div></div><div class="admin-grid" style="grid-template-columns:minmax(0,1fr) minmax(260px,.48fr);align-items:start"><div class="admin-stack"><div class="section-heading" style="margin:0"><div><h2>Team squads</h2><p>${number(report.teams.length)} teams · ${esc(statusText(report.auction.status))}</p></div></div>${teamCards || `<section class="panel"><div class="empty-state"><b>No teams configured</b></div></section>`}</div><div class="admin-stack"><section class="panel"><div class="panel-head"><div><h2>Unsold players</h2><p>${number(report.unsoldPlayers.length)} players</p></div></div><div class="panel-body compact">${unsoldRows}</div></section><section class="panel"><div class="panel-head"><div><h2>Report details</h2><p>Current authoritative state</p></div></div><div class="panel-body"><div class="setting-toggle"><div><strong>Teams</strong></div><b>${number(summary.teams)}</b></div><div class="setting-toggle"><div><strong>Registered players</strong></div><b>${number(summary.players)}</b></div><div class="setting-toggle"><div><strong>Transaction events</strong></div><b>${number(report.transactions.length)}</b></div><div class="setting-toggle"><div><strong>Currency</strong></div><b>${esc(appState().auction.currencySymbol)}</b></div></div></section></div></div>`;
  return adminShell(content, 'Final report', 'Auction analytics and final squad summaries', '/report');
}
function renderAdminRoute(path) {
  if (App.session?.role !== 'admin') return renderAdminLogin();
  if (path === '/admin') return renderOverview();
  if (path === '/players') return renderPlayersPage();
  if (path === '/teams') return renderTeamsPage();
  if (path === '/settings') return renderSettingsPage();
  if (path === '/history') return renderHistoryPage();
  if (path === '/report') return renderReportPage();
  return renderNotFound();
}

function renderTeamsSelection() {
  const active = appState().teams.filter((team) => team.active);
  const loggedTeam = App.session?.role === 'team' ? teamById(App.session.teamId) : null;
  const cards = active.map((team) => `<article class="team-select-card"><div class="team-dashboard-title">${logoMarkup(team)}<div><h2>${esc(team.name)}</h2><p>${esc(team.owner || 'Auction participant')}</p></div></div><div class="team-select-meta"><span>${team.pinRequired ? '🔒 PIN protected' : 'Open dashboard'}</span><strong>${team.purchased !== undefined ? `${number(team.purchased)} players` : 'Squad overview'}</strong></div><button class="btn btn-primary btn-block" data-action="connect-team" data-id="${esc(team.id)}">${loggedTeam?.id === team.id ? 'Open my dashboard' : 'Enter dashboard'} <span>→</span></button></article>`).join('');
  root.innerHTML = `<main class="public-page">${publicHeader(App.session ? `<button class="nav-link" data-action="logout">Sign out</button>` : '')}<div class="page-container"><div class="page-title"><div class="eyebrow">Team access</div><h1>Choose your franchise</h1><p>Each team has a read-only dashboard for its own squad and purse, plus shared live auction information.</p></div>${loggedTeam ? `<div class="form-note" style="margin-bottom:14px">Signed in as <strong>${esc(loggedTeam.name)}</strong>. Choose your team to continue.</div>` : ''}${active.length ? `<div class="team-select-grid">${cards}</div>` : `<div class="empty-state"><b>No teams are configured yet</b><p>The auction organizer can add teams in the administrator console.</p><a class="btn btn-primary" href="/admin" data-nav="/admin" style="margin-top:14px">Operator sign in</a></div>`}<div class="form-note" style="margin-top:18px">Team dashboards are read-only. Purse, player ownership, sale price and auction rules are controlled by the authorized operator.</div></div></main>`;
}
function renderTeamLogin(team) {
  const mismatched = App.session && (App.session.role !== 'team' || App.session.teamId !== team.id);
  root.innerHTML = `<main class="auth-wrap"><section class="auth-card">${logoMarkup(team, 'brand-mark')}<div class="eyebrow">Team dashboard</div><h1>${esc(team.name)}</h1><p>Sign in to view this team’s squad and financial summary. Dashboard data is read-only.</p>${mismatched ? `<div class="form-note">You are signed in as a different user. Sign out first to switch dashboards.</div>` : ''}<form id="team-login-form" data-team-id="${esc(team.id)}">${team.pinRequired ? `<div class="field"><label for="team-pin">Team PIN</label><input id="team-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" autocomplete="current-password" required placeholder="4–12 digits"></div>` : `<div class="form-note">No team PIN is required for this dashboard. Continue to connect to the live auction.</div>`}<div class="form-actions"><button class="btn btn-primary btn-block" type="submit" ${mismatched ? 'disabled' : ''}>Open ${esc(team.name)} dashboard →</button></div></form><div class="auth-foot"><a class="text-button" href="/teams" data-nav="/teams">← Choose another team</a>${mismatched ? `<button class="text-button" data-action="logout">Sign out</button>` : ''}</div></section></main>`;
}
function roleComposition(team) {
  const counts = team.roleCounts || { Batter: 0, Bowler: 0, 'All-rounder': 0, Wicketkeeper: 0 };
  const rules = appState().auction.roleRequirements || {};
  const roleKeys = { Batter: 'batter', Bowler: 'bowler', 'All-rounder': 'all-rounder', Wicketkeeper: 'wicketkeeper' };
  return `<div class="composition-list">${Object.entries(roleKeys).map(([role,key]) => {
    const count = counts[role] || 0; const rule = rules[key] || { min: 0, max: null };
    const cap = rule.max || Math.max(rule.min, count, 1); const percent = Math.min(100, Math.round(count / cap * 100));
    const requirement = `${rule.min ? `Min ${rule.min}` : 'No min'}${rule.max !== null ? ` · Max ${rule.max}` : ''}`;
    const okay = (rule.max === null || count <= rule.max) && count >= rule.min;
    return `<div class="composition-row"><span>${esc(role)}</span><div class="composition-track"><i style="width:${percent}%"></i></div><b title="${esc(requirement)}">${number(count)}</b><span class="muted-2 tiny" style="grid-column:2 / -1;margin-top:-7px">${esc(requirement)} · ${okay ? 'On track' : 'Requirement pending'}</span></div>`;
  }).join('')}</div>`;
}
function renderTeamSquad(team) {
  let squad = appState().players.filter((player) => player.status === 'sold' && player.teamId === team.id);
  if (App.playerRole !== 'all') squad = squad.filter((player) => player.role === App.playerRole);
  if (App.playerSearch) squad = squad.filter((player) => `${player.name} ${player.role}`.toLowerCase().includes(App.playerSearch.toLowerCase()));
  if (App.playerSort === 'price') squad.sort((a,b) => b.salePrice - a.salePrice);
  else if (App.playerSort === 'role') squad.sort((a,b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name));
  else squad.sort((a,b) => a.name.localeCompare(b.name));
  if (!squad.length) return `<div class="empty-state"><b>${team.purchased ? 'No players match these filters' : 'Your squad is ready to be built'}</b><p>${team.purchased ? 'Try clearing a filter.' : 'Players you purchase will appear here with their auction price and sequence.'}</p></div>`;
  return `<div class="table-scroll"><table class="data-table"><thead><tr><th>Player</th><th>Role</th><th class="num">Purchase price</th><th class="num">Sequence</th></tr></thead><tbody>${squad.map((player) => `<tr><td><div class="team-identity">${player.photo ? `<span class="team-logo"><img src="${esc(player.photo)}" alt=""></span>` : `<span class="team-logo">${esc(initials(player.name))}</span>`}<div><strong>${esc(player.name)}</strong><small>${esc(player.category || player.secondaryRole || '')}</small></div></div></td><td>${esc(player.role)}</td><td class="num">${money(player.salePrice)}</td><td class="num">${String(player.sequence || '—').padStart(3,'0')}</td></tr>`).join('')}</tbody></table></div>`;
}
function renderTeamDashboard(team) {
  const auction = appState().auction; const player = currentPlayer();
  const finance = { initialPurse: team.initialPurse ?? 0, spent: team.spent ?? 0, remaining: team.remaining ?? 0, purchased: team.purchased ?? 0 };
  const slots = auction.maxSquadSize === null ? 'Flexible' : Math.max(0, auction.maxSquadSize - finance.purchased);
  const sales = appState().transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).slice().reverse().slice(0,6);
  const otherTeams = appState().teams.filter((other) => other.active && other.id !== team.id);
  const sold = appState().players.filter((item) => item.status === 'sold');
  const available = appState().players.filter((item) => item.status === 'available' || (item.status === 'unsold' && auction.allowUnsoldReintroduction));
  root.innerHTML = `<main class="public-page">${publicHeader(`<span class="connection-pill ${App.connected ? 'online' : 'offline'}"><i class="connection-dot"></i>${App.connected ? 'Live sync' : 'Reconnecting'}</span><button class="nav-link" data-action="logout">Sign out</button>`)}<div class="page-container"><div class="team-dashboard-head"><div class="team-dashboard-title">${logoMarkup(team)}<div><div class="eyebrow">Team dashboard</div><h1>${esc(team.name)}</h1><p>${esc(team.owner || 'Owner not set')} · ${esc(statusText(auction.status))} auction</p></div></div><a class="btn btn-quiet btn-sm" href="/display" data-nav="/display">Projector display ↗</a></div>
    <div class="finance-grid"><div class="finance-tile"><span>Initial purse</span><b>${money(finance.initialPurse)}</b></div><div class="finance-tile"><span>Total spent</span><b>${money(finance.spent)}</b></div><div class="finance-tile highlight"><span>Remaining purse</span><b>${money(finance.remaining)}</b></div><div class="finance-tile"><span>Players · slots</span><b>${number(finance.purchased)} · ${slots === 'Flexible' ? 'Flex' : number(slots)}</b></div></div>
    <div class="team-dashboard-grid"><div class="admin-stack"><section class="panel"><div class="panel-head"><div><h2>Current auction</h2><p>Shared live information · ${esc(timeAgo(appState().updatedAt))}</p></div>${pill(auction.status)}</div><div class="panel-body">${player ? `<div class="live-snapshot"><div><div class="eyebrow">${esc(statusText(auction.result))}</div><h3 style="margin-top:6px">${esc(player.name)}</h3><p>${esc(player.role)} · Base ${money(player.basePrice)}${auction.highestBidTeamId ? ` · Leading ${esc(teamById(auction.highestBidTeamId)?.name || 'team')}` : ''}</p></div><strong>${auction.highestBid === null ? '—' : money(auction.highestBid)}</strong></div>` : `<div class="live-snapshot"><div><div class="eyebrow">${esc(statusText(auction.status))}</div><h3 style="margin-top:6px">${auction.status === 'completed' ? 'Auction completed' : auction.status === 'not-started' ? 'Auction has not started' : 'Next player coming up'}</h3><p>${auction.revealNextPlayer && available[0] ? `Up next: ${esc(available[0].name)} · ${esc(available[0].role)}` : 'The operator will select the next player when ready.'}</p></div><strong>APL</strong></div>`}</div></section>
      <section class="panel"><div class="panel-head"><div><h2>My squad</h2><p>${number(finance.purchased)} purchased · role composition is calculated by the server</p></div><form id="team-squad-filter" class="filters"><input class="search-input" name="query" value="${esc(App.playerSearch)}" placeholder="Search squad"><select class="select-control" name="sort"><option value="name" ${App.playerSort === 'name' ? 'selected' : ''}>Name A–Z</option><option value="price" ${App.playerSort === 'price' ? 'selected' : ''}>Price high–low</option><option value="role" ${App.playerSort === 'role' ? 'selected' : ''}>Role</option></select><select class="select-control" name="role"><option value="all">All roles</option>${['Batter','Bowler','All-rounder','Wicketkeeper'].map((role) => `<option value="${role}" ${App.playerRole === role ? 'selected' : ''}>${role}</option>`).join('')}</select><button class="btn btn-quiet btn-sm" type="submit">Apply</button></form></div><div class="panel-body compact">${renderTeamSquad(team)}</div></section>
      <section class="panel"><div class="panel-head"><div><h2>Shared player pool</h2><p>${number(sold.length)} sold · ${number(available.length)} still eligible</p></div></div><div class="panel-body"><div class="section-heading" style="margin-bottom:8px"><div><h3>Recently sold</h3></div></div>${sold.length ? `<div class="player-mini-list">${sold.slice().sort((a,b) => (b.sequence||0)-(a.sequence||0)).slice(0,8).map((item) => `<div class="player-mini">${item.photo ? `<span class="team-logo"><img src="${esc(item.photo)}" alt=""></span>` : `<span class="team-logo">${esc(initials(item.name))}</span>`}<div><strong>${esc(item.name)}</strong><span>${esc(teamById(item.teamId)?.name || 'Team')} · ${money(item.salePrice)}</span></div></div>`).join('')}</div>` : `<div class="empty-state"><b>No completed sales yet</b></div>`}</div></section>
    </div><div class="admin-stack"><section class="panel"><div class="panel-head"><div><h2>Squad composition</h2><p>Role counts and configured requirements</p></div></div><div class="panel-body">${roleComposition(team)}<div class="form-note" style="margin-top:13px">${auction.maxSquadSize === null ? 'No maximum squad size configured.' : `${number(slots)} squad slots available.`} Minimum squad: ${finance.purchased >= (auction.minSquadSize || 0) ? 'requirement met' : `${number((auction.minSquadSize || 0) - finance.purchased)} more player(s) needed`} (target ${number(auction.minSquadSize || 0)}).</div></div></section><section class="panel"><div class="panel-head"><div><h2>Recent sales</h2><p>Most recent committed purchases</p></div></div><div class="panel-body compact">${sales.length ? sales.map((tx) => `<div class="recent-sale-row"><span class="sale-token">S</span><div><strong>${esc(tx.playerName)}</strong><span>${esc(tx.teamName || teamById(tx.teamId)?.name || 'Team')}</span></div><b class="nowrap">${money(tx.price)}</b></div>`).join('') : `<div class="empty-state"><b>No sales yet</b></div>`}</div></section>${auction.showOtherPurses && otherTeams.length ? `<section class="panel"><div class="panel-head"><div><h2>League purse overview</h2><p>Visible to all teams by auction rule</p></div></div><div class="panel-body compact">${otherTeams.map((other) => `<div class="display-team-row">${logoMarkup(other)}<div><strong>${esc(other.name)}</strong><span>${number(other.purchased || 0)} players · spent ${money(other.spent || 0)}</span></div><b>${money(other.remaining)}</b></div>`).join('')}</div></section>` : ''}</div></div><div class="display-footer" style="margin-top:14px"><span class="display-footer-left"><span class="connection-dot" style="background:${App.connected ? 'var(--lime)' : 'var(--coral)'}"></span>${App.connected ? 'Connected to authoritative local auction server' : 'Reconnecting to the local auction server'}</span><span>State v${number(appState().version)} · ${esc(timeAgo(appState().updatedAt))}</span></div></div></main>`;
}
function activeSales(limit = 5) { return appState().transactions.filter((tx) => tx.type === 'sale' && !tx.reversed).slice().reverse().slice(0,limit); }
function displayStatusCopy(auction) {
  if (auction.status === 'not-started') return 'Auction is ready to begin';
  if (auction.status === 'paused') return 'Auction paused by the operator';
  if (auction.status === 'completed') return 'Auction complete · thank you';
  if (auction.result === 'sold') return 'Player sold';
  if (auction.result === 'unsold') return 'Player unsold';
  if (auction.result === 'live') return 'Live bidding';
  return 'Next player coming up';
}
function renderDisplay() {
  const state = appState(); const auction = state.auction; const selected = playerById(auction.currentPlayerId);
  const reveal = !selected && auction.revealNextPlayer && auction.status === 'live' ? state.players.find((player) => player.status === 'available' || (player.status === 'unsold' && auction.allowUnsoldReintroduction)) : null;
  const player = selected || reveal; const soldCount = state.players.filter((item) => item.status === 'sold').length; const remaining = state.players.filter((item) => item.status === 'available').length;
  const leadingTeam = teamById(auction.highestBidTeamId);
  const sale = auction.result === 'sold' ? state.transactions.slice().reverse().find((tx) => tx.type === 'sale' && tx.playerId === selected?.id && !tx.reversed) : null;
  const teamRows = state.teams.filter((team) => team.active).map((team) => `<div class="display-team-row">${logoMarkup(team)}<div><strong>${esc(team.name)}</strong><span>${team.purchased !== undefined ? `${number(team.purchased)} players` : 'Squad overview'}</span></div><b>${team.remaining !== undefined && (auction.showOtherPurses || team.id === App.session?.teamId) ? money(team.remaining) : ''}</b></div>`).join('') || `<div class="empty-state" style="padding:20px"><b>No teams registered</b></div>`;
  const ticker = activeSales(6); const tickerRows = ticker.length ? ticker.map((tx) => `<div class="ticker-sale"><strong>${esc(tx.playerName)}</strong><span>${esc(tx.teamName || teamById(tx.teamId)?.name || 'Team')}</span><b>${money(tx.price)}</b></div>`).join('') : `<div class="muted small">Recent sales will appear here</div>`;
  let content;
  if (!player) {
    const heading = auction.status === 'live' ? 'NEXT PLAYER COMING UP' : auction.status === 'completed' ? 'AUCTION COMPLETE' : auction.status === 'paused' ? 'AUCTION PAUSED' : 'AUCTION PREMIER LEAGUE';
    content = `<div class="display-player-panel display-empty"><div><span class="display-state-label">${esc(statusText(auction.status))}</span><h1>${esc(heading)}</h1><p>${esc(displayStatusCopy(auction))}${auction.status === 'live' ? ' — the operator will select the next player when ready.' : '.'}</p></div></div>`;
  } else {
    const result = selected && ['sold','unsold'].includes(auction.result);
    const resultClass = auction.result === 'sold' ? 'sold' : auction.result === 'unsold' ? 'unsold' : '';
    content = `<section class="display-player-panel ${resultClass}"><div class="display-player-photo">${player.photo ? `<img src="${esc(player.photo)}" alt="${esc(player.name)}">` : `<span>${esc(initials(player.name))}</span>`}</div><div class="display-player-copy"><div class="display-state-label ${resultClass}"><span class="live-dot"></span>${reveal ? 'UP NEXT' : esc(displayStatusCopy(auction))}</div><h1>${esc(player.name)}</h1><div class="display-subtitle"><span class="pill">${esc(player.role)}</span>${player.category ? `<span class="pill">${esc(player.category)}</span>` : ''}${player.secondaryRole ? `<span>${esc(player.secondaryRole)}</span>` : ''}</div>${player.stats ? `<p class="player-stats">${esc(player.stats)}</p>` : ''}<div class="display-stat-line"><div class="display-price-card"><span>Base price</span><strong>${money(player.basePrice)}</strong></div><div class="display-price-card current"><span>${auction.result === 'sold' ? 'Final sale price' : 'Current highest bid'}</span><strong>${auction.result === 'sold' && sale ? money(sale.price) : auction.highestBid === null ? '—' : money(auction.highestBid)}</strong></div></div>${auction.result === 'sold' && sale ? `<div class="display-leader">Winning team <strong>${esc(sale.teamName || teamById(sale.teamId)?.name || 'Team')}</strong></div>` : leadingTeam ? `<div class="display-leader">Leading team <strong>${esc(leadingTeam.name)}</strong></div>` : `<div class="display-leader">${auction.result === 'unsold' ? 'No team purchased this player.' : 'Waiting for the first bid…'}</div>`}</div>${result ? `<div class="display-result ${auction.result}"><span>${auction.result === 'sold' ? 'SOLD' : 'UNSOLD'}</span></div>` : ''}</section>`;
  }
  const statusTag = auction.status === 'live' ? `<span class="status-pill live"><i class="live-dot"></i> LIVE</span>` : pill(auction.status);
  root.innerHTML = `<main class="display-page"><div class="display-layout"><header class="display-header"><div class="display-brand"><span class="brand-mark">APL</span><div><strong>${esc(auction.name)}</strong><span>Auction Premier League · Live auction</span></div></div><div class="display-header-center"><div class="display-metric"><b>${number(soldCount)}</b><span>Players sold</span></div><div class="display-metric"><b>${number(remaining)}</b><span>Players remaining</span></div><div class="display-metric"><b>${number(state.teams.filter((team) => team.active).length)}</b><span>Teams</span></div></div><div class="display-header-right">${statusTag}<button class="btn btn-quiet btn-sm" data-action="fullscreen">⛶ Fullscreen</button><a class="btn btn-quiet btn-sm" href="/" data-nav="/">APL home</a></div></header><div class="display-main">${content}<aside class="display-side"><section class="display-side-card"><div class="display-side-head"><strong>Team purse overview</strong><span>${auction.showOtherPurses ? 'Remaining purse · squad' : 'Squad count'}</span></div><div class="display-team-list">${teamRows}</div></section><section class="display-side-card"><div class="display-side-head"><strong>Recent sales</strong><span>Latest results</span></div><div class="display-ticker">${tickerRows}</div></section></aside></div><footer class="display-footer"><span class="display-footer-left"><i class="connection-dot" style="background:${App.connected ? 'var(--lime)' : 'var(--coral)'}"></i><span>${App.connected ? 'Live local connection' : 'Reconnecting to auction server'}</span></span><span class="display-footer-right">${esc(displayStatusCopy(auction))} · State v${number(state.version)}</span><span>${esc(timeAgo(state.updatedAt))}</span></footer></div></main>`;
}
function renderNotFound() {
  root.innerHTML = `<main class="auth-wrap"><section class="auth-card"><span class="brand-mark">APL</span><div class="eyebrow">404 · Not found</div><h1>This page isn’t in the auction.</h1><p>The address may be incorrect. Return to the APL home screen or open a known interface.</p><div class="btn-row" style="margin-top:20px"><a class="btn btn-primary" href="/" data-nav="/">APL home</a><a class="btn btn-quiet" href="/display" data-nav="/display">Live display</a></div></section></main>`;
}
function renderView() {
  if (!root) return;
  const path = location.pathname.replace(/\/$/,'') || '/';
  document.title = path === '/display' ? 'APL · Projector Display' : path === '/team-management' ? 'APL · Teams' : `APL · ${path.slice(1).replace(/[-/]/g,' ') || 'Live Auction'}`;
  if (path === '/') return renderLanding();
  if (path === '/display') return renderDisplay();
  if (path === '/teams') return renderTeamsSelection();
  if (path.startsWith('/team/')) {
    const id = decodeURIComponent(path.slice('/team/'.length)); const team = appState().teams.find((item) => item.id === id);
    if (!team) return renderNotFound();
    if (App.session?.role !== 'team' || App.session.teamId !== id) return renderTeamLogin(team);
    return renderTeamDashboard(team);
  }
  const adminPaths = ['/admin','/players','/team-management','/settings','/history','/report'];
  if (adminPaths.includes(path)) {
    if (App.session?.role !== 'admin') return renderAdminLogin();
    if (path === '/team-management') return renderAdminRoute('/teams');
    return renderAdminRoute(path);
  }
  return renderNotFound();
}

function render() {
  const path = location.pathname;
  const active = document.activeElement;
  const preserve = App.renderedPath === path && active && root.contains(active) && active.name && !(active instanceof HTMLInputElement && active.type === 'file')
    ? { name: active.name, id: active.id, value: active.value, checked: active.checked, tag: active.tagName, type: active.type }
    : null;
  renderView();
  App.renderedPath = path;
  if (preserve) {
    const target = (preserve.id && root.querySelector(`#${CSS.escape(preserve.id)}`)) || root.querySelector(`[name="${preserve.name}"]`);
    if (target && target.tagName === preserve.tag) {
      if (preserve.type === 'checkbox' || preserve.type === 'radio') target.checked = preserve.checked;
      else target.value = preserve.value;
      target.focus({ preventScroll: true });
    }
  }
}

async function handleClick(event) {
  const nav = event.target.closest('[data-nav]');
  if (nav) {
    event.preventDefault();
    navigate(nav.dataset.nav);
    return;
  }
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  const id = button.dataset.id;
  if (action === 'close-modal') { if (modal.open) modal.close(); return; }
  if (action === 'logout') {
    try { await request('/api/auth/logout', { method: 'POST', body: {} }); } catch { /* clear local view either way */ }
    App.session = null;
    App.connections = [];
    App.report = null;
    if (App.socket) App.socket.disconnect();
    startSocket(true);
    const route = location.pathname.startsWith('/team/') ? '/teams' : '/';
    navigate(route);
    toast('Signed out.');
    return;
  }
  if (action === 'start-auction') {
    const ok = await confirmDialog('Start the auction?', 'The auction rules, teams and player pool will lock for this run. You can still pause the event and correct the most recent sale.', 'Start auction');
    if (ok) await runAdminAction('/api/admin/start', {}, 'Auction is live. Select the first player when ready.');
    return;
  }
  if (action === 'pause-auction') { await runAdminAction('/api/admin/pause', {}, 'Auction paused.'); return; }
  if (action === 'resume-auction') { await runAdminAction('/api/admin/resume', {}, 'Auction resumed.'); return; }
  if (action === 'end-auction') {
    const ok = await confirmDialog('End this auction?', 'The auction will be marked completed. Resolve the current player as SOLD or UNSOLD first.', 'End auction', true);
    if (ok) await runAdminAction('/api/admin/end', {}, 'Auction marked completed.');
    return;
  }
  if (action === 'reset-auction') {
    const ok = await confirmDialog('Reset the auction?', 'This clears all completed transactions and resets every player to Available. Teams, player records and auction rules remain. The audit log records the reset and an automatic backup is made.', 'Reset auction', true);
    if (ok) await runAdminAction('/api/admin/reset', { confirm: true }, 'Auction reset. Configure or start a new run when ready.');
    return;
  }
  if (action === 'select-player') {
    await runAdminAction('/api/admin/select-player', { playerId: id }, `${playerById(id)?.name || 'Player'} is on the block.`);
    return;
  }
  if (action === 'increment-bid') {
    const input = $('#bid-amount');
    const player = currentPlayer();
    if (!input || !player) return;
    const current = Number(input.value || appState().auction.highestBid || player.basePrice);
    input.value = current + bidIncrement(appState().auction.highestBid ?? current);
    input.focus();
    input.select();
    return;
  }
  if (action === 'cancel-bid') {
    const input = $('#bid-amount');
    const player = currentPlayer();
    if (input && player) input.value = appState().auction.highestBid ?? player.basePrice;
    toast('Unconfirmed bid draft reset. The accepted bid is unchanged.');
    return;
  }
  if (action === 'sell-player') { showSaleDialog(); return; }
  if (action === 'mark-unsold') { showUnsoldDialog(); return; }
  if (action === 'undo-sale') {
    const latest = appState().transactions.at(-1);
    const tx = latest?.type === 'sale' ? latest : null;
    if (!tx) return toast('Only the most recent completed transaction can be undone.', 'error');
    const ok = await confirmDialog('Undo the last sale?', `${tx.playerName} was sold to ${tx.teamName} for ${money(tx.price)}. Undo restores the player to the block, recalculates the team purse and records a reversal in the audit history.`, 'Undo sale', true);
    if (ok) await runAdminAction('/api/admin/undo', { confirm: true }, 'Sale reversed and purse restored.');
    return;
  }
  if (action === 'add-player') { showPlayerForm(); return; }
  if (action === 'edit-player') { showPlayerForm(playerById(id)); return; }
  if (action === 'delete-player') {
    const player = playerById(id);
    const ok = await confirmDialog('Remove this player?', `${player?.name || 'This player'} will be removed from the local pool. Players with transaction history cannot be deleted.`, 'Remove player', true);
    if (ok) {
      const result = await processAdminAction(`/api/admin/players/${encodeURIComponent(id)}`, 'DELETE', {});
      if (result) toast('Player removed.');
    }
    return;
  }
  if (action === 'add-team') { showTeamForm(); return; }
  if (action === 'edit-team') { showTeamForm(teamById(id)); return; }
  if (action === 'delete-team') {
    const team = teamById(id);
    const ok = await confirmDialog('Remove this team?', `${team?.name || 'This team'} will be removed. A team with completed purchases cannot be deleted.`, 'Remove team', true);
    if (ok) {
      const result = await processAdminAction(`/api/admin/teams/${encodeURIComponent(id)}`, 'DELETE', {});
      if (result) toast('Team removed.');
    }
    return;
  }
  if (action === 'connect-team') {
    const team = teamById(id);
    if (!team) return;
    if (App.session?.role === 'team' && App.session.teamId === team.id) { navigate(`/team/${encodeURIComponent(team.id)}`); return; }
    showTeamLogin(team);
    return;
  }
  if (action === 'commit-import') {
    const kind = button.dataset.kind;
    const preview = App.importPreview;
    if (!preview || preview.errors?.length || !preview.rows?.length) return;
    const kindLabel = kind === 'players' ? 'players' : 'teams';
    const ok = await confirmDialog(`Import ${number(preview.rows.length)} ${kindLabel}?`, 'The server revalidates every row and adds all records together. If any duplicate or invalid record is found, nothing is committed.', 'Import records');
    if (!ok) return;
    const endpoint = kind === 'players' ? '/api/admin/players/import/commit' : '/api/admin/teams/import/commit';
    const result = await processAdminAction(endpoint, 'POST', { csv: App.importText });
    if (result) {
      toast(`${result.imported} ${kindLabel} imported.`);
      App.importKind = ''; App.importText = ''; App.importPreview = null;
      render();
    }
    return;
  }
  if (action === 'cancel-import') { App.importKind = ''; App.importText = ''; App.importPreview = null; render(); return; }
  if (action === 'select-restore') { $('#restore-file')?.click(); return; }
  if (action === 'list-backups') { await showBackups(); return; }
  if (action === 'restore-backup') {
    const name = button.dataset.name;
    const info = await request(`/api/admin/backups/${encodeURIComponent(name)}`).catch((error) => ({ error: error.message }));
    if (info.error) return toast(info.error, 'error');
    const ok = await confirmDialog('Restore this server backup?', `${info.auctionName || 'Auction backup'} · ${info.teams} teams · ${info.players} players · ${info.sales} active sales · created ${dateTime(info.createdAt)}. The current state is backed up before restore.`, 'Restore backup', true);
    if (ok) {
      const result = await processAdminAction('/api/admin/restore-backup', 'POST', { name });
      if (result) toast('Backup restored and validated.');
    }
    return;
  }
  if (action === 'fullscreen') {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch { toast('Fullscreen was blocked by the browser. Use the browser’s fullscreen shortcut.', 'error'); }
    return;
  }
  if (action === 'print-report') { window.print(); return; }
}

async function showBackups() {
  try {
    const response = await request('/api/admin/backups');
    const backups = response.backups || [];
    const body = backups.length ? backups.map((backup) => `<div class="queue-row"><span class="queue-number">↺</span><div class="queue-player"><strong>${esc(backup.name)}</strong><span>${dateTime(backup.createdAt)} · ${(backup.size / 1024).toFixed(1)} KB</span></div><button class="btn btn-quiet btn-sm" data-action="restore-backup" data-name="${esc(backup.name)}">Restore</button></div>`).join('') : `<div class="empty-state"><b>No backups yet</b><p>Backups are created automatically before the first committed change.</p></div>`;
    openDialog(`<div class="modal-head"><div><h2>Local recovery backups</h2><p>Latest ${number(backups.length)} timestamped files on this host.</p></div><button class="modal-close" type="button" data-action="close-modal">×</button></div><div class="modal-body">${body}</div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Close</button></div>`, true);
  } catch (error) { toast(error.message, 'error'); }
}

async function handleChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target instanceof HTMLInputElement && target.dataset.uploadInput) {
    await uploadImage(target);
    return;
  }
  if (target instanceof HTMLInputElement && target.dataset.importKind) {
    const file = target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) return toast('CSV files must be smaller than 4 MB.', 'error');
    try { await previewImport(target.dataset.importKind, await file.text()); }
    catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (target instanceof HTMLInputElement && target.id === 'restore-file') {
    const file = target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) return toast('Backup JSON must be smaller than 10 MB.', 'error');
    try {
      const candidate = JSON.parse(await file.text());
      const ok = await showRestoreSummary(candidate, file.name);
      if (!ok) return;
      const result = await processAdminAction('/api/admin/restore', 'POST', { state: candidate });
      if (result) toast('Auction data restored and validated.');
    } catch (error) {
      toast(error.message || 'That JSON backup is invalid.', 'error');
    } finally {
      target.value = '';
    }
  }
  if (target instanceof HTMLInputElement && target.id === 'team-search') {
    App.teamSearch = target.value;
    const query = App.teamSearch.toLowerCase();
    $$('.team-card').forEach((card) => { card.hidden = query && !card.dataset.search?.includes(query); });
  }
}

function handleInput(event) {
  const target = event.target;
  if (target?.id === 'team-search') {
    App.teamSearch = target.value;
    const query = App.teamSearch.toLowerCase();
    $$('.team-card').forEach((card) => { card.hidden = query && !card.dataset.search?.includes(query); });
  }
}

document.addEventListener('click', (event) => { handleClick(event).catch((error) => toast(error.message, 'error')); });
document.addEventListener('submit', (event) => { handleSubmit(event).catch((error) => toast(error.message, 'error')); });
document.addEventListener('change', (event) => { handleChange(event).catch((error) => toast(error.message, 'error')); });
document.addEventListener('input', handleInput);
window.addEventListener('popstate', render);

async function boot() {
  try {
    await refreshSession();
    await Promise.all([refreshNetwork(), refreshState()]);
  } catch (error) {
    toast(error.message, 'error');
  }
  startSocket();
  render();
  if (App.session?.role === 'admin') {
    refreshConnections();
    if (location.pathname === '/history') refreshAudit();
    if (location.pathname === '/report') refreshReport();
  }
}

boot();

function showPlayerForm(player = null) {
  const editing = Boolean(player);
  openDialog(`<div class="modal-head"><div><h2>${editing ? 'Edit player' : 'Add player'}</h2><p>${editing ? 'Update this player record before the auction begins.' : 'Register a player in the local auction pool.'}</p></div><button class="modal-close" type="button" data-action="close-modal" aria-label="Close">×</button></div><form id="player-form" data-original-id="${esc(player?.id || '')}"><div class="modal-body"><div class="form-grid"><div class="field"><label>Player ID</label><input name="id" value="${esc(player?.id || `player-${Math.random().toString(36).slice(2,8)}`)}" pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{1,47}" maxlength="48" required></div><div class="field"><label>Player name</label><input name="name" value="${esc(player?.name || '')}" maxlength="100" required autofocus></div><div class="field"><label>Primary role</label><select name="role" required>${['Batter','Bowler','All-rounder','Wicketkeeper'].map((role) => `<option value="${role}" ${player?.role === role ? 'selected' : ''}>${role}</option>`).join('')}</select></div><div class="field"><label>Base price (whole rupees)</label><input name="basePrice" type="number" min="1" value="${player?.basePrice ?? ''}" required></div><div class="field"><label>Secondary role (optional)</label><input name="secondaryRole" maxlength="40" value="${esc(player?.secondaryRole || '')}" placeholder="e.g. Right-arm fast"></div><div class="field"><label>Category (optional)</label><input name="category" maxlength="60" value="${esc(player?.category || '')}" placeholder="e.g. Platinum"></div><div class="field span-2"><label>Cricket statistics (optional)</label><input name="stats" maxlength="180" value="${esc(player?.stats || '')}" placeholder="e.g. 38 matches · 1,240 runs"></div><div class="field span-2"><label>Player photograph (local file)</label><input name="photo" class="photo-path" value="${esc(player?.photo || '')}" placeholder="Upload to store locally" readonly><input type="file" accept="image/jpeg,image/png,image/webp" data-upload-input="photo" style="margin-top:6px"><small class="field-help">JPG, PNG or WebP · max 5 MB · stored on this server.</small></div></div></div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">${editing ? 'Save player' : 'Add player'}</button></div></form>`, true);
}

function showTeamForm(team = null) {
  const editing = Boolean(team);
  openDialog(`<div class="modal-head"><div><h2>${editing ? 'Edit team' : 'Add team'}</h2><p>Team names and IDs must be unique. PINs are stored as salted hashes.</p></div><button class="modal-close" type="button" data-action="close-modal">×</button></div><form id="team-form" data-original-id="${esc(team?.id || '')}"><div class="modal-body"><div class="form-grid"><div class="field"><label>Unique team ID</label><input name="id" value="${esc(team?.id || '')}" pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{1,47}" maxlength="48" placeholder="north-stars" required></div><div class="field"><label>Team name</label><input name="name" value="${esc(team?.name || '')}" maxlength="80" required></div><div class="field"><label>Owner or captain (optional)</label><input name="owner" value="${esc(team?.owner || '')}" maxlength="80"></div><div class="field"><label>Initial purse (whole rupees)</label><input name="initialPurse" type="number" min="1" value="${team?.initialPurse ?? appState().auction.startingPurse}" required></div><div class="field"><label>${editing ? 'Set new PIN (leave blank to keep)' : 'Team PIN (optional)'}</label><input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" placeholder="4–12 digits"></div><div class="field"><label>Local team logo</label><input name="logo" class="photo-path" value="${esc(team?.logo || '')}" placeholder="Upload to store locally" readonly><input type="file" accept="image/jpeg,image/png,image/webp" data-upload-input="logo" style="margin-top:6px"></div><div class="field span-2"><label class="checkbox-line"><input name="active" type="checkbox" ${team?.active === false ? '' : 'checked'}><span>Team is active and eligible to participate</span></label></div>${editing ? `<div class="field span-2"><label class="checkbox-line"><input name="clearPin" type="checkbox"><span>Remove the existing team PIN</span></label></div>` : ''}</div><div class="form-note">${editing ? 'The PIN is never displayed. Leave it blank to retain the current PIN.' : 'New teams inherit the configured default purse, which can be edited here.'}</div></div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">${editing ? 'Save team' : 'Add team'}</button></div></form>`, true);
}

function showTeamLogin(team) {
  if (App.session && (App.session.role !== 'team' || App.session.teamId !== team.id)) return toast('Sign out of the current session before switching dashboards.', 'error');
  openDialog(`<div class="modal-head"><div><h2>Enter ${esc(team.name)}</h2><p>${team.pinRequired ? 'Enter your team PIN to continue.' : 'This dashboard is available without a PIN.'}</p></div><button class="modal-close" type="button" data-action="close-modal">×</button></div><form id="team-login-form" data-team-id="${esc(team.id)}"><div class="modal-body">${team.pinRequired ? `<div class="field"><label>Team PIN</label><input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,12}" minlength="4" maxlength="12" required autofocus></div>` : `<div class="form-note">You will see this team’s own squad and financial summary. All dashboard controls are read-only.</div>`}</div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">Open dashboard →</button></div></form>`);
}

function showSaleDialog() {
  const player = currentPlayer(); const auction = appState().auction;
  if (!player || auction.highestBid === null) return toast('Accept a valid bid before confirming a sale.', 'error');
  const teams = appState().teams.filter((team) => team.active);
  openDialog(`<div class="modal-head"><div><h2>Confirm player sale</h2><p>Review the winning team and price before committing.</p></div><button class="modal-close" type="button" data-action="close-modal">×</button></div><form id="sale-form"><div class="modal-body"><div class="live-snapshot" style="margin-bottom:14px"><div><div class="eyebrow">${esc(player.name)}</div><p>Base price ${money(player.basePrice)} · highest bid ${money(auction.highestBid)}</p></div><strong>${money(auction.highestBid)}</strong></div><div class="form-grid"><div class="field"><label>Winning team</label><select name="teamId">${teams.map((team) => `<option value="${esc(team.id)}" ${team.id === auction.highestBidTeamId ? 'selected' : ''}>${esc(team.name)}</option>`).join('')}</select></div><div class="field"><label>Final sale price (whole rupees)</label><input name="price" type="number" min="${player.basePrice}" value="${auction.highestBid}" required></div></div>${auction.allowOverride ? `<label class="checkbox-line" style="margin-top:13px"><input name="override" type="checkbox"><span>Authorized override: final team or price differs from the accepted highest bid</span></label>` : ''}<div class="warning-box">The team purse is recalculated and the sale is persisted atomically. This action requires the operator’s confirmation.</div></div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Cancel</button><button class="btn btn-sold" type="submit">Confirm SOLD</button></div></form>`);
}

function showUnsoldDialog() {
  const player = currentPlayer(); const auction = appState().auction;
  if (!player) return;
  openDialog(`<div class="modal-head"><div><h2>Mark player UNSOLD?</h2><p>The player will not be assigned to any team.</p></div><button class="modal-close" type="button" data-action="close-modal">×</button></div><form id="unsold-form"><div class="modal-body"><p class="confirm-copy"><strong>${esc(player.name)}</strong> will be recorded as UNSOLD at base price ${money(player.basePrice)}. You control when the next player appears.</p>${auction.highestBid !== null ? `<div class="warning-box">An accepted bid of ${money(auction.highestBid)} exists for ${esc(teamById(auction.highestBidTeamId)?.name || 'a team')}. ${auction.allowOverride ? 'Check the explicit override below to continue.' : 'Overrides are disabled, so this player cannot be marked UNSOLD.'}</div>${auction.allowOverride ? `<label class="checkbox-line" style="margin-top:12px"><input name="override" type="checkbox" required><span>I confirm this UNSOLD override despite an accepted bid</span></label>` : ''}` : ''}</div><div class="modal-footer"><button class="btn btn-quiet" type="button" data-action="close-modal">Cancel</button><button class="btn btn-unsold" type="submit" ${auction.highestBid !== null && !auction.allowOverride ? 'disabled' : ''}>Confirm UNSOLD</button></div></form>`);
}

function showRestoreSummary(candidate, name = 'selected backup') {
  const teams = candidate.teams?.length || 0; const players = candidate.players?.length || 0;
  const sales = candidate.transactions?.filter((tx) => tx.type === 'sale' && !tx.reversed).length || 0;
  return confirmDialog('Restore auction data?', `This replaces the current auction with ${name}: ${teams} teams, ${players} players, ${sales} active completed sales. A backup of the current file is created first. This cannot be cancelled after it is committed.`, 'Restore data', true);
}

async function uploadImage(input) {
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) return toast('Image must be 5 MB or smaller.', 'error');
  if (!['image/jpeg','image/png','image/webp'].includes(file.type)) return toast('Use a JPG, PNG or WebP image.', 'error');
  try {
    const response = await fetch('/api/admin/assets', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': file.type }, body: file });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Image upload failed.');
    const field = input.closest('.field')?.querySelector('.photo-path');
    if (field) field.value = result.path;
    toast('Image saved locally. Save the record to use it.');
  } catch (error) { toast(error.message, 'error'); }
}

async function previewImport(kind, text) {
  App.importKind = kind; App.importText = text; App.importPreview = null; render();
  try {
    const endpoint = kind === 'players' ? '/api/admin/players/import/preview' : '/api/admin/teams/import/preview';
    App.importPreview = await request(endpoint, { method: 'POST', body: { csv: text } });
  } catch (error) { App.importPreview = { errors: [{ line: 1, message: error.message }], totalRows: 0, rows: [] }; }
  render();
}

function amountFrom(value, label) {
  const parsed = Number(String(value ?? '').replace(/,/g,'').trim());
  if (!Number.isSafeInteger(parsed) || parsed < 0) throw new Error(`${label} must be a whole number of rupees.`);
  return parsed;
}
async function processAdminAction(url, method = 'POST', body = {}) {
  try {
    const result = await request(url, { method, body });
    if (modal.open) modal.close();
    await refreshState();
    if (location.pathname === '/history') await refreshAudit();
    if (location.pathname === '/report') await refreshReport();
    return result;
  } catch (error) { toast(error.message, 'error'); return null; }
}
function readSettingsForm(form) {
  const data = new FormData(form); const bool = (name) => data.get(name) === 'on';
  const tierText = String(data.get('bidTiers') || '').trim(); const bidIncrements = [];
  if (tierText) {
    for (const [index, raw] of tierText.split(/\r?\n/).entries()) {
      const line = raw.trim(); if (!line) continue;
      const match = line.match(/^(\*|[\d,]+)\s*:\s*([\d,]+)$/);
      if (!match) throw new Error(`Bid tier line ${index + 1} must use “price ceiling:increment” or “*:increment”.`);
      bidIncrements.push({ upTo: match[1] === '*' ? null : amountFrom(match[1], 'Price ceiling'), increment: amountFrom(match[2], 'Increment') });
    }
  }
  const roleRequirements = {};
  for (const role of ['batter','bowler','all-rounder','wicketkeeper']) {
    const min = data.get(`role-min-${role}`); const max = data.get(`role-max-${role}`);
    roleRequirements[role] = { min: amountFrom(min || 0, `${role} minimum`), max: String(max || '').trim() ? amountFrom(max, `${role} maximum`) : null };
  }
  return {
    name: data.get('name'), currencySymbol: data.get('currencySymbol'), currency: 'INR',
    startingPurse: amountFrom(data.get('startingPurse'), 'Default purse'),
    defaultBidIncrement: amountFrom(data.get('defaultBidIncrement'), 'Default increment'),
    minSquadSize: amountFrom(data.get('minSquadSize') || 0, 'Minimum squad size'),
    maxSquadSize: String(data.get('maxSquadSize') || '').trim() ? amountFrom(data.get('maxSquadSize'), 'Maximum squad size') : null,
    bidIncrements, roleRequirements,
    showOtherPurses: bool('showOtherPurses'), revealNextPlayer: bool('revealNextPlayer'),
    allowUnsoldReintroduction: bool('allowUnsoldReintroduction'), allowOverride: bool('allowOverride'), requireTeamPin: bool('requireTeamPin')
  };
}

async function handleSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const id = form.id;
  const recognized = ['admin-login-form','team-login-form','bid-form','player-form','team-form','sale-form','unsold-form','settings-form','pin-form','player-search-form','queue-search-form','team-squad-filter'];
  if (!recognized.includes(id)) return;
  event.preventDefault(); const data = new FormData(form);
  try {
    if (id === 'admin-login-form') {
      const next = data.get('next') || new URLSearchParams(location.search).get('next');
      const response = await request('/api/auth/admin/login', { method: 'POST', body: { pin: data.get('pin') } });
      App.session = response.user; await refreshState(); reconnectSocket();
      navigate(next && ['/admin','/players','/team-management','/settings','/history','/report'].includes(next) ? next : '/admin');
      toast('Administrator signed in.'); return;
    }
    if (id === 'team-login-form') {
      const teamId = form.dataset.teamId;
      const response = await request('/api/auth/team/login', { method: 'POST', body: { teamId, pin: data.get('pin') || '' } });
      App.session = response.user; await refreshState(); reconnectSocket();
      if (modal.open) modal.close();
      navigate(`/team/${encodeURIComponent(teamId)}`); toast(`Connected to ${response.user.teamName}.`); return;
    }
    if (id === 'bid-form') {
      const amount = amountFrom(data.get('amount'), 'Bid amount');
      const result = await processAdminAction('/api/admin/bid','POST',{ teamId: data.get('teamId'), amount, override: data.get('override') === 'on' });
      if (result) toast(`Bid recorded: ${money(amount)}.`); return;
    }
    if (id === 'player-form') {
      const originalId = form.dataset.originalId;
      const payload = { id: data.get('id'), name: data.get('name'), role: data.get('role'), basePrice: amountFrom(data.get('basePrice'),'Base price'), secondaryRole: data.get('secondaryRole'), category: data.get('category'), stats: data.get('stats'), photo: data.get('photo') };
      const url = originalId ? `/api/admin/players/${encodeURIComponent(originalId)}` : '/api/admin/players';
      const result = await processAdminAction(url, originalId ? 'PUT' : 'POST', payload);
      if (result) toast(originalId ? 'Player record updated.' : 'Player added to the pool.'); return;
    }
    if (id === 'team-form') {
      const originalId = form.dataset.originalId;
      const payload = { id: data.get('id'), name: data.get('name'), owner: data.get('owner'), initialPurse: amountFrom(data.get('initialPurse'),'Initial purse'), pin: data.get('pin') || '', logo: data.get('logo'), active: data.get('active') === 'on', clearPin: data.get('clearPin') === 'on' };
      const url = originalId ? `/api/admin/teams/${encodeURIComponent(originalId)}` : '/api/admin/teams';
      const result = await processAdminAction(url, originalId ? 'PUT' : 'POST', payload);
      if (result) toast(originalId ? 'Team details updated.' : 'Team registered.'); return;
    }
    if (id === 'sale-form') {
      const result = await processAdminAction('/api/admin/sell','POST',{ teamId: data.get('teamId'), price: amountFrom(data.get('price'),'Sale price'), override: data.get('override') === 'on' });
      if (result) toast('Sale committed. Team purse and squad updated.'); return;
    }
    if (id === 'unsold-form') {
      const result = await processAdminAction('/api/admin/unsold','POST',{ override: data.get('override') === 'on' });
      if (result) toast('Player recorded as UNSOLD.'); return;
    }
    if (id === 'settings-form') {
      const result = await processAdminAction('/api/admin/settings','POST',readSettingsForm(form));
      if (result) toast('Auction configuration saved.'); return;
    }
    if (id === 'pin-form') {
      const pin = String(data.get('pin') || '');
      if (pin !== String(data.get('confirmPin') || '')) throw new Error('PIN confirmation does not match.');
      const result = await processAdminAction('/api/admin/password','POST',{ pin });
      if (result) toast('Administrator PIN updated.'); return;
    }
    if (id === 'player-search-form') {
      App.playerSearch = String(data.get('query') || '').trim(); App.playerRole = data.get('role') || 'all';
      App.playerCategory = data.get('category') || 'all'; App.playerStatus = data.get('status') || 'all'; render(); return;
    }
    if (id === 'queue-search-form') {
      App.queueSearch = String(data.get('query') || '').trim(); App.queueRole = data.get('role') || 'all';
      App.queueCategory = data.get('category') || 'all'; render(); return;
    }
    if (id === 'team-squad-filter') {
      App.playerSearch = String(data.get('query') || '').trim(); App.playerSort = data.get('sort') || 'name';
      App.playerRole = data.get('role') || 'all'; render();
    }
  } catch (error) { toast(error.message, 'error'); }
}
