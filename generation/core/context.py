from typing import Any, Dict, List

from pydantic import BaseModel

from core.clients.s3 import does_file_exist


class Context(BaseModel):
    """One video of a run directory, and where each of its artifacts lives.

    `root` is the run directory as a storage key prefix: "" when the directory itself is the
    local storage root, "prefix/" on S3. Every artifact of the video sits below
    `{root}{folder}/`.
    """
    root: str = ""
    folder: str
    subject: str
    chapter: str
    title: str
    lessons: List[Dict[str, Any]] = []

    @property
    def key(self) -> str:
        return self.folder

    @property
    def base_path(self) -> str:
        return f"{self.root}{self.folder}/"

    @property
    def media_path(self) -> str:
        return f"{self.base_path}media/"

    def artifact_path(self, stage: str) -> str:
        """Where run.py saves a stage's JSON."""
        return f"{self.base_path}{stage}.json"

    def reviewed_path(self, stage: str) -> str:
        """A stage's JSON as downstream stages read it: a reviewer's -edited sidecar wins."""
        edited = f"{self.base_path}{stage}-edited.json"
        return edited if does_file_exist(edited) else self.artifact_path(stage)

    @property
    def video_plan_path(self) -> str:
        return self.reviewed_path("Video Plan")

    @property
    def transcripts_path(self) -> str:
        return self.reviewed_path("Video Transcript")

    @property
    def avatar_assets_path(self) -> str:
        return self.reviewed_path("Avatar Clips")

    @property
    def text_overlays_path(self) -> str:
        return self.reviewed_path("Text Overlays")

    @property
    def clips_path(self) -> str:
        return self.reviewed_path("Scenes Breakdown")
