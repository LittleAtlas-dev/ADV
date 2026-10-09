"""Offline contract checks: never call paid generation APIs."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pinterest_services as api


def response(data, status=200):
    return Mock(ok=status < 400, status_code=status, json=Mock(return_value=data))


class HiggsfieldTests(unittest.TestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {'HF_API_KEY': 'test-key'})
        self.key.start()
        self.addCleanup(self.key.stop)

    @patch.object(api.time, 'sleep')
    @patch.object(api.requests, 'get')
    @patch.object(api.requests, 'post')
    def test_submit_poll_and_complete(self, post, get, sleep):
        post.return_value = response({'request_id': 'request-1'})
        get.side_effect = [response({'status': 'queued'}),
                           response({}, 429),
                           response({'status': 'completed', 'images': [{'url': 'https://example.com/pin.jpg'}]})]
        self.assertEqual(api.higgsfield_generate('test', aspect_ratio='2:3', what='Pin'), 'https://example.com/pin.jpg')
        post.assert_called_once()
        call = post.call_args
        self.assertEqual(call.args[0], 'https://api.higgsfield.ai/higgsfield-ai/soul/standard')
        self.assertEqual(call.kwargs['headers']['Authorization'], 'Key test-key')
        self.assertEqual(call.kwargs['json']['aspect_ratio'], '2:3')
        self.assertEqual(call.kwargs['json']['batch_size'], 1)
        self.assertEqual(get.call_count, 3)

    @patch.object(api.requests, 'get')
    @patch.object(api.requests, 'post')
    def test_terminal_failures(self, post, get):
        for status in ('failed', 'nsfw', 'canceled'):
            with self.subTest(status=status):
                post.return_value = response({'request_id': 'request-1'})
                get.return_value = response({'status': status})
                with self.assertRaisesRegex(RuntimeError, status):
                    api.higgsfield_generate('test', aspect_ratio='2:3', what='Pin')

    @patch.object(api.requests, 'post')
    def test_ambiguous_submission_is_not_retried(self, post):
        post.side_effect = api.requests.Timeout('timeout')
        with self.assertRaises(api.requests.Timeout):
            api.higgsfield_generate('test', aspect_ratio='2:3', what='Pin')
        post.assert_called_once()

    @patch.object(api.time, 'monotonic', side_effect=[0, 1201])
    @patch.object(api.requests, 'get')
    @patch.object(api.requests, 'post')
    def test_poll_timeout_does_not_resubmit(self, post, get, clock):
        post.return_value = response({'request_id': 'request-1'})
        with self.assertRaisesRegex(TimeoutError, 'may still be running'):
            api.higgsfield_generate('test', aspect_ratio='2:3', what='Pin')
        post.assert_called_once()
        get.assert_not_called()

    @patch.object(api.requests, 'get')
    @patch.object(api.requests, 'post')
    def test_missing_image_is_an_error(self, post, get):
        post.return_value = response({'request_id': 'request-1'})
        get.return_value = response({'status': 'completed', 'images': []})
        with self.assertRaisesRegex(RuntimeError, 'without an HTTPS image'):
            api.higgsfield_generate('test', aspect_ratio='2:3', what='Pin')


if __name__ == '__main__':
    unittest.main()
