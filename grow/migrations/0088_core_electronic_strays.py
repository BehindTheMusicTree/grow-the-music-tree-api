from django.db import migrations

CORE = "LOCAL:core-electronic"
EDM = "Q851213"
UNDERGROUND = "LOCAL:underground-electronic"
REASON = "user-requested commercial/underground split of Core electronic"

# item_id -> scene node it moves under.
PLACEMENT = {
    **{
        item: UNDERGROUND
        for item in (
            "Q170611",  # Techno
            "Q388906",  # Hardcore
            "Q663519",  # Breakbeat
            "Q217597",  # Electro (1980s)
            "Q861823",  # Electroclash
            "Q1661924",  # Industrial dance
            "Q107697201",  # Hard drum
            "Q106514601",  # Glitch hop (EDM)
            "Q114880130",  # Bass music (EDM)
            "Q141085400",  # Minimal EDM
            "Q898709",  # Rave music
            "Q55641735",  # Shamstep
            "Q134380635",  # Slimepunk
            "Q1165777",  # UK garage
            "Q9364028",  # UK funky
            "Q1262781",  # Dub techno: Dubtronica sits under Dub music, not under a scene
        )
    },
    **{
        item: EDM
        for item in (
            "Q20502",  # House music
            "Q170435",  # Trance
            "Q12200830",  # Progressive EDM
            "Q1033912",  # Hard dance
            "Q21092",  # Moombahton
            "Q140369806",  # Outrun
        )
    },
}

# Wikidata already nests these under a genre that now sits under a scene, so the rule is dropped.
DROP_RULE = {
    "Q598593": "Q20502",  # Tech house -> House music
    "Q622871": "Q170435",  # Psychedelic trance -> Trance
}


def reparent(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    Genre = apps.get_model("grow", "Genre")
    rules = CurationEntry.objects.filter(user=None, list_name="main_parent")

    for item_id, parent in PLACEMENT.items():
        values = {"parent_item_id": parent, "exclude_other_parents": False}
        if not rules.filter(key=item_id).update(values=values, reason=REASON):
            rules.create(user=None, list_name="main_parent", key=item_id, values=values, reason=REASON)
    rules.filter(key__in=DROP_RULE).delete()

    # Locked genres keep their parent through tree import, so move the rows themselves. Only strays still
    # directly under Core electronic move: a database without them (staging) is left alone.
    core = Genre.objects.filter(wikidata_id=CORE).first()
    if core is None:
        return
    targets = {**PLACEMENT, **DROP_RULE}
    for item_id, parent_item_id in targets.items():
        parent = Genre.objects.filter(wikidata_id=parent_item_id).first()
        if parent is not None:
            Genre.objects.filter(wikidata_id=item_id, parent_id=core.pk).update(parent=parent)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0087_pop_side_item_ids"),
    ]

    operations = [
        migrations.RunPython(reparent, migrations.RunPython.noop),
    ]
