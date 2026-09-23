"""F21 generic version-ledger contract tests; synthetic files only."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import hashlib
import json

from quantlab.data.version_ledger import (
    VersionLedgerBinding, VersionLedgerError, LEDGER_FORMAT, POLICIES,
    canonical_event_id, canonical_revision_id, canonical_content_hash,
    canonical_observation_id, build_version_ledger_summary,
    get_version_ledger_manifest, query_version_ledger,
    get_version_selection_contract, preview_version_selection,
)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def row(*, domain="corporate_action", event_type="rights_issue",
        event_key=None, source_id="tdx", source_revision_key="r1",
        observed_at="2020-01-01T10:00:00+00:00", published_at=None,
        effective_at="2020-01-05", payload=None, supersedes=None):
    event_key = event_key or {"symbol": "sh.600001", "effective_date": "2020-01-05", "kind": "rights"}
    payload = {"rights_per_10": 2.0, "price": 5.0} if payload is None else payload
    event_id = canonical_event_id(domain, event_type, event_key)
    revision_id = canonical_revision_id(event_id, source_id, source_revision_key)
    content_hash = canonical_content_hash(payload)
    observation_id = canonical_observation_id(revision_id, observed_at, content_hash)
    return {
        "domain": domain, "event_type": event_type, "event_key": event_key, "event_id": event_id,
        "source_id": source_id, "source_revision_key": source_revision_key,
        "revision_id": revision_id, "observation_id": observation_id, "content_hash": content_hash,
        "observed_at": observed_at, "published_at": published_at, "effective_at": effective_at,
        "supersedes_revision_id": supersedes, "payload": payload,
    }


class VersionLedgerFixture:
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        first = row()
        repeat = row(observed_at="2020-01-01T11:00:00+00:00")
        second = row(source_revision_key="r2", observed_at="2020-01-03T10:00:00+00:00",
                     payload={"rights_per_10": 2.5, "price": 5.0}, supersedes=first["revision_id"])
        other = row(source_id="cninfo", source_revision_key="c1",
                    observed_at="2020-01-02T12:00:00+00:00",
                    published_at="2020-01-02T08:00:00+00:00",
                    payload={"rights_per_10": 2.4, "price": 5.0})
        self.rows = [first, repeat, second, other]
        self.write()

    def write(self, rows=None, summary_changes=None):
        rows = self.rows if rows is None else rows
        payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")) + "\n" for r in rows).encode()
        self.jsonl = self.root / "observations.jsonl"
        self.summary = self.root / "summary.json"
        self.jsonl.write_bytes(payload)
        summary = build_version_ledger_summary(rows, sha(payload))
        if summary_changes:
            summary.update(summary_changes)
        self.summary.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")), encoding="utf-8")
        self.binding = VersionLedgerBinding(self.jsonl, self.summary, sha(payload), sha(self.summary.read_bytes()))
        return self.binding

    def selection(self, *, event_id=None, source_id="tdx", policy="explicit_revision_v1",
                  revision_id="", as_of=""):
        request = {
            "contract": "niuniu-version-selection-preview-v1",
            "event_id": event_id or self.rows[0]["event_id"],
            "source_id": source_id, "policy": policy,
            "revision_id": revision_id, "as_of": as_of,
        }
        return preview_version_selection(self.binding, request_json=json.dumps(request))


class VersionLedgerTests(VersionLedgerFixture, TestCase):
    def test_manifest_recomputes_all_identities_and_counts_repeated_observation_once_as_revision(self):
        manifest = get_version_ledger_manifest(self.binding)
        self.assertEqual((manifest["records"], manifest["events"], manifest["revisions"], manifest["sources"]),
                         (4, 1, 3, 2))
        self.assertEqual(manifest["ambiguous_event_source_groups"], 0)
        self.assertFalse(manifest["merge_authorized"])
        self.assertFalse(manifest["reconstruction_authorized"])
        queried = query_version_ledger(self.binding, domain="corporate_action", event_type="rights_issue",
                                       event_id="", source_id="tdx", offset=0, limit=20)
        self.assertEqual(queried["pagination"]["total"], 3)
        self.assertEqual(len({item["revision_id"] for item in queried["rows"]}), 2)

    def test_digest_contract_distinguishes_event_revision_content_and_observation(self):
        first, repeat, second, other = self.rows
        self.assertEqual(first["event_id"], repeat["event_id"])
        self.assertEqual(first["revision_id"], repeat["revision_id"])
        self.assertEqual(first["content_hash"], repeat["content_hash"])
        self.assertNotEqual(first["observation_id"], repeat["observation_id"])
        self.assertNotEqual(first["revision_id"], second["revision_id"])
        self.assertNotEqual(first["content_hash"], second["content_hash"])
        self.assertNotEqual(first["revision_id"], other["revision_id"])

    def test_explicit_revision_and_as_of_selection_are_source_scoped(self):
        first, _repeat, second, other = self.rows
        explicit = self.selection(revision_id=second["revision_id"])
        self.assertEqual(explicit["status"], "ready_for_review")
        self.assertEqual(explicit["selected"]["revision_id"], second["revision_id"])
        self.assertFalse(explicit["official_verified"])
        self.assertFalse(explicit["publication_authorized"])
        cninfo = self.selection(source_id="cninfo", revision_id=other["revision_id"])
        self.assertEqual(cninfo["selected"]["source_id"], "cninfo")
        self.assertEqual(cninfo["selected"]["content_hash"], other["content_hash"])

        early = self.selection(policy="latest_observed_revision_as_of_v1",
                               as_of="2020-01-01T10:30:00+00:00")
        self.assertEqual(early["selected"]["revision_id"], first["revision_id"])
        self.assertEqual(early["selected"]["selected_observed_at"], "2020-01-01T10:00:00+00:00")
        later_repeat = self.selection(policy="latest_observed_revision_as_of_v1",
                                      as_of="2020-01-01T11:30:00+00:00")
        self.assertEqual(later_repeat["selected"]["revision_id"], first["revision_id"])
        self.assertEqual(later_repeat["selected"]["selected_observed_at"], "2020-01-01T11:00:00+00:00")
        revised = self.selection(policy="latest_observed_revision_as_of_v1",
                                 as_of="2020-01-04T00:00:00+00:00")
        self.assertEqual(revised["selected"]["revision_id"], second["revision_id"])

    def test_no_as_of_candidate_is_blocked_not_fallback(self):
        result = self.selection(policy="latest_observed_revision_as_of_v1",
                                as_of="2019-12-31T23:59:59+00:00")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("NO_REVISION_OBSERVED_BY_AS_OF", result["blockers"])
        self.assertIsNone(result["selected"])

    def test_explicit_revision_cannot_cross_source_or_event(self):
        other = self.rows[-1]
        result = self.selection(source_id="tdx", revision_id=other["revision_id"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("EXPLICIT_REVISION_NOT_IN_EVENT_SOURCE", result["blockers"])
        event2 = row(event_key={"symbol":"sh.600002","effective_date":"2020-01-05","kind":"rights"},
                     source_revision_key="x1")
        self.write(self.rows + [event2])
        result = self.selection(revision_id=event2["revision_id"])
        self.assertEqual(result["status"], "blocked")

    def test_same_revision_key_with_different_content_is_rejected(self):
        conflicting = row(observed_at="2020-01-01T12:00:00+00:00",
                          payload={"rights_per_10": 9.0, "price": 5.0})
        self.write(self.rows + [conflicting])
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

    def test_same_revision_repeated_observation_must_keep_revision_level_publication_metadata(self):
        first = row(published_at="2019-12-31T09:00:00+00:00")
        repeated = row(observed_at="2020-01-01T11:00:00+00:00",
                       published_at="2019-12-31T10:00:00+00:00")
        self.write([first, repeated])
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

    def test_disconnected_same_source_revision_roots_are_visible_but_as_of_selection_blocks(self):
        first = row(source_revision_key="root-a", observed_at="2020-01-01T10:00:00+00:00")
        second = row(source_revision_key="root-b", observed_at="2020-01-02T10:00:00+00:00",
                     payload={"rights_per_10": 7.0, "price": 5.0})
        self.write([first, second])
        manifest = get_version_ledger_manifest(self.binding)
        self.assertEqual(manifest["ambiguous_event_source_groups"], 1)
        result = self.selection(policy="latest_observed_revision_as_of_v1",
                                as_of="2020-01-03T00:00:00+00:00")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("AMBIGUOUS_REVISION_LINEAGE_AS_OF", result["blockers"])
        self.assertIsNone(result["selected"])

    def test_missing_cross_source_cross_event_parent_and_branch_are_rejected(self):
        first = self.rows[0]
        cases = []
        missing = row(source_revision_key="r3", observed_at="2020-01-04T10:00:00+00:00",
                      payload={"rights_per_10":3.0}, supersedes="0"*64)
        cases.append(self.rows + [missing])
        cross_source = row(source_id="cninfo", source_revision_key="c2",
                           observed_at="2020-01-04T10:00:00+00:00",
                           payload={"rights_per_10":3.0}, supersedes=first["revision_id"])
        cases.append(self.rows + [cross_source])
        event2 = row(event_key={"symbol":"sh.600002","effective_date":"2020-01-05","kind":"rights"},
                     source_revision_key="x1")
        cross_event = row(event_key=event2["event_key"], source_revision_key="x2",
                          observed_at="2020-01-04T10:00:00+00:00",
                          payload={"rights_per_10":3.0}, supersedes=first["revision_id"])
        cases.append(self.rows + [event2, cross_event])
        branch = row(source_revision_key="r3", observed_at="2020-01-04T10:00:00+00:00",
                     payload={"rights_per_10":3.0}, supersedes=first["revision_id"])
        cases.append(self.rows + [branch])
        for rows in cases:
            with self.subTest(rows=len(rows)):
                self.write(rows)
                with self.assertRaises(VersionLedgerError):
                    get_version_ledger_manifest(self.binding)

    def test_cycle_and_observation_time_inversion_are_rejected(self):
        event_key = {"symbol":"sh.600010","effective_date":"2020-01-05","kind":"rights"}
        a = row(event_key=event_key, source_revision_key="a", observed_at="2020-01-02T10:00:00+00:00")
        b = row(event_key=event_key, source_revision_key="b", observed_at="2020-01-02T10:00:00+00:00",
                payload={"rights_per_10":3.0})
        a["supersedes_revision_id"] = b["revision_id"]
        b["supersedes_revision_id"] = a["revision_id"]
        self.write([a, b])
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)
        prior = row(event_key=event_key, source_revision_key="p", observed_at="2020-01-03T10:00:00+00:00")
        child = row(event_key=event_key, source_revision_key="c", observed_at="2020-01-02T10:00:00+00:00",
                    payload={"rights_per_10":4.0}, supersedes=prior["revision_id"])
        self.write([prior, child])
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

    def test_summary_wrong_hash_counts_bool_or_policy_are_rejected(self):
        mutations = [
            {"summarises_jsonl_sha256":"0"*64},
            {"records": True},
            {"events": 99},
            {"deterministic": False},
            {"selection_policies":["latest"]},
        ]
        for change in mutations:
            self.write(summary_changes=change)
            with self.subTest(change=change), self.assertRaises(VersionLedgerError):
                get_version_ledger_manifest(self.binding)

    def test_noncanonical_times_published_after_observed_and_nonfinite_payload_rejected(self):
        variants = []
        bad = deepcopy(self.rows[0]); bad["observed_at"] = "2020-01-01T10:00:00"
        variants.append(bad)
        bad = deepcopy(self.rows[0]); bad["observed_at"] = "2020-01-01T10:00:00Z"
        variants.append(bad)
        bad = deepcopy(self.rows[0]); bad["published_at"] = "2020-01-02T10:00:00+00:00"
        variants.append(bad)
        bad = deepcopy(self.rows[0]); bad["effective_at"] = "20200105"
        variants.append(bad)
        for bad in variants:
            payload = (json.dumps(bad, allow_nan=False) + "\n").encode()
            self.jsonl.write_bytes(payload)
            # invalid rows cannot use helper; bind arbitrary summary to force row parse first
            self.summary.write_text("{}", encoding="utf-8")
            self.binding = VersionLedgerBinding(self.jsonl, self.summary, sha(payload), sha(self.summary.read_bytes()))
            with self.subTest(bad=bad), self.assertRaises(VersionLedgerError):
                get_version_ledger_manifest(self.binding)
        raw = json.dumps(self.rows[0]).replace('"rights_per_10": 2.0', '"rights_per_10": NaN')
        payload = (raw + "\n").encode(); self.jsonl.write_bytes(payload); self.summary.write_text("{}", encoding="utf-8")
        self.binding = VersionLedgerBinding(self.jsonl, self.summary, sha(payload), sha(self.summary.read_bytes()))
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

    def test_extra_field_duplicate_json_key_wrong_hash_changed_bytes_and_symlink_fail(self):
        extra = deepcopy(self.rows[0]); extra["extra"] = 1
        payload = (json.dumps(extra) + "\n").encode()
        self.jsonl.write_bytes(payload); self.summary.write_text("{}", encoding="utf-8")
        self.binding = VersionLedgerBinding(self.jsonl, self.summary, sha(payload), sha(self.summary.read_bytes()))
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

        raw = '{"domain":"x","domain":"y"}\n'.encode()
        self.jsonl.write_bytes(raw); self.binding = VersionLedgerBinding(
            self.jsonl, self.summary, sha(raw), sha(self.summary.read_bytes()))
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(self.binding)

        self.write()
        wrong = VersionLedgerBinding(self.jsonl, self.summary, "0"*64, self.binding.summary_sha256)
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(wrong)
        old = self.binding; self.jsonl.write_bytes(self.jsonl.read_bytes()+b"\n")
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(old)

        self.write(); link = self.root / "link.jsonl"; link.symlink_to(self.jsonl)
        linked = VersionLedgerBinding(link, self.summary, self.binding.jsonl_sha256, self.binding.summary_sha256)
        with self.assertRaises(VersionLedgerError):
            get_version_ledger_manifest(linked)

    def test_selection_request_is_closed_and_deterministic(self):
        second = self.rows[2]
        contract = get_version_selection_contract()
        self.assertEqual(contract["contract"], "niuniu-version-selection-preview-v1")
        result = self.selection(revision_id=second["revision_id"])
        again = self.selection(revision_id=second["revision_id"])
        self.assertEqual(result["selection_digest"], again["selection_digest"])
        bad_requests = [
            {"contract":"niuniu-version-selection-preview-v1","event_id":second["event_id"],
             "source_id":"tdx","policy":"explicit_revision_v1","revision_id":second["revision_id"],
             "as_of":"","extra":1},
            {"contract":"niuniu-version-selection-preview-v1","event_id":second["event_id"],
             "source_id":"tdx","policy":"explicit_revision_v1","revision_id":second["revision_id"],
             "as_of":"2020-01-04T00:00:00+00:00"},
            {"contract":"niuniu-version-selection-preview-v1","event_id":second["event_id"],
             "source_id":"tdx","policy":"latest_observed_revision_as_of_v1","revision_id":"",
             "as_of":"20200104"},
        ]
        for request in bad_requests:
            with self.subTest(request=request), self.assertRaises(VersionLedgerError):
                preview_version_selection(self.binding, request_json=json.dumps(request))

    def test_query_bounds_and_empty_scope_do_not_claim_completeness(self):
        empty = query_version_ledger(self.binding, domain="auction", event_type="", event_id="",
                                     source_id="", offset=0, limit=20)
        self.assertEqual(empty["rows"], [])
        self.assertFalse(empty["query_scope_complete"])
        for kwargs in ({"offset": True}, {"limit": 21}, {"event_id": "x"}):
            args = dict(domain="", event_type="", event_id="", source_id="", offset=0, limit=20)
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(VersionLedgerError):
                query_version_ledger(self.binding, **args)


if __name__ == "__main__":
    import unittest
    unittest.main()
