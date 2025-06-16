FROM python:3.13
WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "discord_music_bot.py"]
