/**
 * BrainBench write-back fidelity — grades the PRODUCTION conversation→memory
 * pipeline (decision 15), not a bench-only path.
 *
 * Flow per fixture:
 *   1. Render the fixture's turns into a conversation page in the
 *      imessage-slack line format the conversation-parser ships
 *      (`**Speaker** (YYYY-MM-DD H:MM AM): text`), import it (noEmbed).
 *   2. Run `runExtractConversationFactsCore` over that page with an injected
 *      GOLD extractor: for each segment, it emits exactly the gold facts whose
 *      source turn text appears in the segment. Zero LLM calls; segmentation,
 *      insertFacts batching, dedup, provenance stamping, terminal-audit rows
 *      all execute the shipped code.
 *      With opts.llm=true the injection is skipped — the real Haiku extractor
 *      runs and extraction_recall / extraction_precision are additionally
 *      scored against the gold keyword probes.
 *   3. Read back via the facts table and score:
 *        write_back_fidelity  — gold facts that survived (keyword probe) with
 *                               the right entity attribution
 *        provenance_accuracy  — surviving facts carrying correct
 *                               {source, source_session, source_markdown_slug}
 */

import type { ExtractInput, ExtractedFact } from '../../../core/facts/extract.ts';
import {
  PER_SEGMENT_SOURCE_PREFIX,
  TERMINAL_AUDIT_SOURCE,
  runExtractConversationFactsCore,
} from '../../../commands/extract-conversation-facts.ts';
import { importFromContent } from '../../../core/import-file.ts';
import type { PGLiteEngine } from '../../../core/pglite-engine.ts';
import type { BrainBenchFixture, FixtureGold, GoldFactSpec } from '../types.ts';
import { SeedError } from '../seed.ts';

export interface WriteBackScore {
  gold_total: number;
  gold_failed: number;
  /** Raw counters so the harness can aggregate across fixtures (Σ-based). */
  survived: number;
  provenance_ok: number;
  /** Total non-audit rows stored (extraction_precision denominator in --llm mode). */
  stored_rows: number;
  metrics: Record<string, number>;
  failed_items: string[];
}

/** Slug the rendered conversation page imports under. */
export function conversationSlug(fixtureId: string): string {
  return `conversations/bench-${fixtureId}`;
}

/** Render a fixture turn timestamp as the imessage-slack inline form (UTC). */
function renderInlineTime(iso: string): string {
  const d = new Date(iso);
  const date = iso.slice(0, 10);
  let h = d.getUTCHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12;
  if (h === 0) h = 12;
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `(${date} ${h}:${mm} ${ampm})`;
}

export function renderConversationPage(fixture: BrainBenchFixture): string {
  const lines: string[] = [
    '---',
    `title: Bench conversation ${fixture.fixture_id}`,
    'type: conversation',
    '---',
    '',
  ];
  for (const turn of fixture.turns) {
    if (!turn.ts) {
      throw new Error(`write-back fixture ${fixture.fixture_id} turn ${turn.turn_id} missing ts`);
    }
    const speaker = turn.role === 'user' ? 'You' : 'Assistant';
    lines.push(`**${speaker}** ${renderInlineTime(turn.ts)}: ${turn.text}`);
  }
  lines.push('');
  return lines.join('\n');
}

/** All gold facts of a fixture, with the turn text that produces each. */
function goldFactsWithSourceText(
  fixture: BrainBenchFixture,
  gold: FixtureGold,
): Array<{ turnText: string; spec: GoldFactSpec }> {
  const out: Array<{ turnText: string; spec: GoldFactSpec }> = [];
  for (const turn of fixture.turns) {
    const tg = gold.turns[String(turn.turn_id)];
    if (!tg?.gold_facts) continue;
    for (const spec of tg.gold_facts) out.push({ turnText: turn.text, spec });
  }
  return out;
}

/**
 * Deterministic gold extractor: emits the gold facts whose source turn text
 * appears verbatim inside the segment the production pipeline hands it.
 */
