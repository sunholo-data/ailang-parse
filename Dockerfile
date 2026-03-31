FROM golang:1.24-bookworm AS builder

# Clone and build AILANG from source (dev branch)
ARG CACHE_BUST=0
RUN git clone --depth 1 --branch dev https://github.com/sunholo-data/ailang.git /ailang
WORKDIR /ailang
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /usr/local/bin/ailang ./cmd/ailang/

# Install package dependencies from registry
WORKDIR /app
COPY ailang.toml ailang.lock ./
RUN ailang lock

# Runtime image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ailang /usr/local/bin/ailang

WORKDIR /app
COPY docparse/ ./docparse/
COPY ailang.toml ailang.lock ./
COPY --from=builder /root/.ailang/ /root/.ailang/

# CLI-only: parse files via volume mount
# Usage: docker run -v $(pwd):/data docparse /data/file.docx
# AI:    docker run -e GOOGLE_API_KEY=... -v $(pwd):/data docparse --ai gemini-2.5-flash /data/file.pdf
ENTRYPOINT ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env", "docparse/main.ail"]
