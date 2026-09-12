import logging

from core.logger import Logger
from core.constants import DDB_TABLE_NAME
from core.aws import get_session

from tenacity import retry, wait_exponential, stop_after_attempt
from boto3.dynamodb.conditions import Key
from decimal import Decimal


logger = Logger("DdbUtility", logging.DEBUG)


def get_ddb_resource():
    session = get_session()
    return session.resource("dynamodb")


def get_ddb_table():
    ddb = get_ddb_resource()
    return ddb.Table(DDB_TABLE_NAME)


def get_item(pk, sk):
    table = get_ddb_table()
    response = table.get_item(
        Key={
            'pk': pk,
            'sk': sk
        }
    )
    if "Item" in response:
        return response["Item"]
    raise Exception(f"No records found for pk: {pk}, sk: {sk}")


def fetch_item(pk, sk):
    table = get_ddb_table()
    response = table.get_item(
        Key={
            'pk': pk,
            'sk': sk
        }
    )
    if "Item" in response:
        return response["Item"]
    return None


def get_items_starting_with(pk, sk_start):
    table = get_ddb_table()
    response = table.query(
        KeyConditionExpression=Key('pk').eq(pk) & Key('sk').begins_with(sk_start)
    )
    if "Items" in response:
        return response["Items"]
    raise Exception(f"No records found for pk: {pk}, sk starting with: {sk_start}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def delete_item(pk, sk):
    try:
        table = get_ddb_table()
        table.delete_item(
            Key={
                'pk': pk,
                'sk': sk
            }
        )
    except Exception as error:
        logger.log_error(f"Failed to delete item from DDB. Error: {error}")
        raise


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def put_item(pk, sk, data):
    item = {
        "pk": pk,
        "sk": sk
    }
    item.update(data)
    try:
        table = get_ddb_table()
        table.put_item(Item=item)
    except Exception as error:
        logger.log_error(f"Failed to put item to DDB. Error: {error}")
        raise


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def incrby(key, field, incr_val):
    try:
        table = get_ddb_table()
        table.update_item(
            Key=key,
            ExpressionAttributeNames={
                '#F': field,
            },
            ExpressionAttributeValues={
                ':inc': Decimal(str(incr_val)),
            },
            UpdateExpression='ADD #F :inc',
            ReturnValues='UPDATED_NEW',
        )
    except Exception as e:
        logger.log_error(f"Failed to update DDb Record: {e}")
        raise
