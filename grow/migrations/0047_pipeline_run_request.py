from django.db import migrations, models

STATUS_CHOICES = [
    ("queued", "Queued"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("superseded", "Superseded"),
    ("cancelled", "Cancelled"),
    ("expired", "Expired"),
]
STAGE_CHOICES = [
    ("fetching_rules", "Fetching Rules"),
    ("ingesting_musicbrainz", "Ingesting Musicbrainz"),
    ("ingesting_wikidata", "Ingesting Wikidata"),
    ("building_songs", "Building Songs"),
    ("building_genres", "Building Genres"),
    ("matching_songs", "Matching Songs"),
    ("importing_tree", "Importing Tree"),
    ("uploading_songs", "Uploading Songs"),
    ("merging_songs", "Merging Songs"),
]
SINGLE_ACTIVE_CONDITION = models.Q(("status__in", ["queued", "running"]))


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0046_curation_apply_request"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="curationapplyrequest", name="curation_apply_request_single_active"),
        migrations.RenameModel(old_name="CurationApplyRequest", new_name="PipelineRunRequest"),
        migrations.AlterModelTable(name="pipelinerunrequest", table="grow_pipeline_run_request"),
        # Every request made before kinds existed was a curation run.
        migrations.AddField(
            model_name="pipelinerunrequest",
            name="kind",
            field=models.TextField(choices=[("curation", "Curation"), ("full", "Full")], default="curation"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="pipelinerunrequest", name="heartbeat_on", field=models.DateTimeField(null=True)
        ),
        # A request already running has no heartbeat yet: start its clock so it can expire.
        migrations.RunSQL(
            "UPDATE grow_pipeline_run_request SET heartbeat_on = NOW() "
            "WHERE status = 'running'",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddField(
            model_name="pipelinerunrequest", name="cancel_requested_on", field=models.DateTimeField(null=True)
        ),
        migrations.AlterField(
            model_name="pipelinerunrequest",
            name="status",
            field=models.TextField(choices=STATUS_CHOICES, default="queued"),
        ),
        migrations.AlterField(
            model_name="pipelinerunrequest",
            name="stage",
            field=models.TextField(choices=STAGE_CHOICES, null=True),
        ),
        migrations.AddConstraint(
            model_name="pipelinerunrequest",
            constraint=models.UniqueConstraint(
                models.Value(True, output_field=models.BooleanField()),
                condition=SINGLE_ACTIVE_CONDITION,
                name="pipeline_run_request_single_active",
            ),
        ),
    ]
