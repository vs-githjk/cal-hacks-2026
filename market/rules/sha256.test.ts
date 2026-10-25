import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { sha256Hex } from './sha256';

// #449 RT-2: the module has no crypto global to lean on, so the hash is plain TS. Node's crypto is the oracle, in tests only.
describe('sha256Hex', () => {
  it('matches the published vectors', () => {
    expect(sha256Hex('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(sha256Hex('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')).toBe('248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1');
  });

  it('agrees with node:crypto across the block boundaries (55, 56, 63, 64, 65 bytes) and random ASCII', () => {
    for (const n of [0, 1, 54, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000]) {
      const s = 'x'.repeat(n);
      expect(sha256Hex(s)).toBe(createHash('sha256').update(s).digest('hex'));
    }
    fc.assert(fc.property(fc.string({ unit: 'binary-ascii', maxLength: 300 }), (s) => sha256Hex(s) === createHash('sha256').update(s, 'latin1').digest('hex')));
  });
});
