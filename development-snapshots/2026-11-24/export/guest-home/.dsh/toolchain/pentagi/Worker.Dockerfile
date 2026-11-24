FROM ubuntu:24.04
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG http_proxy
ARG https_proxy
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get -o Acquire::http::Proxy=http://10.0.2.100:3128 update -qq && apt-get -o Acquire::http::Proxy=http://10.0.2.100:3128 install -y --no-install-recommends python3 curl ca-certificates binutils file nmap procps && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
