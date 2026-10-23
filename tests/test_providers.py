import unittest
from unittest import mock
from helpers import FakeAsk
from cocheck.providers.base import parse_answers
from cocheck.providers import build

T = [{'id': 'x-1', 'asks': [{'i': '0', 'k': 'el', 'q': '?'}]}, {'id': 'y-1', 'asks': [{'i': '0', 'k': 'el', 'q': '?'}]}]


class Retry(unittest.TestCase):
    def test_429_backoff_then_ok(self):
        p = FakeAsk(fail=2)
        with mock.patch('cocheck.providers.base.time.sleep') as sl:
            out = p.ask_batch(T[:1])
        self.assertEqual(out, {'x-1': {'0': 'yes'}})
        self.assertEqual([c.args[0] for c in sl.call_args_list], [4, 8])     # 429 指数退避

    def test_other_error_short_retry(self):
        p = FakeAsk(fail=1, err='connection reset')
        with mock.patch('cocheck.providers.base.time.sleep') as sl: p.ask_batch(T[:1])
        self.assertEqual(sl.call_args_list[0].args[0], 2)

    def test_give_up_leaves_ticket_open(self):
        p = FakeAsk(fail=99)
        with mock.patch('cocheck.providers.base.time.sleep'), mock.patch('builtins.print'):
            out = p.ask_batch(T, jobs=2)
        self.assertEqual(out, {}); self.assertEqual(p.calls, 10)


class Parse(unittest.TestCase):
    def test_parse_noisy(self):
        self.assertEqual(parse_answers('好的：```json\n{"0": "Yes", "1": "可能"}\n```'), {'0': 'yes', '1': 'unsure'})

    def test_unknown_type(self):
        with self.assertRaises(ValueError): build('x', {'type': 'nope'})


if __name__ == '__main__': unittest.main()
