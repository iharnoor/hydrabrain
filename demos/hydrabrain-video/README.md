# HydraBrain enterprise video (HyperFrames)

Problem → solution explainer for company use cases: **cron PUSH → HydraDB → agent PULL**.

Built with [HyperFrames CLI](https://hyperframes.heygen.com/packages/cli) — HTML composition rendered to MP4.

## Story arc (~78s)

| Time | Beat | Message |
|---|---|---|
| 0–12s | **Problem** | Knowledge scattered; agents search stale context |
| 12–22s | **Pain** | Relational questions fail; Postgres stacks take weeks |
| 22–32s | **Solution** | HydraBrain + HydraDB — pip install, native graph |
| 32–48s | **Push** | Cron sync + capture fill HydraDB overnight |
| 48–62s | **Pull** | think · graph · briefing · MCP at point of work |
| 62–78s | **Proof** | 96.5% recall@5 · 30 min to live · zero Postgres |

## Quick start

```bash
cd demos/hydrabrain-video

# Preview in browser (hot reload)
npm run dev

# Regenerate narration (macOS say — or use hyperframes tts after pip install kokoro-onnx)
say -o assets/narration.aiff -r 175 -f script.txt
ffmpeg -y -i assets/narration.aiff -ar 44100 -ac 1 assets/narration.wav

# Lint + render
npm run check
npm run render
# → output/hydrabrain-enterprise.mp4
```

### HyperFrames TTS (optional, higher quality)

```bash
pip install kokoro-onnx soundfile   # in a venv
npx hyperframes tts script.txt --voice am_adam --output assets/narration.wav
```

## Files

| File | Purpose |
|---|---|
| `index.html` | Main composition (6 scenes, GSAP timeline) |
| `script.txt` | Narration script |
| `assets/narration.wav` | Voice track |
| `output/hydrabrain-enterprise.mp4` | Rendered video |

## Edit

- **Copy:** edit `script.txt`, regenerate `assets/narration.wav`, re-render
- **Visuals / timing:** edit scene blocks and `timings` array in `index.html`
- **Interactive playbook:** [`../cron-playbook.html`](../cron-playbook.html)

## Related

- [Company cron playbook](../cron-playbook.html) — filterable use cases by team
- [README enterprise section](../../README.md#-company-brain--cron--push-playbook)
