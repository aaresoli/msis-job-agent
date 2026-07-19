#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=langgraph_user="$LANGGRAPH_POSTGRES_USER" \
  --set=langgraph_password="$LANGGRAPH_POSTGRES_PASSWORD" \
  --set=langgraph_db="$LANGGRAPH_POSTGRES_DB" \
  --set=n8n_user="$N8N_POSTGRES_USER" \
  --set=n8n_password="$N8N_POSTGRES_PASSWORD" \
  --set=n8n_db="$N8N_POSTGRES_DB" \
  --set=phoenix_user="$PHOENIX_POSTGRES_USER" \
  --set=phoenix_password="$PHOENIX_POSTGRES_PASSWORD" \
  --set=phoenix_db="$PHOENIX_POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'langgraph_user', :'langgraph_password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'langgraph_db', :'langgraph_user') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'n8n_user', :'n8n_password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'n8n_db', :'n8n_user') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'phoenix_user', :'phoenix_password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'phoenix_db', :'phoenix_user') \gexec
SQL
