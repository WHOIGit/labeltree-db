#!/usr/bin/env bash
# Build and push the image,
# then (re)start the stack on the remote host

set -euxo pipefail

REGISTRY=harbor-registry.whoi.edu/amplify
REMOTE=sbatchelder@littlerock.whoi.edu
ROOT=/opt/labeltree

IMAGE=$REGISTRY/labeltree-db:latest

docker build . --file Dockerfile -t "$IMAGE"
docker push "$IMAGE"

#ssh "$REMOTE" "mkdir -p $ROOT"
rsync --chmod 660 compose-staging.yaml "$REMOTE:$ROOT/compose.yaml"
rsync --chmod 660 .env-staging "$REMOTE:$ROOT/.env"

ssh "$REMOTE" "cd $ROOT && docker compose pull && docker compose up -d --force-recreate"
