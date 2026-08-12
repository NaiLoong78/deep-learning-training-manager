import asyncio
import unittest

from app.process_manager import decode_output, iter_output_records, split_output_records


class LogEncodingTests(unittest.TestCase):
    def test_utf8_chinese_output(self):
        message = "开始训练：模型 VGG16"
        self.assertEqual(decode_output(message.encode("utf-8")), message)

    def test_gb18030_chinese_output(self):
        message = "训练完成，准确率 95%"
        self.assertEqual(decode_output(message.encode("gb18030")), message)

    def test_progress_updates_split_on_carriage_returns(self):
        records, remainder = split_output_records(b"0%\r10%\r20%\n")
        self.assertEqual(records, [b"0%", b"10%", b"20%"])
        self.assertEqual(remainder, b"")

    def test_partial_line_is_kept_for_the_next_chunk(self):
        records, remainder = split_output_records(b"Epoch 1")
        self.assertEqual(records, [])
        self.assertEqual(remainder, b"Epoch 1")


class AsyncLogReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_tqdm_stream_does_not_hit_readline_limit(self):
        stream = asyncio.StreamReader(limit=64)
        expected = [f"step {index}".encode() for index in range(1000)]
        stream.feed_data(b"\r".join(expected) + b"\r")
        stream.feed_eof()

        actual = [record async for record in iter_output_records(stream)]

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
