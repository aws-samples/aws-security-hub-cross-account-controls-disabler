#!/bin/python

import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
DISABLED_REASON = "Exception"
securityhub_client = None
organizations_client = None
dynamodb_client = None


def lambda_handler(event, context):

    # print(event)
    # get a list of all member accounts

    # Optimization - no need to reinitilize the  security hub client for every instance of this Lambda function
    global securityhub_client
    if not securityhub_client:
        securityhub_client = boto3.client("securityhub")

    global organizations_client
    if not organizations_client:
        organizations_client = boto3.client("organizations")

    global dynamodb_client
    if not dynamodb_client:
        dynamodb_client = boto3.client("dynamodb")

    member_accounts = get_members(securityhub_client)
    active_accounts = get_active_accounts(organizations_client)

    # Filter out suspended accounts from list of Security Hub member accounts.
    # This is for robustness because Security Hub shows suspended member accounts as 'Enabled"
    # when it was suspended without being removed from Security Hub administrator account.
    member_accounts = list(set(member_accounts).intersection(active_accounts))

    response = dynamodb_client.scan(TableName=os.environ["DynamoDB"])
    exceptions = convert_exceptions(response)

    return {
        "statusCode": 200,
        "accounts": member_accounts,
        "exceptions": exceptions,
    }


def convert_exceptions(response):
    """
    Convert exceptions from DynamoDB into simpler dictionary format
    """
    exceptions = dict()
    for control in response["Items"]:
        exceptions[control["ControlId"]["S"]] = dict()

        try:
            exceptions[control["ControlId"]["S"]]["Disabled"] = [
                entry["S"] for entry in control["Disabled"]["L"]
            ]
        except KeyError:
            logger.info('%s: No "Disabled" exceptions', control["ControlId"]["S"])
            exceptions[control["ControlId"]["S"]]["Disabled"] = []

        try:
            exceptions[control["ControlId"]["S"]]["Enabled"] = [
                entry["S"] for entry in control["Enabled"]["L"]
            ]
        except KeyError:
            logger.info('%s: No "Enabled" exceptions', control["ControlId"]["S"])
            exceptions[control["ControlId"]["S"]]["Enabled"] = []

        try:
            if control["DisabledReason"]["S"] != "":
                exceptions[control["ControlId"]["S"]]["DisabledReason"] = control[
                    "DisabledReason"
                ]["S"]
            else:
                logger.info(
                    '%s: No "DisabledReason". Replace by "%s"',
                    control["ControlId"]["S"],
                    DISABLED_REASON,
                )
                exceptions[control["ControlId"]["S"]][
                    "DisabledReason"
                ] = DISABLED_REASON
        except KeyError:
            logger.info(
                '%s: No "DisabledReason". Replace by "%s"',
                control["ControlId"]["S"],
                DISABLED_REASON,
            )
            exceptions[control["ControlId"]["S"]]["DisabledReason"] = DISABLED_REASON

    return exceptions


def get_members(client):
    """
    Use pagination to fetch list of member accounts
    """
    response = client.list_members()
    members = []
    while response:
        members += response["Members"]
        if "NextToken" in response:
            response = client.list_members(NextToken=response["NextToken"])
        else:
            response = None

    accounts = []
    for member in members:
        accounts.append(member["AccountId"])
    # print(accounts)
    return accounts

def get_active_accounts(client):
    """
    Use pagination to fetch list of Organizations member accounts and return list of active(not suspended) accounts
    """
    response = client.list_accounts()
    active_members = []

    while response:
        for account in response["Accounts"]:
            if account["Status"] == "ACTIVE":
                active_members.append(account["Id"])

        if "NextToken" in response:
            response = client.list_accounts(NextToken=response["NextToken"])
        else:
            response = None

    return active_members
