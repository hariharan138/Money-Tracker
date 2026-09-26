from pydantic import BaseModel, Field, field_validator, model_validator

from .expense import utcnow

MAX_NOTE_TEXT = 20_000
# A data URL this size is a ~2.2 MB image before base64 overhead -- several of
# these plus text still sits well under Mongo's 16 MB document limit.
MAX_NOTE_IMAGE_CHARS = 3_000_000
MAX_NOTE_IMAGES = 6


class NoteIn(BaseModel):
    """What the dashboard posts/puts for one note. Mirrors ProfileIn's
    data-URL-in-Mongo approach (see routes/profiles.py) rather than GridFS:
    notes are small and infrequent, so a plain document field is simpler and
    keeps everything in one query."""

    text: str = Field(default="", max_length=MAX_NOTE_TEXT)
    images: list[str] = Field(default_factory=list, max_length=MAX_NOTE_IMAGES)

    @field_validator("text", mode="before")
    @classmethod
    def _blank(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("images")
    @classmethod
    def _images_are_data_urls(cls, v):
        for image in v:
            if not isinstance(image, str) or not image.startswith("data:image/"):
                raise ValueError("each image must be an image data URL")
            if len(image) > MAX_NOTE_IMAGE_CHARS:
                raise ValueError("image too large")
        return v

    @model_validator(mode="after")
    def _not_empty(self):
        # An empty note is a client-side concept (discarded on the way out,
        # see app.js persistCurrentNote) -- reject it here too so a bug on
        # that side can't silently pile up blank documents.
        if not self.text and not self.images:
            raise ValueError("Note must have text or an image")
        return self


__all__ = ["NoteIn", "MAX_NOTE_TEXT", "MAX_NOTE_IMAGE_CHARS", "MAX_NOTE_IMAGES", "utcnow"]
