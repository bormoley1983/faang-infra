FROM ghcr.io/sigstore/cosign/cosign:v3.1.2@sha256:d91bc4e7e95e8d2f549c747a72dc174f90579e410a1695f57f686674f84ce849 AS cosign
FROM ghcr.io/oras-project/oras:v1.3.3@sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8 AS oras
FROM anchore/grype:v0.116.1@sha256:1e71065c0a4cff3e6bd3b8add525ffac4343eb4971694eb90a31cf6d4d3e85db AS grype
FROM curlimages/curl:8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13

USER 0
COPY --from=cosign --chmod=0555 /ko-app/cosign /usr/local/bin/cosign
COPY --from=oras --chmod=0555 /bin/oras /usr/local/bin/oras
COPY --from=grype --chmod=0555 /grype /usr/local/bin/grype

USER 100
WORKDIR /workspace
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["sleep 3600"]
