#!/usr/bin/env bash
# Build and push the image,
# then (re)start the stack on the remote host

set -euxo pipefail

REGISTRY=registry.example.org/amplify   # TODO
REMOTE=user@host.example.org            # TODO
ROOT=/srv/labeltree-db                  # TODO

IMAGE=$REGISTRY/labeltree-db:latest

docker build . --file Dockerfile -t "$IMAGE"
docker push "$IMAGE"

ssh "$REMOTE" "mkdir -p $ROOT"
rsync compose-prod.yaml "$REMOTE:$ROOT/compose.yaml"
rsync .envprod "$REMOTE:$ROOT/.env"

ssh "$REMOTE" "cd $ROOT && IMAGE=$IMAGE docker compose pull && IMAGE=$IMAGE docker compose up -d --force-recreate"
