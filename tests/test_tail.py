import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.tail import FileTail


class TailTests(unittest.TestCase):
    def test_file_initial_latest_append_partial_and_blank(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.txt"
            path.write_bytes(b"OLD\r\nLATEST\r\n")
            tail = FileTail(path)
            self.assertEqual(tail.poll(), "LATEST")
            self.assertIsNone(tail.poll())
            with path.open("ab") as stream:
                stream.write(b"PART")
            self.assertIsNone(tail.poll())
            with path.open("ab") as stream:
                stream.write(b"IAL\n")
            self.assertEqual(tail.poll(), "PARTIAL")
            with path.open("ab") as stream:
                stream.write(b"\n")
            self.assertEqual(tail.poll(), "")

    def test_truncation_rotation_and_latest_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.txt"
            path.write_bytes(b"FIRST\nSECOND\n")
            tail = FileTail(path)
            self.assertEqual(tail.poll(), "SECOND")
            path.write_bytes(b"NEW\n")
            self.assertEqual(tail.poll(), "NEW")
            other = Path(folder) / "replacement"
            other.write_bytes(b"ROTATED\n")
            other.replace(path)
            self.assertEqual(tail.poll(), "ROTATED")
            with path.open("ab") as stream:
                stream.write(b"SKIP\nLATEST\n")
            self.assertEqual(tail.poll(), "LATEST")

    def test_initial_unterminated_line_and_empty_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.txt"
            path.write_bytes(b"")
            tail = FileTail(path)
            self.assertEqual(tail.poll(), "")
            path.write_bytes(b"FIRST\nLAST")
            self.assertEqual(FileTail(path).poll(), "LAST")

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    @patch("ulanzi_tc002.client.cli.sys.stdin", new_callable=lambda: io.StringIO("\x1b[31mRED\x1b[0m\n\nEND"))
    def test_stdin_ansi_blank_and_eof(self, stdin, http_request, _config):
        http_request.return_value = {"accepted": True}
        main(["text", "tail", "-", "--ansi", "--color", "blue"])
        payloads = [call.kwargs["json_body"] for call in http_request.call_args_list]
        self.assertEqual([p["text"] for p in payloads], ["\x1b[31mRED\x1b[0m", "", "END"])
        self.assertTrue(all(p["ansi"] and p["color"] == "#82AAE8" for p in payloads))
