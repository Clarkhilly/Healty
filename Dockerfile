# Hugging Face Spaces (Docker SDK) image.
# Free tier: 16 GB RAM, 2 vCPU, ephemeral disk (data.db rebuilt from CSV on boot).

FROM python:3.12-slim

# HF Spaces requires a non-root user.
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user:user . .

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
