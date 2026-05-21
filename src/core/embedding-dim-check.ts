/**
 * Detect existing-brain embedding-dimension mismatch (v0.28.5 — A4).
 *
 * `gbrain init --embedding-dimensions N` on an existing brain whose
 * `content_chunks.embedding` column is a different `vector(M)` would
 * silently create a config/column drift: the config gets templated to N
 * but the column stays at M. The first sync write blows up with
 * "expected M, got N" — the silent-corruption pattern v0.28.5 is shipped
 * to kill.
 *
 * Loud-failure path: `gbrain init` AND `gbrain doctor` both consult this
 * helper. On mismatch they emit the same inline ALTER recipe (see
 * `embeddingMismatchMessage`) plus a pointer to `docs/embedding-migrations.md`.
 */

import type { BrainEngine } from './engine.ts';
import { PGVECTOR_HNSW_VECTOR_MAX_DIMS } from './vector-index.ts';
import { gbrainPath } from './config.ts';

export interface ColumnDimResult {
  /** Whether the `content_chunks.embedding` column exists. False on a fresh brain. */
  exists: boolean;
  /** Parsed `vector(N)` dimension if known. null when the column doesn't exist or the type isn't vector. */
  dims: number | null;
}

/**
 * Read the actual dimension of `content_chunks.embedding` from the engine.
 *
 * Uses information_schema + a vector-specific catalog query. Returns
 * { exists: false, dims: null } on a fresh brain that doesn't have the
 * column yet. Returns { exists: true, dims: null } on a brain whose
 * column type isn't `vector` (shouldn't happen but defensive).
 */
export async function readContentChunksEmbeddingDim(engine: BrainEngine): Promise<ColumnDimResult> {
  // Probe column existence first to avoid noisy errors on fresh brains.
  const existsRows = await engine.executeRaw<{ exists: boolean }>(
    `SELECT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'content_chunks'
         AND column_name = 'embedding'
     ) AS exists`,
  );
  const exists = !!existsRows?.[0]?.exists;
  if (!exists) return { exists: false, dims: null };

  // pgvector stores dim in pg_type.typmod when atttypmod is set; format_type
  // returns the human-readable `vector(N)`. We parse N out of that.
  const formatRows = await engine.executeRaw<{ formatted: string | null }>(
    `SELECT format_type(a.atttypid, a.atttypmod) AS formatted
       FROM pg_attribute a
       JOIN pg_class c ON c.oid = a.attrelid
       JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relname = 'content_chunks'
        AND a.attname = 'embedding'
        AND NOT a.attisdropped`,
  );
  const formatted = formatRows?.[0]?.formatted ?? null;
  if (!formatted) return { exists: true, dims: null };

  const m = formatted.match(/vector\((\d+)\)/i);
  return { exists: true, dims: m ? parseInt(m[1], 10) : null };
}

/**
 * Build the human-readable recipe printed when an existing brain's column
 * dim doesn't match the requested dim.
 *
 * v0.37 fix wave (Lane D.1): branches on engine kind because the recipes
 * are fundamentally different:
 *
 * - **PGLite** has no native pgvector extension (the WASM build can't
 *   `ALTER COLUMN TYPE vector(N)`), so the only path is wipe-and-reinit
 *   via `gbrain init --pglite --embedding-model X --embedding-dimensions N`.
 *   The recipe derives the active database path so users don't paste a
 *   stale literal that ignores `GBRAIN_HOME` / `--path` / their config.
 * - **Postgres** keeps the existing four-step SQL recipe.
 *
 * The old recipe pointed at `gbrain config set embedding_model X` which
 * is a no-op for the embed pipeline (the embed gateway reads file plane,
 * not DB plane). After Lane C.2 that command refuses; the recipe now
 * points at the actual fix path.
 */
