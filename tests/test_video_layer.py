"""Smoke test for the Spellcaster video layer.

Runs offline -- no WanGP or ComfyUI required -- by hitting the parts of
the stack that are pure logic:

    * Shotboard round-trip (save / load / reorder / status)
    * Trajectory serialisation
    * CinematographerWizard full conversation flow
    * WanGPRunner preset introspection (no network)
    * VideoBridge composition (bridges to unreachable backends gracefully)

Run from the repo root::

    PYTHONPATH=. python tests/test_video_layer.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    sys.path.insert(0, repo_root)

    # Minimal logging config so failures are visible
    import logging
    logging.basicConfig(level=logging.WARNING,
                        format="%(name)s: %(message)s")

    failures = []

    def check(label, fn):
        try:
            fn()
            print(f"  [OK]   {label}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {label}: {exc}")
            traceback.print_exc()
            failures.append(label)

    print("Smoke test: Spellcaster video layer")

    print("-" * 50)

    from scaffold.shotboard import Shotboard, Shot, Trajectory
    from scaffold.video_wizard import CinematographerWizard
    from scaffold.wangp_runner import (
        WanGPRunner, WANGP_PRESETS, describe_preset, preset_names,
    )
    from scaffold.video_bridge import VideoBridge

    with tempfile.TemporaryDirectory() as tmp:
        board_path = os.path.join(tmp, "shotboard.json")

        # ---- Shotboard round-trip ----------------------------------
        def test_board_roundtrip():
            board = Shotboard(board_path)
            assert len(board) == 0
            s1 = board.add(title="Shot A", prompt="a wolf walks")
            s2 = board.add(title="Shot B", prompt="a fox pounces")
            assert s1.index == 0 and s2.index == 1
            board2 = Shotboard(board_path)
            assert len(board2) == 2
            assert board2.all()[0].title == "Shot A"
            assert board2.all()[1].title == "Shot B"
            board2.reorder([s2.id, s1.id])
            board3 = Shotboard(board_path)
            assert board3.all()[0].id == s2.id
            assert board3.all()[1].id == s1.id
            assert board3.all()[0].index == 0

        check("Shotboard persist / reload / reorder", test_board_roundtrip)

        # ---- Trajectory serialisation ------------------------------
        def test_trajectory():
            t = Trajectory(label="zoom",
                           points=[[10, 10], [20, 20], [30, 15]],
                           speeds=[1.0, 1.2],
                           colour="#00ff00")
            d = t.to_dict()
            back = Trajectory.from_dict(d)
            assert back.label == "zoom"
            assert back.points == [[10, 10], [20, 20], [30, 15]]
            assert back.speeds == [1.0, 1.2]

        check("Trajectory round-trip", test_trajectory)

        # ---- CinematographerWizard menu flow ------------------------
        def test_wizard_flow():
            board = Shotboard(os.path.join(tmp, "wizflow.json"))
            wiz = CinematographerWizard(board)
            r1 = wiz.handle("alice", "hi")
            assert "Cinematographer" in r1
            r2 = wiz.handle("alice", "1")
            assert "call this shot" in r2.lower() or "title" in r2.lower()
            r3 = wiz.handle("alice", "INT. forest - dawn")
            assert "describe" in r3.lower()
            r4 = wiz.handle("alice", "a wolf pads through pine trees")
            assert "backend" in r4.lower()
            r5 = wiz.handle("alice", "1")
            assert "preset" in r5.lower()
            r6 = wiz.handle("alice", "1")
            assert "reference image" in r6.lower() or "absolute path" in r6.lower()
            shots = board.all()
            assert len(shots) == 1
            assert shots[0].title == "INT. forest - dawn"
            assert shots[0].prompt.startswith("a wolf")
            assert shots[0].backend == "wangp"
            assert shots[0].preset in preset_names()

        check("CinematographerWizard happy-path flow", test_wizard_flow)

        # ---- Wizard cancel / reset ---------------------------------
        def test_wizard_cancel():
            board = Shotboard(os.path.join(tmp, "wizcancel.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("bob", "hi")
            wiz.handle("bob", "1")
            wiz.handle("bob", "some title")
            out = wiz.handle("bob", "cancel")
            assert "Cinematographer" in out
            sess = wiz.session("bob")
            assert sess.step in ("idle", "pick_action")

        check("Wizard cancel global escape", test_wizard_cancel)

        # ---- Preset catalogue is well-formed -----------------------
        def test_presets():
            assert len(preset_names()) == len(WANGP_PRESETS)
            for key, spec in WANGP_PRESETS.items():
                assert isinstance(spec["label"], str), key
                assert isinstance(spec["inputs"], list), key
                assert "model_hint" in spec, key
                d = describe_preset(key)
                d["label"] = "MUTATED"
                assert spec["label"] != "MUTATED", (
                    f"describe_preset({key}) leaks live reference"
                )

        check("WanGP preset catalogue sanity", test_presets)

        # ---- WanGPRunner graceful unavailability -------------------
        def test_runner_offline():
            runner = WanGPRunner("http://127.0.0.1:1")
            assert runner.is_available() is False
            info = runner.server_info()
            assert info["available"] is False
            result = runner.queue_generation(
                preset="wan22_t2v", prompt="test",
            )
            assert result["status"] == "error"
            assert "not reachable" in result["message"].lower()

        check("WanGPRunner handles dead server gracefully",
              test_runner_offline)

        # ---- Unknown preset handling -------------------------------
        def test_runner_bad_preset():
            runner = WanGPRunner("http://127.0.0.1:1")
            result = runner.queue_generation(
                preset="this_does_not_exist", prompt="x",
            )
            assert result["status"] == "error"
            assert "unknown preset" in result["message"].lower()

        check("WanGPRunner rejects unknown preset",
              test_runner_bad_preset)

        # ---- VideoBridge composition -------------------------------
        def test_bridge_composition():
            bridge_board = os.path.join(tmp, "bridgeboard.json")
            bridge = VideoBridge(
                shotboard_path=bridge_board,
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, "renders"),
            )
            shot_dict = bridge.add_shot(
                title="remote", prompt="a cloud drifts",
                preset="wan22_t2v",
            )
            shot_id = shot_dict["id"]
            assert shot_dict["title"] == "remote"
            health = bridge.health()
            assert health["wangp"]["available"] is False
            assert health["comfyui"]["available"] is False
            assert health["shotboard"]["count"] == 1
            q = bridge.queue_shot(shot_id)
            assert q["status"] == "error"
            shots = bridge.list_shots()["shots"]
            assert any(s["status"] == "failed" for s in shots)

        check("VideoBridge composes end-to-end (offline)",
              test_bridge_composition)

        # ---- Chat -> auto-queue round trip --------------------------
        def test_chat_auto_queue():
            bridge = VideoBridge(
                shotboard_path=os.path.join(tmp, "chat.json"),
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, "chatrenders"),
            )
            bridge.handle_chat("u1", "hi")
            bridge.handle_chat("u1", "1")
            bridge.handle_chat("u1", "Title A")
            bridge.handle_chat("u1", "a river flows")
            bridge.handle_chat("u1", "1")
            wangp_presets = list(WANGP_PRESETS.keys())
            t2v_idx = wangp_presets.index("wan22_t2v") + 1
            bridge.handle_chat("u1", str(t2v_idx))
            final = bridge.handle_chat("u1", "1")
            assert "queued" in final or "pending_render" in final

        check("Chat -> review -> auto-queue (offline)", test_chat_auto_queue)

        # ==============================================================
        # Shotboard edge cases
        # ==============================================================

        def test_board_remove():
            board = Shotboard(os.path.join(tmp, "rm.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            assert len(board) == 3
            assert board.remove(s2.id) is True
            assert len(board) == 2
            assert board.all()[0].index == 0
            assert board.all()[1].index == 1
            assert board.all()[0].id == s1.id
            assert board.all()[1].id == s3.id
            assert board.remove("bogus_id") is False

        check("Shotboard remove + reindex", test_board_remove)

        def test_board_update():
            board = Shotboard(os.path.join(tmp, "upd.json"))
            s = board.add(title="Old", prompt="old prompt")
            board.update(s.id, title="New", prompt="new prompt")
            got = board.get(s.id)
            assert got.title == "New"
            assert got.prompt == "new prompt"
            assert board.update("no_such_id", title="X") is None
            board.update(s.id, this_field_doesnt_exist=42)
            assert not hasattr(board.get(s.id), "this_field_doesnt_exist")

        check("Shotboard update + unknown fields", test_board_update)

        def test_board_navigation():
            board = Shotboard(os.path.join(tmp, "nav.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            assert board.next_of(s1.id).id == s2.id
            assert board.next_of(s2.id).id == s3.id
            assert board.next_of(s3.id) is None
            assert board.previous_of(s1.id) is None
            assert board.previous_of(s2.id).id == s1.id
            assert board.previous_of(s3.id).id == s2.id
            assert board.next_of("bogus") is None
            assert board.previous_of("bogus") is None

        check("Shotboard next_of / previous_of", test_board_navigation)

        def test_board_status_helpers():
            board = Shotboard(os.path.join(tmp, "status.json"))
            s = board.add(title="Job")
            assert s.status == "draft"
            board.mark_queued(s.id, "job-123")
            got = board.get(s.id)
            assert got.status == "queued"
            assert got.job_id == "job-123"
            board.mark_running(s.id)
            assert board.get(s.id).status == "running"
            board.mark_ready(s.id, "/tmp/out.mp4")
            got = board.get(s.id)
            assert got.status == "ready"
            assert got.video_path == "/tmp/out.mp4"
            assert got.job_id is None
            s2 = board.add(title="Fail")
            board.mark_failed(s2.id, "boom")
            got2 = board.get(s2.id)
            assert got2.status == "failed"
            assert got2.error == "boom"
            board.mark_failed(s2.id, "x" * 600)
            assert len(board.get(s2.id).error) == 500

        check("Shotboard status helpers", test_board_status_helpers)

        def test_board_export_for_next():
            board = Shotboard(os.path.join(tmp, "cont.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            result = board.export_for_next(s1.id, "/tmp/frame.png")
            assert result is not None
            assert result.id == s2.id
            assert board.get(s2.id).ref_image == "/tmp/frame.png"
            board.update(s3.id, ref_image="/old.png")
            board.export_for_next(s2.id, "/tmp/frame2.png")
            assert board.get(s3.id).ref_image == "/tmp/frame2.png"
            board.update(s3.id, carry_last_frame=False, ref_image="/keep.png")
            board.export_for_next(s2.id, "/tmp/frame3.png")
            assert board.get(s3.id).ref_image == "/keep.png"
            assert board.export_for_next(s3.id, "/x.png") is None
            board.update(s2.id, ref_image="/original.png",
                         carry_last_frame=True)
            board.export_for_next(s1.id, None)
            assert board.get(s2.id).ref_image == "/original.png"

        check("Shotboard export_for_next (continuity)", test_board_export_for_next)

        def test_board_ready_videos():
            board = Shotboard(os.path.join(tmp, "rv.json"))
            board.add(title="A")
            board.add(title="B")
            board.add(title="C")
            shots = board.all()
            assert board.ready_videos() == []
            board.mark_ready(shots[0].id, "/v1.mp4")
            board.mark_ready(shots[2].id, "/v3.mp4")
            assert board.ready_videos() == ["/v1.mp4", "/v3.mp4"]

        check("Shotboard ready_videos", test_board_ready_videos)

        def test_board_reorder_partial():
            board = Shotboard(os.path.join(tmp, "reop.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            board.reorder([s3.id, s1.id])
            ids = [s.id for s in board.all()]
            assert ids == [s3.id, s1.id, s2.id]
            assert board.all()[0].index == 0
            assert board.all()[1].index == 1
            assert board.all()[2].index == 2

        check("Shotboard reorder with partial ID list", test_board_reorder_partial)

        def test_board_corrupt_json():
            path = os.path.join(tmp, "corrupt.json")
            with open(path, "w") as f:
                f.write("{{{not valid json")
            board = Shotboard(path)
            assert len(board) == 0
            with open(path, "w") as f:
                f.write('"just a string"')
            board2 = Shotboard(path)
            assert len(board2) == 0
            import json
            with open(path, "w") as f:
                json.dump({"version": 1, "shots": [
                    {"id": "abc", "title": "T", "future_field": True}
                ]}, f)
            board3 = Shotboard(path)
            assert len(board3) == 1
            assert board3.all()[0].title == "T"

        check("Shotboard corrupt / future-schema JSON recovery",
              test_board_corrupt_json)


        # ==============================================================
        # CinematographerWizard extended coverage
        # ==============================================================

        def test_wizard_status_action():
            board = Shotboard(os.path.join(tmp, "wizstat.json"))
            board.add(title="Shot X", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "6")  # status
            assert "Shot X" in r or "Shotboard" in r

        check("Wizard status action", test_wizard_status_action)

        def test_wizard_done_action():
            board = Shotboard(os.path.join(tmp, "wizdone.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "7")  # done
            assert "leaving" in r.lower() or "saved" in r.lower()
            sess = wiz.session("u")
            assert sess.step == "idle"

        check("Wizard done action exits cleanly", test_wizard_done_action)

        def test_wizard_edit_existing_shot():
            board = Shotboard(os.path.join(tmp, "wizedit.json"))
            board.add(title="First", prompt="p1", preset="wan22_t2v")
            board.add(title="Second", prompt="p2", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "2")  # edit
            assert "First" in r and "Second" in r
            r2 = wiz.handle("u", "1")  # pick first shot
            assert "Review" in r2 or "review" in r2.lower()

        check("Wizard edit existing shot", test_wizard_edit_existing_shot)

        def test_wizard_edit_empty_board():
            board = Shotboard(os.path.join(tmp, "wizeditempty.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "2")  # edit on empty board
            assert "no shots" in r.lower() or "add a new" in r.lower()

        check("Wizard edit on empty board", test_wizard_edit_empty_board)

        def test_wizard_remove_shot():
            board = Shotboard(os.path.join(tmp, "wizrm.json"))
            board.add(title="Kill Me")
            assert len(board) == 1
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "4")  # remove
            assert "Kill Me" in r
            r2 = wiz.handle("u", "1")  # pick it
            assert "removed" in r2.lower() or "Removed" in r2
            assert len(board) == 0

        check("Wizard remove shot", test_wizard_remove_shot)

        def test_wizard_reorder_shots():
            board = Shotboard(os.path.join(tmp, "wizreord.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "3")  # reorder
            assert "A" in r and "B" in r and "C" in r
            r2 = wiz.handle("u", "3,1,2")
            assert "reordered" in r2.lower() or "Reordered" in r2
            ids = [s.id for s in board.all()]
            assert ids == [s3.id, s1.id, s2.id]

        check("Wizard reorder shots", test_wizard_reorder_shots)

        def test_wizard_reorder_bad_input():
            board = Shotboard(os.path.join(tmp, "wizreordbad.json"))
            board.add(title="A")
            board.add(title="B")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "3")  # reorder
            r = wiz.handle("u", "abc")  # bad input
            assert "numbers" in r.lower() or "commas" in r.lower()

        check("Wizard reorder bad input", test_wizard_reorder_bad_input)

        def test_wizard_render_action():
            board = Shotboard(os.path.join(tmp, "wizrender.json"))
            board.add(title="Render Me", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "5")  # render
            assert "Render Me" in r
            r2 = wiz.handle("u", "1")  # pick it
            assert "queuing" in r2.lower() or "queue" in r2.lower()                 or "bridge" in r2.lower()
            # get_pending_render should return the shot id
            pending = wiz.get_pending_render("u")
            assert pending == board.all()[0].id

        check("Wizard render action sets pending", test_wizard_render_action)

        def test_wizard_invalid_pick():
            board = Shotboard(os.path.join(tmp, "wizinvalid.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "99")  # out of range
            assert "pick a number" in r.lower() or "Cinematographer" in r

        check("Wizard invalid menu pick", test_wizard_invalid_pick)

        def test_wizard_review_reedit():
            board = Shotboard(os.path.join(tmp, "wizreedit.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "1")  # new
            wiz.handle("u", "Original Title")
            wiz.handle("u", "original prompt")
            wiz.handle("u", "1")  # wangp
            keys = preset_names()
            t2v_idx = keys.index("wan22_t2v") + 1
            wiz.handle("u", str(t2v_idx))
            # Now at review; pick "Edit title" (option 2)
            r = wiz.handle("u", "2")
            assert "title" in r.lower()
            wiz.handle("u", "Changed Title")
            # Should be back at prompt edit
            wiz.handle("u", "changed prompt")
            # Pick backend again
            wiz.handle("u", "1")
            wiz.handle("u", str(t2v_idx))
            # Should be at review with updated values
            shot = board.all()[0]
            assert shot.title == "Changed Title"
            assert shot.prompt == "changed prompt"

        check("Wizard review re-edit title+prompt", test_wizard_review_reedit)

        def test_wizard_ref_bad_path():
            board = Shotboard(os.path.join(tmp, "wizrefbad.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "1")  # new
            wiz.handle("u", "T")
            wiz.handle("u", "P")
            wiz.handle("u", "1")  # wangp
            wiz.handle("u", "1")  # first preset (i2v, needs image)
            r = wiz.handle("u", "/nonexistent/path.png")
            assert "can't find" in r.lower() or "upload" in r.lower()

        check("Wizard ref image bad path", test_wizard_ref_bad_path)

        def test_wizard_multi_user_isolation():
            board = Shotboard(os.path.join(tmp, "wizmulti.json"))
            wiz = CinematographerWizard(board)
            # Alice starts a new shot
            wiz.handle("alice", "hi")
            wiz.handle("alice", "1")  # new
            wiz.handle("alice", "Alice Shot")
            # Bob starts independently
            wiz.handle("bob", "hi")
            wiz.handle("bob", "1")
            wiz.handle("bob", "Bob Shot")
            # Alice continues from where she left off (prompt step)
            sess_a = wiz.session("alice")
            assert sess_a.step == "edit_prompt"
            sess_b = wiz.session("bob")
            assert sess_b.step == "edit_prompt"
            assert sess_a.current_shot_id != sess_b.current_shot_id

        check("Wizard multi-user session isolation", test_wizard_multi_user_isolation)

        def test_wizard_trajectory_skip():
            """When trajectories step has no trajectories and user says skip."""
            board = Shotboard(os.path.join(tmp, "wiztrajskip.json"))
            wiz = CinematographerWizard(board)
            # Create a shot manually and force into trajectories step
            shot = board.add(title="T", prompt="P", backend="wangp",
                             preset="wan_move_i2v")
            sess = wiz.session("u")
            sess.step = "trajectories"
            sess.current_shot_id = shot.id
            # Saying "done" with no trajectories should warn
            r = wiz.handle("u", "done")
            assert "don't see" in r.lower() or "draw" in r.lower()
            # Saying "skip" should advance (treated as unknown, falls
            # through to the "say done" message since it's not done/ok/ready)
            r2 = wiz.handle("u", "skip")
            assert "done" in r2.lower() or "draw" in r2.lower()

        check("Wizard trajectory step skip", test_wizard_trajectory_skip)


        # ==============================================================
        # MetaWizard video routing
        # ==============================================================

        from scaffold.meta_wizard import MetaWizard, INTENTS

        # Minimal stubs for SpellcasterWizard / WorkflowWizard so we
        # can test MetaWizard routing without ComfyUI.
        class _StubSession:
            def __init__(self):
                self.step = "idle"
            def is_complete(self):
                return False
            def to_workflow(self):
                return {}

        class _StubSpellWiz:
            def handle(self, uid, text):
                return f"[spell:{text}]"
            def get_session(self, uid):
                return _StubSession()

        class _StubWfWiz:
            def handle(self, uid, text):
                return f"[wf:{text}]"
            def get_session(self, uid):
                return _StubSession()

        def test_meta_video_intent_with_wizard():
            board = Shotboard(os.path.join(tmp, "metav1.json"))
            vid_wiz = CinematographerWizard(board)
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
                video_wizard=vid_wiz,
            )
            # Find the video intent index
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            r = meta.handle("u1", str(video_idx))
            assert "quick render" in r.lower() or "shotboard" in r.lower()
            # Pick shotboard (option 2)
            r2 = meta.handle("u1", "2")
            assert "cinematographer" in r2.lower() or "what would" in r2.lower()
            # Session should now be delegating to video sub
            sess = meta._sessions["u1"]
            assert sess.active_sub == "video"

        check("MetaWizard video intent -> shotboard", test_meta_video_intent_with_wizard)

        def test_meta_video_intent_quick_render():
            board = Shotboard(os.path.join(tmp, "metav2.json"))
            vid_wiz = CinematographerWizard(board)
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
                video_wizard=vid_wiz,
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            meta.handle("u1", str(video_idx))
            # Pick quick render (option 1) -> falls to workflow wizard
            r = meta.handle("u1", "1")
            assert "[wf:" in r  # delegated to workflow stub
            sess = meta._sessions["u1"]
            assert sess.active_sub == "workflow"

        check("MetaWizard video intent -> quick render", test_meta_video_intent_quick_render)

        def test_meta_video_no_wizard():
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
                video_wizard=None,
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            # With no video wizard, should fall through to workflow path
            r = meta.handle("u1", str(video_idx))
            assert "[wf:" in r
            sess = meta._sessions["u1"]
            assert sess.active_sub == "workflow"

        check("MetaWizard video intent without video wizard", test_meta_video_no_wizard)

        def test_meta_video_delegation():
            board = Shotboard(os.path.join(tmp, "metav3.json"))
            vid_wiz = CinematographerWizard(board)
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
                video_wizard=vid_wiz,
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            meta.handle("u1", str(video_idx))
            meta.handle("u1", "2")  # shotboard
            # Now delegating -- add a shot via the wizard
            # First "1" advances idle->pick_action, second "1" picks "new"
            meta.handle("u1", "1")
            r = meta.handle("u1", "1")  # new shot
            assert "call this shot" in r.lower() or "title" in r.lower()
            # Global "menu" should reset back to main menu
            r2 = meta.handle("u1", "menu")
            assert "spellcaster" in r2.lower() or "what would" in r2.lower()
            sess = meta._sessions["u1"]
            assert sess.active_sub is None

        check("MetaWizard video delegation + global menu", test_meta_video_delegation)

        def test_meta_video_choice_bad_input():
            board = Shotboard(os.path.join(tmp, "metav4.json"))
            vid_wiz = CinematographerWizard(board)
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
                video_wizard=vid_wiz,
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            meta.handle("u1", str(video_idx))
            r = meta.handle("u1", "banana")  # invalid pick
            assert "pick a number" in r.lower() or "quick render" in r.lower()

        check("MetaWizard video choice bad input", test_meta_video_choice_bad_input)


        # ==============================================================
        # VideoBridge CRUD + edge cases
        # ==============================================================

        def _make_bridge(name):
            return VideoBridge(
                shotboard_path=os.path.join(tmp, f"{name}.json"),
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, f"{name}_renders"),
            )

        def test_bridge_update_shot():
            bridge = _make_bridge("bupd")
            d = bridge.add_shot(title="Old", prompt="old")
            sid = d["id"]
            r = bridge.update_shot(sid, title="New", prompt="new")
            assert r["title"] == "New"
            assert r["prompt"] == "new"
            # Non-existent
            r2 = bridge.update_shot("nope", title="X")
            assert r2["status"] == "error"

        check("VideoBridge update_shot", test_bridge_update_shot)

        def test_bridge_remove_shot():
            bridge = _make_bridge("brm")
            d = bridge.add_shot(title="Gone")
            sid = d["id"]
            r = bridge.remove_shot(sid)
            assert r["status"] == "ok"
            assert bridge.list_shots()["shot_count"] == 0
            r2 = bridge.remove_shot("nope")
            assert r2["status"] == "error"

        check("VideoBridge remove_shot", test_bridge_remove_shot)

        def test_bridge_reorder_shots():
            bridge = _make_bridge("breord")
            d1 = bridge.add_shot(title="A")
            d2 = bridge.add_shot(title="B")
            d3 = bridge.add_shot(title="C")
            r = bridge.reorder_shots([d3["id"], d1["id"], d2["id"]])
            ids = [s["id"] for s in r["shots"]]
            assert ids == [d3["id"], d1["id"], d2["id"]]

        check("VideoBridge reorder_shots", test_bridge_reorder_shots)

        def test_bridge_attach_ref_missing():
            bridge = _make_bridge("bref")
            d = bridge.add_shot(title="T")
            r = bridge.attach_reference(d["id"], "/nonexistent/file.png")
            assert r["status"] == "error"
            assert "no file" in r["message"].lower()

        check("VideoBridge attach_reference missing file", test_bridge_attach_ref_missing)

        def test_bridge_attach_ref_bad_shot():
            bridge = _make_bridge("bref2")
            r = bridge.attach_reference("nope", "/tmp/x.png")
            assert r["status"] == "error"

        check("VideoBridge attach_reference bad shot", test_bridge_attach_ref_bad_shot)

        def test_bridge_set_trajectories():
            bridge = _make_bridge("btraj")
            d = bridge.add_shot(title="T")
            trajs = [
                {"label": "pan", "points": [[0, 0], [100, 100]], "colour": "#ff0000"},
            ]
            r = bridge.set_trajectories(d["id"], trajs)
            assert len(r["trajectories"]) == 1
            assert r["trajectories"][0]["label"] == "pan"
            # Bad shot
            r2 = bridge.set_trajectories("nope", trajs)
            assert r2["status"] == "error"

        check("VideoBridge set_trajectories", test_bridge_set_trajectories)

        def test_bridge_queue_unknown_backend():
            bridge = _make_bridge("bunk")
            d = bridge.add_shot(title="T", backend="alien_tech")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            assert "unknown backend" in r["message"].lower()

        check("VideoBridge queue unknown backend", test_bridge_queue_unknown_backend)

        def test_bridge_queue_nonexistent_shot():
            bridge = _make_bridge("bne")
            r = bridge.queue_shot("no_such_id")
            assert r["status"] == "error"
            assert "not found" in r["message"].lower()

        check("VideoBridge queue nonexistent shot", test_bridge_queue_nonexistent_shot)

        def test_bridge_queue_comfy_offline():
            bridge = _make_bridge("bcomfy")
            d = bridge.add_shot(title="T", backend="comfyui",
                                preset="ltx2_text_to_video")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            assert "not reachable" in r["message"].lower()

        check("VideoBridge queue ComfyUI offline", test_bridge_queue_comfy_offline)


        # ==============================================================
        # Frame extraction
        # ==============================================================

        from scaffold.frame_extract import (
            extract_last_frame, _ffmpeg_available, _get_duration_s,
        )
        import subprocess

        def test_frame_extract_ffmpeg():
            """Create a tiny 10-frame test video, extract last frame."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid.mp4")
            # Generate a 10-frame video: frames go from black to white
            # (each frame slightly brighter). The last frame is brightest.
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "color=c=red:s=64x64:d=0.5:r=20",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                vid,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               check=True, timeout=15)
            assert os.path.isfile(vid)

            out = extract_last_frame(vid)
            assert out is not None
            assert os.path.isfile(out)
            assert out.endswith(".png")
            assert os.path.getsize(out) > 100  # valid PNG

        check("extract_last_frame with ffmpeg", test_frame_extract_ffmpeg)

        def test_frame_extract_custom_output():
            """Extract to a specified output path."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid2.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "color=c=blue:s=32x32:d=0.3:r=10",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                vid,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               check=True, timeout=15)
            custom_out = os.path.join(tmp, "my_frame.png")
            out = extract_last_frame(vid, output_path=custom_out)
            assert out == custom_out
            assert os.path.isfile(custom_out)

        check("extract_last_frame custom output path", test_frame_extract_custom_output)

        def test_frame_extract_missing_video():
            """Non-existent video returns None, doesn't crash."""
            out = extract_last_frame("/nonexistent/video.mp4")
            assert out is None

        check("extract_last_frame missing video", test_frame_extract_missing_video)

        def test_frame_extract_not_a_video():
            """A non-video file returns None gracefully."""
            bad = os.path.join(tmp, "notavideo.txt")
            with open(bad, "w") as f:
                f.write("hello world")
            out = extract_last_frame(bad)
            assert out is None

        check("extract_last_frame non-video file", test_frame_extract_not_a_video)

        def test_get_duration():
            """ffprobe duration works for our test video."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid.mp4")
            if not os.path.isfile(vid):
                print("  [SKIP] test video not created")
                return
            dur = _get_duration_s(vid)
            assert dur is not None
            assert 0.1 < dur < 5.0  # our tiny test clip

        check("ffprobe duration extraction", test_get_duration)


        # ==============================================================
        # Hybrid upscale chain
        # ==============================================================

        def test_hybrid_queue_offline():
            """Hybrid backend queues WanGP first; with WanGP offline it
            fails cleanly just like the plain WanGP path."""
            bridge = _make_bridge("bhybrid")
            d = bridge.add_shot(title="H", backend="hybrid",
                                preset="wan22_t2v")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            shot = bridge.board.get(d["id"])
            assert shot.status == "failed"

        check("Hybrid queue with offline backends", test_hybrid_queue_offline)

        def test_chain_comfy_upscale_no_comfy():
            """_chain_comfy_upscale skips gracefully when ComfyUI is down."""
            bridge = _make_bridge("bchain1")
            d = bridge.add_shot(title="T")
            # ComfyUI at port 2 is unreachable, so this should just log
            # and return without crashing.
            bridge._chain_comfy_upscale(d["id"], "/tmp/fake.mp4")
            # Shot should be unchanged (no crash, no status change)
            shot = bridge.board.get(d["id"])
            assert shot.status == "draft"

        check("_chain_comfy_upscale skips when ComfyUI offline",
              test_chain_comfy_upscale_no_comfy)

        def test_chain_comfy_upscale_no_workflow():
            """_chain_comfy_upscale skips if the workflow JSON is missing."""
            bridge = _make_bridge("bchain2")
            d = bridge.add_shot(title="T")
            # Monkey-patch ComfyUI as "available" to test the workflow check
            bridge.comfy.is_available = lambda: True
            # The workflow file check will fail naturally since the
            # workflows dir has the real file -- but with a fake video
            # path the run_raw would fail if it got that far. Since
            # ComfyUI isn't really available, run_raw will error.
            # This tests that the function doesn't crash.
            bridge._chain_comfy_upscale(d["id"], "/tmp/fake.mp4")
            shot = bridge.board.get(d["id"])
            assert shot.status == "draft"

        check("_chain_comfy_upscale handles errors gracefully",
              test_chain_comfy_upscale_no_workflow)


        # ==============================================================
        # Trajectory canvas data contract
        # ==============================================================

        def test_trajectory_canvas_js_exists():
            """The trajectory_canvas.js file exists and is valid JS."""
            js_path = os.path.join(
                repo_root, "tavern", "static", "trajectory_canvas.js")
            assert os.path.isfile(js_path), f"Missing {js_path}"
            with open(js_path) as f:
                src = f.read()
            assert "class TrajectoryCanvas" in src
            assert "getTrajectories" in src
            assert "setTrajectories" in src
            # Verify the output shape matches what Trajectory.from_dict expects
            assert "label:" in src or "label :" in src
            assert "points:" in src or "points :" in src
            assert "colour:" in src or "colour :" in src

        check("trajectory_canvas.js exists and has expected API",
              test_trajectory_canvas_js_exists)

        def test_trajectory_data_contract():
            """JS canvas output shape round-trips through Trajectory."""
            # Simulate what the JS canvas outputs (onSave callback)
            js_output = [
                {"label": "path-1", "points": [[10, 20], [30, 40], [50, 60]],
                 "colour": "#ff3366"},
                {"label": "path-2", "points": [[100, 200], [150, 250]],
                 "colour": "#33ccff"},
            ]
            # These must survive Trajectory.from_dict -> to_dict round-trip
            for raw in js_output:
                t = Trajectory.from_dict(raw)
                d = t.to_dict()
                assert d["label"] == raw["label"]
                assert d["points"] == raw["points"]
                assert d["colour"] == raw["colour"]
                # speeds should be absent (canvas doesn't emit it)
                assert "speeds" not in d

        check("Trajectory data contract (JS canvas <-> Python model)",
              test_trajectory_data_contract)

        def test_trajectory_canvas_test_page_exists():
            """The test_trajectory.html test page exists."""
            page = os.path.join(
                repo_root, "tavern", "static", "test_trajectory.html")
            assert os.path.isfile(page), f"Missing {page}"
            with open(page) as f:
                html = f.read()
            assert "TrajectoryCanvas" in html
            assert "trajectory_canvas.js" in html

        check("test_trajectory.html test page exists",
              test_trajectory_canvas_test_page_exists)


        # ── Video Panel frontend tests ──────────────────────────
        def test_video_panel_exists():
            """video_panel.jsx exists and has expected structure."""
            jsx = os.path.join(repo_root, "tavern", "static", "video_panel.jsx")
            assert os.path.isfile(jsx), f"Missing {jsx}"
            with open(jsx) as f:
                src = f.read()
            assert "window.VideoPanel = VideoPanel" in src, "Missing export"
            for ep in ["/api/video/shots", "/api/video/presets",
                       "/api/video/health", "/trajectories", "/render",
                       "/reference", "/api/video/reorder"]:
                assert ep in src, f"Missing endpoint ref: {ep}"
            assert "TrajectoryCanvas" in src, "Missing trajectory integration"
            assert "onDragStart" in src, "Missing drag-to-reorder"
            assert "renderAll" in src, "Missing batch render"
            assert "uploadReference" in src, "Missing reference upload"

        check("video_panel.jsx exists with full API surface",
              test_video_panel_exists)

        def test_video_panel_balance():
            """video_panel.jsx has balanced braces and parens."""
            jsx = os.path.join(repo_root, "tavern", "static", "video_panel.jsx")
            with open(jsx) as f:
                src = f.read()
            assert src.count("{") == src.count("}"), (
                f"Unbalanced braces: {src.count(chr(123))} open vs {src.count(chr(125))} close")
            assert src.count("(") == src.count(")"), (
                f"Unbalanced parens: {src.count(chr(40))} open vs {src.count(chr(41))} close")

        check("video_panel.jsx balanced braces/parens",
              test_video_panel_balance)

        def test_guild_html_script_order():
            """guild.html loads scripts in correct dependency order."""
            html_path = os.path.join(repo_root, "tavern", "static", "guild.html")
            with open(html_path) as f:
                html = f.read()
            tc_pos = html.index("trajectory_canvas.js")
            vp_pos = html.index("video_panel.jsx")
            tw_pos = html.index("travelling_wizard.jsx")
            assert tc_pos < vp_pos < tw_pos

        check("guild.html script load order correct",
              test_guild_html_script_order)

        def test_travelling_wizard_video_tab():
            """travelling_wizard.jsx has Video tab wired in."""
            jsx = os.path.join(repo_root, "tavern", "static", "travelling_wizard.jsx")
            with open(jsx) as f:
                src = f.read()
            assert '"video"' in src, "Missing video tab ID"
            assert "VideoPanel" in src, "Missing VideoPanel reference"

        check("travelling_wizard.jsx has Video tab",
              test_travelling_wizard_video_tab)

        def test_server_video_endpoints():
            """server.py has video file serving + all endpoints."""
            srv = os.path.join(repo_root, "tavern", "server.py")
            with open(srv) as f:
                src = f.read()
            assert "def _serve_file" in src, "Missing _serve_file"
            assert "image_data" in src, "Missing base64 upload"
            for ep in ["/api/video/shots", "/api/video/reorder",
                       "/api/video/chat"]:
                assert ep in src, f"Missing endpoint: {ep}"

        check("server.py has video file serving + all endpoints",
              test_server_video_endpoints)


        def test_video_chat_js_exists():
            """video_chat.js exists with expected structure."""
            js = os.path.join(repo_root, "tavern", "static", "video_chat.js")
            assert os.path.isfile(js), f"Missing {js}"
            with open(js) as f:
                src = f.read()
            assert "/api/video/chat" in src, "Missing chat endpoint"
            assert "videoChatActive" in src, "Missing mode toggle state"
            assert "video-chat-btn" in src, "Missing toggle button"
            assert "Cinematographer" in src, "Missing mode label"
            # Check index.html loads it
            html = os.path.join(repo_root, "tavern", "static", "index.html")
            with open(html) as f:
                h = f.read()
            assert "video_chat.js" in h, "video_chat.js not loaded in index.html"
            assert h.index("app.js") < h.index("video_chat.js"), (
                "video_chat.js must load AFTER app.js")

        check("video_chat.js exists with chat integration",
              test_video_chat_js_exists)

    print("-" * 50)
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
