/**
 * BrainBench orchestrator.
 *
 * Engine economy (eng-review D9): ONE in-memory PGLite for the whole run,
 * `resetTables()` between fixtures — the longmemeval lesson; per-fixture WASM
 * cold boots would blow the <2 min CI budget. Read-only suites (know-to-ask,
 * push) seed once and run ALL adapters against the same brain; mutating work
 * (write-back) runs after the replays, and the next fixture starts from a
 * reset. A sentinel-slug test pins that sharing leaks nothing.
 *
 * Continuity pairs (writer fixture → production write-back → reader fixture)
 * run per ordered (writerHarness ≠ readerHarness) pair on a shared brain;
 * scores land on the READER's cell. With a single requested harness the
 * writer==reader diagonal runs instead (disclosed, not the headline shape).
 *
 * Sealed gold: adapters only ever receive AdapterFixtureView + PublicTurn
 * (toPublicTurn picks fields; gold never crosses).
 */

import { createBenchmarkBrain, resetTables } from '../longmemeval/harness.ts';
import type { PGLiteEngine } from '../../core/pglite-engine.ts';
import { ClaudeCodeAdapter } from './adapters/claude-code.ts';
import { CodexAdapter } from './adapters/codex.ts';
import { OpenClawAdapter } from './adapters/openclaw.ts';
import { scoreKnowToAsk } from './metrics/know-to-ask.ts';
import { scorePush } from './metrics/push.ts';
import { runWriteBack, type WriteBackScore } from './metrics/write-back.ts';
import { scoreContinuityPair } from './metrics/continuity.ts';
import { SeedError, seedBrain, type SeedOutcome } from './seed.ts';
import {
  toPublicTurn,
  type AdapterFixtureView,
  type BrainBenchSuite,
  type HarnessAdapter,
  type HarnessName,
  type LoadedCorpus,
  type LoadedFixture,
  type SuiteMetrics,
  type TurnRow,
} from './types.ts';

export interface RunBrainBenchOpts {
  harnesses: HarnessName[];
  suites: BrainBenchSuite[];
  includeHoldout: boolean;
  /** Run the real LLM extractor for write-back (budget-guarded upstream). */
  llm: boolean;
  /** Spend cap for --llm mode (threaded to the extraction pipeline's tracker). */
  budgetUsd?: number;
  /** Progress note sink (CLI wires the shared stderr reporter). */
  onProgress?: (note: string) => void;
}

export interface RunBrainBenchOutput {
  cells: SuiteMetrics[];
  turn_rows: TurnRow[];
  seed_failures: Array<{ fixture_id: string; error: string }>;
  fixtures_run: number;
}

function makeAdapter(name: HarnessName): HarnessAdapter {
  switch (name) {
    case 'openclaw':
      return new OpenClawAdapter();
    case 'claude-code':
      return new ClaudeCodeAdapter();
    case 'codex':
      return new CodexAdapter();
  }
}

const SEAM: Record<HarnessName, 'production' | 'contract'> = {
  openclaw: 'production',
  'claude-code': 'contract',
  codex: 'contract',
};

function adapterView(lf: LoadedFixture): AdapterFixtureView {
  return {
    fixture_id: lf.fixture.fixture_id,
    active_source: lf.fixture.active_source ?? 'default',
    turns: lf.fixture.turns.map(toPublicTurn),
  };
}

function crossSourceSlugs(
  injected: string[],
  slugSource: Map<string, Set<string>>,
  activeSource: string,
): string[] {
  return injected.filter((s) => {
    const set = slugSource.get(s);
    return set !== undefined && !set.has(activeSource);
  });
}

/**
 * Replay every USER turn of a fixture through one adapter. Assistant turns
 * feed prior context only (the production reflex fires on user messages).
 * Returns one TurnRow per (user turn × suite) so per-suite scorers and
 * external re-scorers see self-contained rows.
 */
async function replayFixture(
  engine: PGLiteEngine,
  adapter: HarnessAdapter,
  lf: LoadedFixture,
  seed: SeedOutcome,
  rowSuites: BrainBenchSuite[],
): Promise<TurnRow[]> {
  const view = adapterView(lf);
  const activeSource = view.active_source;
  await adapter.beginConversation(engine, view);
  const rows: TurnRow[] = [];
  let priorContext = '';
  try {
    for (const turn of view.turns) {
      if (turn.role !== 'user') {
        priorContext += `\n${turn.text}`;
        continue;
      }
      const result = await adapter.replayTurn(turn, priorContext);
      const gold = lf.gold.turns[String(turn.turn_id)] ?? null;
      for (const suite of rowSuites) {
        rows.push({
          fixture_id: lf.fixture.fixture_id,
          turn_id: turn.turn_id,
          harness: adapter.name,
          suite,
          injected_slugs: result.injectedSlugs,
          injected_tokens: result.injectedTokens,
          gold,
          cross_source_slugs: crossSourceSlugs(result.injectedSlugs, seed.slugSource, activeSource),
          latency_ms: Math.round(result.latencyMs * 1000) / 1000,
        });
      }
      priorContext += `\n${turn.text}`;
      if (result.injectedText) priorContext += `\n${result.injectedText}`;
    }
  } finally {
    await adapter.endConversation();
  }
  return rows;
}

