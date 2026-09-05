"""Follow the last line of a UTF-8 file without replaying its history."""
from pathlib import Path
import time


def decode_line(line):
    return line.removesuffix(b"\r").decode("utf-8-sig")


class FileTail:
    def __init__(self, path):
        self.path = Path(path)
        self.identity = None
        self.offset = 0
        self.anchor = b""
        self.pending = b""

    def poll(self):
        """Return the latest new line, or None when no complete line arrived."""
        with self.path.open("rb") as stream:
            import os
            stat = os.fstat(stream.fileno())
            identity = (stat.st_dev, stat.st_ino)
            reset = self.identity != identity or stat.st_size < self.offset
            if not reset and self.anchor:
                stream.seek(self.offset - len(self.anchor))
                reset = stream.read(len(self.anchor)) != self.anchor
            if reset:
                # Find the final line backwards, without loading the whole file.
                end = stat.st_size
                start, data = end, b""
                while start > 0 and data.rstrip(b"\n").count(b"\n") < 1:
                    size = min(4096, start)
                    start -= size
                    stream.seek(start)
                    data = stream.read(size) + data
                parts = data.split(b"\n")
                self.pending = parts[-1]
                line = parts[-2] if data.endswith(b"\n") else parts[-1]
                self.offset = end
                self.identity = identity
            else:
                stream.seek(self.offset)
                data = stream.read()
                self.offset = stream.tell()
                parts = (self.pending + data).split(b"\n")
                self.pending = parts[-1]
                line = parts[-2] if len(parts) > 1 else None
            stream.seek(max(0, self.offset - 64))
            self.anchor = stream.read(self.offset - stream.tell())
        return decode_line(line) if line is not None else None


def follow_file(path):
    follower = FileTail(path)
    while True:
        try:
            line = follower.poll()
        except FileNotFoundError:
            # A writer may temporarily remove a file during rotation.
            line = None
        if line is not None:
            yield line
        time.sleep(0.25)
