// Tests for the ST UI extension's pure-function helpers. index.js is a
// browser script (no ES-module exports), so these tests re-declare the
// helpers verbatim — the tests pin the contract, and any change in
// index.js needs a matching edit here. The verbatim copies are marked
// `// CANONICAL-COPY` so a future maintainer spotting drift knows where
// to look.

import test from 'node:test';
import assert from 'node:assert/strict';

// ── CANONICAL-COPY of _esc from index.js ────────────────────────────
function _esc(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── CANONICAL-COPY of _urlOk from index.js ──────────────────────────
// Inline helper used by both the /sc-inbox slash command and the
// renderInboxMessages SSE renderer. Uses `new URL(u)` WITHOUT a base,
// so protocol-relative URLs (`//evil.com/x.png`) throw and are
// rejected — a deliberate design.
function _urlOk(u) {
    if (typeof u !== 'string' || !u) return false;
    if (u.startsWith('/api/')) return true;
    try {
        const p = new URL(u);
        if (p.protocol === 'http:' || p.protocol === 'https:') return true;
        if (p.protocol === 'data:' && /^data:image\//i.test(u)) return true;
    } catch { return false; }
    return false;
}

// ── CANONICAL-COPY of _ftString, _ftLabel from index.js ─────────────
const _FN_MAX_ARG_CHARS = 2000;
function _ftString(v) {
    if (v == null) return '';
    return String(v).slice(0, _FN_MAX_ARG_CHARS);
}
function _ftLabel(s, max = 80) {
    return String(s ?? '')
        .replace(/[\r\n]+/g, ' ')
        .replace(/[\[\]()*_`~]/g, '')
        .slice(0, max);
}

// ── CANONICAL-COPY of _trimLocation (phase-7 fix landed) ────────────
function _trimLocation(s) {
    let t = String(s).trim();
    const hinge = t.search(/\s+(?:and|but|then|while|because|after|before|until|so|or|where|as)\s+/i);
    if (hinge > 0) t = t.slice(0, hinge);
    const pronoun = t.search(/\s+(?:he|she|they|his|her|their|it)\s+/i);
    if (pronoun > 0) t = t.slice(0, pronoun);
    return t.trim().slice(0, 60);
}


// ══════════════════════════════════════════════════════════════════
// _esc — HTML escape
// ══════════════════════════════════════════════════════════════════
test('_esc escapes the five HTML specials', () => {
    assert.equal(_esc('<b>'), '&lt;b&gt;');
    assert.equal(_esc('hi & bye'), 'hi &amp; bye');
    assert.equal(_esc('"quoted"'), '&quot;quoted&quot;');
    assert.equal(_esc("it's"), 'it&#39;s');
});
test('_esc is safe for null / undefined / non-strings', () => {
    assert.equal(_esc(null), '');
    assert.equal(_esc(undefined), '');
    assert.equal(_esc(42), '42');
});
test('_esc neutralises an attribute-breakout payload', () => {
    const bad = `" onload="alert(1)`;
    assert.equal(_esc(bad), '&quot; onload=&quot;alert(1)');
});

// ══════════════════════════════════════════════════════════════════
// _urlOk — URL allowlist used in /sc-inbox + SSE inbox renderer
// ══════════════════════════════════════════════════════════════════
test('_urlOk accepts http(s) / data:image / relative /api', () => {
    assert.equal(_urlOk('http://example.com/a.png'), true);
    assert.equal(_urlOk('https://example.com/a.png'), true);
    assert.equal(_urlOk('/api/assets/deadbeef'), true);
    assert.equal(_urlOk('data:image/png;base64,abc'), true);
    assert.equal(_urlOk('data:image/webp;base64,xyz'), true);
});
test('_urlOk rejects javascript: / data:text/html / gopher / ftp', () => {
    assert.equal(_urlOk('javascript:alert(1)'), false);
    assert.equal(_urlOk('data:text/html;base64,PHNjcmlwdD4='), false);
    assert.equal(_urlOk('gopher://example.com'), false);
    assert.equal(_urlOk('ftp://example.com/x'), false);
});
test('_urlOk rejects protocol-relative // URLs', () => {
    // `new URL("//evil.com/x.png")` without a base throws TypeError,
    // which `_urlOk`'s try/catch turns into `false`. This is the
    // design: the browser would otherwise resolve it to the page's
    // scheme, bypassing the allowlist.
    assert.equal(_urlOk('//evil.com/x.png'), false);
});
test('_urlOk rejects other non-/api relative paths', () => {
    // Not under /api/ → must be an absolute URL. Plain relative
    // paths would be resolved against the document, bypassing intent.
    assert.equal(_urlOk('foo/bar.png'), false);
    assert.equal(_urlOk('./x.png'), false);
    assert.equal(_urlOk('/characters/alice.png'), false);  // outside /api/
});
test('_urlOk handles non-strings safely', () => {
    assert.equal(_urlOk(null), false);
    assert.equal(_urlOk(undefined), false);
    assert.equal(_urlOk(42), false);
    assert.equal(_urlOk({}), false);
    assert.equal(_urlOk(''), false);
});

// ══════════════════════════════════════════════════════════════════
// _ftString / _ftLabel — function-tool arg sanitizers
// ══════════════════════════════════════════════════════════════════
test('_ftString is null/undefined-safe', () => {
    assert.equal(_ftString(null), '');
    assert.equal(_ftString(undefined), '');
    assert.equal(_ftString(''), '');
});
test('_ftString caps at 2000 chars', () => {
    const long = 'A'.repeat(5000);
    assert.equal(_ftString(long).length, 2000);
});
test('_ftString coerces non-strings', () => {
    assert.equal(_ftString(42), '42');
    assert.equal(_ftString(['a', 'b']), 'a,b');
});

test('_ftLabel strips markdown delimiters', () => {
    assert.equal(_ftLabel('hello [world]'), 'hello world');
    assert.equal(_ftLabel('*bold*'), 'bold');
    assert.equal(_ftLabel('(parens)'), 'parens');
    assert.equal(_ftLabel('`code`'), 'code');
    assert.equal(_ftLabel('~~strike~~'), 'strike');
});
test('_ftLabel kills newlines', () => {
    assert.equal(_ftLabel('line1\nline2'), 'line1 line2');
    assert.equal(_ftLabel('line1\r\nline2'), 'line1 line2');
});
test('_ftLabel blocks markdown injection', () => {
    // Worst case: LLM tries to inject a link to evil via the alt text
    const bad = `tavern](javascript:alert(1))`;
    const cleaned = _ftLabel(bad);
    assert.ok(!cleaned.includes('('));
    assert.ok(!cleaned.includes(')'));
    assert.ok(!cleaned.includes(']'));
});
test('_ftLabel truncates to max', () => {
    const long = 'x'.repeat(500);
    assert.equal(_ftLabel(long, 50).length, 50);
});

// ══════════════════════════════════════════════════════════════════
// _trimLocation — detectStoryChanges post-filter
// ══════════════════════════════════════════════════════════════════
test('_trimLocation stops at conjunctions', () => {
    assert.equal(_trimLocation('bar and ordered drinks'), 'bar');
    assert.equal(_trimLocation('ancient forest and the dragon'), 'ancient forest');
    assert.equal(_trimLocation('tavern but something was off'), 'tavern');
    assert.equal(_trimLocation('castle while rain fell'), 'castle');
    assert.equal(_trimLocation('misty ruins where moss grew'), 'misty ruins');
    assert.equal(_trimLocation('foggy street as night fell'), 'foggy street');
});
test('_trimLocation stops at clause-pronouns', () => {
    assert.equal(_trimLocation('the market she hurried through'), 'the market');
    assert.equal(_trimLocation('library he had visited before'), 'library');
});
test('_trimLocation leaves clean names untouched', () => {
    assert.equal(_trimLocation('ancient forest'), 'ancient forest');
    assert.equal(_trimLocation('cathedral'), 'cathedral');
    assert.equal(_trimLocation('the moonlit clearing'), 'the moonlit clearing');
});
test('_trimLocation caps at 60 chars', () => {
    const long = 'A'.repeat(100);
    assert.equal(_trimLocation(long).length, 60);
});