interface WriteBackAgg {
  gold_total: number;
  gold_failed: number;
  survived: number;
  provenance_ok: number;
  stored_rows: number;
  matched_any_gold: number;
  fixtures: string[];
  failed_items: string[];
}

interface ContinuityAgg {
  gold_total: number;
  gold_failed: number;
  fixtures: string[];
  failed_items: string[];
}

export async function runBrainBench(
  corpus: LoadedCorpus,
  opts: RunBrainBenchOpts,
): Promise<RunBrainBenchOutput> {
  const progress = opts.onProgress ?? (() => {});
  const turnRows: TurnRow[] = [];
  const seedFailures: Array<{ fixture_id: string; error: string }> = [];

  const wantedSuites = new Set(opts.suites);
  const eligible = corpus.fixtures.filter((lf) => {
    if (lf.fixture.holdout && !opts.includeHoldout) return false;
    return lf.fixture.suites.some((s) => wantedSuites.has(s));
  });

  // Continuity pairs are orchestrated separately from regular fixtures.
  const pairFixtures = new Map<string, { writer?: LoadedFixture; reader?: LoadedFixture }>();
  const regular: LoadedFixture[] = [];
  for (const lf of eligible) {
    const cont = lf.fixture.continuity;
    if (cont && wantedSuites.has('continuity')) {
      const p = pairFixtures.get(cont.pair_id) ?? {};
      p[cont.pair_role] = lf;
      pairFixtures.set(cont.pair_id, p);
      // A writer that also declares know-to-ask/push runs as a regular fixture
      // too (its retrieval gold is independent of the pair).
      if (lf.fixture.suites.some((s) => s !== 'continuity' && s !== 'write-back' && wantedSuites.has(s))) {
        regular.push(lf);
      }
    } else {
      regular.push(lf);
    }
  }

  const writeBackAgg: WriteBackAgg = {
    gold_total: 0, gold_failed: 0, survived: 0, provenance_ok: 0,
    stored_rows: 0, matched_any_gold: 0, fixtures: [], failed_items: [],
  };
  const continuityByReader = new Map<HarnessName, ContinuityAgg>();

  const engine = await createBenchmarkBrain();
  let fixturesRun = 0;
  try {
    // ---- regular fixtures: seed once, replay all adapters, then mutate ----
    for (const lf of regular) {
      const id = lf.fixture.fixture_id;
      progress(`fixture ${id}`);
      await resetTables(engine);
      let seed: SeedOutcome;
      try {
        seed = await seedBrain(engine, lf.fixture);
      } catch (err) {
        if (err instanceof SeedError) {
          seedFailures.push({ fixture_id: id, error: err.message });
          continue;
        }
        throw err;
      }
      fixturesRun++;

      const retrievalSuites = lf.fixture.suites.filter(
        (s): s is BrainBenchSuite => (s === 'know-to-ask' || s === 'push') && wantedSuites.has(s),
      );
      if (retrievalSuites.length > 0) {
        for (const harness of opts.harnesses) {
          const adapter = makeAdapter(harness);
          const rows = await replayFixture(engine, adapter, lf, seed, retrievalSuites);
          turnRows.push(...rows);
        }
      }

      if (lf.fixture.suites.includes('write-back') && wantedSuites.has('write-back')) {
        const score = await runWriteBack(engine, lf.fixture, lf.gold, {
          llm: opts.llm,
          budgetUsd: opts.budgetUsd,
        });
        accumulateWriteBack(writeBackAgg, id, score);
      }
    }

    // ---- continuity pairs ----
    const pairHarnesses: Array<[HarnessName, HarnessName]> = [];
    if (opts.harnesses.length === 1) {
      pairHarnesses.push([opts.harnesses[0], opts.harnesses[0]]);
    } else {
      for (const w of opts.harnesses) {
        for (const r of opts.harnesses) {
          if (w !== r) pairHarnesses.push([w, r]);
        }
      }
    }

    for (const [pairId, pair] of pairFixtures) {
      if (!pair.writer || !pair.reader) continue; // loader validates; belt+suspenders
      const writer = pair.writer;
      const reader = pair.reader;
      const decisions = reader.gold.continuity?.decisions ?? [];
      if (!decisions.length) continue;

      for (const [writerHarness, readerHarness] of pairHarnesses) {
        progress(`continuity ${pairId} ${writerHarness}→${readerHarness}`);
        await resetTables(engine);
        let writerSeed: SeedOutcome;
        let readerSeed: SeedOutcome;
        try {
          writerSeed = await seedBrain(engine, writer.fixture);
          readerSeed = await seedBrain(engine, reader.fixture);
        } catch (err) {
          if (err instanceof SeedError) {
            seedFailures.push({ fixture_id: `${pairId} (${writerHarness}→${readerHarness})`, error: err.message });
            continue;
          }
          throw err;
        }

        // Writer conversation replays through ITS harness (suppression state
        // realistic), then its decisions persist via the production pipeline.
        const writerAdapter = makeAdapter(writerHarness);
        await replayFixture(engine, writerAdapter, writer, writerSeed, []);
        await runWriteBack(engine, writer.fixture, writer.gold, {
          llm: opts.llm,
          budgetUsd: opts.budgetUsd,
        });

        // Reader replays on the SAME brain through a different harness.
        const readerAdapter = makeAdapter(readerHarness);
        const readerRows = await replayFixture(engine, readerAdapter, reader, readerSeed, ['continuity']);
        turnRows.push(...readerRows);

        const activeSource = reader.fixture.active_source ?? 'default';
        const score = await scoreContinuityPair(engine, activeSource, pairId, readerRows, decisions);

        const agg = continuityByReader.get(readerHarness) ?? {
          gold_total: 0, gold_failed: 0, fixtures: [], failed_items: [],
        };
        agg.gold_total += score.gold_total;
        agg.gold_failed += score.gold_failed;
        if (!agg.fixtures.includes(reader.fixture.fixture_id)) agg.fixtures.push(reader.fixture.fixture_id);
        agg.failed_items.push(...score.failed_items.map((f) => `${f} [${writerHarness}→${readerHarness}]`));
        continuityByReader.set(readerHarness, agg);
      }
      fixturesRun += 2;
    }
  } finally {
    await engine.disconnect();
  }

  // ---- assemble cells ----
  const cells: SuiteMetrics[] = [];
  for (const harness of opts.harnesses) {
    for (const suite of opts.suites) {
      const cell = assembleCell(harness, suite, turnRows, writeBackAgg, continuityByReader);
      if (cell) cells.push(cell);
    }
  }

  return { cells, turn_rows: turnRows, seed_failures: seedFailures, fixtures_run: fixturesRun };
}

