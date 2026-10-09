# Disabled: Pinterest runs in GitHub Actions; n8n is not required.
# # n8n for Render. Building from the official image keeps Render's Docker build
# # path happy. Persistence is external (Neon Postgres) because Render's free
# # plan has NO persistent disk.
# #
# # PIN THE VERSION. An unpinned `latest` means any redeploy silently upgrades
# # n8n — that is exactly how this service went from "boots" to "OOM crash-loop"
# # without a single commit. Pick a tag from:
# #   https://hub.docker.com/r/n8nio/n8n/tags
# # and set it below (or override with --build-arg N8N_VERSION=...).
# ARG N8N_VERSION=latest
# FROM docker.io/n8nio/n8n:${N8N_VERSION}
