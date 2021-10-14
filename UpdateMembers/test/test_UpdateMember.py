import json
import pytest
import src.UpdateMember.index as UpdateMember
from unittest.mock import patch, MagicMock
import logging
import botocore

logger = logging.getLogger()


def test_get_exceptions():
    event = json.loads('{ "account": "acc_id_1", "exceptions": { "CIS.1.1": { "Disabled": [ "acc_id_1" ], "Enabled": [], "DisabledReason": "Some_Reason"}, "CIS.1.2": { "Disabled": [], "Enabled": [ "acc_id_1" ] , "DisabledReason": "Exception"}, "CIS.1.3": { "Disabled": [ "acc_id_1" ], "Enabled": [ "acc_id_1" ], "DisabledReason": "Exception" }, "CIS.1.4": { "Disabled": [ "acc_id_1" ], "Enabled": [], "DisabledReason": "Exception" }}}')
    expected_response = {"Disabled": ["CIS.1.1", "CIS.1.4"], "Enabled": ["CIS.1.2"], "DisabledReason": {"CIS.1.1": "Some_Reason", "CIS.1.2": "Exception", "CIS.1.3": "Exception", "CIS.1.4": "Exception"}}
    response = UpdateMember.get_exceptions(event)
    assert expected_response == response

    event_missing_disabled_reason = json.loads('{ "account": "acc_id_1", "exceptions": { "CIS.1.1": { "Disabled": [ "acc_id_1" ], "Enabled": [], "DisabledReason": "Some_Reason"}, "CIS.1.2": { "Disabled": [], "Enabled": [ "acc_id_1" ] , "DisabledReason": "Exception"}, "CIS.1.3": { "Disabled": [ "acc_id_1" ], "Enabled": [ "acc_id_1" ], "DisabledReason": "Exception" }, "CIS.1.4": { "Disabled": [ "acc_id_1" ], "Enabled": [], "DisabledReason": "Exception" }, "CIS.1.5": {} }}')
    with pytest.raises(KeyError):
        UpdateMember.get_exceptions(event_missing_disabled_reason)


@patch("src.UpdateMember.index.boto3")
@patch("src.UpdateMember.index.os")
@patch("src.UpdateMember.index.get_enabled_standard_subscriptions")
def test_lambda_handler_success(get_enabled_standard_subscriptions, boto3, os):
    """
    Test assuming no security standards are enabled in SecurityHub Administrator. Only running bare minimum of lambda handler. Runs successfully.
    """
    event = json.loads('{ "account": "acc_1", "exceptions": { "CIS.1.1": { "Disabled": [ "acc_1" ], "Enabled": [], "DisabledReason": "Some_Reason" }, "CIS.1.2": { "Disabled": [], "Enabled": [ "acc_1" ], "DisabledReason": "Exception" }, "CIS.1.4": { "Disabled": [ "acc_1" ], "Enabled": [], "DisabledReason": "Exception" }, "CIS.1.3": { "Disabled": [], "Enabled": [ "acc_1" ], "DisabledReason": "Exception" }, "CIS.1.5": { "Disabled": [], "Enabled": [], "DisabledReason": "Exception" } } }')
    context = MagicMock(return_value="admin_acc")
    expected_response_success = {"statusCode": 200, "account": "acc_1"}
    with patch.object(UpdateMember, "update_standard_subscription", return_value=True):
        response = UpdateMember.lambda_handler(event, context)
    assert get_enabled_standard_subscriptions.call_count == 3
    assert response == expected_response_success


@patch("src.UpdateMember.index.os")
@patch("src.UpdateMember.index.boto3")
def test_lambda_handler_fail(boto3, os):
    """
    Test assuming no security standards are enabled in SecurityHub Administrator. Only running bare minimum of lambda handler. Raises error.
    """
    event = json.loads('{ "account": "acc_1", "exceptions": { "CIS.1.1": { "Disabled": [ "acc_1" ], "Enabled": [], "DisabledReason": "Some_Reason" }, "CIS.1.2": { "Disabled": [], "Enabled": [ "acc_1" ], "DisabledReason": "Exception" }, "CIS.1.4": { "Disabled": [ "acc_1" ], "Enabled": [], "DisabledReason": "Exception" }, "CIS.1.3": { "Disabled": [], "Enabled": [ "acc_1" ], "DisabledReason": "Exception" }, "CIS.1.5": { "Disabled": [], "Enabled": [], "DisabledReason": "Exception" } } }')
    error_message = "SomeClientError"
    operation = "SomeOperation"
    error = MagicMock()
    error.get.return_value.get.return_value = error_message
    boto3.client = MagicMock(side_effect=botocore.exceptions.ClientError(error, operation))
    context = MagicMock(return_value="admin_acc")
    expected_response_fail = {"statusCode": 500, "account": "acc_1", "error": "An error occurred (" + error_message + ") when calling the " + operation + " operation: " + error_message}
    response = UpdateMember.lambda_handler(event, context)
    assert response == expected_response_fail


