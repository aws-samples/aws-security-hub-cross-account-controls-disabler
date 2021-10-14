import json
import pytest
import src.CheckResult.index as CheckResult


def test_lambda_handler():
    event_failed = {"processedItems": [{"statusCode": 500, "account": "acc_1", "error": "Reason"}]}
    event_success = {"processedItems": [{"statusCode": 200, "account": "acc_1"}]}
    expected_response_failed = {"statusCode": 500, "failed_accounts": {"acc_1": "Reason"}}
    expected_response_success = {"statusCode": 200}
    response_failed = CheckResult.lambda_handler(event_failed, {})
    assert expected_response_failed == response_failed
    response_success = CheckResult.lambda_handler(event_success, {})
    assert expected_response_success == response_success
