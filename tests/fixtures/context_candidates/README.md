# Context candidate fixture provenance

`ig_public_meetings_sample.json` contains selected source cells copied without
rewriting from the public research Sheet `1EdsnR7iE8mLyVV0Cv31LEJNjckeM12FmhYeoC7223fE`,
range `Sheet1!A1:P60`, read September 23, 2026.

The first object is the Indianapolis row (Sheet row 2). It proves the real
`1:05:26` / `3926` timestamp pair and that `Sources` is free text. The next two
objects are the two independently researched Dallas rows (Sheet rows 21 and
32). They cite the same social post with different payloads. Their source order
does not establish which research is newer, so one unordered import must reject
both unless the provider supplies distinct stable record keys.

This is a narrow regression fixture, not a copy of the full research Sheet.
