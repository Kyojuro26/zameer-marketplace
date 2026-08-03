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
    set innerHTML(h) { this._html = String(h); if (doc) doc._parse(this._html); },
    addEventListener() {}, removeChild() {}, remove() {}, focus() {}, blur() {},
    insertAdjacentHTML(_pos, h) { if (doc) doc._parse(String(h)); },
    querySelectorAll() { return []; }, querySelector() { return null; },
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
      let m;
      while ((m = tag.exec(html)) !== null) {
        const attrs = m[2];
        const idm = /\bid="([^"]*)"/.exec(attrs);
        if (!idm) continue;
        const el = doc.getElementById(idm[1]);
        el.tagName = m[1].toUpperCase();
        const tm = /\btype="([^"]*)"/.exec(attrs);
        if (tm) el.type = tm[1];
        const vm = /\bvalue="([^"]*)"/.exec(attrs);
        // assign through the setter so date sanitization applies
        el.value = vm ? decodeEntities(vm[1]) : '';
      }
    },
    getElementById(id) {
      if (!els[id]) { const e = makeEl(id, doc); els[id] = e; }
      return els[id];
    },
    createElement(t) { const e = makeEl('', doc); e.tagName = String(t).toUpperCase(); return e; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
  };
  doc.body = makeEl('body', doc);
  doc.documentElement = makeEl('html', doc);
  return doc;
}

function decodeEntities(s) {
  return String(s).replace(/&#47;/g, '/').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

module.exports = { createDocument, makeEl, isValidDateString, decodeEntities };
