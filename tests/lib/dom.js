// Minimal DOM shim for driving the generated CRM bundle under node.
//
// The one thing this MUST get right: `<input type="date">` value sanitization.
// A shim that stores whatever string you assign makes every date-wipe test
// unable to fail -- `snapDates` snapshots `el.value` after insertion, so if the
// browser would have rejected the value and this shim keeps it, the baseline
// and the current value agree for the wrong reason and the test passes on
// broken code. An earlier harness had exactly that hole.
//
// Per HTML: a date input's value is the empty string unless the string is a
// valid date string -- yyyy-mm-dd, 4+ digit year > 0, month 01-12, day within
// that month including leap rules.

function isValidDateString(s) {
  const m = /^(\d{4,})-(\d{2})-(\d{2})$/.exec(String(s));
  if (!m) return false;
  const y = +m[1], mo = +m[2], d = +m[3];
  if (y < 1 || mo < 1 || mo > 12 || d < 1) return false;
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return d <= days[mo - 1];
}

function makeEl(id, doc) {
  const el = {
    id: id || '', tagName: 'DIV', type: '', textContent: '', _value: '',
    _attrs: {}, style: {}, children: [], _classes: new Set(), onclick: null,
    get value() { return this._value; },
    set value(v) {
      // the sanitization step that makes date tests falsifiable
      if (this.type === 'date') {
        this._value = isValidDateString(v) ? String(v) : '';
      } else {
        this._value = v === null || v === undefined ? '' : String(v);
      }
    },
    get className() { return [...this._classes].join(' '); },
    set className(v) {
      this._classes = new Set(String(v || '').split(/\s+/).filter(Boolean));
    },
    classList: null,
    setAttribute(k, v) {
      this._attrs[k] = v;
      if (k === 'id') { this.id = v; if (doc) doc._register(this); }
      if (k === 'type') this.type = v;
      if (k === 'value') this.value = v;
    },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    get innerHTML() { return this._html || ''; },
    // Keep the elements this markup produced, so querySelectorAll below can
    // answer for real. Without it #dbody.querySelectorAll returned [] and
    // anything iterating the form's controls -- doSave's save-time lock --
    // was a no-op under test that no assertion could see.
    set innerHTML(h) {
      this._html = String(h);
      this._parsed = doc ? doc._parse(this._html) : [];
    },
    // Listeners are RECORDED, not just swallowed. A shim that drops them makes
    // every close-affordance test unable to fail: the handler never runs, the
    // drawer never closes, and an assertion of "still open" passes on code
    // that does nothing. See fire() for what this deliberately does NOT model.
    _listeners: Object.create(null),
    addEventListener(type, fn) {
      (this._listeners[type] || (this._listeners[type] = [])).push(fn);
    },
    removeChild() {}, remove() {}, focus() {}, blur() {},
    insertAdjacentHTML(_pos, h) { if (doc) doc._parse(String(h)); },
    // Tag-name selectors only ("input,select,textarea"). Enough for the form
    // lock; anything else still gets [], which is why the header of
    // test_drawer_close.js lists what this shim cannot answer.
    querySelectorAll(sel) {
      const want = String(sel || '').split(',').map(s => s.trim().toUpperCase());
      return (this._parsed || []).filter(e => want.includes(e.tagName));
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    closest() { return null; },
    appendChild(c) { this.children.push(c); if (c && c.id && doc) doc._register(c); return c; },
  };
  el.classList = {
    add: (...c) => c.forEach(x => el._classes.add(x)),
    remove: (...c) => c.forEach(x => el._classes.delete(x)),
    contains: (c) => el._classes.has(c),
    toggle: (c) => (el._classes.has(c) ? el._classes.delete(c) : el._classes.add(c)),
  };
  return el;
}

function createDocument() {
  const els = Object.create(null);          // null proto: '__proto__' is a key
  const doc = {
    _els: els,
    _register(el) { if (el && el.id) els[el.id] = el; },
    // Extract every tag carrying an id so controls exist with their real
    // id/type/value. Not a real parser -- enough to make the handlers, which
    // only ever reach elements via getElementById, behave as in a browser.
    _parse(html) {
      const tag = /<(input|select|textarea|button|div|span|p|a|td|tr)\b([^>]*)>/gi;
      const made = [];
      let m;
      while ((m = tag.exec(html)) !== null) {
        const attrs = m[2];
        const idm = /\bid="([^"]*)"/.exec(attrs);
        if (!idm) continue;
        const el = doc.getElementById(idm[1]);
        made.push(el);
        el.tagName = m[1].toUpperCase();
        const tm = /\btype="([^"]*)"/.exec(attrs);
        if (tm) el.type = tm[1];
        const vm = /\bvalue="([^"]*)"/.exec(attrs);
        // assign through the setter so date sanitization applies
        el.value = vm ? decodeEntities(vm[1]) : '';
        el.disabled = false;   // a re-rendered control starts enabled
      }
      return made;
    },
    getElementById(id) {
      if (!els[id]) { const e = makeEl(id, doc); els[id] = e; }
      return els[id];
    },
    createElement(t) { const e = makeEl('', doc); e.tagName = String(t).toUpperCase(); return e; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    _listeners: Object.create(null),
    addEventListener(type, fn) {
      (doc._listeners[type] || (doc._listeners[type] = [])).push(fn);
    },
  };
  doc.body = makeEl('body', doc);
  doc.documentElement = makeEl('html', doc);
  return doc;
}

// Invoke the handlers registered on `target` for `type`.
//
// This does NOT model bubbling: elements in this shim are a flat id registry,
// not a tree, so an 'input' on a child cannot propagate to #dbody on its own.
// Firing directly at #dbody stands in for "the event reached the delegate",
// which is the browser behaviour the app relies on but is not itself under
// test here. What IS under test is what our handler does once it arrives.
// Returns the number of handlers invoked so a test can assert one was wired.
function fire(target, type, evt) {
  const hs = (target && target._listeners && target._listeners[type]) || [];
  hs.forEach(fn => fn(evt || {}));
  return hs.length;
}

function decodeEntities(s) {
  return String(s).replace(/&#47;/g, '/').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

module.exports = { createDocument, makeEl, isValidDateString, decodeEntities, fire };
