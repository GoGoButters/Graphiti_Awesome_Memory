FROM python:3.11-slim

WORKDIR /app

# Copy requirements from adapter since worker shares dependencies (or at least a subset)
# For now, I will assume I can fix docker-compose.
# Let's write the Dockerfile assuming the context allows access or I will fix it.
# Actually, the user asked for "worker (build worker)".
# If context is ./worker, I can't access adapter code.
# I will duplicate the necessary code or requirements? No, that's bad.
# I will change the docker-compose context for worker to be the project root, so I can COPY backend/adapter.

COPY worker.py .
# We need the app module for the tasks to be importable
# COPY backend/adapter/app /app/app 
# This requires context to be root.

CMD ["python", "worker.py"]
