from django.db import models


class WikidataItem(models.Model):
    """A Wikidata item (or pipeline `LOCAL:` item) the pipeline knows, pruned ones included, with its label.

    Each pipeline report replaces every item: it is the source of curation item names for ids that aren't
    in the canonical tree."""

    item_id = models.CharField(max_length=64, primary_key=True)
    label = models.TextField()

    class Meta:
        db_table = "grow_wikidata_item"
