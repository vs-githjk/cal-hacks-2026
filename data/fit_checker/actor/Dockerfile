FROM apify/actor-python:3.12@sha256:1370f827dfbed63a8a1d91e8b479a33efec9f67ad00500b41e8ec8f6c60d66c8
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
CMD ["python", "-m", "src.main"]