function accumulateWriteBack(agg: WriteBackAgg, fixtureId: string, score: WriteBackScore): void {
  agg.gold_total += score.gold_total;
  agg.gold_failed += score.gold_failed;
  agg.survived += score.survived;
  agg.provenance_ok += score.provenance_ok;
  agg.stored_rows += score.stored_rows;
  agg.fixtures.push(fixtureId);
  agg.failed_items.push(...score.failed_items);
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000;
}

function assembleCell(
  harness: HarnessName,
  suite: BrainBenchSuite,
  turnRows: TurnRow[],
  writeBackAgg: WriteBackAgg,
  continuityByReader: Map<HarnessName, ContinuityAgg>,
): SuiteMetrics | null {
  if (suite === 'write-back') {
    if (writeBackAgg.fixtures.length === 0) return null;
    // The write path is gbrain's pipeline — identical for every harness seam
    // in v1, so each harness cell carries the same (once-computed) numbers.
    // When harness-specific write paths land, this is where they diverge.
    return {
      suite, harness, seam: SEAM[harness],
      gold_total: writeBackAgg.gold_total,
      gold_failed: writeBackAgg.gold_failed,
      metrics: {
        write_back_fidelity: round4(
          writeBackAgg.gold_total > 0 ? writeBackAgg.survived / writeBackAgg.gold_total : 1,
        ),
        provenance_accuracy: round4(
          writeBackAgg.survived > 0 ? writeBackAgg.provenance_ok / writeBackAgg.survived : 1,
        ),
      },
      fixtures: [...writeBackAgg.fixtures],
    };
  }

  if (suite === 'continuity') {
    const agg = continuityByReader.get(harness);
    if (!agg) return null;
    const rows = turnRows.filter((r) => r.harness === harness && r.suite === 'continuity');
    return {
      suite, harness, seam: SEAM[harness],
      gold_total: agg.gold_total,
      gold_failed: agg.gold_failed,
      metrics: {
        continuity_rate: round4(
          agg.gold_total > 0 ? (agg.gold_total - agg.gold_failed) / agg.gold_total : 1,
        ),
        source_isolation_violations: rows.reduce((n, r) => n + r.cross_source_slugs.length, 0),
        avg_injected_tokens: round4(avg(rows.map((r) => r.injected_tokens))),
      },
      fixtures: [...agg.fixtures],
    };
  }

  const rows = turnRows.filter((r) => r.harness === harness && r.suite === suite);
  if (rows.length === 0) return null;
  const score = suite === 'know-to-ask' ? scoreKnowToAsk(rows) : scorePush(rows);
  const fixtures = [...new Set(rows.map((r) => r.fixture_id))];
  return {
    suite, harness, seam: SEAM[harness],
    gold_total: score.gold_total,
    gold_failed: score.gold_failed,
    metrics: {
      ...Object.fromEntries(Object.entries(score.metrics).map(([k, v]) => [k, round4(v)])),
      source_isolation_violations: rows.reduce((n, r) => n + r.cross_source_slugs.length, 0),
      avg_injected_tokens: round4(avg(rows.map((r) => r.injected_tokens))),
    },
    fixtures,
  };
}

function avg(ns: number[]): number {
  return ns.length === 0 ? 0 : ns.reduce((a, b) => a + b, 0) / ns.length;
}
