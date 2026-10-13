"""Workspace index behavior independent of Tk and network."""
import unittest
from client.tauvsync.workspace_data import next_available_name, reconcile_projects, latest_authors


class WorkspaceDataTests(unittest.TestCase):
    def test_unique_names_preserve_existing_projects(self):
        projects = [{"id": "1", "name": "Buck"}, {"id": "2", "name": "buck (1)"}]
        self.assertEqual(next_available_name("Buck", projects), "Buck (2)")
        self.assertEqual(next_available_name("Unrelated", projects), "Unrelated")
        self.assertEqual(next_available_name("buck (1)", projects), "buck (2)")
        self.assertEqual(projects[0]["name"], "Buck")

    def test_case_insensitive_unicode_and_existing_suffix(self):
        projects = [{"name": "Ses Kartı"}, {"name": "Ses Kartı (1)"}]
        self.assertEqual(next_available_name("ses kartı", projects), "ses kartı (2)")
        self.assertEqual(next_available_name(" Ses Kartı ", projects), "Ses Kartı (2)")

    def test_name_truncated_to_safe_length_when_suffixing(self):
        name = "x" * 80
        result = next_available_name(name, [{"name": name}])
        self.assertTrue(result.endswith(" (1)"))
        self.assertLessEqual(len(result), 80)

    def test_missing_remote_preserves_local_checkout(self):
        remote = [{"id": "1", "name": "Active", "cloud_state": "active"}]
        local = {"2": {"name": "Old", "base_revision": 7}}
        result = reconcile_projects(remote, local)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["cloud_state"], "missing_prism")
        self.assertTrue(result[1]["local_only"])
        self.assertEqual(result[1]["head_revision"], 7)
        self.assertEqual(len(remote), 1)

    def test_author_lookup_tracks_current_revision_and_caches(self):
        class API:
            def __init__(self):
                self.calls = []
            def revisions(self, pid):
                self.calls.append(pid)
                return [
                    {"number": 5, "author": "new@team.test"},
                    {"number": 4, "author": "old@team.test"},
                ]
        api = API()
        projects = [{"id": "p", "name": "Buck", "owner": "original@team.test",
                     "cloud_state": "active", "head_revision": 5}]
        authors = latest_authors(api, projects, {})
        self.assertEqual(authors[("p", 5)], "new@team.test")
        self.assertEqual(latest_authors(api, projects, authors), authors)
        self.assertEqual(api.calls, ["p"])


if __name__ == "__main__":
    unittest.main()
