/* Volunteer sign-up: the pop-up on the home page and the page at /volunteer/.
   The form works without this script (it posts and the server checks everything).
   This adds the steps, overlap checks, live spot counts and sending the sign-up
   without leaving the page. The server stays the judge of what's valid. */
(function () {
  'use strict';

  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  // Translations come from /jsi18n/ (Django's JavaScript catalog), loaded before this script.
  const gettext = window.gettext || ((text) => text);
  const ngettext = window.ngettext || ((one, many, n) => (n === 1 ? one : many));
  const fmt = (text, values) => text.replace(/%\((\w+)\)s|%s/g, (m, key) => String(key ? values[key] : values.shift()));
  const shiftsText = (n) => fmt(ngettext('%s shift', '%s shifts', n), [n]);
  const hoursText = (mins) => {
    const h = mins / 60;
    return Number.isInteger(h) ? fmt(ngettext('%s hour', '%s hours', h), [h]) : fmt(gettext('%s hours'), [Math.round(h * 10) / 10]);
  };

  /* ---------- the pop-up ---------- */
  const dialog = document.getElementById('volunteer');
  let opener = null;
  if (dialog && typeof dialog.showModal === 'function') {
    document.querySelectorAll('[data-volunteer-open]').forEach((link) => {
      link.setAttribute('aria-haspopup', 'dialog');
      link.addEventListener('click', (e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // new tab still works
        e.preventDefault();
        opener = link;
        openDialog();
      });
    });
    dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
    dialog.querySelectorAll('[data-vol-dismiss]').forEach((b) => b.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('close', () => {
      document.documentElement.classList.remove('vol-lock');
      dialog.dispatchEvent(new CustomEvent('vol:closed'));
      if (opener) opener.focus();
    });
    if (location.hash === '#volunteer') openDialog();
  }
  function openDialog() {
    if (dialog.open) return;
    dialog.showModal();
    document.documentElement.classList.add('vol-lock');
    dialog.dispatchEvent(new CustomEvent('vol:opened'));
  }

  document.querySelectorAll('[data-vol]').forEach(setup);

  /* ---------- the sign-up ---------- */
  function setup(root) {
    const $ = (sel) => root.querySelector(sel);
    const form = $('form');
    const body = $('[data-vol-body]');
    const inDialog = root.dataset.mode === 'dialog';
    const preview = root.hasAttribute('data-preview');
    const spotsUrl = root.dataset.spotsUrl;
    const steps = {};
    root.querySelectorAll('.vol__step').forEach((s) => { steps[s.dataset.step] = s; });
    const btn = {
      back: $('[data-vol-back]'), next: $('[data-vol-next]'), submit: $('[data-vol-submit]'),
      again: $('[data-vol-again]'), close: $('[data-vol-close]'),
    };
    const submitText = $('[data-vol-submit-text]');
    const sum = $('[data-vol-sum]');
    const live = $('[data-vol-live]');
    const note = $('[data-vol-note]');
    const alertBox = $('[data-vol-alert]');
    const mine = $('[data-vol-mine]');
    const mineList = $('[data-vol-mine-list]');
    const openLine = $('[data-vol-open]');
    const shiftsError = $('#vol-shifts-error');
    const emptyNote = $('[data-vol-empty]');

    const rows = Array.from(root.querySelectorAll('.vol-shift')).map((li) => {
      const d = li.dataset;
      return {
        li, id: d.id, role: d.role, roleName: d.roleName, color: d.color,
        from: +d.from, to: +d.to, minutes: +d.minutes, capacity: +d.capacity, taken: +d.taken,
        started: d.started === '1', day: d.day, shortDay: d.shortDay, time: d.time, startTime: d.startTime,
        where: d.where, gcal: d.gcal,
        input: li.querySelector('input[type="checkbox"]'), slots: li.querySelector('.vol-slots'),
        left: li.querySelector('.vol-left'), why: li.querySelector('.vol-why'), sig: '',
      };
    });
    const byId = {};
    rows.forEach((r) => { byId[r.id] = r; });
    const state = { step: 'pick', role: '', hideFull: false, busy: false, tried: false, lastLoad: Date.now() };

    const picked = () => rows.filter((r) => r.input.checked).sort((a, b) => a.from - b.from);
    const isFull = (r) => r.taken >= r.capacity;
    const shortName = (r) => fmt(gettext('%(role)s, %(day)s at %(time)s'), { role: r.roleName, day: r.shortDay, time: r.startTime });

    function announce(msg) {
      live.textContent = '';
      setTimeout(() => { live.textContent = msg; }, 40);
    }

    /* Shift rows */
    function paintSlots(r, mine) {
      const taken = Math.min(r.taken, r.capacity);
      const sig = `${taken}|${mine}`;
      if (r.sig === sig) return;
      r.sig = sig;
      r.slots.textContent = '';
      if (r.capacity > 20) {
        const meter = document.createElement('span');
        meter.className = 'vol-meter';
        const t = document.createElement('span');
        t.className = 'vol-meter__taken';
        t.style.width = `${(taken / r.capacity) * 100}%`;
        meter.appendChild(t);
        if (mine && taken < r.capacity) {
          const y = document.createElement('span');
          y.className = 'vol-meter__you';
          y.style.width = `${Math.max(3, 100 / r.capacity)}%`;
          meter.appendChild(y);
        }
        r.slots.appendChild(meter);
        return;
      }
      for (let i = 0; i < r.capacity; i++) {
        const slot = document.createElement('span');
        slot.className = 'vol-slot' + (i < taken ? ' is-taken' : (mine && i === taken ? ' is-you' : ''));
        r.slots.appendChild(slot);
      }
    }

    function updateRows() {
      const mineRows = picked();
      rows.forEach((r) => {
        const on = r.input.checked;
        const full = !on && isFull(r);
        const clash = on ? null : (mineRows.find((m) => m.from < r.to && r.from < m.to) || null);
        const off = !on && (r.started || full || !!clash);
        r.li.classList.toggle('is-picked', on);
        r.li.classList.toggle('is-off', off);
        r.input.disabled = off;
        paintSlots(r, on);
        r.left.textContent = r.started ? gettext('Already started')
          : full ? gettext('Full')
          : fmt(ngettext('%(left)s of %(total)s spot left', '%(left)s of %(total)s spots left', r.capacity), { left: Math.max(0, r.capacity - r.taken), total: r.capacity });
        const reason = clash ? fmt(gettext('Overlaps your %(time)s %(role)s shift'), { time: clash.startTime, role: clash.roleName }) : '';
        r.why.textContent = reason;
        r.why.hidden = !reason;
      });
    }

    function applyFilter() {
      let any = false;
      root.querySelectorAll('.vol-day').forEach((day) => {
        let shown = 0;
        day.querySelectorAll('.vol-shift').forEach((li) => {
          const r = byId[li.dataset.id];
          const hide = (state.role && r.role !== state.role) || (state.hideFull && (isFull(r) || r.started) && !r.input.checked);
          li.hidden = !!hide;
          if (!hide) shown++;
        });
        day.hidden = shown === 0;
        if (shown) any = true;
      });
      if (emptyNote) emptyNote.hidden = any || !rows.length;
    }

    function renderOpenLine() {
      if (!openLine) return;
      const total = rows.reduce((n, r) => n + r.capacity, 0);
      const open = rows.reduce((n, r) => n + (r.started ? 0 : Math.max(0, r.capacity - r.taken)), 0);
      openLine.textContent = '';
      const strong = document.createElement('strong');
      strong.textContent = String(open);
      openLine.append(strong, ' ' + fmt(gettext('of %s volunteer spots are open.'), [total]));
    }

    const submitLabel = (n) => (n ? fmt(ngettext('Confirm my shift', 'Confirm my %s shifts', n), [n]) : gettext('Confirm my shifts'));

    function renderSummary() {
      const list = picked();
      const mins = list.reduce((n, r) => n + r.minutes, 0);
      sum.textContent = state.step === 'done' ? ''
        : list.length ? `${shiftsText(list.length)}, ${hoursText(mins)}` : gettext('No shifts chosen yet');
      mineList.textContent = '';
      list.forEach((r) => {
        const li = document.createElement('li');
        li.className = 'vol-mine__item';
        const text = document.createElement('span');
        const when = document.createElement('span');
        when.className = 'vol-mine__when';
        when.textContent = `${r.shortDay}, ${r.time}`;
        const role = document.createElement('span');
        role.className = 'vol-mine__role';
        const dot = document.createElement('span');
        dot.className = 'vol-dot';
        dot.style.setProperty('--role', r.color);
        role.append(dot, r.roleName);
        text.append(when, document.createElement('br'), role);
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'vol-remove';
        remove.dataset.remove = r.id;
        remove.setAttribute('aria-label', fmt(gettext('Remove %s'), [shortName(r)]));
        remove.innerHTML = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8"/></svg>';
        li.append(text, remove);
        mineList.appendChild(li);
      });
      mine.hidden = !list.length;
      if (!state.busy) submitText.textContent = submitLabel(list.length);
    }

    function refresh() {
      updateRows();
      applyFilter();
      renderSummary();
    }

    /* Steps */
    function go(step, opts) {
      const quiet = opts && opts.quiet;
      state.step = step;
      Object.keys(steps).forEach((k) => {
        steps[k].classList.toggle('is-active', k === step);
        if (k === 'done') steps[k].hidden = step !== 'done';
      });
      btn.back.hidden = step !== 'details';
      btn.next.hidden = step !== 'pick';
      btn.submit.hidden = step !== 'details';
      btn.again.hidden = step !== 'done';
      if (btn.close) btn.close.hidden = step !== 'done';
      renderSummary();
      if (quiet) return;
      if (inDialog) body.scrollTop = 0;
      else root.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      const title = steps[step].querySelector('.vol-step-title');
      if (title) title.focus({ preventScroll: true });
    }

    function showShiftError(msg) {
      if (!shiftsError) return;
      shiftsError.textContent = msg;
      shiftsError.hidden = false;
      shiftsError.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
      announce(msg);
    }
    function clearShiftError() {
      if (shiftsError) { shiftsError.hidden = true; shiftsError.textContent = ''; }
    }
    function showNote(msg) {
      note.textContent = msg;
      note.hidden = !msg;
    }

    /* Form checks, matching the server's */
    const checks = [
      { name: 'first_name', test: (v) => !!v.trim(), msg: () => gettext('Enter your first name.') },
      { name: 'last_name', test: (v) => !!v.trim(), msg: () => gettext('Enter your last name.') },
      {
        name: 'email', test: (v) => EMAIL_RE.test(v.trim()),
        msg: (v) => (v.trim() ? gettext('Enter an email address like name@example.com.') : gettext('Enter your email address.')),
      },
      {
        name: 'phone', test: (v) => v.replace(/\D/g, '').length >= 7,
        msg: (v) => (v.trim() ? gettext('Enter a phone number with its area code.') : gettext('Enter a phone number we can reach you on during the event.')),
      },
      { name: 'age_confirmed', box: true, msg: () => gettext('Confirm that you meet the age requirement.') },
      { name: 'agreed', box: true, msg: () => gettext('Tick the box to agree to the volunteer guidelines.') },
    ].filter((c) => form.elements[c.name]);

    function setFieldError(name, msg) {
      const input = $(`#vol-${name}`);
      const err = $(`#vol-${name}-error`);
      if (input) {
        if (msg) input.setAttribute('aria-invalid', 'true');
        else input.removeAttribute('aria-invalid');
      }
      if (err) { err.textContent = msg || ''; err.hidden = !msg; }
    }
    function checkFields(show) {
      const problems = [];
      checks.forEach((c) => {
        const el = form.elements[c.name];
        const value = c.box ? '' : el.value;
        const ok = c.box ? el.checked : c.test(value);
        if (show) setFieldError(c.name, ok ? '' : c.msg(value));
        if (!ok) problems.push({ id: `vol-${c.name}`, msg: c.msg(value) });
      });
      return problems;
    }

    let alertMode = '';
    function showProblems(list, focus) {
      alertBox.textContent = '';
      const title = document.createElement('p');
      title.className = 'vol-alert__title';
      title.textContent = fmt(ngettext('Fix %s thing to finish signing up', 'Fix %s things to finish signing up', list.length), [list.length]);
      const ul = document.createElement('ul');
      list.forEach((p) => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = `#${p.id}`;
        a.dataset.focus = p.id;
        a.textContent = p.msg;
        li.appendChild(a);
        ul.appendChild(li);
      });
      alertBox.append(title, ul);
      alertBox.hidden = false;
      alertMode = 'problems';
      if (focus) alertBox.focus();
    }
    function showAlert(title, text) {
      alertBox.textContent = '';
      const t = document.createElement('p');
      t.className = 'vol-alert__title';
      t.textContent = title;
      const p = document.createElement('p');
      p.textContent = text;
      alertBox.append(t, p);
      alertBox.hidden = false;
      alertMode = 'message';
      alertBox.focus();
    }
    function hideAlert() {
      alertBox.hidden = true;
      alertBox.textContent = '';
      alertMode = '';
    }
    function recheck() {
      if (!state.tried || alertMode === 'message') return;
      const list = checkFields(true);
      if (alertMode === 'problems' || !alertBox.hidden) {
        if (list.length) showProblems(list, false);
        else hideAlert();
      }
    }

    function setBusy(on) {
      state.busy = on;
      btn.submit.disabled = on;
      btn.back.disabled = on;
      btn.submit.classList.toggle('is-busy', on);
      btn.submit.setAttribute('aria-busy', String(on));
      submitText.textContent = on ? gettext('Confirming your shifts…') : submitLabel(picked().length);
    }

    /* Spot counts */
    function applyCounts(counts, prune) {
      if (!counts) return;
      rows.forEach((r) => {
        if (counts[r.id] != null) r.taken = Math.max(0, Math.floor(+counts[r.id]) || 0);
      });
      if (prune) {
        const gone = picked().filter(isFull);
        if (gone.length) {
          gone.forEach((r) => { r.input.checked = false; });
          showNote(fmt(ngettext('%(shifts)s just filled up, so we took it off your schedule.', '%(shifts)s just filled up, so we took them off your schedule.', gone.length), { shifts: gone.map(shortName).join('; ') }));
        }
      }
      refresh();
      renderOpenLine();
    }
    async function loadCounts() {
      if (preview || !spotsUrl) return;
      try {
        const res = await fetch(spotsUrl, { headers: { Accept: 'application/json' }, cache: 'no-store', credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        state.lastLoad = Date.now();
        applyCounts(data.counts, true);
      } catch (e) { /* keep the counts the page came with */ }
    }

    /* Sending */
    function previewSubmit() {
      return new Promise((resolve) => setTimeout(() => {
        const list = picked();
        const full = list.filter(isFull);
        if (full.length) {
          resolve({
            ok: false, error: 'unavailable', title: gettext('A shift is no longer available'),
            message: fmt(gettext('%s filled up while you were signing up.'), [full.map(shortName).join('; ')]), remove: full.map((r) => +r.id),
          });
          return;
        }
        list.forEach((r) => { r.taken += 1; });
        resolve({
          ok: true,
          confirmation: {
            firstName: form.elements.first_name.value.trim(), email: form.elements.email.value.trim(), emailed: false,
            count: list.length, icsUrl: '',
            shifts: list.map((r) => ({ id: r.id, day: r.day, time: r.time, role: r.roleName, where: r.where, color: r.color, gcal: r.gcal })),
          },
        });
      }, 600));
    }

    function applyServerErrors(errors) {
      const problems = [];
      Object.keys(errors || {}).forEach((name) => {
        const msg = (errors[name] || [])[0] || gettext('Check this field.');
        if (name === 'shifts') return;
        if (name === 'website') return;
        if (name === '__all__') { problems.push({ id: 'vol-details-title', msg }); return; }
        setFieldError(name, msg);
        problems.push({ id: `vol-${name}`, msg });
      });
      if (errors && errors.shifts) {
        go('pick');
        showShiftError(errors.shifts[0]);
        return;
      }
      if (problems.length) showProblems(problems, true);
    }

    function showDone(conf) {
      const n = conf.count || conf.shifts.length;
      $('[data-vol-badge-name]').textContent = conf.firstName;
      $('[data-vol-done-title]').textContent = fmt(ngettext('Your shift is confirmed, %(name)s.', 'Your %(count)s shifts are confirmed, %(name)s.', n), { count: n, name: conf.firstName });
      $('[data-vol-done-lede]').textContent = (conf.emailed && !preview ? fmt(gettext('A copy is on its way to %s.'), [conf.email]) + ' ' : '')
        + gettext('Add your shifts to your calendar so you have the times handy.');
      $('[data-vol-preview-note]').hidden = !preview;
      const list = $('[data-vol-tickets]');
      const tpl = $('[data-vol-ticket-template]');
      list.textContent = '';
      conf.shifts.forEach((s) => {
        const item = tpl.content.firstElementChild.cloneNode(true);
        item.querySelector('[data-day]').textContent = s.day;
        item.querySelector('[data-time]').textContent = s.time;
        item.querySelector('[data-role]').textContent = s.where ? `${s.role}, ${s.where}` : s.role;
        item.querySelector('[data-dot]').style.setProperty('--role', s.color);
        item.querySelector('[data-gcal]').href = s.gcal;
        list.appendChild(item);
      });
      const ics = $('[data-vol-ics]');
      ics.parentElement.hidden = !conf.icsUrl;
      if (conf.icsUrl) ics.href = conf.icsUrl;

      form.reset();
      rows.forEach((r) => { r.input.checked = false; });
      checks.forEach((c) => setFieldError(c.name, ''));
      hideAlert();
      showNote('');
      clearShiftError();
      state.tried = false;
      refresh();
      renderOpenLine();
      go('done');
      announce(fmt(ngettext('Signed up. %s shift confirmed.', 'Signed up. %s shifts confirmed.', n), [n]));
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (state.busy) return;
      if (state.step === 'pick') { btn.next.click(); return; }
      if (state.step !== 'details') return;
      state.tried = true;
      if (!picked().length) {
        go('pick');
        showShiftError(gettext('Choose at least one shift.'));
        return;
      }
      const problems = checkFields(true);
      if (problems.length) { showProblems(problems, true); return; }
      hideAlert();
      setBusy(true);
      let res = null;
      let data = null;
      try {
        if (preview) {
          data = await previewSubmit();
        } else {
          res = await fetch(form.action, {
            method: 'POST', body: new FormData(form), credentials: 'same-origin',
            headers: { Accept: 'application/json' },
          });
          data = await res.json().catch(() => null);
        }
      } catch (err) {
        data = null;
      }
      setBusy(false);
      if (!data) {
        if (res && res.status === 403) {
          showAlert(gettext('Your sign-up didn’t go through'), gettext('This page was open for a long time. Reload it, then pick your shifts again.'));
        } else if (res) {
          showAlert(gettext('Your sign-up didn’t go through'), gettext('Something went wrong on our side. Please try again in a minute.'));
        } else {
          showAlert(gettext('We couldn’t send your sign-up'), gettext('Check your internet connection and try again. Your shifts are still selected.'));
        }
        return;
      }
      if (data.ok) {
        if (data.counts) applyCounts(data.counts, false);
        showDone(data.confirmation);
        return;
      }
      if (data.counts) applyCounts(data.counts, false);
      if (data.error === 'invalid') { applyServerErrors(data.errors); return; }
      if (data.error === 'unavailable') {
        (data.remove || []).forEach((id) => { const r = byId[String(id)]; if (r) r.input.checked = false; });
        refresh();
        go('pick');
        showNote(`${data.title}. ${data.message}`);
        announce(data.message);
        return;
      }
      showAlert(data.title || gettext('Your sign-up didn’t go through'), data.message || gettext('Please try again in a minute.'));
    });

    /* Wiring */
    $('[data-vol-sheet]').addEventListener('change', (e) => {
      const input = e.target;
      if (!input || input.type !== 'checkbox') return;
      const r = byId[input.value];
      if (!r) return;
      refresh();
      if (input.checked) { clearShiftError(); showNote(''); }
      announce(fmt(input.checked ? gettext('Added %s.') : gettext('Removed %s.'), [shortName(r)]) + ' '
        + fmt(ngettext('%s shift chosen.', '%s shifts chosen.', picked().length), [picked().length]));
    });
    const chips = root.querySelectorAll('.vol-chip');
    chips.forEach((chip) => chip.addEventListener('click', () => {
      state.role = chip.dataset.role || '';
      chips.forEach((c) => c.setAttribute('aria-pressed', String(c === chip)));
      applyFilter();
    }));
    const hideFull = $('[data-vol-hide-full]');
    if (hideFull) hideFull.addEventListener('change', () => { state.hideFull = hideFull.checked; applyFilter(); });
    mineList.addEventListener('click', (e) => {
      const b = e.target.closest('[data-remove]');
      if (!b) return;
      const r = byId[b.dataset.remove];
      r.input.checked = false;
      refresh();
      announce(fmt(gettext('Removed %s.'), [shortName(r)]));
      if (!picked().length) go('pick');
      else (mineList.querySelector('[data-remove]') || $('#vol-details-title')).focus();
    });
    alertBox.addEventListener('click', (e) => {
      const link = e.target.closest('[data-focus]');
      if (!link) return;
      e.preventDefault();
      const target = document.getElementById(link.dataset.focus);
      if (!target) return;
      if (link.dataset.focus === 'vol-pick-title') go('pick');
      target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
      target.focus({ preventScroll: true });
    });
    form.addEventListener('input', recheck);
    form.addEventListener('change', (e) => { if (!e.target.closest('[data-vol-sheet]')) recheck(); });

    btn.next.addEventListener('click', () => {
      if (!picked().length) { showShiftError(gettext('Choose at least one shift to continue.')); return; }
      clearShiftError();
      go('details');
    });
    btn.back.addEventListener('click', () => go('pick'));
    $('[data-vol-change]').addEventListener('click', () => go('pick'));
    btn.again.addEventListener('click', () => { go('pick'); loadCounts(); });
    if (btn.close) btn.close.addEventListener('click', () => { const d = root.closest('dialog'); if (d) d.close(); });

    const host = root.closest('dialog');
    if (host) {
      host.addEventListener('vol:opened', () => {
        if (Date.now() - state.lastLoad > 15000) loadCounts();
      });
      host.addEventListener('vol:closed', () => { if (state.step === 'done') go('pick', { quiet: true }); });
    }
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && state.step !== 'done' && Date.now() - state.lastLoad > 30000) {
        if (!host || host.open) loadCounts();
      }
    });

    /* Start */
    root.classList.add('is-ready');
    const tools = $('[data-vol-tools]');
    if (tools) tools.hidden = false;
    refresh();
    renderOpenLine();
    go(steps[root.dataset.start] ? root.dataset.start : 'pick', { quiet: true });
  }
})();
