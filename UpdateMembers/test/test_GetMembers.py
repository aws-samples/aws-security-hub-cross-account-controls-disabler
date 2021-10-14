import json
import pytest
import src.GetMembers.index as GetMembers


def test_convert_exceptions():
    dynamodb_response = json.loads('{"Items": [{"ControlId": {"S": "CIS.1.1"}, "Disabled": {"L": [{"S": "111111111111"}]}, "Enabled": {"L": []}, "DisabledReason": {"S": "Some_Reason"}}, {"Disabled": {"L": []}, "ControlId": {"S": "CIS.1.2"}, "Enabled": {"L": [{"S": "22222222222"}]}}, {"Disabled": {"L": [{"S": "111111111111"}]}, "ControlId": {"S": "CIS.1.4"}}, {"ControlId": {"S": "CIS.1.3"}, "Enabled": {"L": [{"S": "22222222222"}]}, "DisabledReason": {"S": ""}}, {"ControlId": {"S": "CIS.1.5"}}]}')
    expected_response = {"CIS.1.1": {"Disabled": ["111111111111"], "Enabled": [], "DisabledReason": "Some_Reason"}, "CIS.1.2": {"Disabled": [], "Enabled": ["22222222222"], "DisabledReason": GetMembers.DISABLED_REASON}, "CIS.1.3": {"Disabled": [], "Enabled": ["22222222222"], "DisabledReason": GetMembers.DISABLED_REASON}, "CIS.1.4": {"Disabled": ["111111111111"], "Enabled": [], "DisabledReason": GetMembers.DISABLED_REASON}, "CIS.1.5": {"Disabled": [], "Enabled": [], "DisabledReason": GetMembers.DISABLED_REASON}}
    response = GetMembers.convert_exceptions(dynamodb_response)
    assert expected_response == response