export interface EmbeddingMismatchOpts {
  currentDims: number;
  requestedDims: number;
  requestedModel?: string;
  source?: 'init' | 'doctor' | 'embed';
  /**
   * PGLite vs Postgres branching. Required so the recipe matches the
   * brain's actual engine. Pre-v0.37 default was 'postgres' (the SQL
   * recipe), which produced the wrong recipe for the default install
   * on PGLite.
   */
  engineKind: 'pglite' | 'postgres';
  /**
   * Active PGLite database path. Used only for the PGLite branch; if
   * omitted, falls back to the default `gbrainPath('brain.pglite')`.
   * Resolving at the call site is preferred because the caller knows
   * about `--path` flags and `GBRAIN_HOME` overrides.
   */
  databasePath?: string;
}

export function embeddingMismatchMessage(opts: EmbeddingMismatchOpts): string {
  const { currentDims, requestedDims, requestedModel, source, engineKind, databasePath } = opts;
  const header = source === 'doctor'
    ? `Embedding dimension mismatch detected.`
    : `Refusing to silently re-template existing brain.`;

  if (engineKind === 'pglite') {
    const activePath = databasePath ?? gbrainPath('brain.pglite');
    const modelArg = requestedModel ? ` --embedding-model ${requestedModel}` : '';
    const lines = [
      header,
      ``,
      `  Existing column: vector(${currentDims})`,
      `  Requested:       vector(${requestedDims})${requestedModel ? `  (${requestedModel})` : ''}`,
      ``,
      `Switching dims is destructive: it drops every embedding in your brain.`,
      `PGLite cannot ALTER vector column types (pgvector ships as embedded WASM,`,
      `not a native extension). Wipe-and-reinit is the only path.`,
      ``,
      `Recommended (one command):`,
      ``,
      `  gbrain reinit-pglite${modelArg} --embedding-dimensions ${requestedDims}`,
      ``,
      `Or by hand:`,
      ``,
      `  mv ${activePath} ${activePath}.bak`,
      `  gbrain init --pglite${modelArg} --embedding-dimensions ${requestedDims}`,
      `  gbrain sync   # re-imports your brain repo from disk`,
      `  gbrain embed --stale`,
      ``,
      `Full guide: docs/embedding-migrations.md`,
    ];
    return lines.join('\n');
  }

  // Postgres branch — preserve the existing SQL recipe.
  const supportsHnsw = requestedDims <= PGVECTOR_HNSW_VECTOR_MAX_DIMS;
  const reindexLine = supportsHnsw
    ? `CREATE INDEX IF NOT EXISTS idx_chunks_embedding\n  ON content_chunks USING hnsw (embedding vector_cosine_ops);`
    : `-- Skip reindex. dims=${requestedDims} exceeds pgvector's HNSW cap of ${PGVECTOR_HNSW_VECTOR_MAX_DIMS};\n-- searchVector falls back to exact scan.`;

  const modelArg = requestedModel ? ` --embedding-model ${requestedModel}` : '';
  const lines = [
    header,
    ``,
    `  Existing column: vector(${currentDims})`,
    `  Requested:       vector(${requestedDims})${requestedModel ? `  (${requestedModel})` : ''}`,
    ``,
    `Switching dims is destructive: it drops every embedding in your brain and`,
    `requires a full re-embed (potentially hours and $1-100 in API calls).`,
    ``,
    `Recipe (run against your Postgres brain):`,
    ``,
    `  BEGIN;`,
    `  DROP INDEX IF EXISTS idx_chunks_embedding;`,
    `  ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(${requestedDims});`,
    `  UPDATE content_chunks SET embedding = NULL, embedded_at = NULL;`,
    `  ${reindexLine.split('\n').join('\n  ')}`,
    `  COMMIT;`,
    ``,
    `Then re-init config (file plane is canonical post-v0.37):`,
    `  gbrain init --supabase${modelArg} --embedding-dimensions ${requestedDims}`,
    `  gbrain embed --stale`,
    ``,
    `Full guide: docs/embedding-migrations.md`,
  ];
  return lines.join('\n');
}
