import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_database_system_checks_pass():
    # `migrate` runs database-tagged checks (e.g. models.E016 on MTI constraints) that plain `check`/pytest skip.
    call_command("check", databases=["default"], fail_level="ERROR")
