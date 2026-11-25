import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

import requests

from tools.request_pr_review import main, request_review


class RequestPrReviewTest(unittest.TestCase):
    def test_temporary_api_failure_is_retried_without_changing_the_target(self):
        with patch("tools.request_pr_review.requests.post", side_effect=[
            Mock(status_code=503), Mock(status_code=201),
        ]) as post, patch("tools.request_pr_review.time.sleep") as sleep, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(request_review("litovle/usneseni-mesta", 87, "honza-kasik", "test-secret"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0], post.call_args_list[1])
        self.assertEqual(post.call_args.args[0], "https://api.github.com/repos/litovle/usneseni-mesta/pulls/87/requested_reviewers")
        self.assertEqual(post.call_args.kwargs["json"], {"reviewers": ["honza-kasik"]})
        sleep.assert_called_once_with(1)
        self.assertNotIn("test-secret", output.getvalue())

    def test_network_failures_are_bounded_and_reported_without_credentials(self):
        with patch("tools.request_pr_review.requests.post", side_effect=requests.Timeout("test-secret")) as post, \
                patch("tools.request_pr_review.time.sleep") as sleep, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(request_review("litovle/litovle.cz", 100, "honza-kasik", "test-secret"))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("::warning::", output.getvalue())
        self.assertIn("litovle/litovle.cz#100", output.getvalue())
        self.assertNotIn("test-secret", output.getvalue())

    def test_permanent_review_error_is_not_retried(self):
        for status in (401, 403, 422):
            with self.subTest(status=status), \
                    patch("tools.request_pr_review.requests.post", return_value=Mock(status_code=status)) as post, \
                    patch("tools.request_pr_review.time.sleep") as sleep, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(request_review("litovle/usneseni-mesta", 87, "honza-kasik", "test-secret"))
            post.assert_called_once()
            sleep.assert_not_called()
            self.assertIn(f"HTTP {status}", output.getvalue())

    def test_no_created_pr_skips_review_without_requiring_a_token(self):
        with patch.dict(os.environ, {}, clear=True), patch("tools.request_pr_review.requests.post") as post:
            self.assertEqual(main(["--repo", "litovle/usneseni-mesta", "--number", "", "--reviewer", "honza-kasik"]), 0)
        post.assert_not_called()

    def test_failed_review_returns_nonzero_for_the_optional_workflow_step(self):
        with patch.dict(os.environ, {"GH_TOKEN": "test-secret"}), \
                patch("tools.request_pr_review.requests.post", return_value=Mock(status_code=422)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--repo", "litovle/litovle.cz", "--number", "100", "--reviewer", "honza-kasik"]), 1)
        self.assertIn("::warning::", output.getvalue())

    def test_missing_token_is_an_explicit_warning(self):
        with patch.dict(os.environ, {}, clear=True), patch("tools.request_pr_review.requests.post") as post, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--repo", "litovle/litovle.cz", "--number", "100", "--reviewer", "honza-kasik"]), 1)
        post.assert_not_called()
        self.assertIn("without GH_TOKEN", output.getvalue())


if __name__ == "__main__":
    unittest.main()
