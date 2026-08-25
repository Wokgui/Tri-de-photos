import ast
import hashlib
import queue
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image


APP_PATH = (
    Path(__file__).parents[1]
    / "Tri de photos v16 avec maximisation précalculée"
    / "triphotos_v14_29.py"
)
ICON_PATH = APP_PATH.with_name("triphotos_icon_final.png")
HD_ICON_PATH = APP_PATH.with_name("triphotos_icon_hd.png")


def load_session_helpers():
    """Charge seulement les fonctions pures, sans initialiser l'interface Tk."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    names = {
        "natural_path_key",
        "build_fresh_session",
        "build_complete_review_queue",
        "review_step_count",
    }
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    app_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TriPhotosApp"
    )
    selected.extend(
        node for node in app_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"normalize_session", "resolve_unique"}
    )
    namespace = {"datetime": datetime}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return (
        namespace["build_fresh_session"],
        namespace["build_complete_review_queue"],
        namespace["normalize_session"],
        namespace["resolve_unique"],
    )


(
    build_fresh_session,
    build_complete_review_queue,
    normalize_session,
resolve_unique,
) = load_session_helpers()


def load_responsiveness_helpers():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    selected = [
        node for node in tree.body
        if (
            isinstance(node, ast.ClassDef) and node.name == "AnalysisCancelled"
        ) or (
            isinstance(node, ast.FunctionDef) and node.name == "sha256_file"
        )
    ]
    progress_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProgressDialog"
    )
    selected.extend(
        node for node in progress_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"update_progress", "_flush_progress"}
    )
    app_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TriPhotosApp"
    )
    selected.extend(
        node for node in app_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_drain_ui_queue"
    )
    namespace = {"hashlib": hashlib, "queue": queue, "time": time}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return (
        namespace["AnalysisCancelled"],
        namespace["sha256_file"],
        namespace["update_progress"],
        namespace["_flush_progress"],
        namespace["_drain_ui_queue"],
    )


(
    AnalysisCancelled,
    sha256_file,
    update_progress,
    flush_progress,
    drain_ui_queue,
) = load_responsiveness_helpers()


class FreshSessionTests(unittest.TestCase):
    def test_hashing_can_be_cancelled_between_chunks(self):
        checks = 0

        def cancel_check():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise AnalysisCancelled("stop")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large-photo.bin"
            path.write_bytes(b"x" * 8192)
            with self.assertRaises(AnalysisCancelled):
                sha256_file(path, chunk=1024, cancel_check=cancel_check)

        self.assertEqual(checks, 3)

    def test_progress_updates_are_coalesced_to_the_latest_value(self):
        queued = []
        applied = []

        class Parent:
            def call_on_ui(self, callback, *args, **kwargs):
                queued.append((callback, args, kwargs))

        dialog = types.SimpleNamespace(
            parent=Parent(),
            _progress_lock=threading.Lock(),
            _pending_progress={},
            _progress_enqueued=False,
        )
        dialog._apply_progress = lambda **values: applied.append(values)
        dialog._flush_progress = types.MethodType(flush_progress, dialog)

        for value in range(200):
            update_progress(dialog, value=value, maximum=200)

        self.assertEqual(len(queued), 1)
        callback, args, kwargs = queued.pop()
        callback(*args, **kwargs)
        self.assertEqual(applied, [{"value": 199, "maximum": 200}])
        self.assertFalse(dialog._progress_enqueued)

    def test_ui_queue_is_drained_in_bounded_batches(self):
        executed = []
        scheduled = []
        app = types.SimpleNamespace(ui_queue=queue.Queue())
        app.winfo_exists = lambda: True
        app.after = lambda delay, callback: scheduled.append((delay, callback))
        app._drain_ui_queue = types.MethodType(drain_ui_queue, app)
        for value in range(100):
            app.ui_queue.put((lambda item=value: executed.append(item), (), {}))

        drain_ui_queue(app)

        self.assertGreater(len(executed), 0)
        self.assertLessEqual(len(executed), 32)
        self.assertGreater(app.ui_queue.qsize(), 0)
        self.assertEqual(scheduled[0][0], 1)

    def test_header_uses_the_approved_transparent_icon_without_extra_shell(self):
        source = APP_PATH.read_text(encoding="utf-8")
        self.assertNotIn('with_name("triphotos_header_icon.png")', source)
        self.assertGreaterEqual(
            source.count('with_name("triphotos_icon_hd.png")'), 3
        )
        self.assertNotIn("round_rect(shell_x1", source)

        with Image.open(ICON_PATH).convert("RGBA") as icon:
            self.assertEqual(icon.size, (96, 96))
            self.assertTrue(all(
                icon.getpixel(point)[3] == 0
                for point in (
                    (0, 0),
                    (icon.width - 1, 0),
                    (0, icon.height - 1),
                    (icon.width - 1, icon.height - 1),
                )
            ))

        with Image.open(HD_ICON_PATH).convert("RGBA") as icon:
            self.assertEqual(icon.size, (1254, 1254))
            self.assertTrue(all(
                icon.getpixel(point)[3] == 0
                for point in (
                    (0, 0),
                    (icon.width - 1, 0),
                    (0, icon.height - 1),
                    (icon.width - 1, icon.height - 1),
                )
            ))

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

        single_group = {
            "type": "unique",
            "items": [str(photos[2])],
            "records": {str(photos[2]): records[2]},
            "status": "done",
            "kept": [str(photos[2])],
            "rejected": [],
            "candidate": str(photos[2]),
            "remaining": [],
            "unique_target": str(photos[2]),
        }
        session = build_fresh_session(
            source, photos, records, [], [stale_group, single_group],
            threshold=8, time_window=120
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
        self.assertEqual(session["groups"][1]["status"], "pending")
        self.assertEqual(session["groups"][1]["candidate"], str(photos[2]))
        self.assertEqual(session["unique_keep"], [])

    def test_six_hundred_photos_all_enter_the_queue_once(self):
        source = Path("C:/Photos/Grand-dossier")
        records = [
            {"path": str(source / f"photo{index:03}.jpg"), "score": 0.5}
            for index in range(1, 601)
        ]
        source_order = {
            record["path"]: index for index, record in enumerate(records)
        }
        pair_types = {}
        for index in range(590, 600, 2):
            pair_types[(records[index]["path"], records[index + 1]["path"])] = "similar"

        groups = build_complete_review_queue(records, pair_types, source_order)

        queued_paths = [path for group in groups for path in group["items"]]
        self.assertEqual(len(queued_paths), 600)
        self.assertEqual(len(set(queued_paths)), 600)
        self.assertEqual(set(queued_paths), {record["path"] for record in records})
        self.assertEqual(len(groups), 300)
        self.assertEqual(groups[0]["items"], [records[0]["path"], records[1]["path"]])
        self.assertEqual(groups[0]["type"], "manual")
        self.assertEqual(groups[-1]["items"], [records[598]["path"], records[599]["path"]])
        self.assertEqual(groups[-1]["type"], "similar")
        self.assertEqual(sum(group["type"] == "similar" for group in groups), 5)
        self.assertEqual(sum(group["type"] == "manual" for group in groups), 295)
        self.assertTrue(all(group["status"] == "pending" for group in groups))

        photos = [Path(record["path"]) for record in records]
        session = build_fresh_session(
            source, photos, records, [], groups, threshold=8, time_window=120
        )
        self.assertEqual(session["total_files"], 600)
        self.assertEqual(session["reviewed_files"], [])
        self.assertEqual(session["unique_keep"], [])
        self.assertEqual(session["group_index"], 0)
        self.assertEqual(session["comparisons_done"], 0)
        self.assertEqual(session["total_candidate_pairs"], len(groups))

    def test_connected_close_duplicates_stay_in_the_same_group(self):
        source = Path("C:/Photos/Doublons")
        records = [
            {"path": str(source / name), "score": 0.5}
            for name in ("a.jpg", "b.jpg", "c.jpg", "d.jpg")
        ]
        source_order = {
            record["path"]: index for index, record in enumerate(records)
        }
        pair_types = {
            (records[0]["path"], records[1]["path"]): "similar",
            (records[0]["path"], records[2]["path"]): "exact",
        }

        groups = build_complete_review_queue(records, pair_types, source_order)

        self.assertEqual(groups[0]["type"], "similar")
        self.assertEqual(
            groups[0]["items"],
            [records[0]["path"], records[1]["path"], records[2]["path"]],
        )
        self.assertEqual(groups[0]["remaining"], [records[1]["path"], records[2]["path"]])
        self.assertEqual(groups[1]["type"], "unique")
        self.assertEqual(groups[1]["items"], [records[3]["path"]])

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

    def test_resume_keeps_an_unreviewed_single_photo_pending(self):
        path = "C:/Photos/photo1.jpg"
        session = {
            "groups": [{
                "type": "unique",
                "items": [path],
                "records": {path: {"path": path}},
                "status": "pending",
                "candidate": path,
                "remaining": [],
                "kept": [],
                "rejected": [],
            }],
            "unique_keep": [],
            "global_rejected": [],
            "all_files": [path],
        }

        normalized = normalize_session(object(), session)

        self.assertEqual(len(normalized["groups"]), 1)
        self.assertEqual(normalized["groups"][0]["status"], "pending")
        self.assertEqual(normalized["group_index"], 0)

    def test_validating_a_single_photo_updates_progress(self):
        path = "C:/Photos/photo1.jpg"
        group = {
            "type": "unique",
            "status": "pending",
            "candidate": path,
            "unique_target": path,
        }

        class DummyApp:
            decision_in_progress = False

            def __init__(self):
                self.session = {
                    "groups": [group],
                    "group_index": 0,
                    "global_rejected": [],
                    "reviewed_files": [],
                    "unique_keep": [],
                    "comparisons_done": 0,
                }

            def current_group(self):
                return self.session["groups"][self.session["group_index"]]

            def snapshot(self):
                pass

            def save_session(self):
                pass

            def show_current_pair(self):
                pass

            def after(self, _delay, callback):
                callback()

        app = DummyApp()
        resolve_unique(app, "keep")

        self.assertEqual(group["status"], "done")
        self.assertEqual(app.session["reviewed_files"], [path])
        self.assertEqual(app.session["unique_keep"], [path])
        self.assertEqual(app.session["comparisons_done"], 1)
        self.assertEqual(app.session["group_index"], 1)


if __name__ == "__main__":
    unittest.main()
