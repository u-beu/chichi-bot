FROM python:3.13
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install pynacl

COPY . .
CMD ["python", "discord_music_bot.py"]
