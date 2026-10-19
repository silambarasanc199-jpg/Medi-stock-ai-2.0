(() => {
  'use strict';

  const DATA_KEY = 'medistock-sentinel-data-v1';
  const SETTINGS_KEY = 'medistock-sentinel-settings-v1';
  const EXPIRY_HORIZON_DAYS = 90;
  const byId = (id) => document.getElementById(id);
  const todayISO = () => new Date().toISOString().slice(0, 10);
  const dateOffset = (days) => {
    const date = new Date(`${todayISO()}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  };
  const newId = () => globalThis.crypto?.randomUUID?.() || `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const safe = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const money = (amount) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(amount) || 0);
  const whole = (amount) => new Intl.NumberFormat().format(Math.round(Number(amount) || 0));
  const dateLabel = (date) => new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${date}T00:00:00`));
  const daysUntil = (date) => Math.floor((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${todayISO()}T00:00:00Z`)) / 86400000);

  function demoBatches() {
    return [
      { id: newId(), medicine_name: 'Amoxicillin 500 mg', sku: 'AMX-500', batch_number: 'AX-41A', expiry_date: dateOffset(12), quantity: 84, daily_usage: 4, reorder_level: 35, lead_time_days: 9, safety_stock: 14, open_orders: 0, target_stock_days: 30, minimum_order_quantity: null, unit_cost: 0.14, synthetic: true },
      { id: newId(), medicine_name: 'Amoxicillin 500 mg', sku: 'AMX-500', batch_number: 'AX-42B', expiry_date: dateOffset(55), quantity: 120, daily_usage: 4, reorder_level: 35, lead_time_days: 9, safety_stock: 14, open_orders: 0, target_stock_days: 30, minimum_order_quantity: null, unit_cost: 0.14, synthetic: true },
      { id: newId(), medicine_name: 'Paracetamol 500 mg', sku: 'PARA-500', batch_number: 'P-209C', expiry_date: dateOffset(180), quantity: 36, daily_usage: 8, reorder_level: 20, lead_time_days: 4, safety_stock: 18, open_orders: 0, target_stock_days: 30, minimum_order_quantity: 100, unit_cost: 0.07, synthetic: true },
      { id: newId(), medicine_name: 'Insulin glargine 100 units/mL', sku: 'INS-100', batch_number: 'IG-812D', expiry_date: dateOffset(250), quantity: 50, daily_usage: 1.2, reorder_level: 18, lead_time_days: 10, safety_stock: 12, open_orders: 0, target_stock_days: 30, minimum_order_quantity: null, unit_cost: 5.8, synthetic: true }
    ];
  }

  function loadData() {
    try {
      const saved = JSON.parse(localStorage.getItem(DATA_KEY));
      if (saved && Array.isArray(saved.batches) && Array.isArray(saved.drafts) && Array.isArray(saved.activity)) return saved;
    } catch (error) {
      console.warn('Saved MediStock data could not be read; restoring the demo dataset.', error);
    }
    const data = { batches: demoBatches(), drafts: [], activity: [] };
    data.activity.push({ id: newId(), kind: 'system', text: 'Synthetic demo dataset loaded. Figures are examples, not measured results.', at: new Date().toISOString() });
    return data;
  }

  let state = loadData();
  let toastTimer;
  function persist() { localStorage.setItem(DATA_KEY, JSON.stringify(state)); }
  function log(text, kind = 'update') {
    state.activity.unshift({ id: newId(), kind, text, at: new Date().toISOString() });
    state.activity = state.activity.slice(0, 50);
  }

  function groupedBatches() {
    const groups = new Map();
    for (const batch of state.batches) {
      const key = batch.sku.toUpperCase();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(batch);
    }
    return groups;
  }

  function analyzeExpiry() {
    const results = [];
    for (const [sku, records] of groupedBatches()) {
      const dailyUsage = Math.max(0, ...records.map((batch) => Number(batch.daily_usage)));
      const sorted = [...records].sort((a, b) => a.expiry_date.localeCompare(b.expiry_date));
      let priorDemandAllocated = 0;
      for (const batch of sorted) {
        const days = daysUntil(batch.expiry_date);
        const expectedDemandThroughExpiry = dailyUsage * Math.max(0, days);
        const priorDemand = priorDemandAllocated;
        const demandRemainingForBatch = Math.max(0, expectedDemandThroughExpiry - priorDemand);
        const potentialSurplus = days < 0 ? Number(batch.quantity) : Math.max(0, Number(batch.quantity) - Math.min(Number(batch.quantity), demandRemainingForBatch));
        if (days >= 0 && days <= EXPIRY_HORIZON_DAYS && Number(batch.quantity) > 0) {
          priorDemandAllocated += Math.min(Number(batch.quantity), demandRemainingForBatch);
        }
        if ((days < 0 || days <= EXPIRY_HORIZON_DAYS) && potentialSurplus > 0) {
          results.push({ batch, sku, days_until_expiry: days, daily_usage: dailyUsage, expected_demand_through_expiry: expectedDemandThroughExpiry, prior_demand_allocated: priorDemand, potential_surplus: potentialSurplus, estimated_exposure: potentialSurplus * Number(batch.unit_cost), status: days < 0 ? 'expired' : 'near_expiry' });
        }
      }
    }
    return results.sort((a, b) => a.days_until_expiry - b.days_until_expiry);
  }

  function analyzeStockout() {
    const results = [];
    for (const [sku, records] of groupedBatches()) {
      const usable = records.filter((batch) => batch.expiry_date >= todayISO());
      const dailyUsage = Math.max(0, ...records.map((batch) => Number(batch.daily_usage)));
      const leadTime = Math.max(0, ...records.map((batch) => Number(batch.lead_time_days)));
      const safetyStock = Math.max(0, ...records.map((batch) => Number(batch.safety_stock)));
      const manualReorderLevel = Math.max(0, ...records.map((batch) => Number(batch.reorder_level)));
      const openOrders = usable.reduce((sum, batch) => sum + Number(batch.open_orders || 0), 0);
      const onHand = usable.reduce((sum, batch) => sum + Number(batch.quantity), 0);
      const calculatedReorderPoint = dailyUsage * leadTime + safetyStock;
      const trigger = Math.max(calculatedReorderPoint, manualReorderLevel);
      const inventoryPosition = onHand + openOrders;
      const targetDays = Math.max(1, ...records.map((batch) => Number(batch.target_stock_days || 30)));
      const targetStock = Math.max(trigger, dailyUsage * (leadTime + targetDays) + safetyStock);
      const rawOrderQuantity = Math.max(0, Math.ceil(targetStock - inventoryPosition));
      const minimumOrderQuantity = Math.max(0, ...records.map((batch) => Number(batch.minimum_order_quantity || 0)));
      const suggestedOrderQuantity = rawOrderQuantity > 0 && minimumOrderQuantity > 0 ? Math.max(rawOrderQuantity, minimumOrderQuantity) : rawOrderQuantity;
      const daysOfStock = dailyUsage > 0 ? onHand / dailyUsage : null;
      const medicineName = records[0]?.medicine_name || sku;
      if (inventoryPosition <= trigger) results.push({ sku, medicine_name: medicineName, daily_usage: dailyUsage, lead_time_days: leadTime, safety_stock: safetyStock, on_hand: onHand, open_orders: openOrders, inventory_position: inventoryPosition, calculated_reorder_point: calculatedReorderPoint, manual_reorder_level: manualReorderLevel, trigger, target_stock: targetStock, suggested_order_quantity: suggestedOrderQuantity, minimum_order_quantity: minimumOrderQuantity, days_of_stock: daysOfStock, batch_ids: usable.map((batch) => batch.id) });
    }
    return results.sort((a, b) => a.days_of_stock - b.days_of_stock);
  }

  function getAnalysis() {
    const expiryRisks = analyzeExpiry();
    const stockoutRisks = analyzeStockout();
    const totalUnits = state.batches.reduce((sum, batch) => sum + Number(batch.quantity), 0);
    const skus = new Set(state.batches.map((batch) => batch.sku.toUpperCase()));
    const exposure = expiryRisks.reduce((sum, risk) => sum + risk.estimated_exposure, 0);
    return { expiryRisks, stockoutRisks, totalUnits, skuCount: skus.size, batchCount: state.batches.length, exposure };
  }

  function createDrafts(analysis) {
    const candidates = [];
    for (const risk of analysis.expiryRisks) {
      const key = `expiry:${risk.batch.id}:${risk.batch.quantity}:${risk.daily_usage}:${risk.batch.unit_cost}:${risk.batch.expiry_date}`;
      const expired = risk.days_until_expiry < 0;
      const title = expired ? `Quarantine review: ${risk.batch.medicine_name}` : `Expiry plan review: ${risk.batch.medicine_name}`;
      const explanation = expired
        ? `This batch passed its recorded expiry date. ${whole(risk.potential_surplus)} units are excluded from usable stock and shown at recorded unit cost. Confirm local quarantine and disposal policy; this estimate is not a measured loss.`
        : `${whole(risk.potential_surplus)} units may remain when this batch expires in ${risk.days_until_expiry} days. Demand through expiry is estimated at ${whole(risk.expected_demand_through_expiry)} units and allocated FEFO so overlapping batch demand is not counted twice. Consider an approved transfer or other policy-compliant action; verify actual sales and local rules.`;
      candidates.push({ source_key: key, type: expired ? 'expired_stock_review' : 'expiry_prevention_review', sku: risk.sku, batch_id: risk.batch.id, title, explanation, evidence: [
        `Batch ${risk.batch.batch_number} · ${dateLabel(risk.batch.expiry_date)}`,
        `${whole(risk.batch.quantity)} units on hand · ${whole(risk.potential_surplus)} estimated surplus`,
        `${whole(risk.daily_usage)} units/day · ${whole(risk.days_until_expiry)} days to expiry`,
        `Estimated cost exposure ${money(risk.estimated_exposure)}`
      ] });
    }
    for (const risk of analysis.stockoutRisks) {
      const key = `reorder:${risk.sku}:${risk.on_hand}:${risk.open_orders}:${risk.daily_usage}:${risk.lead_time_days}:${risk.safety_stock}:${risk.manual_reorder_level}:${risk.target_stock}:${risk.minimum_order_quantity}`;
      const cover = risk.days_of_stock === null ? 'daily use is recorded as zero' : `about ${risk.days_of_stock.toFixed(1)} days of usable stock remain`;
      const explanation = `Inventory position is ${whole(risk.inventory_position)} units (${whole(risk.on_hand)} on hand + ${whole(risk.open_orders)} on order); the calculated reorder point is ${risk.daily_usage} × ${risk.lead_time_days} + ${risk.safety_stock} = ${whole(risk.calculated_reorder_point)} units. The manual reorder level is ${whole(risk.manual_reorder_level)}, so the effective review trigger is ${whole(risk.trigger)}. ${cover}. Suggested quantity ${whole(risk.suggested_order_quantity)} targets ${whole(risk.target_stock)} units of coverage${risk.minimum_order_quantity ? ` and respects the recorded ${whole(risk.minimum_order_quantity)}-unit supplier minimum` : ''}. Check supplier availability, open orders, and current demand before any order.`;
      candidates.push({ source_key: key, type: 'replenishment_review', sku: risk.sku, batch_id: null, title: `Replenishment review: ${risk.medicine_name}`, explanation, evidence: [
        `${whole(risk.on_hand)} units on hand + ${whole(risk.open_orders)} open orders`,
        `Reorder point ${whole(risk.calculated_reorder_point)} units`,
        `${risk.daily_usage} units/day · ${risk.lead_time_days}-day lead time · ${whole(risk.safety_stock)} safety stock`,
        `${whole(risk.suggested_order_quantity)} units suggested · estimate only`
      ] });
    }
    const currentKeys = new Set(candidates.map((candidate) => candidate.source_key));
    for (const draft of state.drafts) {
      if (draft.status === 'pending' && !currentKeys.has(draft.source_key)) {
        draft.status = 'stale';
        draft.reviewed_at = new Date().toISOString();
        draft.reviewer = 'System';
        draft.review_note = 'Inventory changed or the deterministic risk no longer applies. Generate current drafts before deciding.';
        log(`Marked outdated draft as stale: ${draft.title}.`, 'system');
      }
    }
    for (const candidate of candidates) {
      const existing = state.drafts.find((draft) => draft.source_key === candidate.source_key);
      if (existing && ['approved', 'rejected'].includes(existing.status)) continue;
      if (existing) {
        if (existing.status === 'stale') {
          existing.status = 'pending';
          existing.reviewed_at = null;
          existing.reviewer = null;
          existing.review_note = null;
          existing.created_at = new Date().toISOString();
          log(`Reactivated current draft: ${candidate.title}.`, 'draft');
        }
        Object.assign(existing, candidate);
        continue;
      }
      state.drafts.unshift({ id: newId(), ...candidate, status: 'pending', created_at: new Date().toISOString(), reviewed_at: null, reviewer: null, review_note: null });
      log(`Action draft created for ${candidate.title}.`, 'draft');
    }
  }

  function renderMetrics(analysis) {
    byId('metricUnits').textContent = whole(analysis.totalUnits);
    byId('metricMedicines').textContent = whole(analysis.skuCount);
    byId('metricBatches').textContent = whole(analysis.batchCount);
    byId('metricExposure').textContent = money(analysis.exposure);
    byId('metricReorder').textContent = whole(analysis.stockoutRisks.length);
    byId('pendingNavCount').textContent = whole(state.drafts.filter((draft) => draft.status === 'pending').length);
    byId('dataSourceBadge').textContent = state.batches.some((batch) => batch.synthetic) ? 'Synthetic data included' : 'User-entered records';
    byId('todayLabel').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date()).toUpperCase();
  }

  function renderAttention(analysis) {
    const cards = [];
    for (const risk of analysis.expiryRisks) {
      const expired = risk.days_until_expiry < 0;
      cards.push(`<article class="risk-card"><div class="risk-symbol">${expired ? '!' : '◷'}</div><div class="risk-copy"><div class="risk-title">${safe(risk.batch.medicine_name)} <span class="queue-tag">${expired ? 'Expired' : 'Expiry risk'}</span><span class="risk-value">${money(risk.estimated_exposure)}</span></div><p>${whole(risk.potential_surplus)} estimated surplus units in batch ${safe(risk.batch.batch_number)} · ${expired ? 'past expiry' : `${risk.days_until_expiry} days to expiry`}. Cost exposure is an estimate, not a recorded loss.</p></div></article>`);
    }
    for (const risk of analysis.stockoutRisks) {
      cards.push(`<article class="risk-card stockout"><div class="risk-symbol">↗</div><div class="risk-copy"><div class="risk-title">${safe(risk.medicine_name)} <span class="queue-tag">Reorder review</span><span class="risk-value">${whole(risk.suggested_order_quantity)} suggested</span></div><p>Inventory position ${whole(risk.inventory_position)} vs. ${whole(risk.trigger)}-unit trigger · ${risk.days_of_stock === null ? 'daily use not recorded' : `${risk.days_of_stock.toFixed(1)} days of usable stock`} · human review required.</p></div></article>`);
    }
    byId('attentionList').innerHTML = cards.join('');
    byId('queueCount').textContent = `${cards.length} ${cards.length === 1 ? 'item' : 'items'}`;
    byId('attentionEmpty').classList.toggle('hidden', cards.length > 0);
  }

  function batchStatus(batch, analysis) {
    const expiryRisk = analysis.expiryRisks.find((risk) => risk.batch.id === batch.id);
    if (expiryRisk?.status === 'expired') return { label: 'Expired · hold', className: 'expired' };
    if (expiryRisk) return { label: `${expiryRisk.days_until_expiry} days · expiry`, className: 'warning' };
    const reorder = analysis.stockoutRisks.find((risk) => risk.sku === batch.sku.toUpperCase());
    if (reorder) return { label: 'Reorder review', className: 'critical' };
    const days = daysUntil(batch.expiry_date);
    if (days <= EXPIRY_HORIZON_DAYS) return { label: `${Math.max(days, 0)} days · expiry`, className: 'warning' };
    return { label: 'Within range', className: '' };
  }

  function renderInventory(analysis) {
    const query = byId('searchInput').value.trim().toLowerCase();
    const filter = byId('filterSelect').value;
    const filtered = state.batches.filter((batch) => {
      const text = `${batch.medicine_name} ${batch.sku} ${batch.batch_number}`.toLowerCase();
      if (query && !text.includes(query)) return false;
      const expiry = analysis.expiryRisks.some((risk) => risk.batch.id === batch.id);
      const reorder = analysis.stockoutRisks.some((risk) => risk.sku === batch.sku.toUpperCase());
      if (filter === 'expiry' && !expiry) return false;
      if (filter === 'stockout' && !reorder) return false;
      if (filter === 'clear' && (expiry || reorder || daysUntil(batch.expiry_date) < 0)) return false;
      return true;
    }).sort((a, b) => a.expiry_date.localeCompare(b.expiry_date));

    byId('inventoryList').innerHTML = filtered.map((batch) => {
      const status = batchStatus(batch, analysis);
      return `<article class="inventory-card">
        <div class="medicine-main"><strong>${safe(batch.medicine_name)}${batch.synthetic ? '<span class="synthetic-mini">SYNTHETIC</span>' : ''}</strong><small>${safe(batch.sku)} · Batch ${safe(batch.batch_number)}</small></div>
        <div class="inventory-detail"><strong>${whole(batch.quantity)} units</strong><small>On hand</small></div>
        <div class="inventory-detail"><strong>${dateLabel(batch.expiry_date)}</strong><small>Expiry date</small></div>
        <div class="inventory-detail"><strong>${money(batch.unit_cost)}</strong><small>Unit cost</small></div>
        <span class="status-pill ${status.className}">${safe(status.label)}</span>
        <details class="card-menu"><summary aria-label="Batch actions">⋯</summary><div class="menu-actions"><button type="button" data-action="edit" data-id="${safe(batch.id)}">Edit batch</button><button type="button" data-action="delete" data-id="${safe(batch.id)}">Remove batch</button></div></details>
      </article>`;
    }).join('');
    byId('inventoryEmpty').classList.toggle('hidden', filtered.length > 0);
  }

  function renderDrafts() {
    const drafts = [...state.drafts].sort((a, b) => (a.status === 'pending' ? -1 : 1) - (b.status === 'pending' ? -1 : 1) || b.created_at.localeCompare(a.created_at));
    byId('draftList').innerHTML = drafts.map((draft) => {
      const typeLabel = draft.type === 'replenishment_review' ? 'Stockout prevention · proposed order' : draft.type === 'expired_stock_review' ? 'Expired stock · quarantine review' : 'Expiry prevention · proposed review';
      const actions = draft.status === 'pending' ? `<div class="draft-actions"><button class="button button-primary" type="button" data-review="approved" data-id="${safe(draft.id)}">Approve draft</button><button class="button button-danger" type="button" data-review="rejected" data-id="${safe(draft.id)}">Reject</button></div>` : draft.status === 'stale' ? `<p class="activity-copy">This draft is out of date and cannot be reviewed. The underlying inventory or calculated risk changed; use the current draft instead.</p>` : `<p class="activity-copy">Reviewed${draft.reviewer ? ` by ${safe(draft.reviewer)}` : ''} · ${draft.reviewed_at ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(draft.reviewed_at)) : ''}${draft.review_note ? ` · ${safe(draft.review_note)}` : ''}. Approval records a decision only; it does not execute an order or alter physical stock.</p>`;
      return `<article class="draft-card"><div class="draft-header"><div><div class="draft-type">${typeLabel}</div><h3>${safe(draft.title)}</h3></div><span class="draft-state ${safe(draft.status)}">${safe(draft.status)}</span></div><p class="draft-explanation">${safe(draft.explanation)}</p><div class="evidence-row">${draft.evidence.map((item) => `<span class="evidence-chip">${safe(item)}</span>`).join('')}</div>${actions}</article>`;
    }).join('');
    byId('draftEmpty').classList.toggle('hidden', drafts.length > 0);
  }

  function renderActivity() {
    const entries = state.activity.slice(0, 12);
    byId('activityList').innerHTML = entries.map((entry) => `<div class="activity-item"><span class="activity-dot">${entry.kind === 'review' ? '✓' : entry.kind === 'draft' ? '!' : '·'}</span><div class="activity-copy">${safe(entry.text)}</div><time class="activity-time" datetime="${safe(entry.at)}">${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(entry.at))}</time></div>`).join('');
    if (!entries.length) byId('activityList').innerHTML = '<div class="empty-state">Activity will appear here as the inventory is updated and drafts are reviewed.</div>';
  }

  function render() {
    const analysis = getAnalysis();
    createDrafts(analysis);
    renderMetrics(analysis);
    renderAttention(analysis);
    renderInventory(analysis);
    renderDrafts();
    renderActivity();
    persist();
  }

  function toast(message) {
    const node = byId('toast');
    node.textContent = message;
    node.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.add('hidden'), 3200);
  }

  const dialog = byId('medicineDialog');
  function openForm(batch = null) {
    const form = byId('medicineForm');
    form.reset();
    byId('formError').classList.add('hidden');
    byId('dialogTitle').textContent = batch ? 'Edit medicine batch' : 'Add medicine batch';
    form.elements.namedItem('safety_stock').value = batch?.safety_stock ?? '0';
    form.elements.namedItem('open_orders').value = batch?.open_orders ?? '0';
    form.elements.namedItem('target_stock_days').value = batch?.target_stock_days ?? '30';
    if (batch) {
      for (const [key, value] of Object.entries(batch)) {
        const field = form.elements.namedItem(key);
        if (field && field.type !== 'checkbox') field.value = value ?? '';
      }
      form.dataset.editing = batch.id;
    } else delete form.dataset.editing;
    dialog.showModal();
  }

  function formValues(form) {
    const values = Object.fromEntries(new FormData(form).entries());
    for (const key of ['quantity', 'reorder_level', 'lead_time_days', 'safety_stock', 'open_orders', 'target_stock_days']) values[key] = Number(values[key]);
    for (const key of ['daily_usage', 'unit_cost']) values[key] = Number(values[key]);
    values.minimum_order_quantity = values.minimum_order_quantity === '' ? null : Number(values.minimum_order_quantity);
    values.sku = values.sku.trim().toUpperCase();
    values.batch_number = values.batch_number.trim().toUpperCase();
    values.medicine_name = values.medicine_name.trim();
    return values;
  }

  byId('addMedicineButton').addEventListener('click', () => openForm());
  byId('closeDialogButton').addEventListener('click', () => dialog.close());
  byId('cancelDialogButton').addEventListener('click', () => dialog.close());
  byId('medicineForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const errorNode = byId('formError');
    errorNode.classList.add('hidden');
    if (!form.reportValidity()) return;
    const values = formValues(form);
    const editingId = form.dataset.editing;
    const numericFields = ['quantity', 'daily_usage', 'reorder_level', 'lead_time_days', 'safety_stock', 'open_orders', 'target_stock_days', 'unit_cost'];
    const invalid = numericFields.some((key) => !Number.isFinite(values[key]) || values[key] < 0) || values.target_stock_days < 1 || (values.minimum_order_quantity !== null && (!Number.isInteger(values.minimum_order_quantity) || values.minimum_order_quantity < 1)) || !values.medicine_name || !values.sku || !values.batch_number;
    if (invalid) {
      errorNode.textContent = 'Check the required fields. Quantities and costs cannot be negative; target coverage must be at least one day.';
      errorNode.classList.remove('hidden');
      return;
    }
    const duplicate = state.batches.some((item) => item.id !== editingId && item.sku.toUpperCase() === values.sku && item.batch_number.toUpperCase() === values.batch_number);
    if (duplicate) {
      errorNode.textContent = 'That SKU and batch number are already in the register. Batch numbers must be unique within an SKU.';
      errorNode.classList.remove('hidden');
      return;
    }
    if (editingId) {
      const current = state.batches.find((item) => item.id === editingId);
      if (!current) return;
      Object.assign(current, values);
      current.synthetic = false;
      log(`Updated batch ${current.batch_number} (${current.medicine_name}).`);
    } else {
      const batch = { ...values, id: newId(), synthetic: false };
      state.batches.push(batch);
      log(`Added batch ${batch.batch_number} (${batch.medicine_name}).`);
    }
    persist();
    dialog.close();
    render();
    toast(editingId ? 'Batch updated. Risk estimates refreshed.' : 'Batch saved. Risk estimates refreshed.');
  });

  byId('inventoryList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const batch = state.batches.find((item) => item.id === button.dataset.id);
    if (!batch) return;
    if (button.dataset.action === 'edit') openForm(batch);
    if (button.dataset.action === 'delete' && window.confirm(`Remove ${batch.medicine_name}, batch ${batch.batch_number}? This only removes this browser's inventory record.`)) {
      state.batches = state.batches.filter((item) => item.id !== batch.id);
      log(`Removed batch ${batch.batch_number} (${batch.medicine_name}).`);
      render();
      toast('Batch removed from this browser.');
    }
  });

  byId('draftList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-review]');
    if (!button) return;
    const draft = state.drafts.find((item) => item.id === button.dataset.id);
    if (!draft || draft.status !== 'pending') return;
    const decision = button.dataset.review;
    const confirmation = decision === 'approved'
      ? `Approve this draft for ${draft.title}? This records your approval only. It will not place an order or change stock.`
      : `Reject this draft for ${draft.title}?`;
    if (!window.confirm(confirmation)) return;
    draft.status = decision;
    draft.reviewed_at = new Date().toISOString();
    draft.reviewer = 'Local reviewer';
    log(`${decision === 'approved' ? 'Approved' : 'Rejected'} draft: ${draft.title}. No inventory action was executed.`, 'review');
    render();
    toast(`Draft ${decision}. No order or stock change was made.`);
  });

  byId('searchInput').addEventListener('input', () => renderInventory(getAnalysis()));
  byId('filterSelect').addEventListener('change', () => renderInventory(getAnalysis()));
  byId('resetButton').addEventListener('click', () => {
    if (!window.confirm('Restore the synthetic demo dataset and clear current browser data, drafts, and review history?')) return;
    state = { batches: demoBatches(), drafts: [], activity: [{ id: newId(), kind: 'system', text: 'Synthetic demo dataset restored. Figures are examples, not measured results.', at: new Date().toISOString() }] };
    persist();
    render();
    toast('Synthetic demo data restored.');
  });

  byId('exportButton').addEventListener('click', () => {
    log('Exported inventory, drafts, and activity as a JSON file.');
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), application: 'MediStock Sentinel AI', data: state }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `medistock-export-${todayISO()}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    persist();
    renderActivity();
    toast('Inventory export downloaded.');
  });

  let settings = {};
  try { settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (_) { settings = {}; }
  byId('apiBaseUrl').value = settings.apiBaseUrl || '';
  byId('saveApiButton').addEventListener('click', async () => {
    const status = byId('apiStatus');
    const base = byId('apiBaseUrl').value.trim().replace(/\/+$/, '');
    if (!base) {
      status.textContent = 'Enter a backend URL to test. Local inventory is still available.';
      status.className = 'api-status offline';
      return;
    }
    try {
      new URL(base);
    } catch (_) {
      status.textContent = 'Enter a valid URL, including https:// or http://.';
      status.className = 'api-status offline';
      return;
    }
    settings = { ...settings, apiBaseUrl: base };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    status.textContent = 'Testing backend…';
    status.className = 'api-status';
    try {
      const response = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const body = await response.json();
      status.textContent = `Connected to API (${body.agent_mode || 'rule-based'} mode). Local inventory remains available.`;
      status.className = 'api-status online';
    } catch (error) {
      status.textContent = `Backend not reachable (${error.message}). Local inventory still works; check the URL and CORS settings.`;
      status.className = 'api-status offline';
    }
  });

  document.querySelectorAll('.primary-nav a').forEach((link) => link.addEventListener('click', () => {
    document.querySelectorAll('.primary-nav a').forEach((item) => item.classList.toggle('active', item === link));
  }));

  render();
})();
