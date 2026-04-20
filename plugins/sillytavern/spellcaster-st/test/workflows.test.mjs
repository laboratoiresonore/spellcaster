// Workflow-builder snapshot tests. The ST plugin's WAN/LTX path goes
// through the Guild (phase-7 rewrite) but the Klein / Kontext / SDXL
// builders still live inline in server-plugin.js. This suite guards
// the things we've historically regressed on:
//
//   1. Klein node class_types MUST be exact CamelCase — not "FLUX.2
//      Klein" with dots/spaces. The ComfyUI server rejects anything
//      else and the plugin silently 500s.
//   2. Sentinel node lookups (Flux2KleinRefLatentController etc.)
//      must stay in /capabilities so the frontend's arch-gating works.
//   3. The Guild /api/video/shots contract used by _animateViaGuild
//      must keep the fields the server plugin relies on.
//
// These tests read the source text directly rather than running the
// builders (they produce huge node graphs that need a real ComfyUI to
// validate); the source-text assertions are cheap + effective.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, '..', 'server-plugin.js');
const src = fs.readFileSync(srcPath, 'utf8');

// Canonical Klein enhancer node names (from CLAUDE.md §8 and verified
// against ComfyUI's /object_info). Any other casing is a bug.
const KLEIN_CANONICAL = [
    'Flux2KleinRefLatentController',
    'Flux2KleinTextRefBalance',
    'Flux2KleinColorAnchor',
    'Flux2KleinMaskRefController',
];

// Reserved Klein-sounding strings that we should NEVER see in this
// file — they're the hallucinations the audit caught in sibling
// repos. If any of them slip in through a copy-paste, this test fails
// before it reaches a user.
const KLEIN_HALLUCINATIONS = [
    'FLUX.2 Klein Ref',
    'FLUX.2 Klein Text',
    'FLUX.2 Klein Color',
    'Flux 2 Klein Ref',     // spaced variant
    '"Color Anchor"',       // the "friendly name" that ISN'T a class_type
    '"Klein Ref Latent"',
];

test('server-plugin.js has no hallucinated Klein node names', () => {
    for (const bad of KLEIN_HALLUCINATIONS) {
        assert.ok(!src.includes(bad),
            `server-plugin.js leaks a hallucinated Klein node name: ${bad}. ` +
            `Only the CamelCase variants (${KLEIN_CANONICAL.join(', ')}) ` +
            `are valid class_types — ComfyUI will reject the others.`);
    }
});

test('server-plugin.js references at least one Klein canonical name', () => {
    // Capabilities probe + detectEditEngine both check for Klein
    // nodes. If a refactor deleted both, Klein routing silently
    // falls back to SDXL and nobody notices.
    const hit = KLEIN_CANONICAL.some(n => src.includes(n));
    assert.ok(hit,
        `server-plugin.js no longer references any canonical Klein ` +
        `node (${KLEIN_CANONICAL.join(', ')}). The /capabilities ` +
        `endpoint + Klein routing will silently break.`);
});

// Guild contract: _animateViaGuild hits five endpoint shapes. If any
// one breaks, /animate falls back to SDXL noise-inject and the user
// doesn't get real video. These assertions pin the URL structure.
test('_animateViaGuild hits the canonical Guild video endpoints', () => {
    const expected = [
        '/api/video/shots',                     // create + list
        '/api/video/shots/${shotId}/reference', // attach ref
        '/api/video/shots/${shotId}/render',    // start render
        '/api/video/shots/${shotId}/video',     // fetch bytes
        '/api/video/shots/${id}/cancel',        // cancel (phase-8)
    ];
    for (const e of expected) {
        assert.ok(src.includes(e),
            `_animateViaGuild no longer uses ${e}. ` +
            `Check the Guild contract + any phase-8 changes.`);
    }
});

// _rejectUnsafeUrl's metadata host list comes from the cloud-provider
// services that an attacker could pivot through. Keep the list
// anchored — a careless trim could re-open the SSRF vector.
test('_rejectUnsafeUrl blocks the full metadata-host list', () => {
    for (const host of [
        '169.254.169.254',
        'metadata.google.internal',
        ".internal",
    ]) {
        assert.ok(src.includes(host),
            `_rejectUnsafeUrl no longer blocks ${host}. ` +
            `SSRF to cloud metadata services is wide open.`);
    }
});

// Phase-7 /cross/send data-url scheme regex. If this guard is removed
// an attacker can stage `data:text/html` via the cross-interface bus.
test('/cross/send enforces data:image/<type> scheme', () => {
    assert.ok(/data:image\\\/\[a-zA-Z0-9\.\+-\]\+/.test(src),
        `/cross/send lost its data:image/* regex gate. A caller can ` +
        `now smuggle data:text/html through the Guild event bus.`);
});

// Phase-1 /dispatch gate. If the env check is accidentally inverted
// or deleted this becomes a generic remote-workflow-submission
// endpoint with no auth.
test('/dispatch is gated behind SPELLCASTER_ALLOW_DISPATCH=1', () => {
    assert.ok(src.includes('SPELLCASTER_ALLOW_DISPATCH'),
        `/dispatch no longer checks SPELLCASTER_ALLOW_DISPATCH. ` +
        `Raw workflow submission is exposed unauthenticated.`);
});
