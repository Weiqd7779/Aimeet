"""Group shared-screen frames into scenes ("the page that was on screen").

Frames arrive whenever the picture changes or every ~10 s, so one slide yields several
frames. A perceptual difference-hash (dHash, 64 bit) puts frames that look alike into the
same scene; a large hamming distance opens a new one. Scenes are the coarse index that
every utterance is attached to - unlike anchors, no one has to point at anything.

Page boundaries are deliberately fuzzy: an utterance that starts within ADJACENT_SECONDS
of a scene change is also linked to the neighbouring scene, because people usually start
talking about the next slide before (or after) it actually appears.
"""

import io

from PIL import Image

from app.models import Frame, Scene

HASH_SIZE = 8
NEW_SCENE_DISTANCE = 10  # hamming bits out of 64; slides differ by ~25+, cursor moves by ~2
FLICKER_SECONDS = 3.0  # a scene shorter than this that returns to the previous look is merged
ADJACENT_SECONDS = 4.0


def dhash(jpeg_bytes: bytes) -> int:
    image = (
        Image.open(io.BytesIO(jpeg_bytes))
        .convert("L")
        .resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS)
    )
    pixels = list(image.tobytes())
    bits = 0
    for row in range(HASH_SIZE):
        for col in range(HASH_SIZE):
            left = pixels[row * (HASH_SIZE + 1) + col]
            right = pixels[row * (HASH_SIZE + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class SceneTracker:
    def __init__(self, scenes: list[Scene]) -> None:
        self.scenes = scenes  # shared with MeetingSession.scenes

    @property
    def current(self) -> Scene | None:
        return self.scenes[-1] if self.scenes else None

    def add_frame(self, frame: Frame, jpeg_bytes: bytes) -> Scene:
        frame_hash = dhash(jpeg_bytes)
        current = self.current
        if current and hamming(current.hash, frame_hash) <= NEW_SCENE_DISTANCE:
            scene = current
        elif (
            len(self.scenes) >= 2
            and current
            and current.last_ts - current.first_ts < FLICKER_SECONDS
            and hamming(self.scenes[-2].hash, frame_hash) <= NEW_SCENE_DISTANCE
        ):
            # Brief popup / alt-tab: fold the flicker back into the scene before it.
            flicker = self.scenes.pop()
            scene = self.scenes[-1]
            scene.frame_ids.extend(flicker.frame_ids)
        else:
            scene = Scene(
                seq=len(self.scenes),
                first_ts=frame.ts,
                last_ts=frame.ts,
                cover_frame_id=frame.id,
                hash=frame_hash,
            )
            self.scenes.append(scene)
        scene.frame_ids.append(frame.id)
        scene.last_ts = max(scene.last_ts, frame.ts)
        frame.scene_id = scene.id
        return scene

    def scene_at(self, ts: float) -> Scene | None:
        """Scene on screen at `ts`: the last one that started at or before it.
        Lag between speech and the page actually changing is handled by `adjacent`."""
        active = None
        for scene in self.scenes:
            if scene.first_ts <= ts:
                active = scene
            else:
                break
        return active or (self.scenes[0] if self.scenes else None)

    def adjacent(self, ts: float, main: Scene | None) -> list[str]:
        if not main:
            return []
        index = self.scenes.index(main)
        neighbours: list[str] = []
        if index > 0 and ts - main.first_ts <= ADJACENT_SECONDS:
            neighbours.append(self.scenes[index - 1].id)
        if (
            index + 1 < len(self.scenes)
            and self.scenes[index + 1].first_ts - ts <= ADJACENT_SECONDS
        ):
            neighbours.append(self.scenes[index + 1].id)
        return neighbours
