from django.db import models


class ImportAttempt(models.Model):
    """Technical history independent of staging rows and django-q result persistence."""

    class State(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        COMMITTING = "committing"
        CLEANING_UP = "cleaning_up"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        INTERRUPTED = "interrupted"

    run_id = models.BigIntegerField(db_index=True)
    task_id = models.TextField(db_index=True)
    kind = models.TextField()
    mode = models.TextField()
    user_id = models.IntegerField(null=True)
    attempt = models.PositiveIntegerField()
    state = models.TextField(choices=State.choices, default=State.QUEUED)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True, db_index=True)
    step = models.TextField(null=True)
    step_started_at = models.DateTimeField(null=True)
    last_progress_at = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)
    completed_steps = models.JSONField(default=list)
    backend_pid = models.IntegerField(null=True)
    backend_start = models.DateTimeField(null=True)
    error = models.TextField(null=True)
    result = models.JSONField(null=True)
    data_applied = models.BooleanField(default=False)

    class Meta:
        db_table = "grow_import_attempt"
        constraints = [models.UniqueConstraint(fields=["run_id", "attempt"], name="grow_import_attempt_unique")]


class ImportReceipt(models.Model):
    """Written atomically with business data: a crash after commit must never replay a merge."""

    run_id = models.BigIntegerField(primary_key=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    result = models.JSONField()

    class Meta:
        db_table = "grow_import_receipt"