export function makeGoldExtractor(
  fixture: BrainBenchFixture,
  gold: FixtureGold,
): (input: ExtractInput) => Promise<ExtractedFact[]> {
  const items = goldFactsWithSourceText(fixture, gold);
  return async (input: ExtractInput): Promise<ExtractedFact[]> => {
    const out: ExtractedFact[] = [];
    for (const { turnText, spec } of items) {
      if (!input.turnText.includes(turnText)) continue;
      out.push({
        fact: spec.fact,
        kind: spec.kind ?? 'fact',
        entity_slug: spec.entity_slug,
        source: input.source,
        confidence: 1.0,
        notability: 'medium',
        embedding: null,
      });
    }
    return out;
  };
}

interface StoredFactRow {
  fact: string;
  entity_slug: string | null;
  source: string;
  source_session: string | null;
  source_markdown_slug: string | null;
}

export async function runWriteBack(
  engine: PGLiteEngine,
  fixture: BrainBenchFixture,
  gold: FixtureGold,
  opts: { llm: boolean; budgetUsd?: number },
): Promise<WriteBackScore> {
  const sourceId = fixture.active_source ?? 'default';
  const slug = conversationSlug(fixture.fixture_id);

  const body = renderConversationPage(fixture);
  const imported = await importFromContent(engine, slug, body, { noEmbed: true, sourceId });
  if (imported.status !== 'imported') {
    throw new SeedError(
      fixture.fixture_id,
      slug,
      `conversation page import status=${imported.status}${imported.error ? ` (${imported.error})` : ''}`,
    );
  }

  await runExtractConversationFactsCore(engine, {
    sourceId,
    slug,
    types: ['conversation'],
    overrideDisabled: true,
    sleepMs: 0,
    // Deterministic CI mode injects the gold extractor; --llm runs the real
    // one under the caller's budget cap (cost-guard pattern, decision 2).
    ...(opts.llm
      ? { maxCostUsd: opts.budgetUsd }
      : { extractor: makeGoldExtractor(fixture, gold) }),
  });

  const stored = await engine.executeRaw<StoredFactRow>(
    `SELECT fact, entity_slug, source, source_session, source_markdown_slug
       FROM facts
      WHERE source_id = $1
        AND source_markdown_slug = $2
        AND source <> $3`,
    [sourceId, slug, TERMINAL_AUDIT_SOURCE],
  );

  const expectedSession = `${PER_SEGMENT_SOURCE_PREFIX}:${slug}`;
  const goldItems = goldFactsWithSourceText(fixture, gold);

  let survived = 0;
  let provenanceOk = 0;
  const failed: string[] = [];
  for (const { spec } of goldItems) {
    const match = stored.find(
      (row) =>
        spec.match_keywords.every((kw) => row.fact.toLowerCase().includes(kw.toLowerCase())) &&
        (spec.entity_slug === null || row.entity_slug === spec.entity_slug),
    );
    if (!match) {
      failed.push(`${fixture.fixture_id} (gold fact lost: ${spec.gist})`);
      continue;
    }
    survived++;
    if (
      match.source === PER_SEGMENT_SOURCE_PREFIX &&
      match.source_session === expectedSession &&
      match.source_markdown_slug === slug
    ) {
      provenanceOk++;
    } else {
      failed.push(`${fixture.fixture_id} (provenance wrong on: ${spec.gist})`);
    }
  }

  const metrics: Record<string, number> = {
    write_back_fidelity: goldItems.length > 0 ? survived / goldItems.length : 1,
    provenance_accuracy: survived > 0 ? provenanceOk / survived : 1,
  };

  if (opts.llm) {
    // Extraction quality vs gold, only meaningful when the real extractor ran.
    const matchedAnyGold = stored.filter((row) =>
      goldItems.some(({ spec }) =>
        spec.match_keywords.every((kw) => row.fact.toLowerCase().includes(kw.toLowerCase())),
      ),
    ).length;
    metrics.extraction_recall = goldItems.length > 0 ? survived / goldItems.length : 1;
    metrics.extraction_precision = stored.length > 0 ? matchedAnyGold / stored.length : 1;
  }

  // gold_failed counts BOTH lost facts and provenance failures — a fact that
  // survived with wrong provenance is a failed gold item for the count gate.
  return {
    gold_total: goldItems.length,
    gold_failed: goldItems.length - survived + (survived - provenanceOk),
    survived,
    provenance_ok: provenanceOk,
    stored_rows: stored.length,
    metrics,
    failed_items: failed,
  };
}
