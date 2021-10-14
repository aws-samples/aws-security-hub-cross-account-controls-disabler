#!/bin/python

import logging
import os
import time
from typing import List, Dict
import boto3
import botocore

from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_enabled_standard_subscriptions(standards, account_id, security_hub_client):
    """ return enabled standard in account_id """
    standards_subscription_arns_plain = [
        arn["StandardsArn"] for arn in standards["Standards"]
    ]
    standards_subscription_arns = [
        arn.replace(":::", "::" + account_id + ":").replace(
            ":" + os.environ["AWS_REGION"] + "::",
            ":" + os.environ["AWS_REGION"] + ":" + account_id + ":",
        )
        for arn in standards_subscription_arns_plain
    ]
    enabled_standards = security_hub_client.get_enabled_standards(
        StandardsSubscriptionArns=standards_subscription_arns
    )
    return enabled_standards


def get_controls(enabled_standards, security_hub_client):
    """ return list of controls for all aneabled standards """
    controls = dict()
    for standard in enabled_standards["StandardsSubscriptions"]:
        controls[
            standard["StandardsArn"]
        ] = security_hub_client.describe_standards_controls(
            StandardsSubscriptionArn=standard["StandardsSubscriptionArn"]
        )[
            "Controls"
        ]
    return controls


class SecurityStandardUpdateError(Exception):
    """ Error Class for failed security standard subscription update """

    pass


administrator_security_hub_client = None
sts_client = None
DISABLED_REASON = "Control disabled in the SecurityHub administrator account."
DISABLED = "DISABLED"
ENABLED = "ENABLED"


def lambda_handler(event, context):

    logger.info(event)

    try:
        # set variables and boto3 clients
        config = Config(
            retries = {
                'max_attempts': 23,
                'mode': 'standard'
                }
            )
        administrator_account_id = context.invoked_function_arn.split(":")[4]
        member_account_id = event["account"]

        role_arn = os.environ["MemberRole"].replace("<accountId>", member_account_id)
        global sts_client
        if not sts_client:
            sts_client = boto3.client("sts")
        assumed_role_object = sts_client.assume_role(
            RoleArn=role_arn, RoleSessionName="SecurityHubUpdater"
        )
        credentials = assumed_role_object["Credentials"]
        member_security_hub_client = boto3.client(
            "securityhub",
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            config=config,
        )

        # Optimization - no need to reinitilize the administrator security hub client for every instance of this Lambda function
        global administrator_security_hub_client
        if not administrator_security_hub_client:
            administrator_security_hub_client = boto3.client("securityhub", config=config)

        # Get standard subscription controls
        standards = administrator_security_hub_client.describe_standards()
        administrator_enabled_standards = get_enabled_standard_subscriptions(
            standards, administrator_account_id, administrator_security_hub_client
        )
        member_enabled_standards = get_enabled_standard_subscriptions(
            standards, member_account_id, member_security_hub_client
        )

        logger.info("Update Account %s", member_account_id)

        # Update standard subscriptions in member account
        standards_updated = update_standard_subscription(
            administrator_enabled_standards,
            member_enabled_standards,
            member_security_hub_client,
        )
        if standards_updated:
            logger.info("Fetch enabled standards again.")
            member_enabled_standards = get_enabled_standard_subscriptions(
                standards, member_account_id, member_security_hub_client
            )

        # Get Controls
        admin_controls = get_controls(
            administrator_enabled_standards, administrator_security_hub_client
        )
        member_controls = get_controls(
            member_enabled_standards, member_security_hub_client
        )

        # Get exceptions
        exceptions = get_exceptions(event)
        logger.debug("Exceptions: %s", str(exceptions))

        # Disable/enable the controls in member account
        update_member(
            admin_controls, member_controls, member_security_hub_client, exceptions
        )

    except botocore.exceptions.ClientError as error:
        logger.error(error)
        return {"statusCode": 500, "account": member_account_id, "error": str(error)}

    return {"statusCode": 200, "account": member_account_id}


def update_member(
    admin_controls, member_controls, member_security_hub_client, exceptions
):
    """
    Identifying which control needs to be updated
    """

    for admin_key in admin_controls:
        for member_key in member_controls:
            if admin_key == member_key:
                # Same security standard TODO
                for admin_control, member_control in zip(
                    admin_controls[admin_key], member_controls[member_key]
                ):
                    logger.info(admin_control)
                    logger.info(member_control)
                    # Check for exceptions first
                    if admin_control["ControlId"] in exceptions["Disabled"]:
                        if member_control["ControlStatus"] != DISABLED:
                            # Disable control in member account
                            update_control_status(
                                member_control,
                                member_security_hub_client,
                                DISABLED,
                                disabled_reason=exceptions["DisabledReason"][
                                    admin_control["ControlId"]
                                ],
                            )
                    elif admin_control["ControlId"] in exceptions["Enabled"]:
                        if member_control["ControlStatus"] != ENABLED:
                            # Enable control in member account
                            update_control_status(
                                member_control, member_security_hub_client, ENABLED
                            )
                    elif (
                        admin_control["ControlStatus"]
                        != member_control["ControlStatus"]
                    ):
                        # Update control in member account to reflect configuration in SecurityHub admin account
                        update_control_status(
                            member_control,
                            member_security_hub_client,
                            admin_control["ControlStatus"],
                        )


