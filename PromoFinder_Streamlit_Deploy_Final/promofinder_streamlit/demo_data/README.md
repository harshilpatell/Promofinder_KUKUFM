# Demo data (synthetic — no client content)

- `synthetic_show.zip`: *The Florist Who Owned the City*, an original 3-episode microdrama written only for testing and demos. It uses the same file format as real input packs. Episode 3 uses the upper-case header variant. Regenerate it with `python -m promofinder.demo`.
- `synthetic_llm_responses/`: **saved example LLM responses** for that show. They were written with Claude (an AI assistant) for the demo and are replayed offline by the `file` provider. **They are not produced by a live model call when you click the demo.** Each file's `produced_by` field says so, and the app labels results as *offline replay of saved responses*.

  The responses deliberately produce every kind of outcome: 2 ranked promos, 1 cross-episode alternate (X1), 1 near-miss (C02-1, 17s, too short), and 1 repair request answered "unfixable".
