/**
 * v0.28.5 (A4) — Existing-brain dimension-mismatch detection unit tests.
 *
 * Pairs with `gbrain init` and `gbrain doctor`'s loud-failure paths. Validates
 * that:
 *   1. readContentChunksEmbeddingDim correctly reports null on a fresh brain.
 *   2. After initSchema, it returns the actual templated dim (1536 default).
 *   3. embeddingMismatchMessage produces a recipe that explicitly drops the
 *      HNSW index, alters the column, wipes embeddings, and conditionally
 *      reindexes — codex's #8 finding from plan review.
 */

import { test, expect, describe, beforeAll, afterAll } from 'bun:test';
import { PGLiteEngine } from '../src/core/pglite-engine.ts';
import {
  readContentChunksEmbeddingDim,
  embeddingMismatchMessage,
} from '../src/core/embedding-dim-check.ts';

// Canonical pattern: single engine per file, init once, disconnect once.
// The two tests below diverge in whether they want a migrated brain or a
// pre-initSchema brain — handled by inline reset / second-engine instead of
// resetting in beforeEach (keeps the migrated state cached for the LATEST case).
let engine: PGLiteEngine;

beforeAll(async () => {
  engine = new PGLiteEngine();
  await engine.connect({});
  await engine.initSchema();
});

afterAll(async () => {
  await engine.disconnect();
});

describe('readContentChunksEmbeddingDim', () => {
  test('returns dims from a migrated brain (1536d via legacy-embedding preload)', async () => {
    // v0.37 fix wave: the canonical gateway default is now 1280 (ZE).
    // However, `bunfig.toml` preloads `test/helpers/legacy-embedding-preload.ts`
    // which configures the gateway to OpenAI/1536 BEFORE any test runs.
    // This preserves the 20+ test files with hardcoded 1536-d
    // Float32Array fixtures. So initSchema() under tests produces a
    // 1536-d column.
    //
    // New v0.37 tests that need to assert the ZE/1280 default can call
    // configureGateway() explicitly in their own beforeAll, which
    // overrides the preload.
    const result = await readContentChunksEmbeddingDim(engine);
    expect(result.exists).toBe(true);
    expect(result.dims).toBe(1536);
  }, 30000);

  test('returns { exists: false, dims: null } on a fresh brain (no initSchema)', async () => {
    // One-off engine for the fresh-brain case. Never call initSchema so
    // content_chunks doesn't exist yet. Cleaned up at end of test.
    const fresh = new PGLiteEngine();
    await fresh.connect({});
    try {
      const result = await readContentChunksEmbeddingDim(fresh);
      expect(result.exists).toBe(false);
      expect(result.dims).toBeNull();
    } finally {
      await fresh.disconnect();
    }
  }, 30000);
});

describe('embeddingMismatchMessage', () => {
  test('Postgres branch inlines all four recipe steps for HNSW-eligible dims', () => {
    const msg = embeddingMismatchMessage({
      currentDims: 1536,
      requestedDims: 768,
      requestedModel: 'nomic-embed-text',
      source: 'init',
      engineKind: 'postgres',
    });
    expect(msg).toContain('vector(1536)');
    expect(msg).toContain('vector(768)');
    expect(msg).toContain('DROP INDEX IF EXISTS idx_chunks_embedding');
    expect(msg).toContain('ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(768)');
    expect(msg).toContain('UPDATE content_chunks SET embedding = NULL');
    expect(msg).toContain('CREATE INDEX IF NOT EXISTS idx_chunks_embedding');
    expect(msg).toContain('docs/embedding-migrations.md');
  });

  test('Postgres branch skips HNSW recreate when requested dims exceed pgvector cap', () => {
    // Codex finding #8: 2048d (Voyage 4 Large) cannot be HNSW-indexed in pgvector.
    // The recipe must NOT instruct a CREATE INDEX HNSW for that dim.
    const msg = embeddingMismatchMessage({
      currentDims: 1536,
      requestedDims: 2048,
      requestedModel: 'voyage-4-large',
      source: 'init',
      engineKind: 'postgres',
    });
    expect(msg).toContain('vector(2048)');
    expect(msg).toContain('Skip reindex');
    expect(msg).toContain("exceeds pgvector's HNSW cap");
    // The HNSW CREATE INDEX line must NOT appear in the 2048d recipe.
    expect(msg).not.toContain('CREATE INDEX IF NOT EXISTS idx_chunks_embedding\n  ON content_chunks USING hnsw');
  });

  test('source: doctor uses a different header than source: init', () => {
    const initMsg = embeddingMismatchMessage({ currentDims: 1536, requestedDims: 768, source: 'init', engineKind: 'postgres' });
    const doctorMsg = embeddingMismatchMessage({ currentDims: 1536, requestedDims: 768, source: 'doctor', engineKind: 'postgres' });
    expect(initMsg).toContain('Refusing to silently re-template');
    expect(doctorMsg).toContain('Embedding dimension mismatch detected');
  });

  // v0.37 fix wave Lane D.1: PGLite branch uses wipe-and-reinit recipe
  // because PGLite can't ALTER vector column types.
  test('PGLite branch uses wipe-and-reinit, not ALTER COLUMN', () => {
    const msg = embeddingMismatchMessage({
      currentDims: 1536,
      requestedDims: 1280,
      requestedModel: 'zeroentropyai:zembed-1',
      source: 'init',
      engineKind: 'pglite',
      databasePath: '/tmp/test-brain.pglite',
    });
    expect(msg).toContain('vector(1536)');
    expect(msg).toContain('vector(1280)');
    expect(msg).toContain('mv /tmp/test-brain.pglite /tmp/test-brain.pglite.bak');
    expect(msg).toContain('gbrain init --pglite --embedding-model zeroentropyai:zembed-1 --embedding-dimensions 1280');
    expect(msg).toContain('PGLite cannot ALTER vector column types');
    // Must NOT contain the Postgres-only SQL recipe.
    expect(msg).not.toContain('ALTER TABLE content_chunks ALTER COLUMN');
    expect(msg).not.toContain('DROP INDEX IF EXISTS idx_chunks_embedding');
  });

  test('PGLite branch falls back to default database path when omitted', () => {
    const msg = embeddingMismatchMessage({
      currentDims: 1536,
      requestedDims: 1280,
      source: 'init',
      engineKind: 'pglite',
    });
    // Default falls back to gbrainPath('brain.pglite').
    expect(msg).toMatch(/mv .+brain\.pglite .+brain\.pglite\.bak/);
  });

  test('PGLite branch must NOT recommend `gbrain config set embedding_model` (no-op after Lane C.2)', () => {
    const msg = embeddingMismatchMessage({
      currentDims: 1536,
      requestedDims: 1280,
      requestedModel: 'zeroentropyai:zembed-1',
      source: 'doctor',
      engineKind: 'pglite',
    });
    // The pre-v0.37 recipe pointed at `gbrain config set embedding_model X`
    // which is a no-op after C.2. Recipe must point at init instead.
    expect(msg).not.toContain('gbrain config set embedding_model');
    expect(msg).not.toContain('gbrain config set embedding_dimensions');
  });
});
