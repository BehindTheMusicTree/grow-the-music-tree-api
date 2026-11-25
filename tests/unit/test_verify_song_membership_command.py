import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_negative_sample_is_rejected_before_any_query():
    with pytest.raises(CommandError, match="--sample"):
        call_command("verify_song_membership", sample=-1)