def update_control_status(member_control, client, new_status, disabled_reason=None):
    """
    Updates the Security Hub control as specified in the the security hub administrator account
    """
    if DISABLED == new_status:
        client.update_standards_control(
            StandardsControlArn=member_control["StandardsControlArn"],
            ControlStatus=new_status,
            DisabledReason=disabled_reason if disabled_reason else DISABLED_REASON,
        )
    else:
        # ENABLE control
        client.update_standards_control(
            StandardsControlArn=member_control["StandardsControlArn"],
            ControlStatus=new_status,
        )


def update_standard_subscription(
    administrator_enabled_standards, member_enabled_standards, client
):
    """
    Update security standards to reflect state in administrator account
    """
    admin_standard_arns = [
        standard["StandardsArn"]
        for standard in administrator_enabled_standards["StandardsSubscriptions"]
    ]
    member_standard_arns = [
        standard["StandardsArn"]
        for standard in member_enabled_standards["StandardsSubscriptions"]
    ]
    standards = client.describe_standards()["Standards"]
    standard_to_be_enabled = []
    standard_to_be_disabled = []

    for standard in standards:
        if (
            standard["StandardsArn"] in admin_standard_arns
            and standard["StandardsArn"] not in member_standard_arns
        ):
            # enable standard
            standard_to_be_enabled.append({"StandardsArn": standard["StandardsArn"]})
        if (
            standard["StandardsArn"] not in admin_standard_arns
            and standard["StandardsArn"] in member_standard_arns
        ):
            # disable standard
            for subscription in member_enabled_standards["StandardsSubscriptions"]:
                if (
                    subscription["StandardsArn"].split("/")[-3]
                    == standard["StandardsArn"].split("/")[-3]
                ):
                    standard_to_be_disabled.append(
                        subscription["StandardsSubscriptionArn"]
                    )

    standards_changed = False

    if len(standard_to_be_enabled) > 0:
        # enable standard
        logger.info("Enable standards: %s", str(standard_to_be_enabled))
        client.batch_enable_standards(
            StandardsSubscriptionRequests=standard_to_be_enabled
        )
        ready = False
        while not ready:
            response = client.get_enabled_standards()
            subscription_statuses = [
                subscription["StandardsStatus"]
                for subscription in response["StandardsSubscriptions"]
            ]
            ready = all(
                (status in ("READY", "INCOMPLETE") for status in subscription_statuses)
            )
            if not ready:
                if "FAILED" in subscription_statuses:
                    logger.error(
                        "Standard could not be enabled: %s",
                        str(response["StandardsSubscriptions"]),
                    )
                    raise SecurityStandardUpdateError(
                        "Security standard could not be enabled: "
                        + str(response["StandardsSubscriptions"])
                    )
            logger.info("Wait until standards are enabled...")
            time.sleep(1)
        if "INCOMPLETE" in subscription_statuses:
            logger.warning(
                "Standard could not be enabled completely. Some controls may not be available: %s",
                str(response["StandardsSubscriptions"]),
            )
        logger.info("Standards enabled")
        standards_changed = True

    if len(standard_to_be_disabled) > 0:
        # disable standard
        logger.info("Disable standards: %s", str(standard_to_be_disabled))
        client.batch_disable_standards(
            StandardsSubscriptionArns=standard_to_be_disabled
        )
        ready = False
        while not ready:
            response = client.get_enabled_standards()
            subscription_statuses = [
                subscription["StandardsStatus"]
                for subscription in response["StandardsSubscriptions"]
            ]
            ready = all(
                (status in ("READY", "INCOMPLETE") for status in subscription_statuses)
            )
            if not ready:
                if "FAILED" in subscription_statuses:
                    logger.error(
                        "Standard could not be disabled: %s",
                        str(response["StandardsSubscriptions"]),
                    )
                    raise SecurityStandardUpdateError(
                        "Security standard could not be disabled: "
                        + str(response["StandardsSubscriptions"])
                    )
            logger.info("Wait until standards are disabled...")
            time.sleep(1)
        if "INCOMPLETE" in subscription_statuses:
            logger.warning(
                "Standard could not be enabled completely. Some controls may not be available: %s",
                str(response["StandardsSubscriptions"]),
            )
        logger.info("Standards disabled")
        standards_changed = True
    return standards_changed


def get_exceptions(event):
    """
    extract exceptions related to the processed account from event. Return dictionary.
    """
    exceptions_dict = event["exceptions"]
    account_id = event["account"]
    exceptions = dict()
    exceptions["Disabled"] = []
    exceptions["Enabled"] = []
    exceptions["DisabledReason"] = dict()

    # Identify exceptions for this account
    for control in exceptions_dict.keys():
        disabled = False
        enabled = False

        try:
            if account_id in exceptions_dict[control]["Disabled"]:
                disabled = True
        except KeyError:
            logger.info('%s: No "Disabled" exceptions.', control)

        try:
            if account_id in exceptions_dict[control]["Enabled"]:
                enabled = True
        except KeyError:
            logger.info('%s: No "Enabled" exceptions.', control)

        try:
            exceptions["DisabledReason"][control] = exceptions_dict[control][
                "DisabledReason"
            ]
        except KeyError as error:
            logger.error('%s: No "DisabledReason".', control)
            raise error

        if enabled and disabled:
            # Conflict - you cannot enable and disable a control at the same time - fallback to default settin in administrator account
            logger.warning(
                "%s: Conflict - exception states that this control should be enabled AND disabled. Fallback to SecurityHub Administrator configuration.",
                control,
            )
        elif disabled:
            exceptions["Disabled"].append(control)
        elif enabled:
            exceptions["Enabled"].append(control)

    return exceptions
