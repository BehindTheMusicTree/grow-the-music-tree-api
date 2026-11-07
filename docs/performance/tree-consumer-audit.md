# Tree response consumer audit — 2026-11-07

Audited fetched integration refs: app-kit `70a007c`, genre-tree-view `c908df1`, Hear frontend `3ad615c`, Grow frontend `965cc62b` (app-kit 34.0.0). Hear pins app-kit/app-kit-ui 24.0.1; its tagged schemas were checked as well.

Both app-kit 24.0.1 and 34.0.0 parse tree criteria through `CriteriaMinimumSchema`, which has no summary. Zod removes this unused field. app-kit-ui summary rendering uses the independently fetched `CriteriaOverview` (`GenreDetailExtras`), and Grow's `GenreSummaryEditor` also takes that overview. genre-tree-view receives tree nodes, not criteria summaries. Artist trees use the same tree schema/projection. No audited tree consumer reads `criteria.summary`.

Only summary is removed. Keep catalogue and playlist membership counts distinct, and preserve criterion/playlist parent identities, graph links, timestamps, artist scoping and artist `no-store`. Paginated genre responses and overview endpoints retain their summary. Representation/cache namespace changes from `scoped-v2` to `scoped-v3`, preventing reuse of an older serialized response.

The pinned canonical performance tree must remain below 1,100 serialized bytes per node. The payload test populates summaries with 2,400 bytes per genre and explicitly asserts that they stay absent; compressed transport bytes are measured separately. This is a payload contract budget, not a latency ceiling.
