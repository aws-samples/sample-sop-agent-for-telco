#!/bin/sh
# Configure AWS assume-role for Bedrock access in Workshop Studio environments
if [ -n "$BEDROCK_ROLE_ARN" ]; then
  mkdir -p /home/app/.aws
  cat > /home/app/.aws/config << EOF
[default]
role_arn = $BEDROCK_ROLE_ARN
credential_source = Ec2InstanceMetadata
region = ${BEDROCK_REGION:-us-west-2}
EOF
  export AWS_CONFIG_FILE=/home/app/.aws/config
fi

exec "$@"
