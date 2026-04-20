// Tests for the ST server plugin's validators. Uses Node's built-in
// test runner (node --test). Run from the plugin directory:
//
//   node --test test/
//
// Imports the REAL helpers from server-plugin.js via its named exports
// — no copy/paste — so the tests catch the validator drifting from its
// tested contract.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
    _rejectOversizedB64,
    _rejectUnsafeUrl,
    _safeNameOrNull,
    _roundMod,
    _capPrompt,
} from '../server-plugin.js';

// ── _rejectOversizedB64 ─────────────────────────────────────────────
test('_rejectOversizedB64 passes small strings', () => {
    assert.equal(_rejectOversizedB64('abc'), null);
    assert.equal(_rejectOversizedB64('A'.repeat(1024)), null);
});
test('_rejectOversizedB64 rejects oversize', () => {
    const huge = 'A'.repeat(28 * 1024 * 1024 + 1);
    const err = _rejectOversizedB64(huge);
    assert.equal(typeof err.error, 'string');
    assert.match(err.error, /too large/);
});
test('_rejectOversizedB64 rejects non-strings', () => {
    assert.ok(_rejectOversizedB64(null));
    assert.ok(_rejectOversizedB64(undefined));
    assert.ok(_rejectOversizedB64(42));
    assert.ok(_rejectOversizedB64({}));
});

// ── _rejectUnsafeUrl ────────────────────────────────────────────────
test('_rejectUnsafeUrl accepts http(s)', () => {
    assert.equal(_rejectUnsafeUrl('http://127.0.0.1:8188/'), null);
    assert.equal(_rejectUnsafeUrl('https://example.com/foo'), null);
    assert.equal(_rejectUnsafeUrl('http://192.168.1.50:7777'), null);
});
test('_rejectUnsafeUrl rejects non-http schemes', () => {
    for (const u of [
        'file:///etc/passwd',
        'gopher://example.com',
        'ftp://example.com',
        'javascript:alert(1)',
        'data:image/png;base64,abc',
    ]) {
        const err = _rejectUnsafeUrl(u);
        assert.ok(err, `should reject: ${u}`);
        assert.ok(err.error, `should have error string for: ${u}`);
    }
});
test('_rejectUnsafeUrl rejects cloud metadata hosts', () => {
    assert.ok(_rejectUnsafeUrl('http://169.254.169.254/latest/meta-data'));
    assert.ok(_rejectUnsafeUrl('http://metadata.google.internal/computeMetadata/v1/'));
    assert.ok(_rejectUnsafeUrl('http://foo.internal/'));
});
test('_rejectUnsafeUrl rejects malformed / empty', () => {
    assert.ok(_rejectUnsafeUrl(''));
    assert.ok(_rejectUnsafeUrl(null));
    assert.ok(_rejectUnsafeUrl(42));
    assert.ok(_rejectUnsafeUrl('not a url'));
});

// ── _safeNameOrNull ─────────────────────────────────────────────────
test('_safeNameOrNull accepts normal names', () => {
    assert.equal(_safeNameOrNull('alice.png'), 'alice.png');
    assert.equal(_safeNameOrNull('wizard_01.png'), 'wizard_01.png');
    assert.equal(_safeNameOrNull('Séraphine'), 'Séraphine');        // Unicode
    assert.equal(_safeNameOrNull('文字化け.png'), '文字化け.png');        // CJK
    assert.equal(_safeNameOrNull('  trimmed  '), 'trimmed');
});
test('_safeNameOrNull rejects path traversal', () => {
    assert.equal(_safeNameOrNull('../../etc/passwd'), null);
    assert.equal(_safeNameOrNull('..\\..\\etc'), null);
    assert.equal(_safeNameOrNull('foo/bar'), null);
    assert.equal(_safeNameOrNull('foo\\bar'), null);
    assert.equal(_safeNameOrNull('.'), null);
    assert.equal(_safeNameOrNull('..'), null);
});
test('_safeNameOrNull rejects control chars + NUL', () => {
    assert.equal(_safeNameOrNull('evil\x00name'), null);
    assert.equal(_safeNameOrNull('evil\x1fname'), null);
    assert.equal(_safeNameOrNull('line\nbreak'), null);
});
test('_safeNameOrNull rejects Windows specials', () => {
    assert.equal(_safeNameOrNull('C:foo'), null);
    assert.equal(_safeNameOrNull('file*.png'), null);
    assert.equal(_safeNameOrNull('file?.png'), null);
    assert.equal(_safeNameOrNull('file<>.png'), null);
    assert.equal(_safeNameOrNull('pipe|name'), null);
});
test('_safeNameOrNull rejects empty / oversize', () => {
    assert.equal(_safeNameOrNull(''), null);
    assert.equal(_safeNameOrNull('a'.repeat(200)), null);
    assert.equal(_safeNameOrNull(null), null);
    assert.equal(_safeNameOrNull(undefined), null);
});

// ── _roundMod ───────────────────────────────────────────────────────
test('_roundMod rounds to nearest multiple', () => {
    assert.equal(_roundMod(100, 16, 64, 2048), 96);
    assert.equal(_roundMod(105, 16, 64, 2048), 112);
    assert.equal(_roundMod(1024, 16, 64, 2048), 1024);
});
test('_roundMod clamps to min/max', () => {
    assert.equal(_roundMod(10, 16, 256, 2048), 256);       // min kicks in
    assert.equal(_roundMod(10000, 16, 64, 2048), 2048);    // max kicks in
    assert.equal(_roundMod(1e9, 16, 64, 2048), 2048);      // huge value capped
});
test('_roundMod handles garbage', () => {
    // NaN -> minV per the implementation
    assert.equal(_roundMod(NaN, 16, 64, 2048), 64);
    assert.equal(_roundMod('abc', 16, 64, 2048), 64);
    assert.equal(_roundMod(null, 16, 64, 2048), 64);
});

// ── _capPrompt ──────────────────────────────────────────────────────
test('_capPrompt passes short strings unchanged', () => {
    assert.equal(_capPrompt('hello'), 'hello');
    assert.equal(_capPrompt(''), '');
});
test('_capPrompt truncates at cap', () => {
    const long = 'A'.repeat(5000);
    const out = _capPrompt(long, 100);
    assert.equal(out.length, 100);
    assert.equal(out, 'A'.repeat(100));
});
test('_capPrompt handles null/undefined', () => {
    assert.equal(_capPrompt(null), '');
    assert.equal(_capPrompt(undefined), '');
});
test('_capPrompt coerces non-strings to string', () => {
    assert.equal(_capPrompt(42), '42');
    assert.equal(_capPrompt({ toString: () => 'obj' }), 'obj');
});
