#!/usr/bin/env bash
# Creates exactly the resources Terraform will create later, with the same names (DESIGN.md
# section 10). Keep the two in sync. LocalStack state is in-memory, so this runs on every start.
set -euo pipefail

REGION=us-east-1
ACCT=000000000000
BUS=retail-events

awslocal events create-event-bus --name "$BUS" >/dev/null

mk_queue() {  # $1 = queue name; creates "<name>-dlq" first, then the queue redriving to it
  local dlq_url dlq_arn
  dlq_url=$(awslocal sqs create-queue --queue-name "$1-dlq" \
    --attributes MessageRetentionPeriod=1209600 --query QueueUrl --output text)
  dlq_arn=$(awslocal sqs get-queue-attributes --queue-url "$dlq_url" \
    --attribute-names QueueArn --query Attributes.QueueArn --output text)
  awslocal sqs create-queue --queue-name "$1" --attributes \
    "{\"VisibilityTimeout\":\"60\",\"ReceiveMessageWaitTimeSeconds\":\"20\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$dlq_arn\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}" \
    >/dev/null
}

route() {  # $1 = rule, $2 = queue, $3 = JSON array of detail-types
  mk_queue "$2"
  awslocal events put-rule --event-bus-name "$BUS" --name "$1" \
    --event-pattern "{\"detail-type\":$3}" >/dev/null
  awslocal events put-targets --event-bus-name "$BUS" --rule "$1" \
    --targets "Id=1,Arn=arn:aws:sqs:$REGION:$ACCT:$2" >/dev/null
}

route to-inventory    inventory-order-events '["OrderCreated"]'
route to-order        order-inventory-events '["InventoryReserved","InventoryFailed"]'
route to-notification notification-events    '["InventoryReserved","InventoryFailed","OrderStatusUpdated"]'

awslocal dynamodb create-table --table-name inventory \
  --attribute-definitions AttributeName=sku,AttributeType=S \
  --key-schema AttributeName=sku,KeyType=HASH --billing-mode PAY_PER_REQUEST >/dev/null
awslocal dynamodb create-table --table-name inventory_reservations \
  --attribute-definitions AttributeName=order_id,AttributeType=S \
  --key-schema AttributeName=order_id,KeyType=HASH --billing-mode PAY_PER_REQUEST >/dev/null
awslocal dynamodb create-table --table-name notifications \
  --attribute-definitions AttributeName=order_id,AttributeType=S AttributeName=event_id,AttributeType=S \
  --key-schema AttributeName=order_id,KeyType=HASH AttributeName=event_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST >/dev/null
for table in inventory_reservations notifications; do
  awslocal dynamodb update-time-to-live --table-name "$table" \
    --time-to-live-specification Enabled=true,AttributeName=ttl >/dev/null
done

# Lambdas: the same scripts/package_lambda.py the platform workflows run builds both zips
# (/opt holds functions/, scripts/package_lambda.py and nft-collection/, mounted read-only).
python3 /opt/scripts/package_lambda.py /tmp/lambda >/dev/null
awslocal lambda create-function --function-name low-stock-alert --runtime python3.13 \
  --handler handler.lambda_handler --zip-file fileb:///tmp/lambda/low-stock-alert.zip \
  --role "arn:aws:iam::$ACCT:role/lambda-role" \
  --environment "Variables={LOW_STOCK_THRESHOLD=5}" >/dev/null
awslocal events put-rule --event-bus-name "$BUS" --name to-low-stock \
  --event-pattern '{"detail-type":["InventoryReserved"]}' >/dev/null
awslocal events put-targets --event-bus-name "$BUS" --rule to-low-stock \
  --targets "Id=1,Arn=arn:aws:lambda:$REGION:$ACCT:function:low-stock-alert" >/dev/null

# market-activity-email (DESIGN.md section 16.11): every MarketActivity on a CloudPunk becomes an
# email through SES. LocalStack keeps sent mail instead of delivering it: GET /_aws/ses lists it.
ACTIVITY_EMAIL=activity@cloudpunks.local
awslocal ses verify-email-identity --email-address "$ACTIVITY_EMAIL" >/dev/null
awslocal lambda create-function --function-name market-activity-email --runtime python3.13 \
  --handler handler.lambda_handler --zip-file fileb:///tmp/lambda/market-activity-email.zip \
  --role "arn:aws:iam::$ACCT:role/lambda-role" --timeout 15 \
  --environment "Variables={EMAIL_FROM=$ACTIVITY_EMAIL,EMAIL_TO=$ACTIVITY_EMAIL,STOREFRONT_URL=http://localhost:8080}" \
  >/dev/null
awslocal events put-rule --event-bus-name "$BUS" --name to-market-activity-email \
  --event-pattern '{"detail-type":["MarketActivity"],"detail":{"data":{"sku":[{"prefix":"CP-"}]}}}' \
  >/dev/null
awslocal events put-targets --event-bus-name "$BUS" --rule to-market-activity-email \
  --targets "Id=1,Arn=arn:aws:lambda:$REGION:$ACCT:function:market-activity-email" >/dev/null

echo "retail bootstrap complete"
touch /tmp/bootstrap.done
