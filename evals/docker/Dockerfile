# Linux box for the live eval suite (evals/live/). `claude plugin eval` refuses any case that
# grants Bash unless it can confine the shell; on Linux that is bubblewrap plus socat, and native
# Windows has no backend at all. See evals/docker/README.md.
# The digest is what builds; the tag beside it is what Dependabot follows (node:22-bookworm-slim).
FROM node:26-bookworm-slim@sha256:5df79989ed685e09f0a98019db4cebfb22fb9df1a53c0161664a011f7ff6b0f1

ARG CLAUDE_CODE_VERSION=2.1.308

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bubblewrap socat git ca-certificates ripgrep python3 python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

# The package is installed editable from a copy at /work at build time; at run time the repository
# is mounted over /work, so `rqh` runs the checked-out code. Rebuild when dependencies change.
RUN mkdir -p /work /opt/venv /home/node/.claude-config /home/node/.eval-tmp && chown -R node:node /work /opt/venv /home/node
USER node
# Each eval run lives in a folder under TMPDIR. The run's Bash sandbox allows writes in that folder
# but denies all of /tmp, and on Linux the deny wins: under /tmp the working directory is read-only.
ENV PATH=/opt/venv/bin:$PATH \
    CLAUDE_CONFIG_DIR=/home/node/.claude-config \
    TMPDIR=/home/node/.eval-tmp \
    DISABLE_AUTOUPDATER=1
COPY --chown=node:node pyproject.toml README.md LICENSE NOTICE /work/
COPY --chown=node:node src /work/src
RUN python3 -m venv /opt/venv && pip install --no-cache-dir -e /work

WORKDIR /work
CMD ["bash"]
