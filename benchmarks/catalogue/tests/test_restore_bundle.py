"""Approval failures must precede any database operation."""

import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from benchmarks.catalogue import restore_bundle as bundle
from benchmarks.catalogue.restore_execution import Approval


class RestoreBundleTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path("/operator/restore")
        self.pre, self.post = b"CREATE TABLE reviewed();", b"CREATE INDEX reviewed;"
        self.approval = {
            "version": 1,
            "backup_sha256": "a" * 64,
            "pre_data_sha256": hashlib.sha256(self.pre).hexdigest(),
            "post_data_sha256": hashlib.sha256(self.post).hexdigest(),
        }
        self.session = SimpleNamespace(backup_sha256="a" * 64)
        self.database = Mock()
        self.paths = self.enterContext(patch.object(bundle, "private_path"))
        self.json = self.enterContext(patch.object(bundle, "trusted_json", return_value=self.approval))
        self.schemas = self.enterContext(patch.object(bundle, "schema_bytes", side_effect=[self.pre, self.post]))
        self.restore = self.enterContext(patch.object(bundle, "restore", return_value={"status": "projected"}))

    def test_exact_approved_inputs_reach_restore(self):
        self.assertEqual(bundle.restore_approved(self.database, self.session, self.directory), {"status": "projected"})
        self.json.assert_called_once_with(self.directory / "approval.json")
        self.assertEqual(
            [call.args[0] for call in self.schemas.call_args_list],
            [self.directory / "pre-data.sql", self.directory / "post-data.sql"],
        )
        self.restore.assert_called_once_with(self.database, Approval.parse(self.approval), self.pre, self.post)

    def test_session_backup_mismatch_refused_before_transport(self):
        self.session.backup_sha256 = "b" * 64
        self.refused("session backup")
        self.schemas.assert_not_called()

    def test_changed_schema_refused_before_transport(self):
        self.schemas.side_effect = [self.pre + b"SELECT 1;", self.post]
        self.refused("independent operator approval")

    def test_unknown_approval_field_refused_before_transport(self):
        self.approval["candidate_approved"] = True
        self.refused("exactly these keys")

    def test_untrusted_bundle_refused_before_transport(self):
        self.paths.side_effect = ValueError("private root-owned")
        self.refused("root-owned")
        self.json.assert_not_called()

    def refused(self, message):
        with self.assertRaisesRegex(ValueError, message):
            bundle.restore_approved(self.database, self.session, self.directory)
        self.restore.assert_not_called()
        self.database.assert_not_called()
        self.assertEqual(self.database.method_calls, [])
