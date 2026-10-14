from django.db import models

from grow.model.import_run.ImportRun import ImportRun


class BulkImportRun(models.Model):
    """A staged import of one `kind`: parts are uploaded into the kind's staging table, then one commit merges them."""

    kind = models.TextField(choices=ImportRun.Kind.choices)
    created_on = models.DateTimeField(auto_now_add=True)
    committed_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_bulk_import_run"
