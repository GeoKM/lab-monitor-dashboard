// ── Lab Monitor Dashboard — app.js ────────────────────────────────────────

const API = '/api';

// ── state ───────────────────────────────────────────────────────────────────
let hosts = [];

// ── init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', loadHosts);

// ── fetch & render ────────────────────────────────────────────────────────────
async function loadHosts() {
  const btn = document.getElementById('refresh-btn');
  btn.textContent = '…';
  try {
    const res = await fetch(`${API}/hosts`);
    if (!res.ok) throw new Error(res.status);
    hosts = await res.json();
    renderGrid(hosts);
    document.getElementById('last-updated').textContent =
      `Updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    console.error(e);
  } finally {
    btn.textContent = 'Refresh';
  }
}

// ── grid ─────────────────────────────────────────────────────────────────────
function renderGrid(data) {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';

  if (!data.length) {
    grid.innerHTML = '<p class="no-data">No hosts found.</p>';
    return;
  }

  // Group by status: red first, then orange, then green
  const order = { red: 0, orange: 1, green: 2 };
  data.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

  data.forEach(h => {
    const card = document.createElement('div');
    card.className = `card ${h.status}`;
    card.onclick = () => openDetail(h.hostname);

    const uptime = h.uptime_seconds ? formatUptime(h.uptime_seconds) : null;
    const memAvail = h.mem_available ? formatBytes(h.mem_available) : null;
    const memTotal = h.mem_total ? formatBytes(h.mem_total) : null;
    const cpuIdle = h.cpu_idle != null ? `${h.cpu_idle}%` : null;
    const load1m = h.load_1m != null ? h.load_1m.toFixed(2) : null;

    card.innerHTML = `
      <div class="card-name">${h.hostname}</div>
      <div class="card-status">${h.status}</div>
      <div class="card-meta">
        ${cpuIdle ? `<span>CPU idle: ${cpuIdle}</span>` : ''}
        ${load1m ? `<span>Load 1m: ${load1m}</span>` : ''}
        ${memAvail && memTotal ? `<span>RAM: ${memAvail} / ${memTotal}</span>` : ''}
        ${uptime ? `<span>Uptime: ${uptime}</span>` : ''}
        ${h.alerts?.length ? `<span style="color:var(--orange)">${h.alerts.length} alert${h.alerts.length > 1 ? 's' : ''}</span>` : ''}
      </div>`;
    grid.appendChild(card);
  });
}

// ── detail panel ─────────────────────────────────────────────────────────────
async function openDetail(hostname) {
  const body = document.getElementById('detail-body');
  document.getElementById('detail-hostname').textContent = hostname;
  body.innerHTML = '<p class="no-data">Loading …</p>';
  showOverlay();
  showPanel();

  try {
    const res = await fetch(`${API}/hosts/${hostname}`);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    renderDetail(data);
  } catch (e) {
    body.innerHTML = `<p class="no-data">Failed to load: ${e}</p>`;
  }
}

function renderDetail(data) {
  const snap = data.snapshot;
  const body = document.getElementById('detail-body');
  const alerts = data.alerts || [];

  const html = `
    <!-- status -->
    <section>
      <h3>Status</h3>
      <div class="metric-row">
        <span class="label">Current</span>
        <span class="value" style="color:var(--${data.status})">${data.status.toUpperCase()}</span>
      </div>
      ${snap?.timestamp ? `<div class="metric-row"><span class="label">Snapshot</span><span class="value">${new Date(snap.timestamp).toLocaleString()}</span></div>` : ''}
      ${snap?.kernel ? `<div class="metric-row"><span class="label">Kernel</span><span class="value">${snap.kernel}</span></div>` : ''}
      ${snap?.uptime_seconds ? `<div class="metric-row"><span class="label">Uptime</span><span class="value">${formatUptime(snap.uptime_seconds)}</span></div>` : ''}
    </section>

    <!-- alerts -->
    ${alerts.length ? `
    <section>
      <h3>Alerts (${alerts.length})</h3>
      <ul class="alert-list">
        ${alerts.map(a => `<li class="${a.level.toLowerCase()}">${escapeHtml(a.message)}</li>`).join('')}
      </ul>
    </section>` : ''}

    <!-- CPU -->
    ${snap?.cpu ? `
    <section>
      <h3>CPU</h3>
      ${utilBar('User', snap.cpu.user_pct)}
      ${utilBar('System', snap.cpu.system_pct)}
      ${utilBar('I/O Wait', snap.cpu.iowait_pct)}
      <div class="metric-row" style="margin-top:8px">
        <span class="label">Idle</span>
        <span class="value">${snap.cpu.idle_pct}%</span>
      </div>
    </section>` : ''}

    <!-- Load -->
    ${snap?.load ? `
    <section>
      <h3>Load Average</h3>
      <div class="metric-row"><span class="label">1 min</span><span class="value">${snap.load['1m']}</span></div>
      <div class="metric-row"><span class="label">5 min</span><span class="value">${snap.load['5m']}</span></div>
      <div class="metric-row"><span class="label">15 min</span><span class="value">${snap.load['15m']}</span></div>
    </section>` : ''}

    <!-- Memory -->
    ${snap?.memory ? `
    <section>
      <h3>Memory</h3>
      ${memBar(snap.memory)}
    </section>` : ''}

    <!-- Disk -->
    ${snap?.disk?.length ? `
    <section>
      <h3>Disk (${snap.disk.length} volumes)</h3>
      ${snap.disk.map(d => diskRow(d)).join('')}
    </section>` : ''}

    <!-- Network -->
    ${snap?.network ? `
    <section>
      <h3>Network — TCP States</h3>
      <div class="metric-row"><span class="label">ESTABLISHED (0x0A)</span><span class="value">${snap.network.tcp?.['0x0A'] ?? 0}</span></div>
      <div class="metric-row"><span class="label">TIME_WAIT (0x06)</span><span class="value">${snap.network.tcp?.['0x06'] ?? 0}</span></div>
      <div class="metric-row"><span class="label">CLOSE_WAIT (0x01)</span><span class="value">${snap.network.tcp?.['0x01'] ?? 0}</span></div>
    </section>` : ''}

    <!-- Processes -->
    ${snap?.processes ? `
    <section>
      <h3>Top Processes — CPU</h3>
      <ul class="process-list">
        ${(snap.processes.top_cpu || []).slice(0, 8).map(p => `
          <li>
            <span class="cmd">${escapeHtml(p.cmd)}</span>
            <span class="pid">${p.pid}</span>
            <span class="cpu">${p.cpu}%</span>
            <span class="mem">${p.mem}%</span>
          </li>`).join('')}
      </ul>
    </section>
    <section>
      <h3>Top Processes — Memory</h3>
      <ul class="process-list">
        ${(snap.processes.top_mem || []).slice(0, 8).map(p => `
          <li>
            <span class="cmd">${escapeHtml(p.cmd)}</span>
            <span class="pid">${p.pid}</span>
            <span class="cpu">${p.cpu}%</span>
            <span class="mem">${p.mem}%</span>
          </li>`).join('')}
      </ul>
    </section>` : ''}
  `;

  body.innerHTML = html;
}

// ── helpers ─────────────────────────────────────────────────────────────────

function showOverlay() {
  document.getElementById('overlay').classList.add('show');
}
function hideOverlay() {
  document.getElementById('overlay').classList.remove('show');
}
function showPanel() {
  document.getElementById('detail-panel').classList.remove('hidden');
}
function closeDetail() {
  document.getElementById('detail-panel').classList.add('hidden');
  hideOverlay();
}
document.getElementById('overlay').addEventListener('click', closeDetail);

function utilBar(label, pct) {
  const n = parseFloat(pct);
  const cls = n > 80 ? 'red' : n > 50 ? 'orange' : 'green';
  return `<div class="bar-wrap">
    <span class="bar-label">${label}</span>
    <div class="bar-track"><div class="bar-fill ${cls}" style="width:${n}%"></div></div>
    <span style="font-size:0.78rem;min-width:40px">${pct}%</span>
  </div>`;
}

function memBar(mem) {
  const total = mem.total;
  const avail = mem.available;
  const pct = ((total - avail) / total * 100).toFixed(1);
  const used = formatBytes(total - avail);
  return `
    <div class="bar-wrap">
      <span class="bar-label">Used</span>
      <div class="bar-track"><div class="bar-fill ${parseFloat(pct) > 80 ? 'red' : parseFloat(pct) > 50 ? 'orange' : 'green'}" style="width:${pct}%"></div></div>
      <span style="font-size:0.78rem;min-width:40px">${pct}%</span>
    </div>
    <div class="metric-row" style="margin-top:8px">
      <span class="label">Used</span><span class="value">${used}</span>
    </div>
    <div class="metric-row">
      <span class="label">Available</span><span class="value">${formatBytes(avail)}</span>
    </div>
    <div class="metric-row">
      <span class="label">Total</span><span class="value">${formatBytes(total)}</span>
    </div>
    ${mem.swap_total ? `
    <div class="metric-row" style="margin-top:8px">
      <span class="label">Swap used</span><span class="value">${formatBytes(mem.swap_used)} / ${formatBytes(mem.swap_total)}</span>
    </div>` : ''}
  `;
}

function diskRow(d) {
  const pct = parseFloat(d.use_pct);
  const cls = pct > 90 ? 'red' : pct > 70 ? 'orange' : 'green';
  const label = d.mount.replace(/^_/, '');
  return `<div style="margin-bottom:12px">
    <div class="bar-wrap">
      <span class="bar-label">${label || '/'}</span>
      <div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
      <span style="font-size:0.78rem;min-width:40px">${d.use_pct}</span>
    </div>
    <div class="metric-row">
      <span class="label" style="padding-left:110px">Used</span><span class="value">${formatBytes(d.used)}</span>
      <span class="label" style="padding-left:10px">Free</span><span class="value">${formatBytes(d.avail)}</span>
    </div>
  </div>`;
}

function formatBytes(b) {
  if (!b && b !== 0) return '—';
  for (const unit of ['B','KB','MB','GB','TB']) {
    if (b < 1024) return `${b.toFixed(1)} ${unit}`;
    b /= 1024;
  }
  return `${b.toFixed(1)} PB`;
}

function formatUptime(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return [d ? `${d}d` : '', h ? `${h}h` : '', m ? `${m}m` : ''].filter(Boolean).join(' ') || '<1m';
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}