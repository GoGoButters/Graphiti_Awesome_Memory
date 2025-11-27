FROM python:3.11-slim

WORKDIR /app

# Copy requirements from adapter since worker shares dependencies (or at least a subset)
# We assume the build context is the worker dir, but we need adapter code.
# The docker-compose context for worker is ./worker.
# We should probably copy requirements.txt to worker dir or use a shared context.
# For simplicity, I'll just install the necessary packages here directly or copy a local requirements.txt if I make one.
# Better: I will create a requirements.txt in worker/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# We need the app code to run the tasks
# In a real monorepo, we'd install the app as a package.
# Here, I'll copy the backend/adapter/app directory to /app/app so imports work.
# BUT, the docker context is ./worker. I cannot copy from ../backend/adapter.
# Solution: Change docker-compose context to root or use a different strategy.
# I will change docker-compose context for worker to root, or copy the code in CI/build time.
# EASIEST FIX: Update docker-compose to use context: . and dockerfile: worker/Dockerfile
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
