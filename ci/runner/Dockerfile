FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436

ARG RUNNER_VERSION=2.336.0
ARG RUNNER_SHA256=04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      build-essential \
      ca-certificates \
      curl \
      git \
      jq \
      libicu72 \
      libkrb5-3 \
      liblttng-ust1 \
      libssl3 \
      procps \
      python3 \
      python3-dev \
      python3-pip \
      python3-venv \
      zlib1g \
    && curl --fail --location --silent --show-error \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
      --output /tmp/actions-runner.tar.gz \
    && echo "${RUNNER_SHA256}  /tmp/actions-runner.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/actions-runner /runner \
    && tar --extract --gzip --file /tmp/actions-runner.tar.gz --directory /opt/actions-runner \
    && rm /tmp/actions-runner.tar.gz \
    && useradd --create-home --uid 10001 runner \
    && chown -R runner:runner /opt/actions-runner /runner /home/runner \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 entrypoint.sh register.sh /usr/local/bin/

USER runner
WORKDIR /runner

ENTRYPOINT ["entrypoint.sh"]
CMD ["./run.sh"]
