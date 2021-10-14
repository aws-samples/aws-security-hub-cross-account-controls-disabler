#!/bin/python


def lambda_handler(event, context):
    result = {}
    failed = False
    for execution in event["processedItems"]:
        if execution["statusCode"] == 500:
            failed = True
            result[execution["account"]] = execution["error"]

    if failed:
        return {"statusCode": 500, "failed_accounts": result}

    return {"statusCode": 200}
