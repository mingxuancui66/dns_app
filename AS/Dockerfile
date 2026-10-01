FROM python:3.12-slim
WORKDIR /app
COPY app.py /app/app.py
ENV PYTHONUNBUFFERED=1
EXPOSE 53533/udp
CMD ["python", "/app/app.py"]