@patch("src.UpdateMember.index.os")
def test_get_enabled_standard_subscriptions(os):
    os.environ = {"AWS_REGION": "us-west-1"}
    client = MagicMock()
    account_id = "acc_id"
    standards = {'Standards': [{'StandardsArn': 'arn:aws:securityhub:us-west-1::standard/aws-foundational-security-best-practices/v/1.0', 'Name': 'name', 'Description': 'description', 'EnabledByDefault': True}], 'NextToken': 'string'}
    subscription_arns = ["arn:aws:securityhub:us-west-1:acc_id:standard/aws-foundational-security-best-practices/v/1.0"]
    UpdateMember.get_enabled_standard_subscriptions(standards, account_id, client)
    client.get_enabled_standards.assert_called_with(StandardsSubscriptionArns=subscription_arns)


@patch("src.UpdateMember.index.update_control_status")
def test_update_member_exception_disabled(update_control_status):
    """
    Top level for loop identifying which control needs to be updated. Exceptionally disable control.
    """
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    client = MagicMock()
    admin_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": ENABLED, "ControlId": "CIS.1.1"}]}
    member_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": ENABLED, "ControlId": "CIS.1.1"}]}
    exceptions = {"Disabled": ["CIS.1.1"], "Enabled": [], "DisabledReason": {"CIS.1.1": "SomeReason"}}

    UpdateMember.update_member(admin_controls, member_controls, client, exceptions)
    update_control_status.assert_called_once_with(member_controls["standard_1"][0], client, DISABLED, disabled_reason=exceptions["DisabledReason"]["CIS.1.1"])


@patch("src.UpdateMember.index.update_control_status")
def test_update_member_exception_enabled(update_control_status):
    """
    Top level for loop identifying which control needs to be updated. Exceptionally enable control.
    """
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    client = MagicMock()
    admin_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": DISABLED, "ControlId": "CIS.1.1"}]}
    member_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": DISABLED, "ControlId": "CIS.1.1"}]}
    exceptions = {"Disabled": [], "Enabled": ["CIS.1.1"], "DisabledReason": {}}

    UpdateMember.update_member(admin_controls, member_controls, client, exceptions)
    update_control_status.assert_called_once_with(member_controls["standard_1"][0], client, ENABLED)


@patch("src.UpdateMember.index.update_control_status")
def test_update_member_regular(update_control_status):
    """
    Top level for loop identifying which control needs to be updated without exception.
    """
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    client = MagicMock()
    admin_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": DISABLED, "ControlId": "CIS.1.1"}]}
    member_controls = {"standard_1": [{"StandardsControlArn": "cis_1_1_arn", "ControlStatus": ENABLED, "ControlId": "CIS.1.1"}]}
    exceptions = {"Disabled": [], "Enabled": [], "DisabledReason": {}}

    UpdateMember.update_member(admin_controls, member_controls, client, exceptions)
    update_control_status.assert_called_once_with(member_controls["standard_1"][0], client, DISABLED)


def test_update_standard_subscription_enable():
    """
    Enable standard control
    """
    administrator_enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "standard_1"}]}
    administrator_enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "standard_1"}]}
    member_enabled_standards_none = {"StandardsSubscriptions": []}
    client = MagicMock()

    attrs = {
        'describe_standards.return_value': {"Standards": [{"StandardsArn": "standard_1"}]},
        'get_enabled_standards.return_value': {"StandardsSubscriptions": [{"StandardsStatus": "INCOMPLETE"}]},
    }
    client.configure_mock(**attrs)

    standards_changed = UpdateMember.update_standard_subscription(administrator_enabled_standards, member_enabled_standards_none, client)
    assert standards_changed


