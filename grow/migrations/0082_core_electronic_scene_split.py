from django.db import migrations

EDM = "Q851213"
UNDERGROUND = "LOCAL:underground-electronic"
REASON = "user-requested commercial/underground split of Core electronic"

UNDER_EDM = [
    "Q106574871",
    "Q106576170",
    "Q112997482",
    "Q122216296",
    "Q19938910",
    "Q2146293",
    "Q3876770",
    "Q757143",
    "Q90568328",
]

UNDER_UNDERGROUND = [
    "Q105763581",
    "Q106369996",
    "Q106422444",
    "Q106528337",
    "Q106582942",
    "Q107697234",
    "Q108297235",
    "Q1100989",
    "Q111387914",
    "Q11308620",
    "Q115063474",
    "Q127470373",
    "Q131286868",
    "Q1326777",
    "Q134983275",
    "Q135637",
    "Q1403744",
    "Q141085413",
    "Q1507298",
    "Q15733887",
    "Q16002495",
    "Q1658757",
    "Q17231682",
    "Q1840167",
    "Q188994",
    "Q193207",
    "Q2342263",
    "Q2626684",
    "Q310871",
    "Q3476798",
    "Q4736507",
    "Q5358022",
    "Q65937906",
    "Q66686936",
    "Q7410145",
    "Q79784514",
    "Q85765918",
    "Q9298306",
    "Q96740854",
    "Q98804240",
]


def reparent(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    for parent, item_ids in ((EDM, UNDER_EDM), (UNDERGROUND, UNDER_UNDERGROUND)):
        for item_id in item_ids:
            values = {"parent_item_id": parent, "exclude_other_parents": False}
            entries = CurationEntry.objects.filter(user=None, list_name="main_parent", key=item_id)
            if not entries.update(values=values, reason=REASON):
                CurationEntry.objects.create(
                    user=None, list_name="main_parent", key=item_id, values=values, reason=REASON
                )


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0081_artist_image"),
    ]

    operations = [
        migrations.RunPython(reparent, migrations.RunPython.noop),
    ]
