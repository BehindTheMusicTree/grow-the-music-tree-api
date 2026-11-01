---
paths:
  - "grow/model/**/*.py"
  - "grow/migrations/*.py"
---

# Migration review

This service owns its migration history; do not copy migrations from the shared kits or hear-api. Model changes need matching migrations. Review generated migrations rather than assuming they are correct.

Changes to Django MTI `bases=` require particular care: `SeparateDatabaseAndState.database_operations` does not see the `bases=` changes in `state_operations`, so a naive `AlterField` can inject an unwanted parent pointer column. Hand-author the necessary database/state operations when appropriate; study `grow/migrations/0006_move_track_to_genre_kit.py` and validate the resulting schema and data behavior. Do not reject a migration merely because it was hand-edited.
