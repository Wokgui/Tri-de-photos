import ast
import unittest
from datetime import datetime
from pathlib import Path


APP_PATH = (
    Path(__file__).parents[1]
    / "Tri de photos v16 avec maximisation précalculée"
    / "triphotos_v14_29.py"
)


def load_session_helpers():
    """Charge seulement les fonctions pures, sans initialiser l'interface Tk."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    names = {"natural_path_key", "build_fresh_session"}
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    namespace = {"datetime": datetime}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return namespace["build_fresh_session"]


build_fresh_session = load_session_helpers()


class FreshSessionTests(unittest.TestCase):
    def test_previous_progress_is_reset_for_a_new_folder_analysis(self):
        source = Path("C:/Photos/Vacances")
        photos = [source / "photo1.jpg", source / "photo2.jpg", source / "photo3.jpg"]
        records = [{"path": str(path), "score": 0.5} for path in photos]
        stale_group = {
            "type": "similar",
            "items": [str(photos[0]), str(photos[1])],
            "records": {record["path"]: record for record in records[:2]},
            "status": "done",
            "kept": [str(photos[0])],
            "rejected": [str(photos[1])],
            "aside": [str(photos[1])],
            "candidate": str(photos[1]),
            "remaining": [],
            "display_left": str(photos[0]),
            "display_right": str(photos[1]),
        }

        session = build_fresh_session(
            source, photos, records, [], [stale_group], threshold=8, time_window=120
        )

        self.assertEqual(session["all_files"], [str(path) for path in photos])
        self.assertEqual(session["reviewed_files"], [])
        self.assertEqual(session["global_rejected"], [])
        self.assertEqual(session["comparisons_done"], 0)
        self.assertEqual(session["group_index"], 0)
        self.assertFalse(session["review_complete"])
        self.assertFalse(session["complete"])

        group = session["groups"][0]
        self.assertEqual(group["status"], "pending")
        self.assertEqual(group["kept"], [])
        self.assertEqual(group["rejected"], [])
        self.assertEqual(group["candidate"], str(photos[0]))
        self.assertEqual(group["remaining"], [str(photos[1])])
        self.assertNotIn("display_left", group)
        self.assertNotIn("display_right", group)
        self.assertEqual(session["unique_keep"], [str(photos[2])])

    def test_fresh_session_does_not_mutate_the_analyzed_groups(self):
        source = Path("C:/Photos")
        photos = [source / "a.jpg", source / "b.jpg"]
        records = [{"path": str(path)} for path in photos]
        original = {
            "type": "exact",
            "items": [str(path) for path in photos],
            "status": "done",
            "kept": [str(photos[0])],
            "rejected": [str(photos[1])],
        }

        build_fresh_session(source, photos, records, [], [original], 4, 20)

        self.assertEqual(original["status"], "done")
        self.assertEqual(original["kept"], [str(photos[0])])
        self.assertEqual(original["rejected"], [str(photos[1])])


if __name__ == "__main__":
    unittest.main()