def test_update_standard_subscription_enable_fail():
    """
    Fail enabling standard control
    """
    administrator_enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "standard_1"}]}
    member_enabled_standards_none = {"StandardsSubscriptions": []}
    client = MagicMock()

    # Failed standards update
    attrs = {
        'describe_standards.return_value': {"Standards": [{"StandardsArn": "standard_1"}]},
        'get_enabled_standards.return_value': {"StandardsSubscriptions": [{"StandardsStatus": "FAILED"}, {"StandardsStatus": "READY"}]},
    }
    client.configure_mock(**attrs)

    with pytest.raises(UpdateMember.SecurityStandardUpdateError):
        UpdateMember.update_standard_subscription(administrator_enabled_standards, member_enabled_standards_none, client)


def test_update_standard_subscription_disable():
    """
    Disable standard control
    """
    administrator_enabled_standards_none = {"StandardsSubscriptions": []}
    member_enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "arn:aws:securityhub:us-west-1:acc_id:standard/aws-foundational-security-best-practices/v/1.0", "StandardsSubscriptionArn": "arn:aws:securityhub:us-west-1:acc_id:subscription/aws-foundational-security-best-practices/v/1.0"}]}
    client = MagicMock()

    attrs = {
        'describe_standards.return_value': {"Standards": [{"StandardsArn": "arn:aws:securityhub:us-west-1:acc_id:standard/aws-foundational-security-best-practices/v/1.0"}]},
        'get_enabled_standards.return_value': {"StandardsSubscriptions": [{"StandardsStatus": "INCOMPLETE"}]},
    }
    client.configure_mock(**attrs)

    standards_changed = UpdateMember.update_standard_subscription(administrator_enabled_standards_none, member_enabled_standards, client)
    assert standards_changed


def test_update_standard_subscription_disable_fail():
    """
    Fail disabling standard control
    """
    administrator_enabled_standards_none = {"StandardsSubscriptions": []}
    member_enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "arn:aws:securityhub:us-west-1:acc_id:standard/aws-foundational-security-best-practices/v/1.0", "StandardsSubscriptionArn": "arn:aws:securityhub:us-west-1:acc_id:subscription/aws-foundational-security-best-practices/v/1.0"}]}
    client = MagicMock()

    attrs = {
        'describe_standards.return_value': {"Standards": [{"StandardsArn": "arn:aws:securityhub:us-west-1:acc_id:standard/aws-foundational-security-best-practices/v/1.0"}]},
        'get_enabled_standards.return_value': {"StandardsSubscriptions": [{"StandardsStatus": "FAILED"}, {"StandardsStatus": "READY"}]},
    }
    client.configure_mock(**attrs)

    with pytest.raises(UpdateMember.SecurityStandardUpdateError):
        UpdateMember.update_standard_subscription(administrator_enabled_standards_none, member_enabled_standards, client)


def test_update_control_status():
    member_control = {"StandardsControlArn": "Arn"}
    client = MagicMock()
    disabled_reason = "Some_Reason"

    new_status = "DISABLED"
    UpdateMember.update_control_status(member_control, client, new_status, disabled_reason)
    client.update_standards_control.assert_called_with(StandardsControlArn="Arn", ControlStatus=new_status, DisabledReason="Some_Reason")
    UpdateMember.update_control_status(member_control, client, new_status)
    client.update_standards_control.assert_called_with(StandardsControlArn="Arn", ControlStatus=new_status, DisabledReason=UpdateMember.DISABLED_REASON)

    new_status = "ENABLED"
    UpdateMember.update_control_status(member_control, client, new_status, disabled_reason)
    client.update_standards_control.assert_called_with(StandardsControlArn="Arn", ControlStatus=new_status)


def test_get_controls():
    enabled_standards = {"StandardsSubscriptions": [{"StandardsArn": "arn", "StandardsSubscriptionArn": "arn"}]}
    control = {'StandardsControlArn': 'string', 'ControlStatus': 'ENABLED', 'DisabledReason': 'string', 'ControlStatusUpdatedAt': "date", 'ControlId': 'string', 'Title': 'string', 'Description': 'string', 'RemediationUrl': 'string', 'SeverityRating': 'LOW', 'RelatedRequirements': ['string']}
    client = MagicMock()
    client.describe_standards_controls.return_value = {"Controls": [control]}
    expected_response = {"arn": [control]}
    response = UpdateMember.get_controls(enabled_standards, client)
    assert response == expected_response
