FROM openpolicyagent/opa:1.17.0 AS opa

FROM python:3.12-slim
COPY --from=opa /opa /usr/local/bin/opa
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/opa"]
CMD ["run"]
