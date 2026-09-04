import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.models import Frame, MeetingSession, TranscriptEntry
from app.record.scenes import SceneTracker, dhash, hamming
from app.record.store import Recorder, load_session, save_report
from app.synthesis.mock import build_mock_report
from app.synthesis.record import build_pages, build_timeline


def slide(title: str, *, cursor: tuple[int, int] | None = None) -> bytes:
    """A fake slide: big title text + a few bars, optionally with a small cursor blob."""
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 30), title, fill="black")
    for index, height in enumerate([80, 140, 200] if "A" in title else [200, 60, 120]):
        draw.rectangle([80 + index * 150, 330 - height, 180 + index * 150, 330], fill="steelblue")
    if cursor:
        draw.ellipse([cursor[0], cursor[1], cursor[0] + 8, cursor[1] + 8], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


def test_dhash_separates_slides_but_not_cursor_moves() -> None:
    a, a_cursor, b = slide("Slide A"), slide("Slide A", cursor=(300, 100)), slide("Slide B")
    assert hamming(dhash(a), dhash(a_cursor)) <= 4
    assert hamming(dhash(a), dhash(b)) > 10


def test_periodic_frames_of_same_slide_join_one_scene() -> None:
    tracker = SceneTracker([])
    for ts in (0.0, 10.0, 20.0):
        tracker.add_frame(Frame(ts=ts, jpeg_b64="", reason="periodic"), slide("Slide A"))
    tracker.add_frame(Frame(ts=25.0, jpeg_b64="", reason="diff"), slide("Slide B"))
    assert [len(s.frame_ids) for s in tracker.scenes] == [3, 1]
    assert tracker.scenes[0].last_ts == 20.0 and tracker.scenes[1].first_ts == 25.0


def test_utterance_near_page_change_links_both_pages(tmp_path: Path) -> None:
    session = MeetingSession()
    recorder = Recorder(session, tmp_path)
    frame_a = Frame(ts=0.0, jpeg_b64="", reason="manual")
    session.frames.append(frame_a)
    recorder.add_frame(frame_a, slide("Slide A"))
    recorder.add_utterance(id="u1", ts=5.0, speaker="我", text="A 頁中間")
    recorder.add_utterance(id="u2", ts=18.5, speaker="我", text="翻頁前最後一句")
    frame_b = Frame(ts=20.0, jpeg_b64="", reason="diff")
    session.frames.append(frame_b)
    recorder.add_frame(frame_b, slide("Slide B"))
    recorder.add_utterance(id="u3", ts=21.0, speaker="與會者", text="翻頁後第一句")
    recorder.add_utterance(id="u4", ts=40.0, speaker="與會者", text="B 頁中間")

    scene_a, scene_b = session.scenes
    by_id = {u.id: u for u in recorder.utterances}
    assert by_id["u1"].scene_id == scene_a.id and by_id["u1"].adjacent_scene_ids == []
    assert by_id["u2"].scene_id == scene_a.id and by_id["u2"].adjacent_scene_ids == [scene_b.id]
    assert by_id["u3"].scene_id == scene_b.id and by_id["u3"].adjacent_scene_ids == [scene_a.id]
    assert by_id["u4"].scene_id == scene_b.id and by_id["u4"].adjacent_scene_ids == []

    record = json.loads((tmp_path / session.id / "record.json").read_text("utf-8"))
    assert [s["seq"] for s in record["scenes"]] == [0, 1]
    assert (tmp_path / session.id / "frames" / f"{frame_a.id}.jpg").exists()

    # synthesis view: boundary utterances appear on both pages, marked also_in
    session.transcript = [
        TranscriptEntry(id=u.id, ts=u.ts, speaker=u.speaker, text=u.text)
        for u in recorder.utterances
    ]
    pages = build_pages(session, build_timeline(session))

    def texts(page: dict) -> list[tuple[str, int | None]]:
        return [(i["text"], i.get("also_in")) for i in page["items"]]

    assert texts(pages[0]) == [("A 頁中間", None), ("翻頁前最後一句", None), ("翻頁後第一句", 2)]
    assert texts(pages[1]) == [("翻頁前最後一句", 1), ("翻頁後第一句", None), ("B 頁中間", None)]


def test_session_and_report_survive_restart(tmp_path: Path) -> None:
    session = MeetingSession()
    recorder = Recorder(session, tmp_path)
    frame = Frame(ts=0.0, jpeg_b64="", reason="manual")
    session.frames.append(frame)
    recorder.add_frame(frame, slide("Slide A"))
    recorder.add_utterance(id="u1", ts=1.0, speaker="我", text="成本上限八百五")
    recorder.close()
    session.report = build_mock_report(session)
    session.report_model, session.report_mock = "mock", True
    save_report(tmp_path, session)

    restored = load_session(tmp_path, session.id)
    assert restored is not None
    assert [(u.speaker, u.text) for u in restored.transcript] == [("我", "成本上限八百五")]
    assert restored.frames[0].jpeg_b64 and restored.frames[0].scene_id == session.scenes[0].id
    assert restored.scenes[0].cover_frame_id == frame.id
    assert restored.report is not None and restored.report.scenes[0].seq == 0
    assert load_session(tmp_path, "nope") is None
