from django.db import models


class SongImportRun(models.Model):
    """A staged songs import: parts are uploaded into `SongImportStaging`, then one commit merges them."""

    created_on = models.DateTimeField(auto_now_add=True)
    committed_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_song_import_run"
