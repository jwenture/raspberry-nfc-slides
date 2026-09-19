import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TagInfo:
    uid: str
    name: str
    remote_path: str


class UnknownTagError(Exception):
    pass


class TagMapper:
    def __init__(self, tags_file: str | Path) -> None:
        self._tags_file = Path(tags_file)
        self._last_mtime: float = 0.0
        self._tags: dict[str, TagInfo] = {}
        self._load()

    def _load(self) -> None:
        with open(self._tags_file) as f:
            data = json.load(f)

        self._tags = {
            tag["uid"]: TagInfo(
                uid=tag["uid"],
                name=tag["name"],
                remote_path=tag["remote_path"],
            )
            for tag in data["tags"]
        }
        self._last_mtime = self._tags_file.stat().st_mtime
        logger.info("Loaded %d tags from %s", len(self._tags), self._tags_file)

    def lookup(self, uid: str) -> TagInfo:
        if uid not in self._tags:
            raise UnknownTagError(f"Unknown tag UID: {uid}")
        return self._tags[uid]

    def all_tags(self) -> list[TagInfo]:
        return list(self._tags.values())

    def maybe_reload(self) -> None:
        current_mtime = self._tags_file.stat().st_mtime
        if current_mtime != self._last_mtime:
            self._load()
            logger.info("Reloaded tags.json (mtime changed)")
