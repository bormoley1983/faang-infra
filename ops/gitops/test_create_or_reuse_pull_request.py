import io
import json
import unittest
from unittest.mock import patch

from create_or_reuse_pull_request import PullRequestError, create_or_reuse_pull_request


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode("utf-8"))

    def __exit__(self, _error_type, _error, _traceback):
        return None


class PullRequestTests(unittest.TestCase):
    @patch("create_or_reuse_pull_request.urllib.request.urlopen")
    def test_reuses_exact_open_pull_request(self, urlopen) -> None:
        urlopen.return_value = _Response([{"html_url": "https://example.test/pull/1"}])

        url, created = create_or_reuse_pull_request("owner/repo", "owner", "token")

        self.assertFalse(created)
        self.assertEqual("https://example.test/pull/1", url)
        request = urlopen.call_args.args[0]
        self.assertEqual("GET", request.method)
        self.assertIn("head=owner%3Agitops%2Fpromotions", request.full_url)
        self.assertNotIn("token", request.full_url)

    @patch("create_or_reuse_pull_request.urllib.request.urlopen")
    def test_creates_pull_request_when_none_is_open(self, urlopen) -> None:
        urlopen.side_effect = [
            _Response([]),
            _Response({"html_url": "https://example.test/pull/2"}),
        ]

        url, created = create_or_reuse_pull_request("owner/repo", "owner", "token")

        self.assertTrue(created)
        self.assertEqual("https://example.test/pull/2", url)
        create_request = urlopen.call_args_list[1].args[0]
        self.assertEqual("POST", create_request.method)
        payload = json.loads(create_request.data)
        self.assertEqual("gitops/promotions", payload["head"])
        self.assertEqual("dev-local", payload["base"])

    @patch("create_or_reuse_pull_request.urllib.request.urlopen")
    def test_rejects_ambiguous_open_pull_requests(self, urlopen) -> None:
        urlopen.return_value = _Response(
            [
                {"html_url": "https://example.test/pull/1"},
                {"html_url": "https://example.test/pull/2"},
            ]
        )

        with self.assertRaises(PullRequestError):
            create_or_reuse_pull_request("owner/repo", "owner", "token")

    def test_rejects_missing_token_before_network_access(self) -> None:
        with self.assertRaises(PullRequestError):
            create_or_reuse_pull_request("owner/repo", "owner", "")


if __name__ == "__main__":
    unittest.main()
